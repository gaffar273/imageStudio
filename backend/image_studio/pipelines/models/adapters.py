"""Adapters: one small class per way of reaching a model. Each turns the engine's neutral
message (a system text, then text parts and JPEG image parts) into its provider's request, and
returns the reply text, or the parsed JSON when the provider guarantees it.

- ``local``: the bundled Qwen3.5-9B vision model on llama.cpp (services/brain.py). Schemas are
  enforced as a grammar, and its boxes are on Qwen's trained 0–1000 grid.
- ``openai``: anything that speaks the OpenAI chat-completions protocol: OpenAI itself, Ollama,
  LM Studio, vLLM, llama.cpp servers elsewhere, OpenRouter, Groq, Together, and Google Gemini's
  OpenAI-compatible endpoint.
- ``anthropic``: Claude through the official ``anthropic`` SDK, with structured outputs.

Adding a provider means adding a class with ``available()`` and ``complete()``; nothing in the
pipelines changes.
"""

import json
import os
import urllib.error
import urllib.request

from . import contract


class Adapter:
    kind = ''
    # Whether the provider enforces a JSON schema itself ('grammar' or 'json_schema'), only
    # promises JSON ('json_object'), or nothing ('none').
    structured = 'none'
    vision = True

    def __init__(self, spec):
        self.spec = dict(spec)
        self.structured = spec.get('structured') or self.structured
        self.vision = spec.get('vision', self.vision)

    @property
    def name(self):
        return self.spec.get('label') or f'{self.kind}:{self.spec.get("model", "")}'

    def api_key(self):
        env = self.spec.get('api_key_env')
        return (os.environ.get(env) if env else None) or self.spec.get('api_key') or ''

    def available(self):
        raise NotImplementedError

    def complete(self, system, content, schema=None, max_tokens=2500, temperature=0.0):
        """The reply: text, or a dict when the provider already parsed JSON for us."""
        raise NotImplementedError


def _text_only(content):
    return [part for part in content if part.get('type') == 'text']


class Local(Adapter):
    """The bundled editing brain (Qwen3.5-9B on llama.cpp)."""

    kind = 'local'
    structured = 'grammar'

    def available(self):
        from image_studio.services import brain

        return brain.available()

    def complete(self, system, content, schema=None, max_tokens=2500, temperature=0.0):
        from image_studio.services import brain

        # Looked up at call time, so tests and the bench can substitute brain.chat.
        return brain.chat(system, content, schema=schema, max_tokens=max_tokens, temperature=temperature)


def _post(url, body, headers, timeout=600):
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                     headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:400]
        raise RuntimeError(f'The model server answered {exc.code}: {detail}') from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f'Could not reach the model server at {url}: {exc}') from exc


class OpenAICompatible(Adapter):
    """Any server speaking OpenAI's /chat/completions: hosted or on this machine."""

    kind = 'openai'
    structured = 'json_object'

    def available(self):
        if not self.spec.get('base_url') or not self.spec.get('model'):
            return False
        return bool(self.api_key()) or not self.spec.get('api_key_env') or self.spec.get('local', False)

    def complete(self, system, content, schema=None, max_tokens=2500, temperature=0.0):
        parts = content if self.vision else _text_only(content)
        body = {'model': self.spec['model'], 'max_tokens': max_tokens, 'temperature': temperature,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': parts}]}
        if schema is not None and self.structured == 'json_schema':
            body['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'answer', 'schema': contract.portable(schema), 'strict': False}}
        elif schema is not None and self.structured == 'json_object':
            body['response_format'] = {'type': 'json_object'}
        headers = {'Authorization': f'Bearer {self.api_key()}'} if self.api_key() else {}
        reply = _post(self.spec['base_url'].rstrip('/') + '/chat/completions', body, headers,
                      timeout=self.spec.get('timeout', 600))
        choice = (reply.get('choices') or [{}])[0]
        return (choice.get('message') or {}).get('content') or ''


class Anthropic(Adapter):
    """Claude through the official Anthropic SDK, answering in the schema with structured outputs."""

    kind = 'anthropic'
    structured = 'json_schema'

    def available(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        # The SDK also finds credentials from `ant auth login`, so a missing variable is not fatal.
        return True

    def _blocks(self, content):
        blocks = []
        for part in content:
            if part.get('type') == 'text':
                blocks.append({'type': 'text', 'text': part['text']})
            elif part.get('type') == 'image_url' and self.vision:
                url = part['image_url']['url']
                media, _, data = url.partition(';base64,')
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': media.removeprefix('data:'),
                                                           'data': data}})
        return blocks

    def complete(self, system, content, schema=None, max_tokens=2500, temperature=0.0):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError('Claude needs the Anthropic SDK: pip install anthropic') from exc
        client = anthropic.Anthropic(api_key=self.api_key() or None)
        request = dict(model=self.spec.get('model') or 'claude-opus-5-5',
                       # Thinking is always on for current Claude models and counts toward the limit.
                       max_tokens=max(16000, max_tokens), system=system,
                       messages=[{'role': 'user', 'content': self._blocks(content)}],
                       output_config={'effort': self.spec.get('effort', 'medium'),
                                      **({'format': {'type': 'json_schema', 'schema': contract.portable(schema)}}
                                         if schema is not None else {})})
        if self.spec.get('fallbacks', True):
            # On a safety decline the API re-runs the request on a fallback model in the same call.
            response = client.beta.messages.create(betas=['server-side-fallback-2026-07-01'], fallbacks='default',
                                                   **request)
        else:
            response = client.messages.create(**request)
        if response.stop_reason == 'refusal':
            raise RuntimeError('The model declined this request.')
        return ''.join(block.text for block in response.content if block.type == 'text')


KINDS = {'local': Local, 'openai': OpenAICompatible, 'anthropic': Anthropic}


def build(spec):
    kind = spec.get('kind', 'local')
    if kind not in KINDS:
        raise ValueError(f'Unknown model kind {kind!r}; use one of {", ".join(KINDS)}.')
    return KINDS[kind](spec)

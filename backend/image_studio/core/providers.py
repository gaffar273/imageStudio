"""Model providers: the services a person can connect with an API key, and what each is used for.

Three uses, each optional:

- ``images``: create pictures in Create (OpenAI, Google Gemini, fal.ai, Replicate).
- ``edits``: change a photo from a description in Edit (OpenAI, Google Gemini, fal.ai).
- ``assistant``: the language and vision model that plans and checks PhotoCraft edits
  (pipelines/models). Any OpenAI-compatible server works here, local ones included.

Which model a provider uses is a plain, editable name, because providers rename their models
often; the defaults below are the current ones and "Test" lists what the key can reach.
Keys live in core/credentials.py, never in settings.json. This module only reads settings
and keys, so both the desktop app and the engine use it; the engine does the image calls
(services/cloud.py).
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from image_studio.core import credentials, paths

PROVIDERS = {
    'openai': dict(
        label='OpenAI', env='OPENAI_API_KEY', keys='https://platform.openai.com/api-keys',
        about='GPT Image creates and edits pictures. GPT models can run the editing assistant.',
        images=['gpt-image-2.5-flare', 'gpt-image-2.5-sunburst', 'gpt-image-2'],
        edits=['gpt-image-2.5-sunburst', 'gpt-image-2.5-flare', 'gpt-image-2'],
        assistant='openai', base_url='https://api.openai.com/v1',
    ),
    'gemini': dict(
        label='Google Gemini', env='GEMINI_API_KEY', keys='https://aistudio.google.com/apikey',
        about='Gemini image models (Nano Banana) create and edit pictures. Gemini can run the assistant.',
        images=['gemini-3.1-flash-image', 'gemini-3-pro-image', 'gemini-nano-banana-2.1'],
        edits=['gemini-3.1-flash-image', 'gemini-3-pro-image', 'gemini-nano-banana-2.1'],
        assistant='gemini', base_url='https://generativelanguage.googleapis.com/v1beta',
    ),
    'anthropic': dict(
        label='Anthropic', env='ANTHROPIC_API_KEY', keys='https://console.anthropic.com/settings/keys',
        about='Claude plans and checks PhotoCraft edits with strong vision and reasoning.',
        assistant='anthropic', assistant_models=['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'],
        base_url='https://api.anthropic.com/v1',
    ),
    'fal': dict(
        label='fal.ai', env='FAL_KEY', keys='https://fal.ai/dashboard/keys',
        about='Fast hosted FLUX and other open image models, for creating and editing.',
        images=['fal-ai/flux/dev', 'fal-ai/flux/schnell', 'fal-ai/flux-pro/v1.1'],
        edits=['fal-ai/flux-pro/kontext'],
        base_url='https://fal.run',
    ),
    'replicate': dict(
        label='Replicate', env='REPLICATE_API_TOKEN', keys='https://replicate.com/account/api-tokens',
        about='Thousands of community image models, run by name (owner/model).',
        images=['black-forest-labs/flux-schnell', 'black-forest-labs/flux-1.1-pro', 'black-forest-labs/flux-dev'],
        base_url='https://api.replicate.com/v1',
    ),
    'openrouter': dict(
        label='OpenRouter', env='OPENROUTER_API_KEY', keys='https://openrouter.ai/settings/keys',
        about='One key for hundreds of language models, for the editing assistant.',
        assistant='openrouter', base_url='https://openrouter.ai/api/v1',
    ),
    'ollama': dict(
        label='Ollama', local=True, keys='https://ollama.com/download',
        about='Language and vision models running on this PC. No key needed.',
        assistant='ollama', base_url='http://127.0.0.1:11434/v1',
    ),
    'lmstudio': dict(
        label='LM Studio', local=True, keys='https://lmstudio.ai',
        about='Models served by LM Studio on this PC. No key needed.',
        assistant='lmstudio', base_url='http://127.0.0.1:1234/v1',
    ),
    'custom': dict(
        label='Other OpenAI-compatible server', custom=True, keys='',
        about='vLLM, Groq, Together, a llama.cpp server or any service that speaks the OpenAI API.',
        assistant='custom', base_url='',
    ),
}
LOCAL_ASSISTANT = 'local'  # the bundled Qwen model (services/brain.py)
TIMEOUT = 20


def credential_name(provider):
    return f'provider:{provider}'


def saved():
    return paths.load_settings().get('providers') or {}


def options(provider):
    """The provider's settings: what was saved, over the defaults."""
    spec = PROVIDERS[provider]
    values = dict(base_url=spec.get('base_url', ''), image_model=(spec.get('images') or [''])[0],
                  edit_model=(spec.get('edits') or [''])[0], enabled=False)
    values.update({key: value for key, value in (saved().get(provider) or {}).items() if value not in (None, '')})
    return values


def key(provider):
    return credentials.get(credential_name(provider), PROVIDERS[provider].get('env'))


def needs_key(provider):
    spec = PROVIDERS[provider]
    return not spec.get('local') and not spec.get('custom')


def connected(provider):
    """Set up and usable: a key for hosted services; switched on (and with an address) for the others."""
    if needs_key(provider):
        return bool(key(provider))
    values = options(provider)
    return bool(values.get('enabled')) and bool(values.get('base_url'))


def save(provider, api_key=None, **values):
    """Store the provider's settings, and its key when one is given ('' removes it)."""
    everything = dict(saved())
    current = dict(everything.get(provider) or {})
    current.update(values)
    everything[provider] = {name: value for name, value in current.items() if value is not None}
    paths.save_settings(providers=everything)
    if api_key is not None:
        credentials.put(credential_name(provider), api_key.strip())


def disconnect(provider):
    credentials.delete(credential_name(provider))
    everything = dict(saved())
    everything.pop(provider, None)
    paths.save_settings(providers=everything or None)


def cloud_id(provider, model):
    return f'{provider}:{model}'


def split(model_id):
    """'openai:gpt-image-2' -> ('openai', 'gpt-image-2'); a local model id -> (None, id)."""
    provider, found, model = str(model_id).partition(':')
    return (provider, model) if found and provider in PROVIDERS else (None, model_id)


def image_models():
    """Cloud models for Create: one per provider that creates pictures."""
    return [dict(id=cloud_id(name, options(name)['image_model']), provider=name, label=spec['label'],
                 model=options(name)['image_model'], ready=connected(name))
            for name, spec in PROVIDERS.items() if spec.get('images')]


def edit_models():
    """Cloud editors for Edit: one per provider that edits pictures."""
    return [dict(id=cloud_id(name, options(name)['edit_model']), provider=name, label=spec['label'],
                 model=options(name)['edit_model'], ready=connected(name))
            for name, spec in PROVIDERS.items() if spec.get('edits')]


# The editing assistant ---------------------------------------------------------------------

ROLES = ('planner', 'grounder', 'checker')


def assistant():
    """{'provider': id or 'local', 'model': name} the planner uses; the other roles follow it."""
    spec = (paths.load_settings().get('models') or {}).get('planner') or {}
    provider = spec.get('preset') or spec.get('provider') or LOCAL_ASSISTANT
    return dict(provider=provider if provider in PROVIDERS else LOCAL_ASSISTANT, model=spec.get('model', ''))


def use_assistant(provider, model=''):
    """Connect every assistant role to one model ('local' for the bundled one)."""
    if provider == LOCAL_ASSISTANT:
        paths.save_settings(models=None)
        return
    spec = PROVIDERS[provider]
    if provider == 'custom':
        role = dict(provider='custom', kind='openai', base_url=options('custom')['base_url'], model=model,
                    structured='json_object', credential=credential_name('custom'), label=spec['label'])
    else:
        role = dict(preset=spec['assistant'], model=model)
        if spec.get('local'):
            role['base_url'] = options(provider)['base_url']
    roles = {name: dict(role) for name in ROLES}
    from image_studio.pipelines import models

    if not models.can_ground(role) and models.available_spec({'preset': 'local'}):
        # Finding things in the photo is a trained skill most chat models lack; the bundled
        # model keeps that job when it is installed (the planner and the checker move).
        roles['grounder'] = {'preset': 'local'}
    paths.save_settings(models=roles)


# Testing a connection ----------------------------------------------------------------------

def _get(url, headers):
    request = urllib.request.Request(url, headers={'User-Agent': 'ImageStudio/2.0', **headers})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read() or b'{}')


def _reason(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return 'The key was refused. Check that it is copied in full and still active.'
        try:
            detail = json.loads(exc.read() or b'{}')
            detail = (detail.get('error') or {}).get('message') if isinstance(detail.get('error'), dict) else (
                detail.get('error') or detail.get('detail'))
        except (ValueError, AttributeError):
            detail = None
        return f'The service answered {exc.code}{": " + str(detail)[:200] if detail else "."}'
    if type(exc) is ValueError:  # already worded for people
        return str(exc)
    if isinstance(exc, ValueError):
        return 'The service sent an answer this app could not read.'
    reason = getattr(exc, 'reason', exc)
    return f'Could not reach the service: {reason}'


def _claude_models(api_key, base):
    """Claude's model list, through the Anthropic SDK where it is installed (the engine has it)."""
    try:
        import anthropic
    except ImportError:  # the app's own small Python: a plain listing checks the key just as well
        answer = _get(f'{base}/models?limit=100', {'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
        return [item['id'] for item in answer.get('data') or []]
    try:
        return [model.id for model in anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT).models.list()]
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise ValueError('The key was refused. Check that it is copied in full and still active.') from exc
    except anthropic.APIConnectionError as exc:
        raise ValueError(f'Could not reach the service: {exc}') from exc
    except anthropic.APIStatusError as exc:
        raise ValueError(f'The service answered {exc.status_code}: {exc.message}'[:240]) from exc


def test(provider, api_key=None, base_url=None):
    """Check a key (or a local server) by listing models. Returns (ok, message, model names)."""
    PROVIDERS[provider]
    api_key = key(provider) if api_key is None else api_key.strip()
    base = (base_url or options(provider).get('base_url') or '').rstrip('/')
    if needs_key(provider) and not api_key:
        return False, 'Paste a key first.', []
    if not base and provider not in ('fal',):
        return False, 'Enter the server address first.', []
    try:
        if provider == 'gemini':
            answer = _get(f'{base}/models?pageSize=1000', {'x-goog-api-key': api_key})
            names = [item['name'].removeprefix('models/') for item in answer.get('models') or []]
        elif provider == 'anthropic':
            names = _claude_models(api_key, base)
        elif provider == 'replicate':
            answer = _get(f'{base}/account', {'Authorization': f'Bearer {api_key}'})
            return True, f'Connected as {answer.get("username") or "your account"}.', []
        elif provider == 'fal':
            # fal has no free "who am I" call: only a refusal says the key is wrong.
            try:
                _get('https://api.fal.ai/v1/models?limit=1', {'Authorization': f'Key {api_key}'})
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise
            return True, 'Key saved. fal checks it again with the first picture.', []
        elif provider == 'openrouter':
            _get(f'{base}/key', {'Authorization': f'Bearer {api_key}'})
            answer = _get(f'{base}/models', {})
            names = [item['id'] for item in answer.get('data') or []]
        else:  # OpenAI and every OpenAI-compatible server
            headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
            answer = _get(f'{base}/models', headers)
            names = [item['id'] for item in answer.get('data') or []]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        return False, _reason(exc), []
    names = sorted(set(names))
    count = f'{len(names)} model{"" if len(names) == 1 else "s"} available.' if names else 'Connected.'
    return True, f'Connected. {count}' if names else count, names

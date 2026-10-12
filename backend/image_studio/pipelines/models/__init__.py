"""Connecting any language or vision model to the pipeline engine.

The engine asks models three kinds of questions, each a *role*:

- ``planner``: read the request and the photo, and choose pipelines from the menu.
- ``grounder``: find a named thing in the photo and give its boxes.
- ``checker``: compare before and after, and answer multiple-choice checks.

Each role is connected to one model, set in the studio settings (``models`` in settings.json) or
with ``connect()``. By default all three use the bundled local model. A role can use any adapter
kind (see adapters.py): the local llama.cpp model, any OpenAI-compatible server (Ollama, LM Studio,
vLLM, OpenAI, Gemini, OpenRouter…), or Claude. Whatever the model, the answer goes through the
same contract (contract.py): parsed, checked against the schema, repaired where that needs no
guess, and asked again with the problems listed when it cannot be repaired.

    from image_studio.pipelines import models
    models.connect('planner', preset='ollama', model='qwen2.5vl:7b')
    answer = models.chat('planner', system, content, schema=SCHEMA)
"""

import copy

from . import adapters, contract

ROLES = ('planner', 'grounder', 'checker')

# Ready-made connections. API keys are read from the named environment variable, never stored
# in the preset.
PRESETS = {
    'local': {'kind': 'local', 'label': 'Bundled Qwen3.5-9B vision (this PC)', 'boxes': 'xyxy_1000'},
    'ollama': {'kind': 'openai', 'base_url': 'http://127.0.0.1:11434/v1', 'model': 'qwen2.5vl:7b', 'local': True,
               'structured': 'json_schema', 'label': 'Ollama (this PC)'},
    'lmstudio': {'kind': 'openai', 'base_url': 'http://127.0.0.1:1234/v1', 'model': '', 'local': True,
                 'structured': 'json_schema', 'label': 'LM Studio (this PC)'},
    'vllm': {'kind': 'openai', 'base_url': 'http://127.0.0.1:8000/v1', 'model': '', 'local': True,
             'structured': 'json_schema', 'label': 'vLLM server'},
    'openai': {'kind': 'openai', 'base_url': 'https://api.openai.com/v1', 'model': '',
               'api_key_env': 'OPENAI_API_KEY', 'structured': 'json_schema', 'label': 'OpenAI'},
    'gemini': {'kind': 'openai', 'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
               'model': '', 'api_key_env': 'GEMINI_API_KEY', 'structured': 'json_schema',
               # Gemini is trained to give boxes as [ymin, xmin, ymax, xmax] on a 0–1000 grid.
               'boxes': 'yxyx_1000', 'label': 'Google Gemini'},
    'openrouter': {'kind': 'openai', 'base_url': 'https://openrouter.ai/api/v1', 'model': '',
                   'api_key_env': 'OPENROUTER_API_KEY', 'structured': 'json_object', 'label': 'OpenRouter'},
    'anthropic': {'kind': 'anthropic', 'model': 'claude-opus-5-5', 'api_key_env': 'ANTHROPIC_API_KEY',
                  'label': 'Anthropic Claude'},
}

_override = {}


def settings():
    """{role: connection spec} from the studio settings, local by default."""
    from image_studio.core.paths import load_settings

    saved = load_settings().get('models') or {}
    result = {}
    for role in ROLES:
        spec = _override.get(role) or saved.get(role) or {'preset': 'local'}
        result[role] = resolve(spec)
    return result


def resolve(spec):
    """A connection spec with its preset filled in (explicit fields win)."""
    spec = dict(spec or {})
    preset = spec.pop('preset', None)
    base = copy.deepcopy(PRESETS.get(preset, {})) if preset else {}
    if preset and preset not in PRESETS:
        raise ValueError(f'Unknown model preset {preset!r}; choose one of {", ".join(PRESETS)}.')
    base.update({key: value for key, value in spec.items() if value not in (None, '')})
    base.setdefault('kind', 'local')
    if preset:
        base['preset'] = preset
    return base


def connect(role, save=False, **spec):
    """Connect a role to a model (``preset=`` and/or explicit fields). ``save`` writes it to the
    studio settings; otherwise it lasts for this process (tests, benchmarks, one-off runs)."""
    if role not in ROLES:
        raise ValueError(f'Unknown role {role!r}; use one of {", ".join(ROLES)}.')
    resolved = resolve(spec)
    adapters.build(resolved)  # fails early on an unknown kind
    if save:
        from image_studio.core.paths import load_settings, save_settings

        saved = dict(load_settings().get('models') or {})
        saved[role] = {key: value for key, value in spec.items() if key != 'api_key'}
        save_settings(models=saved)
        _override.pop(role, None)
    else:
        _override[role] = spec
    return resolved


def disconnect(role=None):
    """Forget process-level connections (all roles, or one)."""
    if role:
        _override.pop(role, None)
    else:
        _override.clear()


def adapter(role):
    return adapters.build(settings()[role])


def available(role='planner'):
    try:
        return adapter(role).available()
    except (ValueError, RuntimeError):
        return False


def box_format(role='grounder'):
    """How the role's model writes boxes: 'xyxy_1000' or 'yxyx_1000'."""
    return settings()[role].get('boxes', 'xyxy_1000')


def describe():
    """Which model answers each role, for the interface and the logs."""
    return {role: {'name': adapters.build(spec).name, 'kind': spec['kind'], 'model': spec.get('model', ''),
                   'available': available(role)} for role, spec in settings().items()}


def image_part(image, longest=1024):
    """A picture in the engine's neutral message format (a JPEG data URL)."""
    from image_studio.services import brain

    return brain.image_part(image) if longest == 1024 else brain.image_part(image, longest)


class ModelAnswerError(RuntimeError):
    pass


def chat(role, system, content, schema=None, max_tokens=2500, temperature=0.0, attempts=3):
    """The role's model's answer. With a schema: a dict that fits it (repaired where that needs no
    guess), asking again with the problems listed when the answer does not fit."""
    model = adapter(role)
    if isinstance(content, str):
        content = [{'type': 'text', 'text': content}]
    content = list(content)
    if schema is None:
        reply = model.complete(system, content, None, max_tokens, temperature)
        return reply if isinstance(reply, str) else str(reply)
    if model.structured not in ('grammar', 'json_schema'):
        system = f'{system}\n\n{contract.instructions(schema)}'
    problems = ['the answer was not a JSON object']
    best = None
    for attempt in range(attempts):
        reply = model.complete(system, content, schema, max_tokens, temperature if attempt == 0 else 0.3)
        value = contract.extract(reply)
        if value is None:
            problems = ['the answer was not a JSON object']
        else:
            fixed, problems = contract.conform(value, schema)
            if not problems:
                return fixed
            best = fixed
        content = content + [{'type': 'text', 'text': 'Your previous answer did not fit the required JSON: '
                              + '; '.join(problems[:12]) + '. Answer again with the corrected JSON object only.'}]
    if best is not None:
        # Every remaining problem is in a field the engine's own guards check again (an unknown
        # pipeline becomes “other”, a number not in the request is dropped).
        return best
    raise ModelAnswerError(f'{model.name} did not give a usable answer: {"; ".join(problems)}')

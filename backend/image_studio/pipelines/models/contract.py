"""The contract between the pipeline engine and any language or vision model.

Every question the engine asks a model has a JSON schema made of closed menus: pipeline ids,
targets, strengths, positions, verdicts. Models differ in how well they keep to it. A local
llama.cpp server can enforce the schema as a grammar; hosted APIs offer JSON-schema modes with
their own limits; small local models may only promise JSON, or nothing at all. So the engine never
trusts the answer as it arrives:

1. ``portable(schema)`` drops the constraints some providers reject (lengths, ranges, item counts);
   they are enforced here instead.
2. ``instructions(schema)`` spells the schema out in the prompt for models that cannot enforce it.
3. ``extract(text)`` finds the JSON in a reply (code fences, prose around it, trailing commas).
4. ``conform(value, schema)`` checks the answer against the full schema and repairs what can be
   repaired without guessing: a menu choice in other letter case or with spaces for underscores,
   a number written as text, a missing optional field, a list that is too long. Whatever cannot be
   repaired is reported, and the model is asked again with those problems listed.
"""

import difflib
import json
import re

DROPPED = ('maxItems', 'minItems', 'minimum', 'maximum', 'minLength', 'maxLength', 'multipleOf', 'pattern')


def portable(schema):
    """The schema without constraints that some providers' JSON modes reject."""
    if isinstance(schema, dict):
        return {key: portable(value) for key, value in schema.items() if key not in DROPPED}
    if isinstance(schema, list):
        return [portable(item) for item in schema]
    return schema


def instructions(schema):
    """The schema in words, for models that cannot enforce it."""
    return ('Answer with one JSON object only, no prose and no code fences. It must match this JSON schema '
            'exactly; every "enum" is a closed menu, so copy one of its values letter for letter:\n'
            + json.dumps(portable(schema), ensure_ascii=False))


def extract(text):
    """The JSON object inside a model's reply, or None."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start < 0 or end <= start:
        return None
    candidate = cleaned[start:end + 1]
    for attempt in (candidate, re.sub(r',\s*([}\]])', r'\1', candidate)):
        try:
            value = json.loads(attempt)
            return value if isinstance(value, dict) else None
        except ValueError:
            continue
    return None


def _menu_choice(value, options):
    """`value` matched to a closed menu: exact, then ignoring case and separators, then a close
    spelling (“blur background” → “blur_background”). None when nothing is close enough."""
    if value in options:
        return value
    if not isinstance(value, str):
        return None
    key = lambda text: re.sub(r'[\s_\-]+', ' ', str(text).strip().lower())  # noqa: E731
    by_key = {key(option): option for option in options}
    if key(value) in by_key:
        return by_key[key(value)]
    close = difflib.get_close_matches(key(value), list(by_key), n=1, cutoff=0.85)
    return by_key[close[0]] if close else None


def _empty(schema):
    kinds = _types(schema)
    if 'enum' in schema:
        return '' if '' in schema['enum'] else (None if None in schema['enum'] else schema['enum'][0])
    if 'null' in kinds:
        return None
    return {'string': '', 'array': [], 'object': {}, 'boolean': False, 'number': None, 'integer': None}.get(
        kinds[0] if kinds else 'string', None)


def _types(schema):
    kind = schema.get('type')
    if isinstance(kind, list):
        return kind
    if kind:
        return [kind]
    if 'anyOf' in schema:
        return [t for option in schema['anyOf'] for t in _types(option)]
    return []


def conform(value, schema, path='answer'):
    """(the value repaired to fit the schema, [problems that could not be repaired])."""
    if 'anyOf' in schema:
        best = None
        for option in schema['anyOf']:
            fixed, problems = conform(value, option, path)
            if not problems:
                return fixed, []
            if best is None or len(problems) < len(best[1]):
                best = (fixed, problems)
        return best
    if 'enum' in schema:
        chosen = _menu_choice(value, schema['enum'])
        if chosen is None and (value is None or value == ''):
            chosen = _empty(schema)
            if chosen is not None or None in schema['enum']:
                return chosen, []
        if chosen is None:
            return value, [f'{path} must be one of the menu values, not {json.dumps(value, ensure_ascii=False)}']
        return chosen, []
    kinds = _types(schema)
    if value is None and 'null' in kinds:
        return None, []
    if 'object' in kinds:
        if not isinstance(value, dict):
            return value, [f'{path} must be a JSON object']
        properties = schema.get('properties', {})
        result, problems = {}, []
        for name, sub in properties.items():
            if name in value:
                result[name], found = conform(value[name], sub, f'{path}.{name}')
                problems += found
            elif name in schema.get('required', ()):
                # A missing field is filled with its empty value; the engine's own guards decide
                # what an empty slot means (no number written, no position named).
                result[name] = _empty(sub)
        if schema.get('additionalProperties', True) is not False:
            result.update({k: v for k, v in value.items() if k not in properties})
        return result, problems
    if 'array' in kinds:
        if not isinstance(value, list):
            value = [] if value in (None, '') else [value]
        items = schema.get('items', {})
        result, problems = [], []
        for number, item in enumerate(value[:schema.get('maxItems', len(value))]):
            fixed, found = conform(item, items, f'{path}[{number}]')
            result.append(fixed)
            problems += found
        return result, problems
    if 'number' in kinds or 'integer' in kinds:
        if isinstance(value, str):
            try:
                value = float(value.strip().rstrip('%'))
            except ValueError:
                return value, [f'{path} must be a number']
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, [f'{path} must be a number']
        return (round(value) if 'integer' in kinds and 'number' not in kinds else value), []
    if 'boolean' in kinds:
        if isinstance(value, str) and value.strip().lower() in ('true', 'false', 'yes', 'no'):
            return value.strip().lower() in ('true', 'yes'), []
        if not isinstance(value, bool):
            return value, [f'{path} must be true or false']
        return value, []
    if 'string' in kinds:
        if value is None:
            return '', []
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value), []
        if not isinstance(value, str):
            return json.dumps(value, ensure_ascii=False), []
        return value, []
    return value, []

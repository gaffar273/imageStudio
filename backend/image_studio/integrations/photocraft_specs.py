"""Typed views of PhotoCraft's parameter specifications.

The command registry describes each command's parameters as compact text, for example
``{"radius":0.1..1000=1,"distribution":"uniform|gaussian","monochromatic":bool}``.
This module turns that text into fields (number ranges, choices, switches, colors) so that
the interface can draw real controls and generated parameters can be checked and clamped
before they reach the engine.
"""

import re

NUMBER = r'-?\d+(?:\.\d+)?'
RANGE = re.compile(rf'^({NUMBER})\s*\.\.\s*=?\s*({NUMBER})?')
DEFAULT = re.compile(r'=\s*("[^"]*"|-?\d+(?:\.\d+)?|true|false)')
UNITS = ('px', 'deg', 'pt', 'ppi', '%', 'mm', 'u32', 'i32', 'u64', 'em')


def _top_level(text):
    """The text inside the first top-level {...} split into (key, raw value) pairs."""
    start = text.find('{')
    if start < 0:
        return []
    depth, quote, pairs, token = 0, False, [], ''
    for char in text[start + 1 :]:
        if quote:
            token += char
            quote = char != '"'
            continue
        if char == '"':
            quote = True
        elif char in '{[(':
            depth += 1
        elif char in '}])':
            if depth == 0:
                break
            depth -= 1
        elif char == ',' and depth == 0:
            pairs.append(token)
            token = ''
            continue
        token += char
    pairs.append(token)
    result = []
    for pair in pairs:
        match = re.match(r'\s*"(\w+)"\s*:\s*(.*)$', pair, re.DOTALL)
        if match:
            result.append((match.group(1), match.group(2).strip()))
    return result


def _number(text):
    value = float(text)
    return int(value) if value.is_integer() and '.' not in text else value


def field(name, raw):
    """One parameter's type, range, choices and default from its specification text."""
    spec = {'name': name, 'optional': '?' in raw.split('(')[0], 'note': ''}
    note = re.search(r'\((.*)\)\s*$', raw)
    if note:
        spec['note'] = note.group(1)[:200]
    default = DEFAULT.search(raw)
    span = RANGE.match(raw)
    choices = re.match(r'^"([^"#<>/]*\|[^"#<>/]*)"', raw)
    if span:
        low = _number(span.group(1))
        high = _number(span.group(2)) if span.group(2) else None
        spec.update(type='number', min=low, max=high)
        spec['integer'] = isinstance(low, int) and (high is None or isinstance(high, int))
        if default and re.fullmatch(NUMBER, default.group(1)):
            spec['default'] = _number(default.group(1))
    elif choices and '…' not in choices.group(1):
        options = [option.strip() for option in choices.group(1).split('|') if option.strip()]
        spec.update(type='choice', options=options)
        if default and default.group(1).startswith('"'):
            spec['default'] = default.group(1).strip('"')
    elif raw.startswith('bool'):
        spec.update(type='bool')
        if default and default.group(1) in ('true', 'false'):
            spec['default'] = default.group(1) == 'true'
    elif '#rrggbb' in raw:
        spec.update(type='color')
        if default and default.group(1).startswith('"#'):
            spec['default'] = default.group(1).strip('"')
    elif raw.startswith(('str', 'text')) or raw.startswith('"') and raw.count('"') == 2 and '|' not in raw:
        spec.update(type='text')
    elif raw.split('=')[0].split('?')[0].strip() in UNITS or raw.startswith(('px', 'deg', 'pt')):
        spec.update(type='number', min=None, max=None, integer=raw.startswith(('u32', 'i32', 'u64')))
        if default and re.fullmatch(NUMBER, default.group(1)):
            spec['default'] = _number(default.group(1))
    elif raw.startswith('id'):
        spec.update(type='layer')
    else:
        spec.update(type='json')
    return spec


def parse(text):
    """All parameters of one command, in the registry's order."""
    return [field(name, raw) for name, raw in _top_level(text or '')]


def sanitize(params, fields, open_ended=False):
    """Generated parameters made safe for the engine: numbers clamped into their ranges,
    unknown choices and wrongly typed values dropped (the engine then uses its default).
    Open-ended specifications ("…") keep settings they do not list. Returns (clean params,
    notes about what changed)."""
    if not fields:
        return dict(params), []
    known = {spec['name']: spec for spec in fields}
    clean, notes = {}, []
    for key, value in params.items():
        spec = known.get(key)
        if spec is None:
            if open_ended:
                clean[key] = value
            else:
                notes.append(f'Ignored unknown setting “{key}”.')
            continue
        kind = spec['type']
        if kind == 'number':
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                notes.append(f'Ignored non-numeric “{key}”.')
                continue
            bounded = value
            if spec.get('min') is not None:
                bounded = max(spec['min'], bounded)
            if spec.get('max') is not None:
                bounded = min(spec['max'], bounded)
            if spec.get('integer'):
                bounded = round(bounded)
            if bounded != value:
                notes.append(f'Kept “{key}” within its range ({value} → {bounded}).')
            clean[key] = bounded
        elif kind == 'choice':
            if value in spec['options']:
                clean[key] = value
            else:
                lowered = {option.lower(): option for option in spec['options']}
                if isinstance(value, str) and value.lower() in lowered:
                    clean[key] = lowered[value.lower()]
                else:
                    notes.append(f'Ignored unsupported “{key}” value {value!r}.')
        elif kind == 'bool':
            if isinstance(value, bool):
                clean[key] = value
            else:
                notes.append(f'Ignored non-boolean “{key}”.')
        elif kind == 'color':
            if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', value):
                clean[key] = value.lower()
            elif isinstance(value, list) and 3 <= len(value) <= 4:
                clean[key] = value
            else:
                notes.append(f'Ignored invalid color for “{key}”.')
        else:
            clean[key] = value
    return clean, notes

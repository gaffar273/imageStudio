"""What the studio learns from the person using it, kept on this computer.

Three kinds of memory, all in WORK/studio-memory/memory.json:

- Words: "remember: make it pop means more contrast and vibrance", or a correction right after
  a request ("no, I meant warmer"), teaches what a phrase means. Later requests containing the
  phrase are rewritten before planning, so the rules, the planner and the editing brain all
  see what the person means. Nothing is trained; a lesson works from the next request on.
- Strength: "too much" / "less" or "more" / "not enough" right after a request redoes it
  weaker or stronger, and nudges how strong that kind of step is made from then on.
- Favorites: the pictures marked as favorites in the Library, for the settings profile and
  the personal style LoRA (personal.py).

A correction or a "less"/"more" first takes back the last request by deleting the layers it
added (found by comparing the layer list before and after it), so nothing older is touched.
When the last request changed the picture in place (crop, resize, flatten...), the lesson is
still kept and the person is asked to press Undo."""

import json
import re
import threading
import time
from collections import Counter

from image_studio.core.paths import WORK

FOLDER = WORK / 'studio-memory'
FILE = FOLDER / 'memory.json'
_lock = threading.RLock()
_last = None  # the last planned request: dict(request, steps, how, before, time); not saved

# Arguments that set how strong a step is (others, such as sizes and angles, are kept).
STRENGTH_ARGS = ('amount', 'strength', 'radius', 'length')
# Steps that change the picture in place, so deleting new layers cannot take them back.
IN_PLACE = {
    'crop',
    'crop_to_selection',
    'resize',
    'rotate',
    'flip',
    'new_canvas',
    'delete_layer',
    'rename_layer',
    'select_layer',
    'layer_opacity',
    'blend_mode',
    'hide_layer',
    'show_layer',
    'move_layer',
    'merge_down',
    'flatten',
    'undo',
    'redo',
    'save_to_library',
}
LESS, MORE = 0.6, 1.5  # redo factor for "too much" / "not enough"
NUDGE_LESS, NUDGE_MORE = 0.85, 1.15
LOWEST, HIGHEST = 0.4, 2.0  # learned strength factors stay in this range
REDO_SECONDS = 30 * 60  # a correction refers to a request at most this old

_QUOTE = '["“”\'‘’]?'
TEACH = [
    re.compile(
        rf'^(?:please\s+)?(?:remember|learn|note)(?:\s+that)?\s*[:,-]?\s*{_QUOTE}(?P<phrase>.+?){_QUOTE}\s+'
        r'(?:means|=|is the same as|should mean)\s+(?P<means>.+)$',
        re.I,
    ),
    re.compile(
        rf'^when i say\s+{_QUOTE}(?P<phrase>.+?){_QUOTE}\s*,?\s+(?:i mean|it means|do|make it|i want)\s+(?P<means>.+)$',
        re.I,
    ),
]
_NO = r"(?:no|nope|wrong|not that|that'?s wrong|that'?s not (?:it|right|what i (?:meant|wanted)))"
CORRECT = [
    re.compile(
        rf'^{_NO}\b[\s,.!:;-]*(?:i meant|i mean|i wanted|i said|instead|rather)\b[\s,:;-]*(?P<means>.+)$',
        re.I,
    ),
    re.compile(rf'^{_NO}\s*[,.!:;-]+\s*(?P<means>.+)$', re.I),
    re.compile(r'^(?:i meant|what i meant was|i wanted)\b[\s,:;-]*(?P<means>.+)$', re.I),
]
FORGET_ALL = re.compile(r'^(?:forget|unlearn) (?:everything|all)(?: you (?:learned|know))?[.!]*$', re.I)
FORGET = re.compile(
    rf'^(?:forget|unlearn)\s+(?:what\s+)?(?:i taught you about\s+|that\s+)?{_QUOTE}(?P<phrase>.+?){_QUOTE}'
    r'(?:\s+means.*)?[.!]*$',
    re.I,
)
_LEAD = r"(?:(?:that'?s|it'?s|its|way|a bit|a little|slightly|much|even|still)\s+)*"
WEAKER = re.compile(
    _LEAD + r'(?:too (?:much|strong|intense|heavy|far|strong)|less|weaker|softer|tone it down|subtler|'
    r'more subtle|not so much|overdone)(?:\s+please)?[.!]*$',
    re.I,
)
STRONGER = re.compile(
    _LEAD
    + r'(?:more|stronger|not enough|too (?:weak|subtle|little|faint)|increase it|push it)(?:\s+please)?[.!]*$',
    re.I,
)


# ---- Storage ---------------------------------------------------------------------------


def _empty():
    return dict(version=1, words=[], strength={}, favorites=[])


def load():
    with _lock:
        try:
            data = json.loads(FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return _empty()
        return {**_empty(), **data}


def save(data):
    with _lock:
        FOLDER.mkdir(parents=True, exist_ok=True)
        temporary = FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(FILE)


def phrase_key(text):
    """A phrase as it is matched: lower case, single spaces, no quotes or end punctuation."""
    text = ' '.join(str(text).lower().split())
    return text.strip(' "“”\'‘’.,!?;:')


# ---- Words -----------------------------------------------------------------------------


def teach(phrase, means, source='taught'):
    """Remember that `phrase` means `means`. Returns the saved entry, or None if unusable."""
    key, means = phrase_key(phrase), ' '.join(str(means).split()).strip(' "“”\'‘’')
    if len(key) < 3 or not means or key == phrase_key(means) or len(key) > 200 or len(means) > 500:
        return None
    with _lock:
        data = load()
        data['words'] = [word for word in data['words'] if word['phrase'] != key]
        entry = dict(phrase=key, means=means, source=source, created=time.time(), used=0)
        data['words'].append(entry)
        save(data)
        return entry


def forget(phrase=None):
    """Forget one phrase, or every word and strength preference when `phrase` is None.
    Returns how many were forgotten."""
    with _lock:
        data = load()
        if phrase is None:
            count = len(data['words']) + len(data['strength'])
            data['words'], data['strength'] = [], {}
        else:
            key = phrase_key(phrase)
            kept = [word for word in data['words'] if word['phrase'] != key]
            count = len(data['words']) - len(kept)
            data['words'] = kept
        save(data)
        return count


def rewrite(text):
    """`text` with every taught phrase replaced by its meaning (longest phrases first, one
    pass, so a meaning is never rewritten again). Returns (text, [phrases used])."""
    words = load()['words']
    if not words or not text:
        return text, []
    meaning = {word['phrase']: word['means'] for word in words}
    pattern = re.compile(
        r'(?<!\w)(' + '|'.join(re.escape(key) for key in sorted(meaning, key=len, reverse=True)) + r')(?!\w)',
        re.I,
    )
    used = []

    def replace(match):
        key = phrase_key(match.group(0))
        used.append(key)
        return meaning.get(key, match.group(0))

    result = pattern.sub(replace, text)
    if used:
        with _lock:
            data = load()
            for word in data['words']:
                if word['phrase'] in used:
                    word['used'] = word.get('used', 0) + 1
            save(data)
    return result, used


# ---- Strength --------------------------------------------------------------------------


def _clamped(op, name, value):
    from image_studio.services import agent

    rule = agent.OPS.get(op, {}).get('args', {}).get(name)
    if rule is None or isinstance(rule[0], list) or rule[0] in (str, bool) or len(rule) < 4:
        return value
    return rule[0](max(rule[2], min(rule[3], value)))


def scaled(step, factor):
    """`step` made `factor` times as strong: its strength arguments, or each grade layer's
    adjustments. Steps without a strength are returned unchanged."""
    from image_studio.services import agent, grading

    step = dict(step)
    op = step.get('op')
    if op == 'grade' and isinstance(step.get('layers'), list):
        step['layers'] = [
            grading.scale_layer(layer, min(1.5, factor)) if isinstance(layer, dict) else layer
            for layer in step['layers']
        ]
        return step
    spec = agent.OPS.get(op, {}).get('args', {})
    for name in STRENGTH_ARGS:
        value = step.get(name)
        if name in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
            step[name] = _clamped(op, name, value * factor)
    return step


def has_strength(step):
    from image_studio.services import agent

    if step.get('op') == 'grade':
        return isinstance(step.get('layers'), list)
    spec = agent.OPS.get(step.get('op'), {}).get('args', {})
    return any(name in spec and isinstance(step.get(name), (int, float)) for name in STRENGTH_ARGS)


def personalize(steps):
    """Steps with the learned strength preferences applied."""
    preferences = load()['strength']
    if not preferences:
        return steps
    return [
        scaled(step, preferences[step['op']]) if step.get('op') in preferences else step for step in steps
    ]


def nudge(steps, factor):
    """Move the learned strength of these kinds of step a little by `factor`."""
    with _lock:
        data = load()
        for op in {step['op'] for step in steps if has_strength(step)}:
            value = data['strength'].get(op, 1.0) * factor
            if abs(value - 1.0) < 0.03:
                data['strength'].pop(op, None)
            else:
                data['strength'][op] = round(max(LOWEST, min(HIGHEST, value)), 3)
        save(data)


# ---- Favorites -------------------------------------------------------------------------


def favorites():
    return list(load()['favorites'])


def set_favorite(name, favorite=True):
    with _lock:
        data = load()
        names = [item for item in data['favorites'] if item != name]
        if favorite:
            names.append(name)
        data['favorites'] = names
        save(data)
        return names


# ---- Taking back the last request -------------------------------------------------------


def _same_document(before, now):
    keys = ('name', 'width', 'height')
    return bool(before) and bool(now) and all(before.get(key) == now.get(key) for key in keys)


def added_layers(before, now):
    """Names of the top-most layers in `now` that were not in `before` (a new group counts,
    not the layers inside it), or None when that cannot be told safely: another picture, a
    changed size, a layer list cut short, or a new layer named like an older one."""
    if not _same_document(before, now):
        return None
    old_layers, new_layers = before.get('layers') or [], now.get('layers') or []
    if len(old_layers) >= 60 or len(new_layers) >= 60:
        return None
    old = Counter((layer['name'], layer['type']) for layer in old_layers)
    remaining = Counter(old)
    added, kept_names, parents = [], set(), []
    for layer in new_layers:
        depth = int(layer.get('depth', 0))
        parents = parents[:depth]
        key = (layer['name'], layer['type'])
        is_new = remaining[key] <= 0
        if not is_new:
            remaining[key] -= 1
            kept_names.add(layer['name'].lower())
        elif not any(parents):
            added.append(layer['name'])
        parents.append(is_new)
    if any(name.lower() in kept_names for name in added) or len(set(added)) != len(added):
        return None
    return added


def _take_back(now):
    """Steps that delete what the last request added, or None if it cannot be done safely."""
    if _last is None or any(step.get('op') in IN_PLACE for step in _last['steps']):
        return None
    names = added_layers(_last['before'], now)
    if names is None:
        return None
    return [dict(op='delete_layer', layer=name) for name in names]


def _recent():
    return _last is not None and time.time() - _last['time'] < REDO_SECONDS


# ---- Hooks for planning (workflows.editor_plan) ------------------------------------------


class Intent:
    """How a typed request is understood before planning: `result` is a finished answer
    (forget, redo weaker...), otherwise `text` is planned and `finish` completes it."""

    def __init__(self, request, text, state):
        self.request, self.text, self.state = request, text, state
        self.result = None
        self.notes = []
        self.teach_phrase = None  # learn that this phrase means the planned text
        self.teach_only = False  # only learn; do not change the picture
        self.take_back = []  # steps that remove the last request first
        self.base = state  # the layer list the new request starts from
        self.redo = None  # the last request redone weaker or stronger
        self.correcting = False  # a correction of the last request


def _answer(text, notes=()):
    return dict(steps=[dict(op='say', text=text)], how='memory', notes=list(notes))


def understand(request, state):
    """Read memory commands and corrections in `request` (see the module docstring)."""
    text = ' '.join(str(request).split())
    intent = Intent(request, text, state)

    if FORGET_ALL.match(text):
        count = forget()
        intent.result = _answer(f'Forgotten: {count} thing' + ('s' if count != 1 else '') + ' I had learned.')
        return intent
    match = FORGET.match(text)
    if match:
        count = forget(match['phrase'])
        intent.result = _answer(
            f'Forgotten: "{phrase_key(match["phrase"])}".'
            if count
            else f'I had not learned "{match["phrase"]}".'
        )
        return intent
    for pattern in TEACH:
        match = pattern.match(text)
        if match:
            intent.text, intent.teach_phrase, intent.teach_only = (
                match['means'].strip(),
                match['phrase'],
                True,
            )
            return intent

    weaker, stronger = WEAKER.match(text), STRONGER.match(text)
    if (weaker or stronger) and _recent() and any(has_strength(step) for step in _last['steps']):
        factor = LESS if weaker else MORE
        back = _take_back(state)
        if back is None:
            intent.result = _answer('I cannot take that change back by itself. Press Undo, then ask again.')
            return intent
        nudge(_last['steps'], NUDGE_LESS if weaker else NUDGE_MORE)
        steps = back + [scaled(step, factor) for step in _last['steps']]
        intent.result = dict(
            steps=steps,
            how='memory',
            notes=[
                'Redone ' + ('weaker' if weaker else 'stronger') + '. I will remember you like it that way.'
            ],
        )
        intent.base = _last['before']
        intent.redo = dict(request=_last['request'], steps=[scaled(step, factor) for step in _last['steps']])
        return intent

    for pattern in CORRECT:
        match = pattern.match(text)
        if match and _recent():
            intent.text = match['means'].strip()
            intent.teach_phrase = _last['request']
            intent.correcting = True
            back = _take_back(state)
            if back is None:
                intent.teach_only = True
                intent.notes.append(
                    'I could not take the last change back by itself. Press Undo, then ask again.'
                )
            else:
                intent.take_back = back
                intent.base = _last['before']
            return intent

    rewritten, used = rewrite(text)
    if used:
        intent.text = rewritten
        intent.notes.append('Using what you taught me: ' + ', '.join(f'"{phrase}"' for phrase in used) + '.')
    return intent


def finish(intent, steps, how, notes=()):
    """The plan after memory: learned strengths applied, a lesson saved, and the last change
    taken back first when this is a correction. `notes` are the planner's. Returns (steps,
    how, notes)."""
    global _last
    notes = list(notes) + list(intent.notes)
    if intent.result is not None:
        steps, how = intent.result['steps'], intent.result['how']
        notes = intent.result.get('notes', []) + notes
        redo = intent.redo
        if redo is not None:
            _last = dict(
                request=redo['request'],
                steps=redo['steps'],
                how='memory',
                before=intent.base,
                time=time.time(),
            )
        return steps, how, notes

    if not re.search(r'\d', intent.text) and how != 'vision':
        steps = personalize(steps)
    if intent.teach_phrase and steps and not all(step.get('op') == 'say' for step in steps):
        entry = teach(
            intent.teach_phrase, intent.text, source='taught' if intent.teach_only else 'correction'
        )
        if entry is not None:
            notes.append(f'Learned: "{entry["phrase"]}" means "{entry["means"]}".')
    if intent.teach_only:
        if intent.teach_phrase and not any(note.startswith('Learned') for note in notes):
            notes.append('I could not learn that one. Try: remember: <phrase> means <what to do>.')
        return [dict(op='say', text=' '.join(notes) or 'Noted.')], 'memory', notes

    changes = [step for step in steps if step.get('op') != 'say']
    if changes:
        # A second correction in a row still refers to what was first asked.
        request = intent.teach_phrase if intent.correcting else intent.request
        _last = dict(request=request, steps=changes, how=how, before=intent.base, time=time.time())
    return intent.take_back + steps, how, notes


# ---- What the studio knows (Settings page) -----------------------------------------------


def profile():
    """The settings most of the favorite pictures were made with."""
    from image_studio.core.catalog import MODELS
    from image_studio.core.paths import IMAGES

    repos = {entry.get('repo'): key for key, entry in MODELS.items()}
    counts = dict(model=Counter(), size=Counter(), finish=Counter(), realism=Counter())
    for name in favorites():
        try:
            meta = json.loads((IMAGES / name).with_suffix('.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        model = repos.get(meta.get('model')) or meta.get('model_key')
        if model:
            counts['model'][model] += 1
        if meta.get('width') and meta.get('height'):
            counts['size'][f'{meta["width"]} × {meta["height"]}'] += 1
        if meta.get('finish'):
            counts['finish'][str(meta['finish'])] += 1
        counts['realism'][round(float((meta.get('realism_lora') or {}).get('strength', 0)), 2)] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in counts.items() if counter}


def snapshot():
    data = load()
    return dict(
        words=sorted(data['words'], key=lambda word: -word.get('created', 0)),
        strength=data['strength'],
        favorites=len(data['favorites']),
        profile=profile(),
    )

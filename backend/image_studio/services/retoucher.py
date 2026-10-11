"""The retoucher: plans professional edits with the editing brain (brain.py) and checks its
own color grades before Krita gets them.

1. The brain sees the photo, colorist measurements of it (grading.stats) and the request,
   and answers with steps: Krita operations (agent.OPS), AI edits, and `grade` steps that
   hold layers of a raw-developer / color-grading recipe with masks (grading.py).
2. Each grade is rendered on a preview and the brain compares it with the original and the
   request, then corrects the numbers (up to REVIEWS times) until it looks right.
3. Krita runs the steps; a grade becomes a group of layers with masks (runner.py)."""

import json
import re

from image_studio.services import agent, brain, grading

REVIEWS = 2
PREVIEW = 768

# Simple color operations of Krita that a grade does better; the brain uses grades instead.
GRADED = {'brightness', 'contrast', 'saturation', 'hue', 'warmth', 'tint', 'black_and_white', 'sepia',
          'colorize', 'auto_levels', 'vignette', 'grain', 'relight'}
BRAIN_OPS = [name for name in agent.OPS if name not in GRADED and name != 'recolor_selection']

NUMBER = {'type': 'number'}
WHEEL = {'type': 'object', 'properties': {'hue': NUMBER, 'amount': NUMBER, 'luminance': NUMBER},
         'additionalProperties': False}
BAND = {'type': 'object', 'properties': {'hue': NUMBER, 'saturation': NUMBER, 'luminance': NUMBER},
        'additionalProperties': False}
MASK_SCHEMA = {
    'type': 'object',
    'properties': {
        'kind': {'enum': ['everything', 'object', 'luminance', 'color', 'linear', 'radial']},
        'target': {'type': 'string'}, 'from': {}, 'to': NUMBER, 'hue': NUMBER, 'range': NUMBER,
        'start': NUMBER, 'end': NUMBER, 'x': NUMBER, 'y': NUMBER, 'size': NUMBER, 'inside': {'type': 'boolean'},
        'invert': {'type': 'boolean'}, 'feather': NUMBER,
    },
    'required': ['kind'], 'additionalProperties': False,
}
CURVE = {'type': 'array', 'items': {'type': 'array', 'items': NUMBER, 'minItems': 2, 'maxItems': 2},
         'maxItems': 8}
LAYER_SCHEMA = {
    'type': 'object',
    'properties': dict(
        {'name': {'type': 'string'}, 'mask': MASK_SCHEMA},
        **{key: NUMBER for key in ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks',
                                   'temperature', 'tint', 'vibrance', 'saturation', 'clarity', 'texture',
                                   'dehaze', 'fade', 'glow', 'halation', 'vignette', 'grain', 'amount')},
        **{key: CURVE for key in ('curve', 'curve_red', 'curve_green', 'curve_blue')},
        **{key: WHEEL for key in ('shadows_color', 'midtones_color', 'highlights_color')},
        hsl={'type': 'object', 'properties': {band: BAND for band in grading.BANDS}, 'additionalProperties': False},
        split_toning={'type': 'object', 'properties': {key: NUMBER for key in (
            'shadow_hue', 'shadow_saturation', 'highlight_hue', 'highlight_saturation', 'balance')},
            'additionalProperties': False},
    ),
    'required': ['name'], 'additionalProperties': False,
}
ARGS = {'target', 'color', 'instruction', 'description', 'replacement', 'text', 'position', 'font', 'aspect',
        'name', 'layer', 'mode', 'direction'}
NUMBERS = {'amount', 'degrees', 'size', 'scale', 'width', 'height', 'radius', 'pixels', 'opacity', 'times',
           'x', 'y', 'w', 'h', 'dx', 'dy', 'strength', 'levels', 'level', 'angle', 'length'}
GRADE_KNOBS = {
    'look': {'enum': ['none'] + list(grading.LOOKS)}, 'strength': NUMBER,
    'light_x': NUMBER, 'light_y': NUMBER, 'horizon': NUMBER,
    'adjust': {'type': 'object', 'properties': {key: NUMBER for key in grading.ADJUST},
               'additionalProperties': False},
    'local': {'type': 'array', 'items': LAYER_SCHEMA, 'maxItems': 4},
}
KNOBS = list(GRADE_KNOBS)
# The review answers with judgments, not numbers: a 9B model judges reliably but sets
# numbers erratically (measured: it swung between "blown out" and "too dark" when it wrote
# the settings itself). Each judgment moves one setting by a fixed step.
JUDGE = lambda *choices: {'enum': list(choices)}  # noqa: E731
REVIEW_SCHEMA = {
    'type': 'object',
    'properties': {
        'problems': {'type': 'string'},
        'effect': JUDGE('much weaker', 'weaker', 'right', 'stronger', 'much stronger'),
        'brightness': JUDGE('darker', 'right', 'brighter'),
        'warmth': JUDGE('cooler', 'right', 'warmer'),
        'colorfulness': JUDGE('less', 'right', 'more'),
        'light_in_right_place': {'type': 'boolean'},
        'light_x': NUMBER, 'light_y': NUMBER,
    },
    'required': ['problems', 'effect', 'brightness', 'warmth', 'colorfulness', 'light_in_right_place'],
    'additionalProperties': False,
}
STEPS = {
    'effect': {'much weaker': -40, 'weaker': -20, 'stronger': 20, 'much stronger': 40},
    'brightness': {'darker': -0.2, 'brighter': 0.2},
    'warmth': {'cooler': -10, 'warmer': 10},
    'colorfulness': {'less': -12, 'more': 12},
}
# Limits for the planner's own numbers unless the request asks for something extreme.
TASTE = dict(exposure=0.6, default=40)
EXTREME = re.compile(r'\b(very|much|extreme|extremely|dramatic|strong|heavily|a lot|way)\b', re.I)
STEP_SCHEMA = {
    'anyOf': [
        {'type': 'object', 'properties': dict({'op': {'const': 'grade'}}, **GRADE_KNOBS),
         'required': ['op', 'look', 'strength', 'adjust'], 'additionalProperties': False},
        {'type': 'object', 'properties': dict(
            {'op': {'enum': BRAIN_OPS}}, **{key: {'type': 'string'} for key in ARGS},
            **{key: NUMBER for key in NUMBERS}),
         'required': ['op'], 'additionalProperties': False},
    ]
}
PLAN_SCHEMA = {
    'type': 'object',
    'properties': {'seen': {'type': 'string'}, 'approach': {'type': 'string'},
                   'steps': {'type': 'array', 'items': STEP_SCHEMA, 'maxItems': 12}},
    'required': ['seen', 'approach', 'steps'], 'additionalProperties': False,
}
GRADE_KNOBS = {
    'look': {'enum': ['none'] + list(grading.LOOKS)}, 'strength': NUMBER,
    'light_x': NUMBER, 'light_y': NUMBER, 'horizon': NUMBER,
    'adjust': {'type': 'object', 'properties': {key: NUMBER for key in grading.ADJUST},
               'additionalProperties': False},
    'local': {'type': 'array', 'items': LAYER_SCHEMA, 'maxItems': 4},
}
KNOBS = list(GRADE_KNOBS)
# The review answers with judgments, not numbers: a 9B model judges reliably but sets
# numbers erratically (measured: it swung between "blown out" and "too dark" when it wrote
# the settings itself). Each judgment moves one setting by a fixed step.
JUDGE = lambda *choices: {'enum': list(choices)}  # noqa: E731
REVIEW_SCHEMA = {
    'type': 'object',
    'properties': {
        'problems': {'type': 'string'},
        'effect': JUDGE('much weaker', 'weaker', 'right', 'stronger', 'much stronger'),
        'brightness': JUDGE('darker', 'right', 'brighter'),
        'warmth': JUDGE('cooler', 'right', 'warmer'),
        'colorfulness': JUDGE('less', 'right', 'more'),
        'light_in_right_place': {'type': 'boolean'},
        'light_x': NUMBER, 'light_y': NUMBER,
    },
    'required': ['problems', 'effect', 'brightness', 'warmth', 'colorfulness', 'light_in_right_place'],
    'additionalProperties': False,
}
STEPS = {
    'effect': {'much weaker': -40, 'weaker': -20, 'stronger': 20, 'much stronger': 40},
    'brightness': {'darker': -0.2, 'brighter': 0.2},
    'warmth': {'cooler': -10, 'warmer': 10},
    'colorfulness': {'less': -12, 'more': 12},
}
# Limits for the planner's own numbers unless the request asks for something extreme.
TASTE = dict(exposure=0.6, default=40)
EXTREME = re.compile(r'\b(very|much|extreme|extremely|dramatic|strong|heavily|a lot|way)\b', re.I)
STEP_SCHEMA = {
    'anyOf': [
        {'type': 'object', 'properties': dict({'op': {'const': 'grade'}}, **GRADE_KNOBS),
         'required': ['op', 'look', 'strength', 'adjust'], 'additionalProperties': False},
        {'type': 'object', 'properties': dict(
            {'op': {'enum': BRAIN_OPS}}, **{key: {'type': 'string'} for key in ARGS},
            **{key: NUMBER for key in NUMBERS}),
         'required': ['op'], 'additionalProperties': False},
    ]
}
PLAN_SCHEMA = {
    'type': 'object',
    'properties': {'seen': {'type': 'string'}, 'approach': {'type': 'string'},
                   'steps': {'type': 'array', 'items': STEP_SCHEMA, 'maxItems': 12}},
    'required': ['seen', 'approach', 'steps'], 'additionalProperties': False,
}
REVIEW_SCHEMA = {
    'type': 'object',
    'properties': dict({'problems': {'type': 'string'}, 'looks_right': {'type': 'boolean'}}, **GRADE_KNOBS),
    'required': ['problems', 'looks_right', 'look', 'strength', 'adjust'], 'additionalProperties': False,
}

SYSTEM = f"""You are a senior photo retoucher and colorist working in Krita. You see the photo, measurements of it and a request. Plan the edit a professional would make, as JSON steps.

STEP OPERATIONS
- grade: the tool for ALL light, color, tone and mood work: exposure, contrast, white balance, color grading, time of day, film looks, black and white, vignette, grain. A professional grading engine builds it from your choices:
  look: a finished look made of several masked layers, or "none": {', '.join(grading.LOOKS)}.
  strength: 0-150, how strong the look is (100 = standard).
  light_x, light_y: where the light source (the sun) is or should be, percent of width and height (x 0 = left, y 0 = top). For a sunset or sunrise put it low on the horizon, on the side the light comes from.
  horizon: height of the horizon in percent from the top (where sky meets land or sea).
  adjust: global corrections after the look, each -100..100 (exposure in stops, -2..2): {', '.join(grading.ADJUST)}.
  local: optional extra layers for one area, e.g. brighten a face or darken the sky: {{"name": "...", "mask": <mask>, <adjust keys>}}. {grading.MASK}
{agent.catalog_text_for(BRAIN_OPS)}

HOW A PROFESSIONAL WORKS
- Lighting, time of day, mood, weather light and color changes are grades, never ai_edit: they keep every detail of the photo. Only use ai_edit, replace or remove when objects must appear, disappear or change shape or material.
- Changing the color of one object (a building, car, shirt) is recolor.
- Pick the look that matches the request and place the light and horizon where they are in THIS photo. A look is already balanced (it darkens for sunsets and night by itself): leave adjust empty unless the request asks for more, such as brighter or more contrast.
- Without a look (look "none"), adjust does the work, e.g. fixing a dull, dark or color-cast photo.
- Read the measurements: protect clipped highlights (highlights -), open crushed shadows (shadows +), remove color casts with temperature/tint.
- Be tasteful: typical adjust values are 5-30. Use only what the request needs; never crop, resize, flatten or delete unless asked.
- "seen": what in the photo matters for this edit (light direction, horizon height, subject). "approach": the plan in one or two sentences."""

REVIEW_SYSTEM = """You are a senior colorist checking a grade. You see the ORIGINAL photo first, then the GRADED result, then the request. Judge the graded result like a demanding client: does it do what was asked, convincingly and naturally, as a real photo would look?
Answer each question about the GRADED result: is the effect too weak or too strong for the request, should it be darker or brighter, cooler or warmer, less or more colorful? Answer "right" when it is right; most good grades are "right" on every question. Is the light (glow, sun) in a believable place? If not, give light_x, light_y in percent where it should be. In "problems" say briefly what you see."""


def describe_state(state):
    return agent.describe_document(state)


def grade_knobs(raw):
    """The grade settings from an answer, without unknown keys."""
    knobs = {key: raw[key] for key in KNOBS if key in raw}
    if knobs.get('look') == 'none':
        knobs['look'] = None
    return knobs


def plan(request, image, state=None, status=print, known=None, whole=None):
    """Steps for a request, with every grade reviewed on a preview. Returns (steps, notes).
    `known`: steps already planned for other parts of the `whole` request."""
    preview = image.convert('RGB')
    preview.thumbnail((PREVIEW, PREVIEW))
    measurements = grading.stats(preview)
    status('Studying the photo...')
    done = ''
    if known:
        done = (f'\n(The rest of the request, "{whole}", is already handled by these steps: '
                f'{", ".join(agent.summary(step) for step in known)}. Plan only the request below.)')
    answer = brain.chat(
        SYSTEM,
        [brain.image_part(preview),
         {'type': 'text', 'text': f'{describe_state(state)}\nMeasurements: {json.dumps(measurements)}{done}\n'
                                  f'Request: {request}'}],
        schema=PLAN_SCHEMA, max_tokens=3000)
    notes = [answer.get('seen', ''), answer.get('approach', '')]
    steps = list(known or [])
    for raw in answer.get('steps') or []:
        if raw.get('op') == 'grade':
            # One grade per request: its layers already cover global and local work. (Measured:
            # a second grade the model added on its own turned the sky almost black.)
            if not any(step['op'] == 'grade' for step in steps):
                steps.append(dict(op='grade', knobs=grade_knobs(raw)))
        else:
            steps.extend(agent.normalize([raw]))
    steps = agent.check(steps, whole or request, state)
    if not re.search(r'\bselect', whole or request, re.I):
        steps = unused_selections_dropped(steps)
    # A colorist grades last: content and color changes first, so the grade's light falls on
    # them too; then canvas changes and saving.
    late = {'crop', 'crop_to_selection', 'resize', 'rotate', 'flip', 'save_to_library', 'say'}
    steps = ([step for step in steps if step['op'] != 'grade' and step['op'] not in late]
             + [step for step in steps if step['op'] == 'grade']
             + [step for step in steps if step['op'] in late])
    masks = {}
    for step in steps:
        if step['op'] == 'grade':
            step['knobs'] = review(request, preview, step['knobs'], masks, status)
            step['layers'] = grading.build_layers(**step['knobs'])
            step['label'] = 'Grade: ' + (step['knobs'].get('look') or 'adjustments')
    steps = [step for step in steps if step['op'] != 'grade' or step['layers']]
    return steps, [note for note in notes if note]


SELECTING = {'select', 'select_box', 'invert_selection', 'grow_selection', 'feather_selection'}


def unused_selections_dropped(steps):
    """Steps without selections that no later step uses before the next deselect (a grade
    ignores selections: it has its own masks). They cost a segmentation for nothing."""
    out, pending = [], []
    for step in steps:
        if step['op'] in SELECTING:
            pending.append(step)
        elif step['op'] == 'deselect':
            if not pending and not (out and out[-1]['op'] == 'deselect'):
                out.append(step)
            pending = []
        elif step['op'] == 'grade':
            out.append(step)
        else:
            out += pending + [step]
            pending = []
    return out


def object_mask(preview, masks, status):
    """segment(target) for grading.make_mask, remembering each target's mask."""
    from image_studio.services import segment

    def find(target):
        key = target.lower().strip()
        if key not in masks:
            status(f'Finding {target}...')
            masks[key] = segment.select(preview, target, status=status)[0]
        return masks[key].resize(preview.size)
    return find


AREA = re.compile(r'\b(sky|face|skin|eyes?|hair|background|foreground|subject|person|people|water|sea|'
                  r'buildings?|shadows?|highlights?|corners?|edges?|left|right|top|bottom)\b', re.I)


def tasteful(knobs, request):
    """The planner's numbers kept to what the request asks for: a finished look is calibrated,
    so corrections on top of it stay small, and local layers need an area named in the request."""
    extreme = EXTREME.search(request)
    with_look = bool(knobs.get('look'))
    adjust = {}
    for key, value in (knobs.get('adjust') or {}).items():
        if not isinstance(value, (int, float)):
            continue
        if key == 'exposure':
            limit = 0.6 if extreme else (0.15 if with_look else TASTE['exposure'])
        else:
            limit = 60 if extreme else (15 if with_look else TASTE['default'])
        adjust[key] = max(-limit, min(limit, value))
    knobs = dict(knobs, adjust=adjust)
    if not AREA.search(request):
        knobs['local'] = []
    return knobs


def guard(before, after, knobs, request):
    """Objective checks on the rendered grade: no new clipping, and a change of light that does
    not brighten the picture unless asked. Returns corrected settings or None."""
    adjust = dict(knobs.get('adjust') or {})
    exposure = float(adjust.get('exposure', 0) or 0)
    fixes = []
    if after['clipped_highlights_pct'] > before['clipped_highlights_pct'] + 1.5:
        fixes.append(-0.15)
    look = knobs.get('look') or ''
    asked_brighter = re.search(r'\b(bright|lighter|exposure|lift)', request, re.I)
    if look in ('sunset', 'blue hour', 'night', 'sunrise') and not asked_brighter \
            and after['median_brightness'] > before['median_brightness'] + 3:
        fixes.append(-0.15)
    if not fixes:
        return None
    adjust['exposure'] = round(exposure + min(fixes), 2)
    return dict(knobs, adjust=adjust)


def judged(knobs, verdict):
    """Settings moved one step in the direction of each judgment."""
    knobs = dict(knobs)
    adjust = dict(knobs.get('adjust') or {})
    knobs['strength'] = max(0, min(150, float(knobs.get('strength') or 100)
                                   + STEPS['effect'].get(verdict.get('effect'), 0)))
    for key, judgment, setting in (('brightness', verdict.get('brightness'), 'exposure'),
                                   ('warmth', verdict.get('warmth'), 'temperature'),
                                   ('colorfulness', verdict.get('colorfulness'), 'vibrance')):
        step = STEPS[key].get(judgment, 0)
        if step:
            adjust[setting] = round(float(adjust.get(setting, 0) or 0) + step, 2)
    knobs['adjust'] = adjust
    if not verdict.get('light_in_right_place'):
        for key in ('light_x', 'light_y'):
            if isinstance(verdict.get(key), (int, float)):
                knobs[key] = grading.percent(verdict[key])
    return knobs


def changed(verdict):
    return any(verdict.get(key) not in (None, 'right') for key in STEPS) or not verdict.get('light_in_right_place', True)


def render(preview, knobs, find, status):
    try:
        return grading.render_layers(preview, grading.build_layers(**knobs), find)[1], knobs
    except ValueError as exc:
        # A mask that cannot be made (nothing matched): drop that local layer.
        status(str(exc))
        knobs = dict(knobs, local=[layer for layer in knobs.get('local') or []
                                   if (layer.get('mask') or {}).get('kind') != 'object'])
        return grading.render_layers(preview, grading.build_layers(**knobs), find)[1], knobs


def review(request, preview, knobs, masks, status):
    """Grade settings corrected by measuring and looking at the rendered result."""
    find = object_mask(preview, masks, status)
    before = grading.stats(preview)
    knobs = tasteful(knobs, request)
    for attempt in range(REVIEWS + 1):
        status('Rendering the grade...' if attempt == 0 else f'Correcting the grade ({attempt})...')
        graded, knobs = render(preview, knobs, find, status)
        fixed = guard(before, grading.stats(graded), knobs, request)
        if fixed is not None:
            knobs = fixed
            graded, knobs = render(preview, knobs, find, status)
        if attempt == REVIEWS:
            break
        status('Checking the result...')
        verdict = brain.chat(
            REVIEW_SYSTEM,
            [{'type': 'text', 'text': 'ORIGINAL:'}, brain.image_part(preview),
             {'type': 'text', 'text': 'GRADED:'}, brain.image_part(graded),
             {'type': 'text', 'text': f'Request: {request}'}],
            schema=REVIEW_SCHEMA, max_tokens=600)
        if not changed(verdict):
            break
        status(f'Adjusting: {short(verdict.get("problems", ""))}')
        knobs = judged(knobs, verdict)
    return knobs


def short(text, limit=80):
    text = ' '.join(re.sub(r'\s+', ' ', str(text)).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'

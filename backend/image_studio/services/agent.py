"""Editing by prompt: a request such as "blur the background and make it warmer" becomes
a list of steps that Krita runs (see krita-plugin/ai_prompt/ops.py).

Steps are of three kinds:
- Krita's own tools: selections, adjustment layers (non-destructive filter layers), canvas
  changes (crop, resize, rotate, flip), layers, text, fills.
- AI steps that run on this laptop's GPU through the bridge: select an object by
  description (Qwen3-VL finds it, SAM 2.1 outlines it), change pictures by instruction
  (FLUX.1 Kontext), new pictures (Z-Image / RealVisXL), detail and face repair.
- Messages back to the person (`say`).

Common requests are understood instantly by rules (`quick_plan`); anything else is
planned by the prompt assistant (Qwen3-VL-2B), whose answer is checked against OPS so
only known operations with valid arguments reach Krita."""

import json
import re

# Argument specs: (type, default, low, high) for numbers, (str, default) for text,
# (list of choices, default) for choices, (bool, default). Required text has default None.
DIRECTIONS = ['horizontal', 'vertical']
POSITIONS = [
    'top',
    'center',
    'bottom',
    'top left',
    'top right',
    'bottom left',
    'bottom right',
    'left',
    'right',
]
# Lighting looks for relight, graded by the grading engine (grading.LOOKS has the same names).
LIGHTS = ['sunset', 'golden hour', 'sunrise', 'blue hour', 'night', 'overcast', 'midday']
LIGHT_WORDS = {'evening': 'sunset', 'dusk': 'sunset', 'dawn': 'sunrise', 'morning': 'sunrise', 'noon': 'midday',
               'daylight': 'midday', 'cloudy': 'overcast', 'golden': 'golden hour', 'twilight': 'blue hour'}
BLEND_MODES = {
    'normal': 'normal',
    'multiply': 'multiply',
    'screen': 'screen',
    'overlay': 'overlay',
    'soft light': 'soft_light',
    'hard light': 'hard_light',
    'color': 'color',
    'hue': 'hue',
    'saturation': 'saturation',
    'luminosity': 'luminize',
    'darken': 'darken',
    'lighten': 'lighten',
    'color dodge': 'dodge',
    'color burn': 'burn',
    'add': 'add',
    'subtract': 'subtract',
    'difference': 'diff',
    'exclusion': 'exclusion',
    'divide': 'divide',
}
OPS = {
    # Selection: later steps change only the selected area, until deselect.
    'select': dict(
        args=dict(target=(str, None)),
        group='selection',
        doc='select something by description: "the dog", "the woman on the left", "sky", "subject", "background", "all"',
    ),
    'select_box': dict(
        args=dict(x=(float, 25, 0, 100), y=(float, 25, 0, 100), w=(float, 50, 1, 100), h=(float, 50, 1, 100)),
        group='selection',
        doc='select a rectangle; x, y, w, h in percent of the picture',
    ),
    'invert_selection': dict(args={}, group='selection', doc='swap selected and unselected'),
    'grow_selection': dict(
        args=dict(pixels=(int, 10, 1, 200)), group='selection', doc='enlarge the selection'
    ),
    'feather_selection': dict(args=dict(pixels=(int, 10, 1, 200)), group='selection', doc='soften its edge'),
    'deselect': dict(args={}, group='selection', doc='select nothing (later steps change the whole picture)'),
    # Light and color: each is an adjustment layer you can change or delete later.
    'brightness': dict(
        args=dict(amount=(int, 25, -100, 100)), group='color', doc='lighter (+) or darker (-)'
    ),
    'contrast': dict(
        args=dict(amount=(int, 25, -100, 100)), group='color', doc='more (+) or less (-) contrast'
    ),
    'saturation': dict(
        args=dict(amount=(int, 25, -100, 100)), group='color', doc='more (+) or less (-) vivid color'
    ),
    'hue': dict(
        args=dict(degrees=(int, 30, -180, 180)), group='color', doc='shift all colors around the color wheel'
    ),
    'warmth': dict(
        args=dict(amount=(int, 20, -100, 100)), group='color', doc='warmer/orange (+) or cooler/blue (-)'
    ),
    'tint': dict(args=dict(amount=(int, 20, -100, 100)), group='color', doc='magenta (+) or green (-)'),
    'black_and_white': dict(args={}, group='color', doc='grayscale'),
    'sepia': dict(args=dict(strength=(int, 60, 0, 100)), group='color', doc='old brown photo tone'),
    'colorize': dict(args=dict(color=(str, 'blue')), group='color', doc='tint everything one color'),
    'recolor': dict(
        args=dict(target=(str, None), color=(str, None)),
        group='color',
        doc='change the color of one thing (building, car, wall, shirt, sky), keeping its texture and shading; color is a name or #rrggbb',
    ),
    'recolor_selection': dict(
        args=dict(color=(str, None)), group='color', doc='change the color of what is selected'
    ),
    'relight': dict(
        args=dict(time=(LIGHTS, 'sunset'), strength=(int, 100, 10, 150)),
        group='color',
        doc='change the lighting / time-of-day mood of the whole photo with grading layers; every object and the sky stay as they are',
    ),
    'auto_levels': dict(args={}, group='color', doc='fix dull or faded light and color automatically'),
    'invert_colors': dict(args={}, group='color', doc='negative image'),
    'posterize': dict(args=dict(levels=(int, 6, 2, 64)), group='color', doc='few flat color bands'),
    'threshold': dict(args=dict(level=(int, 128, 1, 254)), group='color', doc='pure black and white'),
    # Effects (also adjustment layers).
    'blur': dict(args=dict(radius=(int, 10, 1, 200)), group='effect', doc='soft blur'),
    'motion_blur': dict(
        args=dict(angle=(int, 0, -180, 180), length=(int, 30, 1, 400)),
        group='effect',
        doc='streaks of movement',
    ),
    'lens_blur': dict(args=dict(radius=(int, 12, 1, 100)), group='effect', doc='camera out-of-focus blur'),
    'sharpen': dict(args=dict(amount=(int, 50, 1, 100)), group='effect', doc='crisper edges'),
    'denoise': dict(args=dict(strength=(int, 50, 1, 100)), group='effect', doc='remove grain and noise'),
    'grain': dict(args=dict(amount=(int, 20, 1, 100)), group='effect', doc='add film grain'),
    'pixelate': dict(args=dict(size=(int, 16, 2, 200)), group='effect', doc='big square pixels'),
    'oil_paint': dict(args=dict(size=(int, 3, 1, 10)), group='effect', doc='oil painting look'),
    'emboss': dict(args={}, group='effect', doc='raised relief look'),
    'edges': dict(
        args={}, group='effect', doc='glowing edge-detection filter (not a drawing or sketch style)'
    ),
    'vignette': dict(args=dict(amount=(int, 50, 1, 100)), group='effect', doc='darker corners'),
    'round_corners': dict(args=dict(radius=(int, 40, 1, 500)), group='effect', doc='rounded picture corners'),
    # Canvas.
    'crop': dict(
        args=dict(aspect=(str, '1:1')),
        group='canvas',
        doc='crop around the center to a shape like "1:1", "16:9", "4:5"',
    ),
    'crop_to_selection': dict(args={}, group='canvas', doc='crop to the selected area'),
    'resize': dict(
        args=dict(scale=(float, 0, 0, 800), width=(int, 0, 0, 16000), height=(int, 0, 0, 16000)),
        group='canvas',
        doc='scale in percent, or a width and/or height in pixels',
    ),
    'rotate': dict(
        args=dict(degrees=(float, 90, -360, 360)), group='canvas', doc='turn the whole picture clockwise'
    ),
    'flip': dict(args=dict(direction=(DIRECTIONS, 'horizontal')), group='canvas', doc='mirror the picture'),
    'new_canvas': dict(
        args=dict(width=(int, 1024, 64, 8192), height=(int, 1024, 64, 8192)),
        group='canvas',
        doc='start a new empty picture',
    ),
    # Layers.
    'new_layer': dict(args=dict(name=(str, 'Layer')), group='layer', doc='empty layer to paint on'),
    'duplicate_layer': dict(args={}, group='layer', doc='copy the active layer'),
    'delete_layer': dict(
        args=dict(layer=(str, 'active')), group='layer', doc='delete a layer by name, or the active one'
    ),
    'rename_layer': dict(args=dict(name=(str, None)), group='layer', doc='rename the active layer'),
    'select_layer': dict(args=dict(layer=(str, None)), group='layer', doc='make a layer active by name'),
    'layer_opacity': dict(
        args=dict(opacity=(int, 50, 0, 100)), group='layer', doc='active layer opacity in percent'
    ),
    'blend_mode': dict(
        args=dict(mode=(list(BLEND_MODES), 'multiply')), group='layer', doc='active layer blending mode'
    ),
    'hide_layer': dict(args=dict(layer=(str, 'active')), group='layer', doc='hide a layer'),
    'show_layer': dict(args=dict(layer=(str, 'active')), group='layer', doc='show a layer'),
    'move_layer': dict(
        args=dict(dx=(float, 0, -100, 100), dy=(float, 0, -100, 100)),
        group='layer',
        doc='move the active layer; percent of the picture, + is right / down',
    ),
    'merge_down': dict(args={}, group='layer', doc='merge the active layer into the one below'),
    'flatten': dict(args={}, group='layer', doc='merge all layers into one'),
    'fill': dict(
        args=dict(color=(str, 'white'), opacity=(int, 100, 0, 100)),
        group='layer',
        doc='new layer filled with a color (only the selection, if any)',
    ),
    'add_text': dict(
        args=dict(
            text=(str, None),
            position=(POSITIONS, 'center'),
            size=(int, 8, 1, 50),
            color=(str, 'white'),
            font=(str, 'Arial'),
        ),
        group='layer',
        doc='text layer; size in percent of picture height',
    ),
    # AI (GPU, takes from seconds to minutes).
    'ai_edit': dict(
        args=dict(instruction=(str, None)),
        group='ai',
        doc='change picture content by instruction (objects, clothes, expression, style, weather, time of day); only inside the selection if there is one',
    ),
    'ai_generate': dict(
        args=dict(description=(str, None)),
        group='ai',
        doc='paint a new picture as a layer, filling the selection or the whole canvas',
    ),
    'remove': dict(
        args=dict(target=(str, None)), group='ai', doc='erase an object or person and fill in what is behind'
    ),
    'replace': dict(
        args=dict(target=(str, None), replacement=(str, None)), group='ai', doc='swap one object for another'
    ),
    'replace_background': dict(
        args=dict(description=(str, None)), group='ai', doc='new background, subject kept'
    ),
    'remove_background': dict(args={}, group='ai', doc='make the background transparent'),
    'enhance': dict(
        args=dict(scale=(float, 1.0, 1.0, 2.0)),
        group='ai',
        doc='sharper real-photo detail, repaired faces and hands; scale 1.5 or 2 also enlarges',
    ),
    'fix_faces': dict(args={}, group='ai', doc='repair faces and hands only'),
    # Other.
    'undo': dict(args=dict(times=(int, 1, 1, 50)), group='other', doc="undo Krita's last changes"),
    'redo': dict(args=dict(times=(int, 1, 1, 50)), group='other', doc='redo'),
    'save_to_library': dict(args={}, group='other', doc='save the picture to the Image Studio library'),
    'say': dict(
        args=dict(text=(str, None)), group='other', doc='answer a question or explain what cannot be done'
    ),
}
AI_OPS = {name for name, spec in OPS.items() if spec['group'] == 'ai'} | {'select'}
# Names the model sometimes uses for an operation.
ALIASES = {
    'brighten': 'brightness',
    'exposure': 'brightness',
    'lighten': 'brightness',
    'darken': 'brightness',
    'temperature': 'warmth',
    'warm': 'warmth',
    'cool': 'warmth',
    'grayscale': 'black_and_white',
    'greyscale': 'black_and_white',
    'desaturate': 'black_and_white',
    'bw': 'black_and_white',
    'gaussian_blur': 'blur',
    'noise': 'grain',
    'film_grain': 'grain',
    'mirror': 'flip',
    'scale': 'resize',
    'upscale': 'enhance',
    'text': 'add_text',
    'write': 'add_text',
    'inpaint': 'ai_edit',
    'edit': 'ai_edit',
    'generate': 'ai_generate',
    'create': 'ai_generate',
    'erase': 'remove',
    'delete': 'remove',
    'select_all': 'select',
    'select_none': 'deselect',
    'clear_selection': 'deselect',
    'invert': 'invert_colors',
    'opacity': 'layer_opacity',
    'auto_contrast': 'auto_levels',
    'auto_enhance': 'auto_levels',
    'auto_color': 'auto_levels',
    'unsharp_mask': 'sharpen',
    'reduce_noise': 'denoise',
    'blending_mode': 'blend_mode',
    'remove_bg': 'remove_background',
    'change_background': 'replace_background',
    'message': 'say',
    'reply': 'say',
    'recolour': 'recolor',
    'change_color': 'recolor',
    'change_colour': 'recolor',
    'color_change': 'recolor',
    'relighting': 'relight',
    'lighting': 'relight',
    'light': 'relight',
    'time_of_day': 'relight',
    'color_grade': 'relight',
}

SYSTEM = """You plan edits in a photo editor. Turn the request into steps using ONLY these operations, and answer with JSON only: {"steps": [{"op": "<name>", <arguments>}]}.

%s

Rules:
- Light, color and effects use the adjustment and effect operations, never ai_edit.
- Changing the color of one thing (a building, car, wall, shirt) uses recolor, never ai_edit or fill.
- Changing the lighting, mood or time of day ("sunset light", "golden hour", "make it look like night") uses relight. It keeps the sky; use replace on the sky only when the request asks for a new sky, clouds, a sun or a moon.
- Anything that changes what is in the picture (add, remove or change objects, clothes, materials, patterns, weather, style, scenery) uses ai_edit, remove, replace or replace_background.
- Adding something to the photo is ai_edit. ai_generate only paints a whole new picture.
- To adjust only one part (the sky, the background, a person), select it first, then adjust, then deselect.
- fill covers an area with flat paint; use it only when asked to fill an area with a flat or solid color.
- Never delete, merge or flatten layers unless the request says so.
- Amounts: "a bit"/"slightly" = 15, plain = 30, "much"/"very" = 60.
- Questions, or requests that are impossible: use say."""

EXAMPLES = [
    (
        'make it a bit brighter and warmer',
        '{"steps": [{"op": "brightness", "amount": 15}, {"op": "warmth", "amount": 15}]}',
    ),
    (
        'make the background darker',
        '{"steps": [{"op": "select", "target": "background"}, {"op": "brightness", "amount": -30}, {"op": "deselect"}]}',
    ),
    ('remove the man on the left', '{"steps": [{"op": "remove", "target": "the man on the left"}]}'),
    ('select the lamp and delete it', '{"steps": [{"op": "remove", "target": "the lamp"}]}'),
    (
        'black and white with strong contrast, then crop to square',
        '{"steps": [{"op": "black_and_white"}, {"op": "contrast", "amount": 60}, {"op": "crop", "aspect": "1:1"}]}',
    ),
    (
        'replace the sky with a stormy sunset',
        '{"steps": [{"op": "replace", "target": "the sky", "replacement": "a dramatic stormy sunset sky"}]}',
    ),
    ('make the car red', '{"steps": [{"op": "recolor", "target": "the car", "color": "red"}]}'),
    (
        'change the color of the buildings to a light terracotta',
        '{"steps": [{"op": "recolor", "target": "the buildings", "color": "#d98c5f"}]}',
    ),
    ('change the background lighting to sunset', '{"steps": [{"op": "relight", "time": "sunset", "strength": 100}]}'),
    (
        'make it look like a moody night scene',
        '{"steps": [{"op": "relight", "time": "night", "strength": 110}]}',
    ),
    (
        'give it a sunset sky with the sun on the horizon',
        '{"steps": [{"op": "replace", "target": "the sky", "replacement": "a warm sunset sky with the sun low on the horizon"}, {"op": "relight", "time": "sunset", "strength": 90}]}',
    ),
    (
        'make the jacket leather',
        '{"steps": [{"op": "select", "target": "the jacket"}, {"op": "ai_edit", "instruction": "Make the jacket black leather. Keep its shape, the person and everything else the same."}, {"op": "deselect"}]}',
    ),
    (
        'add a cup of coffee on the table',
        '{"steps": [{"op": "ai_edit", "instruction": "Add a white cup of coffee on the table. Keep everything else the same."}]}',
    ),
    (
        'write SUMMER SALE at the top in yellow',
        '{"steps": [{"op": "add_text", "text": "SUMMER SALE", "position": "top", "size": 10, "color": "yellow"}]}',
    ),
    (
        'make the sky more blue',
        '{"steps": [{"op": "select", "target": "sky"}, {"op": "saturation", "amount": 30}, {"op": "warmth", "amount": -20}, {"op": "deselect"}]}',
    ),
    (
        'duplicate the layer and set it to multiply at 40% opacity',
        '{"steps": [{"op": "duplicate_layer"}, {"op": "blend_mode", "mode": "multiply"}, {"op": "layer_opacity", "opacity": 40}]}',
    ),
    (
        'make it look like winter',
        '{"steps": [{"op": "ai_edit", "instruction": "Make it winter: snow on the ground and surfaces, cold overcast light. Keep the people, objects and composition the same."}]}',
    ),
    (
        'make it pop',
        '{"steps": [{"op": "contrast", "amount": 20}, {"op": "saturation", "amount": 20}, {"op": "sharpen", "amount": 30}]}',
    ),
    ('cut out the person', '{"steps": [{"op": "remove_background"}]}'),
]


def catalog_text_for(names):
    return '\n'.join(f'- {name}({", ".join(OPS[name]["args"])}): {OPS[name]["doc"]}' for name in names)


def catalog_text():
    lines = []
    for name, spec in OPS.items():
        args = ', '.join(spec['args'])
        lines.append(f'- {name}({args}): {spec["doc"]}')
    return '\n'.join(lines)


def system_prompt():
    return SYSTEM % catalog_text()


# Colors the planner and rules may name; anything else is passed to Krita as written
# (Qt understands CSS color names and #rrggbb).
def clamp(value, low, high):
    return max(low, min(high, value))


def coerce(op, raw):
    """A step with known arguments of the right type, clamped to range, or None."""
    spec = OPS[op]['args']
    step = {'op': op}
    for name, rule in spec.items():
        kind, default = rule[0], rule[1]
        value = raw.get(name, default)
        if value is None:
            # Accept the single text argument under another name ("prompt", "value"...).
            others = [
                v for k, v in raw.items() if k != 'op' and k not in spec and isinstance(v, str) and v.strip()
            ]
            if kind is str and others:
                value = others[0]
            else:
                return None
        try:
            if isinstance(kind, list):
                value = str(value).strip().lower().replace('_', ' ')
                value = (
                    value if value in kind else next((c for c in kind if c.startswith(value[:4])), default)
                )
            elif kind is bool:
                value = bool(value)
            elif kind is str:
                value = ' '.join(str(value).split())[:500]
                if not value:
                    return None
            else:
                value = kind(float(str(value).strip().rstrip('%').replace('px', '')))
                value = clamp(value, rule[2], rule[3])
        except (TypeError, ValueError):
            value = default
            if value is None:
                return None
        step[name] = value
    return step


def expand(step):
    """Macro operations as the steps Krita runs."""
    op = step['op']
    if op == 'remove':
        return [
            dict(op='select', target=step['target']),
            dict(op='grow_selection', pixels=12),
            dict(
                op='ai_edit',
                instruction=f'Remove {step["target"]} completely and fill the area with the '
                'background that would naturally be behind it. Keep everything '
                'else exactly the same.',
                label=f'Remove {step["target"]}',
            ),
            dict(op='deselect'),
        ]
    if op == 'replace':
        return [
            dict(op='select', target=step['target']),
            dict(op='grow_selection', pixels=8),
            dict(
                op='ai_edit',
                instruction=f'Replace {step["target"]} with {step["replacement"]}. Keep '
                'everything else exactly the same.',
                label=f'Replace {step["target"]}',
            ),
            dict(op='deselect'),
        ]
    if op == 'relight':
        from image_studio.services import grading

        return [dict(op='grade', layers=grading.build_layers(look=step['time'], strength=step['strength']),
                     label=f'{step["time"].capitalize()} light')]
    if op == 'recolor':
        return [
            dict(op='select', target=step['target']),
            dict(op='recolor_selection', color=step['color'], label=f'Recolor {step["target"]} {step["color"]}'),
            dict(op='deselect'),
        ]
    if op == 'replace_background':
        return [
            dict(op='select', target='background'),
            dict(
                op='ai_edit',
                instruction=f'Change the background to {step["description"]}. Keep the '
                'subject, their pose, face and outline exactly the same.',
                label='New background',
            ),
            dict(op='deselect'),
        ]
    return [step]


def normalize(steps):
    """Known steps with valid arguments, macros expanded. Unknown steps are dropped."""
    result = []
    for raw in steps if isinstance(steps, list) else []:
        if not isinstance(raw, dict):
            continue
        op = (
            str(raw.get('op') or raw.get('operation') or raw.get('name') or '')
            .strip()
            .lower()
            .replace(' ', '_')
        )
        op = ALIASES.get(op, op)
        if op not in OPS:
            continue
        if op == 'brightness' and str(raw.get('op', '')).lower() == 'darken' and 'amount' in raw:
            raw = dict(raw, amount=-abs(float(raw['amount'])))
        if op == 'relight':
            time = str(raw.get('time') or raw.get('mood') or raw.get('look') or 'sunset').strip().lower()
            time = time.replace('_', ' ').removesuffix(' light').removesuffix(' lighting')
            raw = dict(raw, time=LIGHT_WORDS.get(time, time))
        step = coerce(op, raw)
        if step is not None:
            result.extend(expand(step))
    return result


def parse(answer):
    """The steps in the planner's answer (JSON, possibly inside a code fence)."""
    text = re.sub(r'<think>.*?</think>', '', answer, flags=re.S)
    match = re.search(r'\{.*\}|\[.*\]', text, flags=re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get('steps', [data] if 'op' in data else [])
    return data if isinstance(data, list) else []


# ---- Instant rules for common requests -------------------------------------------------

AMOUNTS = [
    (r'\b(slightly|a (little )?bit|a touch|subtly|little)\b', 15),
    (r'\b(much|very|lot|strongly|way|really|super|heavily|extremely)\b', 60),
]
NUMBER = r'(-?\d+(?:\.\d+)?)'


def amount(text, plain=30):
    number = re.search(NUMBER + r'\s*%', text)
    if number:
        return int(float(number.group(1)))
    for pattern, value in AMOUNTS:
        if re.search(pattern, text):
            return value
    return plain


COLORS_RE = (
    'white|black|red|green|blue|yellow|orange|purple|pink|grey|gray|brown|gold|golden|silver|cyan|magenta|navy|'
    'teal|beige|maroon|violet|cream|coral|turquoise|olive|lavender|crimson|ivory|tan|khaki|salmon|indigo'
)
TIMES = '|'.join(sorted(LIGHTS + list(LIGHT_WORDS), key=len, reverse=True))
LIGHT_RULES = [
    # "change the (background) lighting to sunset", "set the mood to golden hour"
    re.compile(
        r'^(?:change|set|make|turn|switch|adjust)(?: the)?(?: (?:background|scene|photo|overall))? '
        r'(?:light(?:ing)?|mood|tone|atmosphere|time of day|colou?r grad(?:e|ing))'
        r'(?: of (?:the |this )?(?:photo|picture|image|scene))?(?: to| into| like| for)?(?: an?| the)? '
        rf'(?P<time>{TIMES})(?: time| light(?:ing)?| look| mood| vibe)?$'
    ),
    # "sunset lighting", "give it golden hour light", "make it look like blue hour lighting"
    re.compile(
        r'^(?:(?:give it|add|apply|use|make it(?: look like)?)(?: an?| some| the)? )?'
        rf'(?P<time>{TIMES})(?: time)? (?:light(?:ing)?|glow|mood|look|tone|colou?r grad(?:e|ing))$'
    ),
]
RECOLOR_RULE = re.compile(
    r'^(?:make|turn|paint|colou?r|recolou?r|change)(?: the colou?rs? of)? (?P<target>the [a-z][a-z \'-]*?)'
    r'(?: colou?rs?)?(?: to| into| in)?(?: an?)? (?P<color>(?:(?:light|dark|bright|deep|pale|pastel|soft|baby) )?(?:' + COLORS_RE + r'))'
    r'(?: colou?r)?$'
)


def _light_rule(c):
    for rule in LIGHT_RULES:
        match = rule.fullmatch(c)
        if match:
            time = LIGHT_WORDS.get(match.group('time'), match.group('time'))
            return [dict(op='relight', time=time, strength={15: 60, 60: 130}.get(amount(c, 100), 100))]
    return None


def _recolor_rule(c):
    match = RECOLOR_RULE.fullmatch(c)
    if not match or match.group('target').strip() in ('the picture', 'the photo', 'the image'):
        return None
    return [dict(op='recolor', target=match.group('target').strip(), color=match.group('color'))]


def _rule_steps(clause):
    """Steps for one short clause, or None if no rule matches it entirely."""
    c = clause.strip().lower().strip('.!?').strip()
    c = re.sub(r'^(please|can you|could you|now|also|then)\s+', '', c)
    c = re.sub(r'\s+(please|for me)$', '', c)
    if not c:
        return []
    found = _light_rule(c) or _recolor_rule(c)
    if found:
        return found
    a = amount(c)
    # Where: "blur the background", "make the sky warmer", "brighten the subject a bit"
    where = re.search(r'\s*\b(?:of |on |in |for |to )?the (background|sky|subject|person|foreground)\b', c)
    target = None
    if where and re.search(
        r'\b(blur|bright|light|dark|warm|cool|cold|saturat|vivid|colou?rful|contrast|sharp|'
        r'black and white|gr[ae]yscale|muted)',
        c,
    ):
        target = {'foreground': 'subject', 'person': 'subject'}.get(where.group(1), where.group(1))
        c = ' '.join((c[: where.start()] + ' ' + c[where.end() :]).split())
        c = re.sub(r'^(make|turn)(?! it\b)', r'\1 it', c)
    simple = [
        (
            r'^(make (it|this|the (photo|picture|image)) )?(a (little )?bit |slightly |much |way |very )?(brighter|lighter)$|^brighten( it| up)?( a bit| a little| slightly| a lot)?$|^increase (the )?(brightness|exposure)',
            lambda: [dict(op='brightness', amount=a)],
        ),
        (
            r'^(make (it|this) )?(a (little )?bit |slightly |much |very )?darker$|^darken( it)?( a bit| a little| slightly| a lot)?$|^(decrease|reduce|lower) (the )?(brightness|exposure)',
            lambda: [dict(op='brightness', amount=-a)],
        ),
        (
            r'^(more|increase|boost|add)( the)? contrast|^(make it )?(a bit |slightly |much )?(more contrasty|punchier)$',
            lambda: [dict(op='contrast', amount=a)],
        ),
        (r'^(less|decrease|reduce|lower)( the)? contrast', lambda: [dict(op='contrast', amount=-a)]),
        (
            r'^(make (it|this) )?(a (little )?bit |slightly |much |very )?(warmer)$|^warm (it )?up|^(add|more) warmth',
            lambda: [dict(op='warmth', amount=a)],
        ),
        (
            r'^(make (it|this) )?(a (little )?bit |slightly |much |very )?(cooler|colder)$|^cool (it )?down',
            lambda: [dict(op='warmth', amount=-a)],
        ),
        (
            r'^(make (it|this) )?(a (little )?bit |slightly |much |very )?(more (vivid|colou?rful|saturated))$|^(more|increase|boost)( the)? (saturation|colou?rs?|vibrance)',
            lambda: [dict(op='saturation', amount=a)],
        ),
        (
            r'^(make (it|this) )?(a bit |slightly |much )?(less (vivid|colou?rful|saturated)|muted)$|^(less|decrease|reduce|lower)( the)? (saturation|colou?rs?)|^desaturate',
            lambda: [dict(op='saturation', amount=-a)],
        ),
        (
            r'^(make (it|this) |turn (it|this) |convert (it )?(in)?to )?(black (and|&) white|b ?& ?w|gr[ae]yscale|monochrome)$',
            lambda: [dict(op='black_and_white')],
        ),
        (
            r'^(make (it|this) )?sepia( tone)?$|^(make (it|this) )?look (old|vintage)$',
            lambda: [dict(op='sepia', strength=60)],
        ),
        (r'^invert( the)? colou?rs$|^(make (it|this) )?(a )?negative$', lambda: [dict(op='invert_colors')]),
        (
            r'^(auto ?(fix|enhance|levels|contrast|color|colour|correct))( (the )?(colou?rs?|light(ing)?))?$|^fix (the )?(colou?rs?|light(ing)?|exposure)$',
            lambda: [dict(op='auto_levels')],
        ),
        (
            r'^blur( it| this| everything)?( a bit| slightly| more| a lot)?$|^(make it|add)( a)? blur(ry)?$',
            lambda: [dict(op='blur', radius={15: 6, 60: 30}.get(a, 14))],
        ),
        (
            r'^sharpen( it| this)?( a bit| slightly| more| a lot)?$|^(make it )?(sharper|crisper)$',
            lambda: [dict(op='sharpen', amount=clamp(a + 20, 1, 100))],
        ),
        (
            r'^(add|apply)( some| a bit of| a little| more)? (film )?(grain|noise)$',
            lambda: [dict(op='grain', amount=clamp(a - 10, 5, 100))],
        ),
        (
            r'^(remove|reduce)( the)? (noise|grain)$|^denoise( it)?$',
            lambda: [dict(op='denoise', strength=50)],
        ),
        (
            r'^(add|apply)( a| some)? vignette$|^darken( the)? (corners|edges)$',
            lambda: [dict(op='vignette', amount=clamp(a + 20, 1, 100))],
        ),
        (r'^pixelate( it)?$', lambda: [dict(op='pixelate', size=16)]),
        (r'^(make it look like an? )?oil paint(ing)?$', lambda: [dict(op='oil_paint', size=3)]),
        (
            r'^(flip|mirror)( it| the (photo|picture|image))?( horizontally)?$',
            lambda: [dict(op='flip', direction='horizontal')],
        ),
        (
            r'^(flip|mirror)( it| the (photo|picture|image))? (vertically|upside down)$',
            lambda: [dict(op='flip', direction='vertical')],
        ),
        (r'^rotate( it)?( 90( degrees)?)?( clockwise| right)?$', lambda: [dict(op='rotate', degrees=90)]),
        (
            r'^rotate( it)?( 90( degrees)?)? (counter-?clockwise|anti-?clockwise|left)$',
            lambda: [dict(op='rotate', degrees=-90)],
        ),
        (r'^(rotate|turn)( it)? (180|upside down)( degrees)?$', lambda: [dict(op='rotate', degrees=180)]),
        (r'^(crop|make)( it)?( to)?( a)? square$', lambda: [dict(op='crop', aspect='1:1')]),
        (
            r'^crop( it)?( to)? (\d+)[:x/ ](\d+)$',
            lambda: [
                dict(op='crop', aspect=re.sub(r'[^\d]+', ':', re.search(r'(\d+[:x/ ]\d+)$', c).group(1)))
            ],
        ),
        (r'^crop( it)?( to)?( the)? selection$', lambda: [dict(op='crop_to_selection')]),
        (
            r'^(remove|delete|cut out|erase)( the)? background$|^(cut out|isolate)( the)? (subject|person)$|^make( the)? background transparent$',
            lambda: [dict(op='remove_background')],
        ),
        (
            r'^(enhance|upscale|improve)( it| this| the (photo|picture|image|quality|details?))?( quality)?$',
            lambda: [dict(op='enhance', scale=1.0)],
        ),
        (r'^(upscale|enlarge)( it)? ?(2x|x2|twice|double)$', lambda: [dict(op='enhance', scale=2.0)]),
        (r'^(fix|repair)( the)? (faces?|hands?|faces and hands)$', lambda: [dict(op='fix_faces')]),
        (r'^undo( that| it| the last( change)?)?$', lambda: [dict(op='undo', times=1)]),
        (r'^redo$', lambda: [dict(op='redo', times=1)]),
        (r'^(deselect|select none|clear( the)? selection)$', lambda: [dict(op='deselect')]),
        (r'^select (all|everything)$', lambda: [dict(op='select', target='all')]),
        (r'^invert( the)? selection$', lambda: [dict(op='invert_selection')]),
        (r'^flatten( the image| all layers| layers)?$', lambda: [dict(op='flatten')]),
        (r'^merge( it)? down$', lambda: [dict(op='merge_down')]),
        (r'^duplicate( the)?( this| active)? layer$', lambda: [dict(op='duplicate_layer')]),
        (r'^(add|create|make)( a)? new( empty)? layer$', lambda: [dict(op='new_layer', name='Layer')]),
        (
            r'^(save|send)( it| this)?( to)?( the)? (library|studio|image studio)$',
            lambda: [dict(op='save_to_library')],
        ),
    ]
    for pattern, build in simple:
        if re.fullmatch(pattern, c):
            steps = build()
            if target:
                return [dict(op='select', target=target)] + steps + [dict(op='deselect')]
            return steps
    match = re.match(r'^(?:set |change |make )?(?:the )?(?:layer )?opacity(?: to)? ' + NUMBER + r'\s*%?$', c)
    if match:
        return [dict(op='layer_opacity', opacity=int(float(match.group(1))))]
    match = re.match(
        r'^rotate(?: it)?(?: by)? '
        + NUMBER
        + r'(?:\s*(?:degrees|deg|°))?( counter-?clockwise| anti-?clockwise| left)?$',
        c,
    )
    if match:
        degrees = float(match.group(1))
        return [dict(op='rotate', degrees=-degrees if match.group(2) else degrees)]
    match = re.match(r'^(?:resize|scale)(?: it)?(?: to)? ' + NUMBER + r'\s*%$', c)
    if match:
        return [dict(op='resize', scale=float(match.group(1)))]
    match = re.match(r'^(?:resize|scale)(?: it)?(?: to)? (\d+)\s*[x×]\s*(\d+)(?: ?px| pixels)?$', c)
    if match:
        return [dict(op='resize', width=int(match.group(1)), height=int(match.group(2)))]
    match = re.match(
        r'^(?:set |change )?(?:the )?(?:layer )?(?:blend(?:ing)? mode )?(?:to )?('
        + '|'.join(BLEND_MODES)
        + r')(?: mode| blend(?:ing)?(?: mode)?)?$',
        c,
    )
    if match and ('mode' in c or 'blend' in c or c == match.group(1)) and match.group(1) != 'color':
        return [dict(op='blend_mode', mode=match.group(1))]
    match = re.match(
        r'^(?:blur|soften)(?: the)? (background|sky)(?: a bit| slightly| a lot| more)?$',
        clause.strip().lower(),
    )
    if match:
        return [
            dict(op='select', target=match.group(1)),
            dict(op='blur', radius={15: 10, 60: 40}.get(a, 20)),
            dict(op='deselect'),
        ]
    return None


COLORS = (
    'white|black|red|green|blue|yellow|orange|purple|pink|grey|gray|brown|gold|silver|cyan|magenta|navy|'
    'teal|beige|maroon|violet'
)
TEXT_RULE = re.compile(
    r'(?:please\s+)?(?:(?P<write>write|type)|add|put|place|insert)\s+(?:the\s+|a\s+|some\s+)?'
    r'(?P<kind>text|title|caption|heading|headline|words?|label)?\s*:?\s*(?:saying\s+|that says\s+|reading\s+)?'
    r'(?:(?P<quote>["“\'])(?P<quoted>.+?)["”\']|(?P<text>.+?))'
    r'(?:\s+(?:(?:at|on|in|to|along)\s+the\s+)?(?P<pos>top left|top right|bottom left|bottom right|top|bottom|center|'
    r'centre|middle|left|right)(?:\s+(?:corner|side|edge))?(?:\s+of the (?:picture|image|photo|canvas))?)?'
    r'(?:\s*,?\s+in\s+(?P<color>'
    + COLORS
    + r'))?(?:\s*,?\s+(?:in\s+)?(?P<size>small|big|large|huge|tiny)(?: letters| text| font)?)?'
    r'\.?',
    re.I,
)


def text_plan(text):
    """A text step for "write SUMMER at the top in white" and similar, else None."""
    match = TEXT_RULE.fullmatch(text.strip())
    if not match or not (match.group('write') or match.group('kind') or match.group('quote')):
        return None
    words = (match.group('quoted') or match.group('text') or '').strip().strip('"“”\'')
    if not words or len(words) > 120:
        return None
    if not match.group('quoted') and re.search(r'\b(and|then|also)\b|[,;]', words):
        return None  # probably more than one request: the planner splits it
    position = (
        (match.group('pos') or 'center').lower().replace('centre', 'center').replace('middle', 'center')
    )
    size = {'tiny': 4, 'small': 5, 'big': 13, 'large': 13, 'huge': 20}.get(
        (match.group('size') or '').lower(), 9
    )
    return normalize(
        [
            dict(
                op='add_text',
                text=words,
                position=position,
                size=size,
                color=(match.group('color') or 'white').lower(),
                font='Arial',
            )
        ]
    )


CLAUSES = r'\s*(?:,|;|\.\s|\band then\b|\bthen\b|\band\b|&|\+)\s*'


def partial_plan(text, skip=('relight',)):
    """(steps for the clauses the rules understand, the other clauses as text). Rules whose
    first op is in `skip` count as not understood (the brain does them better)."""
    text = ' '.join(text.split())
    steps, rest = [], []
    for clause in re.split(CLAUSES, text.strip()):
        found = _rule_steps(clause) if clause else None
        if found and found[0]['op'] not in skip:
            steps += found
        elif clause:
            rest.append(clause)
    return normalize(steps), ', '.join(rest)


def quick_plan(text):
    """Steps for requests made only of common, unambiguous commands, else None."""
    text = ' '.join(text.split())
    steps = text_plan(text) if text else None
    if steps:
        return steps
    if not text or len(text) > 160 or re.search(r'["“”]', text):
        return None
    clauses = re.split(CLAUSES, text.strip())
    steps = []
    for clause in clauses:
        found = _rule_steps(clause)
        if found is None:
            return None
        steps += found
    return normalize(steps) or None


# ---- Planning with a language model -----------------------------------------------


def describe_document(state):
    """One short paragraph about the open picture for the planner."""
    if not state:
        return 'No picture is open.'
    layers = ', '.join(
        f'"{layer["name"]}"' + (' (active)' if layer.get('active') else '')
        for layer in state.get('layers', [])[:12]
    )
    selection = 'There is a selection.' if state.get('selection') else 'Nothing is selected.'
    return f'Picture: {state.get("width")} x {state.get("height")} pixels. Layers, top first: {layers}. {selection}'


QUESTION = re.compile(
    r"^(what|what's|which|who|where|why|how many|how much|is there|are there|is it|is this|"
    r'does|do you see|can you see|describe|tell me about|count)\b',
    re.I,
)


def is_question(text):
    text = text.strip()
    return bool(QUESTION.match(text)) or (
        text.endswith('?') and not re.match(r'(can|could|would|will) you\b|please\b', text, re.I)
    )


def _planner_linear():
    import torch

    class PlannerLinear(torch.nn.Module):
        """Z-Image's 8-bit Qwen3 weight rows times their scales, with the scale applied to
        the output (exact, and 1.45x faster than expanding the weights first)."""

        def __init__(self, weight, scale):
            super().__init__()
            self.register_buffer('weight', weight)
            self.register_buffer('scale', scale.reshape(-1))

        def forward(self, x):
            return torch.nn.functional.linear(x, self.weight.to(x.dtype)) * self.scale.to(x.dtype)

    return PlannerLinear


def _load_planner():
    """Qwen3-4B, the language model Z-Image reads prompts with, as a chat model: the
    same 8-bit file (4.4 GB), its head tied to the token embeddings as in Qwen3-4B."""
    import torch
    from accelerate import init_empty_weights
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, Qwen3Config, Qwen3ForCausalLM
    from image_studio.core.catalog import MODELS

    folder = MODELS['accurate']['folder']
    with init_empty_weights():
        model = Qwen3ForCausalLM(Qwen3Config.from_pretrained(folder / 'text_encoder'))
    state = load_file(str(folder / 'text_encoder' / 'model-fp8.safetensors'), device='cuda')
    linear = _planner_linear()
    for name, module in list(model.named_modules()):
        for child_name, child in list(module.named_children()):
            if isinstance(child, torch.nn.Linear) and child_name != 'lm_head':
                key = f'{name}.{child_name}' if name else child_name
                setattr(module, child_name, linear(state.pop(f'{key}.weight'), state.pop(f'{key}.scale')))
    model.load_state_dict(state, strict=False, assign=True)
    model.lm_head.weight = model.model.embed_tokens.weight
    if any(param.is_meta for param in model.parameters()):
        raise RuntimeError('The accurate model text encoder is incomplete. Run Download accurate model.bat.')
    return dict(model=model.to('cuda').eval(), tokenizer=AutoTokenizer.from_pretrained(folder / 'tokenizer'))


def planner_available():
    from image_studio.core.catalog import MODELS

    return (MODELS['accurate']['folder'] / 'download-complete.json').exists()


def ask_planner(request_text, keep=True):
    """The planner's raw answer for one request (Qwen3-4B, no thinking)."""
    import torch
    from image_studio.services import assistant

    messages = [{'role': 'system', 'content': system_prompt()}]
    for idea, answer in EXAMPLES:
        messages += [
            {'role': 'user', 'content': f'Request: {idea}'},
            {'role': 'assistant', 'content': answer},
        ]
    messages.append({'role': 'user', 'content': request_text})
    with assistant.Resident('planner', _load_planner, keep=keep) as parts:
        tokenizer, model = parts['tokenizer'], parts['model']
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False, return_dict=True, return_tensors='pt'
        ).to('cuda')
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=400,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=tokenizer.eos_token_id,
            )
        return tokenizer.decode(output[0, inputs['input_ids'].shape[1] :], skip_special_tokens=True)


def answer_question(request, image, status=print):
    """A short answer about the picture from the vision assistant."""
    from image_studio.services import assistant

    status('Looking at the picture...')
    with assistant.Session(keep=True) as session:
        return clean_answer(
            session.ask(
                'Answer the question about the picture in one or two short sentences. Say only what you can see.',
                [],
                request,
                image=image,
                max_new_tokens=120,
                repetition_penalty=1.05,
                image_size=768,
                prefix='',
            )
        )


def clean_answer(text):
    return ' '.join(re.sub(r'<think>.*?</think>', '', text, flags=re.S).split())[:600]


DESTRUCTIVE = {
    'delete_layer': r'\b(delete|remove)\b.*\blayer|\blayer\b.*\b(delete|remove)',
    'flatten': r'\bflatten',
    'merge_down': r'\bmerge',
}


def check(steps, request, state):
    """Guard rails on a plan: no layer deletion or flattening that the request did not ask
    for, no new picture painted over an open one by mistake, and a selection the plan made
    released at the end unless the request was to select something."""
    text = request.lower()
    result = []
    for step in steps:
        op = step['op']
        if op in DESTRUCTIVE and not re.search(DESTRUCTIVE[op], text):
            continue
        if op == 'new_canvas' and state and not re.search(r'\b(new|blank|empty)\b', text):
            continue
        if op == 'save_to_library' and not re.search(r'\b(save|library|keep)\b', text):
            continue
        if op == 'select_layer' and result and result[-1]['op'] == 'duplicate_layer':
            continue  # the copy is already the active layer
        if (
            op == 'ai_generate'
            and state
            and not any(s['op'] in ('select', 'select_box') for s in result)
            and not re.search(r'\b(new (picture|image|layer)|generate|create|draw|paint)\b', text)
        ):
            step = dict(op='ai_edit', instruction=request)
        if op == 'fill' and not re.search(r'\b(fill|flat|solid)\b', text):
            # Recolor the object with its texture kept, rather than covering it with paint.
            if result and result[-1]['op'] in ('select', 'grow_selection', 'feather_selection'):
                step = dict(op='recolor_selection', color=step['color'])
            else:
                step = dict(op='ai_edit', instruction=request)
        if op == 'edges' and re.search(r'\b(sketch|drawing|drawn|pencil|charcoal|ink)\b', text):
            step = dict(op='ai_edit', instruction=request)
        if (
            op == 'select'
            and result
            and result[-1]['op'] == 'select'
            and result[-1]['target'] == step['target']
        ):
            result.pop()
        if op == 'deselect' and result and result[-1]['op'] == 'deselect':
            continue
        result.append(step)
    selecting = {'select', 'select_box', 'invert_selection', 'grow_selection', 'feather_selection'}
    # "everything except the cat": the selection is the cat, so it is inverted after selecting.
    if re.search(r'\b(except|but not|apart from|other than|everything but)\b', text):
        for index, step in enumerate(result):
            if step['op'] == 'select' and (
                index + 1 == len(result) or result[index + 1]['op'] != 'invert_selection'
            ):
                result.insert(index + 1, dict(op='invert_selection'))
                break
    if (
        any(s['op'] in ('select', 'select_box') for s in result)
        and result[-1]['op'] not in selecting | {'deselect', 'crop_to_selection'}
        and not re.search(r'\bselect', text)
    ):
        result.append(dict(op='deselect'))
    return result


def plan(request, state=None, image=None, status=print):
    """(steps, how) for a request: instant rules when they cover it, a direct answer for a
    question about the picture, else the planner. `state` describes the open document
    (None when none is open) and `image` is a preview of it."""
    steps = quick_plan(request)
    if steps:
        return steps, 'rules'
    if is_question(request) and image is not None:
        from image_studio.services import assistant

        if assistant.available():
            return [dict(op='say', text=answer_question(request, image, status))], 'vision'
    if planner_available():
        status('Planning the edit...')
        steps = check(
            normalize(parse(ask_planner(f'{describe_document(state)}\nRequest: {request}'))), request, state
        )
        if steps:
            return steps, 'planner'
    # Whatever was asked, a generative edit (or a new picture) can attempt it.
    if state:
        return [dict(op='ai_edit', instruction=request)], 'fallback'
    return [
        dict(op='new_canvas', width=1024, height=1024),
        dict(op='ai_generate', description=request),
    ], 'fallback'


def short(text, limit=48):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


LABELS = {
    'select': lambda s: f'Select {s["target"]}',
    'select_box': lambda s: 'Select a rectangle',
    'grow_selection': lambda s: f'Grow selection {s["pixels"]} px',
    'feather_selection': lambda s: f'Feather selection {s["pixels"]} px',
    'hue': lambda s: f'Hue {s["degrees"]:+d}°',
    'sepia': lambda s: 'Sepia',
    'colorize': lambda s: f'Colorize {s["color"]}',
    'recolor_selection': lambda s: f'Recolor {s["color"]}',
    'relight': lambda s: f'{s["time"].capitalize()} light',
    'posterize': lambda s: f'Posterize {s["levels"]}',
    'threshold': lambda s: f'Threshold {s["level"]}',
    'blur': lambda s: f'Blur {s["radius"]}',
    'motion_blur': lambda s: f'Motion blur {s["length"]}',
    'lens_blur': lambda s: f'Lens blur {s["radius"]}',
    'sharpen': lambda s: f'Sharpen {s["amount"]}',
    'denoise': lambda s: f'Reduce noise {s["strength"]}',
    'grain': lambda s: f'Film grain {s["amount"]}',
    'pixelate': lambda s: f'Pixelate {s["size"]}',
    'oil_paint': lambda s: 'Oil paint',
    'vignette': lambda s: f'Vignette {s["amount"]}',
    'round_corners': lambda s: 'Round corners',
    'crop': lambda s: f'Crop {s["aspect"]}',
    'resize': lambda s: (
        f'Resize {s["scale"]:g}%'
        if s['scale']
        else f'Resize {s["width"] or "auto"} × {s["height"] or "auto"}'
    ),
    'rotate': lambda s: f'Rotate {s["degrees"]:g}°',
    'flip': lambda s: f'Flip {s["direction"]}',
    'new_canvas': lambda s: f'New canvas {s["width"]} × {s["height"]}',
    'new_layer': lambda s: f'New layer "{s["name"]}"',
    'delete_layer': lambda s: f'Delete layer {s["layer"]}',
    'rename_layer': lambda s: f'Rename layer to "{s["name"]}"',
    'select_layer': lambda s: f'Select layer {s["layer"]}',
    'layer_opacity': lambda s: f'Layer opacity {s["opacity"]}%',
    'blend_mode': lambda s: f'Blend mode {s["mode"]}',
    'hide_layer': lambda s: f'Hide layer {s["layer"]}',
    'show_layer': lambda s: f'Show layer {s["layer"]}',
    'move_layer': lambda s: f'Move layer {s["dx"]:+g}%, {s["dy"]:+g}%',
    'fill': lambda s: f'Fill {s["color"]}',
    'add_text': lambda s: f'Text "{short(s["text"], 30)}"',
    'ai_edit': lambda s: short(s['instruction']),
    'ai_generate': lambda s: short(s['description']),
    'enhance': lambda s: 'Enhance' + (f' {s["scale"]:g}×' if s['scale'] > 1 else ''),
    'fix_faces': lambda s: 'Repair faces and hands',
    'undo': lambda s: 'Undo' + (f' {s["times"]}×' if s['times'] > 1 else ''),
    'redo': lambda s: 'Redo' + (f' {s["times"]}×' if s['times'] > 1 else ''),
    'say': lambda s: 'Answer',
}


def summary(step):
    """A short label for a step: the layer name in Krita and the line in the step list."""
    if step.get('label'):
        return step['label']
    op = step['op']
    if op in LABELS:
        return LABELS[op](step)
    name = op.replace('_', ' ').capitalize()
    amount = step.get('amount')
    if isinstance(amount, int) and op in ('brightness', 'contrast', 'saturation', 'warmth', 'tint'):
        return f'{name} {amount:+d}'
    return name

"""PhotoCraft edit language: what a request means, compiled into exact engine commands.

The vision planner only *chooses*: an action from a closed vocabulary, a target, a direction,
a strength, a position, a color name, the exact words of a title. It never writes engine
parameters. Every number that reaches PhotoCraft is either a number the person typed (checked
against their words) or is computed here from the document: crop rectangles from aspect ratios,
text placement from the measured text box, rotation crops from trigonometry, object masks from
boxes. This split exists because a 9B model judges images well but writes numbers erratically
(see docs/photocraft-assistant.md).

Edits are ordered the way a retoucher works, so they do not interfere: layer changes, pixel
retouching, raw development, AI layers, adjustments, effects and cut-outs while every object is
still whole in the frame (masks are cropped along with their layers), then geometry, and finally
text and graphics on the final canvas, where color changes cannot tint them.
"""

import colorsys
import math
import re
from collections.abc import Mapping

# ---- Vocabulary -----------------------------------------------------------------------------

POSITIONS = [
    'top left', 'top', 'top right', 'left', 'center', 'right', 'bottom left', 'bottom', 'bottom right',
]
TARGETS = [
    'whole image', 'main subject', 'background', 'sky', 'object', 'color', 'shadows', 'midtones',
    'highlights', 'area', 'layer',
]
STRENGTHS = ['subtle', 'moderate', 'strong']
DIRECTIONS = ['increase', 'decrease', 'none']
SIZES = ['small', 'medium', 'large', 'huge']
LUTS = ['warm', 'cool', 'tealOrange', 'bleachBypass', 'fadedFilm', 'dayForNight', 'monoContrast', 'crossProcess']

# Camera Raw parameters: (engine name, moderate amount, lowest, highest). PhotoCraft's scales are
# gentle: temperature 7.5 moves skin by ~2.6 of 255 and shadows 15 lifts dark cloth by ~3, which
# nobody sees, so these amounts are measured to be visible at “slightly”.
RAW = {
    'exposure': ('exposure', 0.5, -5, 5),
    'highlights': ('highlights', 40, -100, 100),
    'shadows': ('shadows', 40, -100, 100),
    'whites': ('whites', 20, -100, 100),
    'blacks': ('blacks', 20, -100, 100),
    'clarity': ('clarity', 20, -100, 100),
    'texture': ('texture', 30, -100, 100),
    'dehaze': ('dehaze', 15, -100, 100),
    'temperature': ('temperature', 30, -100, 100),
    'tint': ('tint', 10, -100, 100),
    'sharpen': ('sharpenAmount', 40, 0, 150),
    'noise_reduction': ('noiseLuminance', 30, 0, 100),
    'grain': ('grainAmount', 25, 0, 100),
    'vignette': ('vignetteAmount', -25, -100, 100),
}

# Adjustment layers: (command suffix, parameter, moderate amount, lowest, highest).
ADJUST = {
    'brightness': ('brightnessContrast', 'brightness', 25, -150, 150),
    'contrast': ('brightnessContrast', 'contrast', 20, -50, 100),
    'saturation': ('hueSaturation', 'saturation', 20, -100, 100),
    'vibrance': ('vibrance', 'vibrance', 35, -100, 100),
    'hue_shift': ('hueSaturation', 'hue', 30, -180, 180),
    'posterize': ('posterize', 'levels', 6, 2, 255),
    'threshold': ('threshold', 'level', 128, 1, 255),
}

class _Actions(Mapping):
    """{pipeline id: (stage, what the planner reads)} for every registered pipeline. The edit
    language's `action` is a pipeline id; image_studio.pipelines holds the pipelines themselves."""

    _data = None

    def _load(self):
        if _Actions._data is None:
            from image_studio.pipelines import REGISTRY

            _Actions._data = {p.id: (p.stage, p.summary) for p in REGISTRY.values()}
        return _Actions._data

    def __getitem__(self, key):
        return self._load()[key]

    def __iter__(self):
        return iter(self._load())

    def __len__(self):
        return len(self._load())


ACTIONS = _Actions()
GROUP_ORDER = ['layer', 'retouch', 'develop', 'ai', 'adjust', 'effect', 'cutout', 'geometry', 'graphics', 'output',
               'expert']
AI_REMOVAL_AREA = 0.015  # larger objects are rebuilt by AI; content-aware fill smears them (measured)

COLORS = {
    'white': '#ffffff', 'black': '#000000', 'red': '#d62828', 'crimson': '#b3122e', 'maroon': '#800020',
    'orange': '#f77f00', 'amber': '#ffbf00', 'yellow': '#fcd116', 'gold': '#d4af37', 'golden': '#e0a526',
    'green': '#2a9d3f', 'lime': '#8bd346', 'olive': '#708238', 'emerald': '#2e8b57', 'teal': '#1d7874',
    'cyan': '#1fb6d6', 'turquoise': '#30d5c8', 'blue': '#1f4fd1', 'sky blue': '#5fb4ee', 'navy': '#14213d',
    'indigo': '#3f37c9', 'purple': '#7b2cbf', 'violet': '#8f5bd6', 'lavender': '#b8a9e3', 'magenta': '#d0218d',
    'pink': '#f08ab8', 'hot pink': '#ff3ea5', 'coral': '#ff6f61', 'salmon': '#fa8072', 'peach': '#ffb38a',
    'brown': '#7b4a2a', 'chocolate': '#5a3825', 'tan': '#d2b48c', 'beige': '#e8dcc0', 'cream': '#f6efd9',
    'ivory': '#fffff0', 'silver': '#c0c0c0', 'gray': '#8a8a8a', 'grey': '#8a8a8a', 'charcoal': '#333333',
    'warm': '#ff9d3c', 'cool': '#3c8dff',
}
FILTERS = {
    'warm': 'warming85', 'warming': 'warming85', 'orange': 'orange', 'cool': 'cooling80', 'cooling': 'cooling80',
    'sepia': 'sepia', 'red': 'red', 'yellow': 'yellow', 'green': 'green', 'cyan': 'cyan', 'blue': 'blue',
    'violet': 'violet', 'purple': 'violet', 'magenta': 'magenta', 'underwater': 'underwater',
}
ARTISTIC = {
    'oil paint': ('filter.stylize.oilPaint', {}), 'oil painting': ('filter.stylize.oilPaint', {}),
    'watercolor': ('filter.gallery.watercolor', {}), 'pencil': ('filter.gallery.coloredPencil', {}),
    'colored pencil': ('filter.gallery.coloredPencil', {}), 'cutout': ('filter.gallery.cutout', {}),
    'dry brush': ('filter.gallery.dryBrush', {}), 'poster edges': ('filter.gallery.posterEdges', {}),
    'ink outlines': ('filter.gallery.inkOutlines', {}), 'sponge': ('filter.gallery.sponge', {}),
    'paint daubs': ('filter.gallery.paintDaubs', {}), 'pastel': ('filter.gallery.roughPastels', {}),
    'sumi-e': ('filter.gallery.sumiE', {}), 'plastic wrap': ('filter.gallery.plasticWrap', {}),
    'emboss': ('filter.stylize.emboss', {}), 'find edges': ('filter.stylize.findEdges', {}),
    'solarize': ('filter.stylize.solarize', {}), 'diffuse': ('filter.stylize.diffuse', {}),
    'pixelate': ('filter.pixelate.mosaic', {'cellSize': 16}), 'pixel': ('filter.pixelate.mosaic', {'cellSize': 16}),
    'mosaic': ('filter.pixelate.mosaic', {'cellSize': 16}), 'halftone': ('filter.pixelate.colorHalftone', {}),
    'crystallize': ('filter.pixelate.crystallize', {}), 'pointill': ('filter.pixelate.pointillize', {}),
    'cartoon': ('filter.gallery.cutout', {}), 'comic': ('filter.gallery.posterEdges', {}),
    'charcoal': ('filter.gallery.charcoal', {}), 'chalk': ('filter.gallery.chalkCharcoal', {}),
    'sketch': ('filter.gallery.graphicPen', {}), 'fresco': ('filter.gallery.fresco', {}),
    'neon': ('filter.gallery.neonGlow', {}), 'glass': ('filter.gallery.glass', {}),
    'stained glass': ('filter.gallery.stainedGlass', {}), 'mezzotint': ('filter.pixelate.mezzotint', {}),
    'twirl': ('filter.distort.twirl', {}), 'ripple': ('filter.distort.ripple', {}),
    'spherize': ('filter.distort.spherize', {}), 'fisheye': ('filter.distort.spherize', {}),
    'wind': ('filter.stylize.wind', {}), 'extrude': ('filter.stylize.extrude', {}),
    'tiles': ('filter.stylize.tiles', {}), 'trace': ('filter.stylize.traceContour', {}),
}
RECIPES = {
    'professional polish': {'raw': {'contrast': 10, 'highlights': -18, 'shadows': 16, 'clarity': 10, 'vibrance': 14}},
    'enhance': {'raw': {'contrast': 10, 'highlights': -18, 'shadows': 16, 'clarity': 10, 'vibrance': 14}},
    'warm portrait': {'raw': {'temperature': 12, 'vibrance': 8, 'texture': -8, 'highlights': -10}},
    'cinematic': {'lut': 'tealOrange', 'raw': {'contrast': 12, 'vignetteAmount': -18}},
    'vintage': {'lut': 'fadedFilm', 'raw': {'grainAmount': 20, 'vignetteAmount': -15}},
    'retro': {'lut': 'fadedFilm', 'raw': {'grainAmount': 20}},
    'moody': {'raw': {'exposure': -0.2, 'contrast': 15, 'dehaze': 8, 'vibrance': -12, 'vignetteAmount': -28}},
    'dramatic': {'raw': {'contrast': 22, 'clarity': 25, 'dehaze': 10, 'highlights': -25, 'vignetteAmount': -20}},
    # Skies get deeper and richer rather than flatter: pulling highlights down greys a sunset.
    'dramatic sky': {'raw': {'dehaze': 22, 'contrast': 18, 'clarity': 10, 'vibrance': 22, 'blacks': -10,
                             'highlights': -8}},
    'bright and airy': {'raw': {'exposure': 0.3, 'shadows': 25, 'highlights': -12, 'contrast': -10, 'vibrance': 8}},
    'matte': {'curves': [[0, 28], [64, 68], [192, 196], [255, 240]]},
    'hdr': {'raw': {'highlights': -45, 'shadows': 45, 'clarity': 30, 'vibrance': 12}},
    'pop art': {'raw': {'saturation': 45, 'contrast': 35, 'clarity': 20}, 'posterize': 5},
    'orton': {'raw': {'clarity': -15, 'exposure': 0.15, 'saturation': 12}},
    'cyberpunk': {'lut': 'tealOrange', 'raw': {'temperature': -25, 'tint': 30, 'contrast': 20, 'vibrance': 25}},
    'golden hour': {'raw': {'temperature': 35, 'tint': 8, 'highlights': -15, 'shadows': 12, 'vibrance': 15}},
    'kodak portra': {'raw': {'temperature': 10, 'contrast': -8, 'highlights': -20, 'shadows': 15, 'saturation': -8,
                             'grainAmount': 12}, 'curves': [[0, 18], [64, 66], [192, 194], [255, 246]]},
    'bleach bypass': {'lut': 'bleachBypass', 'raw': {'contrast': 15}},
    'high key': {'raw': {'exposure': 0.6, 'shadows': 40, 'contrast': -15, 'whites': 20}},
    'low key': {'raw': {'exposure': -0.5, 'shadows': -30, 'contrast': 20, 'blacks': -20}},
}
LEVEL = {'subtle': 0.6, 'moderate': 1.0, 'strong': 2.0}
# “Keep me sharp”, “leave the face as it is”: a promise to protect, not an edit. A clause that
# also asks for a change (“keep the colors but make them warmer”) is still an edit.
KEEP_ONLY = re.compile(
    r"^\W*(?:keep|leave|preserve|protect|don['’]?t (?:change|touch|edit)|do not (?:change|touch|edit))\b"
    r"(?!.*\b(?:make|add|but|while|turn|warmer|cooler|brighter|darker|more|less)\b)", re.IGNORECASE)

# ---- Understanding helpers ------------------------------------------------------------------


def hex_color(name):
    """'#rrggbb' for a color name or hex, else None."""
    if not name:
        return None
    text = name.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{6}', text):
        return text
    if re.fullmatch(r'#[0-9a-f]{3}', text):
        return '#' + ''.join(c * 2 for c in text[1:])
    for key in sorted(COLORS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(key)}\b', text):
            shade = COLORS[key]
            if re.search(r'\b(dark|deep)\b', text):
                return mix(shade, '#000000', 0.35)
            if re.search(r'\bpastel\b', text):
                return mix(shade, '#ffffff', 0.45)
            if re.search(r'\b(light|pale|soft)\b', text):
                return mix(shade, '#ffffff', 0.3)
            return shade
    return None


def mix(color, other, amount):
    """`color` moved toward `other` by `amount` (0..1); pastel pink stays pink, not white."""
    a = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i : i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * amount):02x}' for x, y in zip(a, b))


def hls(color):
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def luminance(color):
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def color_family(color):
    hue, light, sat = hls(color)
    if sat < 0.15:
        return 'highlights' if light > 0.7 else 'shadows' if light < 0.3 else 'midtones'
    degrees = hue * 360
    for limit, name in ((20, 'reds'), (75, 'yellows'), (160, 'greens'), (200, 'cyans'), (275, 'blues'),
                        (335, 'magentas'), (361, 'reds')):
        if degrees < limit:
            return name
    return 'reds'


def numbers_in(text):
    return [float(value) for value in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?', text or '')]


# Which way an amount goes, read from the words. Each word moves one quantity (an axis) up or down;
# an action reads the words of its own axis. “Less”, “too” and “reduce” turn a word around: “less
# dark” and “too dark” are brighter, “reduce the warmth” is cooler.
AXES = {
    'light': ('brightness', 'exposure', 'exposure_fix', 'whites', 'blacks', 'shadows', 'highlights', 'vignette'),
    'warm': ('temperature',),
    'color': ('saturation', 'vibrance'),
    'punch': ('contrast', 'clarity', 'texture', 'sharpen', 'dehaze'),
    'haze': ('dehaze',),
}
AXIS_WORDS = [  # (word pattern, {axis: +1 more of it, -1 less})
    (r'bright\w*|light(er|en\w*)?|lift\w*|illuminat\w*|sunn\w*', {'light': 1}),
    (r'dark\w*|dim(mer|med|ming)?|gloom\w*|crush\w*|underexposed', {'light': -1}),
    (r'overexposed|blown(\s+out)?', {'light': -1}),
    (r'deep(en\w*|er)?', {'light': -1, 'color': 1, 'punch': 1}),
    (r'warm\w*|golden', {'warm': 1}),
    (r'cool\w*|cold\w*|chill\w*', {'warm': -1}),
    (r'vivid\w*|vibran\w*|colou?rful|saturated|rich\w*|intens\w*|bold\w*|pop\w*|punch\w*', {'color': 1, 'punch': 1}),
    (r'desaturat\w*|mut(e|ed|ing)|dull\w*|pale\w*|bland', {'color': -1, 'punch': -1}),
    (r'washed[\s-]*out|fad(e|ed|ing)|flat\w*|matte|muddy', {'color': -1, 'punch': -1}),
    (r'contrast\w*|crisp\w*|sharp\w*|defin\w*|detail\w*', {'punch': 1}),
    (r'soft\w*|smooth\w*|blurr?\w*', {'punch': -1}),
    (r'clear\w*', {'haze': 1, 'punch': 1}),
    (r'haz(e|y|ier|iness)|fog\w*|mist\w*', {'haze': -1}),
]
TURN_WORDS = [  # words that set or reverse the direction of what follows them
    (r'too|overly|less|reduc\w*|decreas\w*|tone\s+down|weaker|minimi[sz]\w*|remov\w*|'
     r'eliminat\w*', -1),
    (r'more|increas\w*|boost\w*|enhanc\w*|add\w*|amplif\w*|intensif\w*|stronger|bump\s+up|maximi[sz]\w*', 1),
]
# Only verbs when they start the clause: “lower the exposure”, but “the lower half”.
LEAD_TURN_WORDS = [(r'lower|cut|turn\s+down|dial\s+down|recover\w*|tame', -1), (r'raise|push|turn\s+up|dial\s+up', 1)]
NAMING = re.compile(r'add\w*|remov\w*|eliminat\w*')  # “add a shadow”, “remove the dog”: things, not amounts
PHRASE_BREAK = ('and', 'but', 'or', 'while', 'then', 'with', 'except', 'keep', 'keeping')
LEAD = {'please', 'pls', 'can', 'could', 'would', 'you', 'kindly', 'i', 'want', 'to', 'd', 'like', 'let', 's',
        'lets', 'and', 'also', 'then', 'now', 'just', 'so', 'ok', 'okay'}


def _axis_sign(word, action):
    """+1/-1 when the word moves the action's quantity, None when it says nothing about it."""
    axes = [axis for axis, actions in AXES.items() if action in actions]
    word = re.sub(r' (up|down)$', '', word)  # “warm up”, “cool down”
    for pattern, signs in AXIS_WORDS:
        if re.fullmatch(pattern, word, re.IGNORECASE):
            if not axes:
                return None  # not an amount pipeline: its direction is the planner's
            found = [signs[axis] for axis in axes if axis in signs]
            return found[0] if found else None
    return None


def _turn_sign(word, leading=False):
    for pattern, sign in TURN_WORDS + (LEAD_TURN_WORDS if leading else []):
        if re.fullmatch(pattern, word, re.IGNORECASE):
            return sign
    return None


def direction_from_words(text, action):
    """('increase' | 'decrease' | None, sure) for the edit's own words. `sure` answers override
    the planner; the rest only fill a direction it left empty. Only the amount pipelines (light,
    warmth, colour, punch, haze) are ever sure: for the rest (“remove the dog”, “add a soft
    shadow”) direction is not an amount, so words never overrule the planner. Shadows read only
    light words (“reduce the shadows” lifts them, “deepen the shadows” darkens them), and so does a
    vignette."""
    words = re.findall(r"[a-z]+(?:[\s-]+(?:out|down|up))?", (text or '').lower())
    words = [re.sub(r'[\s-]+', ' ', word) for word in words]
    joined = ' '.join(words)
    pick = lambda sign: 'increase' if sign > 0 else 'decrease'  # noqa: E731
    amount = any(action in actions for actions in AXES.values())
    generic = action not in ('shadows', 'vignette')
    start = next((number for number, word in enumerate(words) if word not in LEAD), len(words))

    def answer(sign):
        return pick(sign), amount

    # 1. A turning word in front of a word of the action's axis (“less dark”, “reduce the warmth”).
    for number, word in enumerate(words):
        # “Recover the blown out sky” lowers the highlights; it does not turn “blown out” around.
        turn = None if re.fullmatch(r'recover\w*|tame', word) else _turn_sign(word, leading=number == start)
        if re.match(r'not (so|as|too)\b', ' '.join(words[number:number + 2])):
            turn, number = -1, number + 1
        if turn is None:
            continue
        for follower in words[number + 1:number + 5]:
            if follower in PHRASE_BREAK or _turn_sign(follower) is not None:
                break
            sign = _axis_sign(follower, action)
            if sign is not None:
                return answer(turn * sign)
    # “not bright enough” asks for more of it.
    enough = re.search(r'\bnot (\w+ )?(\w+) enough\b', joined)
    if enough and _axis_sign(enough.group(2), action) is not None:
        return answer(_axis_sign(enough.group(2), action))
    # 2. The verb the clause starts with (“brighten the darker areas”, “recover the blown out sky”).
    first = words[start] if start < len(words) else ''
    sign = _axis_sign(first, action)
    if sign is not None:
        return answer(sign)
    if generic and _turn_sign(first, leading=True) is not None and first not in ('too', 'less') and             not NAMING.fullmatch(first):
        return answer(_turn_sign(first, leading=True))
    # 3. “The photo is blurry, make it sharper”: what it should be made, then any word of the axis.
    for number, word in enumerate(words):
        if word in ('make', 'get', 'turn', 'render'):
            for follower in words[number + 1:number + 6]:
                if follower in PHRASE_BREAK:
                    break
                sign = _axis_sign(follower, action)
                if sign is not None:
                    return answer(sign)
    for word in words:
        sign = _axis_sign(word, action)
        if sign is not None:
            return answer(sign)
    if generic:
        # “More”, “less”, “increase”: only fills an empty direction. “Add” and “remove” name things
        # (“add a soft shadow”, “remove the dog”), not amounts.
        for word in words:
            if _turn_sign(word) is not None and not NAMING.fullmatch(word):
                return pick(_turn_sign(word)), False
    return None, False


def strength_from_words(text, chosen):
    """Words beat the planner's guess: “slightly” is subtle, “much more” is strong."""
    lowered = (text or '').lower()
    if re.search(r'\b(slight(ly)?|a (little )?bit|a touch|subtl[ey]|gentl[ey]|hint of|tiny bit|barely)\b', lowered):
        return 'subtle'
    if re.search(r'\b(very|much|lots?|strong(ly)?|heav(y|ily)|extreme(ly)?|dramatic(ally)?|really|way more|'
                 r'a lot|significantly|intense(ly)?|super)\b', lowered):
        return 'strong'
    return chosen if chosen in STRENGTHS else 'moderate'


UNIT = r'(?:mm|cm|in(?:ch(?:es)?)?\b|"|px|pixels?)'
SIZE = re.compile(rf'(\d+(?:\.\d+)?)\s*({UNIT})?\s*(?::|x|×|by|\*)\s*(\d+(?:\.\d+)?)\s*({UNIT})?', re.IGNORECASE)
# “passport”, and the misspellings people type for it (passfort, pasport, passfoto, pass photo).
PASSPORT = re.compile(r'\bpas+\s*-?\s*[pf]h?o[rt]|\b(?:id|visa)\s*(?:card\s*)?(?:photo|pic|picture)s?\b|'
                      r'\bstamp\s*-?\s*size', re.IGNORECASE)
STAMP_SIZE = (20, 25, 'mm')
PRINT_PPI = 300
PASSPORT_DEFAULT = (35, 45, 'mm')
PASSPORT_HEAD = "the person's head"
PASSPORT_HEAD_SHARE = 0.68  # crown to chin: 50-69% of a US 2x2, 71-80% of a 35x45 mm photo
PASSPORT_TOP_MARGIN = 0.1


# Named output sizes, most specific first: (pattern, width, height, unit, how). “crop” fills the
# format around the subject; “fit” keeps the picture's shape and scales its long side; print
# sizes turn to match the photo unless the request says portrait or landscape.
FORMATS = [
    (r'instagram\s*(portrait|4\s*:\s*5)', 1080, 1350, 'px', 'crop'),
    (r'instagram\s*(landscape|horizontal)', 1080, 566, 'px', 'crop'),
    (r'\bstor(y|ies)\b|\breels?\b|tik\s*tok|\bshorts\b|whatsapp status|phone wallpaper|mobile wallpaper',
     1080, 1920, 'px', 'crop'),
    (r'insta(gram)?|\bsquare post\b', 1080, 1080, 'px', 'crop'),
    (r'youtube\s*(banner|channel art|cover)', 2560, 1440, 'px', 'crop'),
    (r'youtube|\bthumbnail\b', 1280, 720, 'px', 'crop'),
    (r'linked\s*in\s*(banner|cover|background|header)', 1584, 396, 'px', 'crop'),
    (r'linked\s*in', 1200, 627, 'px', 'crop'),
    (r'facebook\s*(cover|banner)|\bfb\s*cover', 851, 315, 'px', 'crop'),
    (r'facebook|\bfb\b', 1200, 630, 'px', 'crop'),
    (r'(twitter|\bx)\s*(header|banner)', 1500, 500, 'px', 'crop'),
    (r'twitter|tweet', 1600, 900, 'px', 'crop'),
    (r'pinterest|\bpin\b', 1000, 1500, 'px', 'crop'),
    (r'profile (pic|photo|picture)|\bdp\b|display picture|avatar', 1080, 1080, 'px', 'crop'),
    (r'desktop wallpaper|\bwallpaper\b', 3840, 2160, 'px', 'crop'),
    (r'\b8k\b', 7680, 4320, 'px', 'fit'),
    (r'\b4k\b|\buhd\b|2160p', 3840, 2160, 'px', 'fit'),
    (r'\b2k\b|1440p|\bqhd\b', 2560, 1440, 'px', 'fit'),
    (r'full\s*hd|\bfhd\b|1080p', 1920, 1080, 'px', 'fit'),
    (r'\bhd\b|720p', 1280, 720, 'px', 'fit'),
    (r'\ba3\b', 297, 420, 'mm', 'print'),
    (r'\ba4\b', 210, 297, 'mm', 'print'),
    (r'\ba5\b', 148, 210, 'mm', 'print'),
    (r'\ba6\b', 105, 148, 'mm', 'print'),
    (r'\bletter\b', 8.5, 11, 'in', 'print'),
    (r'\blegal\b', 8.5, 14, 'in', 'print'),
    (r'post\s*card', 6, 4, 'in', 'print'),
]
MULTIPLIERS = {'half': 0.5, 'quarter': 0.25, 'third': 1 / 3, 'double': 2, 'twice': 2, 'triple': 3}


def output_size(text, width, height):
    """What a size request asks for, or None: {'size': (w, h) px, 'ppi': print resolution or None,
    'crop': whether to cut to the new shape first, 'label': plain words}. Handles pixel sizes,
    print sizes with units (“4x6 inch”, “35x45 mm”), percentages and multiples (“2x bigger”, “half”),
    one side (“1080 px wide”), named formats (“instagram post”, “A4”, “4k”) and dpi alone."""
    lowered = (text or '').lower()
    dpi = re.search(r'(\d{2,4})\s*(?:dpi|ppi|dots per inch|pixels per inch)', lowered)
    ppi = int(dpi.group(1)) if dpi else None
    portrait = re.search(r'\b(portrait|vertical|tall)\b', lowered)
    landscape = re.search(r'\b(landscape|horizontal|wide)\b', lowered)

    def turned(w, h):
        if portrait and w > h or landscape and w < h or not (portrait or landscape) and (w > h) != (width > height) \
                and w != h:
            return h, w
        return w, h

    size = print_size(lowered)
    if size and not size[2] and max(size[:2]) <= 40 and re.search(r'\bprint|photo ?lab|frame\b', lowered):
        size = (size[0], size[1], 'in')  # “an 8x10 print” is in inches
    if size and size[2] in ('mm', 'cm', 'in'):
        inches = {'mm': 25.4, 'cm': 2.54, 'in': 1}[size[2]]
        w, h = turned(size[0], size[1])
        ppi = ppi or PRINT_PPI
        unit = 'inch' if size[2] == 'in' else size[2]
        return {'size': (round(w / inches * ppi), round(h / inches * ppi)), 'ppi': ppi, 'crop': True,
                'label': f'{w:g}×{h:g} {unit} at {ppi} ppi'}
    if size and (size[2] == 'px' or min(size[0], size[1]) >= 16):
        w, h = round(size[0]), round(size[1])
        return {'size': (w, h), 'ppi': ppi, 'crop': True, 'label': f'{w}×{h}'}
    percent = re.search(r'(\d+(?:\.\d+)?)\s*%', lowered)
    times = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:x|×|times)(?=\s|$|\W)', lowered)
    named = next((value for word, value in MULTIPLIERS.items() if re.search(rf'\b{word}\b', lowered)), None)
    scale = float(percent.group(1)) / 100 if percent else float(times.group(1)) if times else named
    if scale:
        if re.search(r'\b(smaller|reduce|shrink|down|less)\b', lowered) and scale > 1:
            scale = 1 / scale
        elif percent and re.search(r'\b(bigger|larger|increase|enlarge|grow)\w*\s+(?:\w+\s+){0,3}by\b', lowered):
            scale += 1  # “enlarge it by 50%” is 150%
        return {'size': (round(width * scale), round(height * scale)), 'ppi': ppi, 'crop': False,
                'label': f'{scale:.0%} size'}
    edge = re.search(r'(\d{2,5})\s*(?:px|pixels?)', lowered)
    if edge:
        side = int(edge.group(1))
        if re.search(r'\bwidth|wide\b', lowered):
            w, h = side, round(height * side / width)
        elif re.search(r'\bheight|tall|high\b', lowered):
            w, h = round(width * side / height), side
        else:
            scale = side / max(width, height)
            w, h = round(width * scale), round(height * scale)
        return {'size': (w, h), 'ppi': ppi, 'crop': False, 'label': f'{w}×{h}'}
    for pattern, w, h, unit, how in FORMATS:
        match = re.search(pattern, lowered)
        if not match:
            continue
        name = match.group(0).strip()
        if how == 'fit':
            scale = max(w, h) / max(width, height)
            return {'size': (round(width * scale), round(height * scale)), 'ppi': ppi, 'crop': False,
                    'label': f'{name.upper() if len(name) <= 4 else name} ({max(w, h)} px long side)'}
        if how == 'print':
            w, h = turned(w, h)
            inches = 25.4 if unit == 'mm' else 1
            ppi = ppi or PRINT_PPI
            return {'size': (round(w / inches * ppi), round(h / inches * ppi)), 'ppi': ppi, 'crop': True,
                    'label': f'{name.upper() if len(name) <= 3 else name} ({w:g}×{h:g} '
                             f'{"inch" if unit == "in" else unit}) at {ppi} ppi'}
        return {'size': (w, h), 'ppi': ppi, 'crop': True, 'label': f'{name} ({w}×{h})'}
    if ppi:
        return {'size': (width, height), 'ppi': ppi, 'crop': False, 'label': f'{ppi} ppi'}
    return None


PLAIN_BACKDROP = re.compile(r'\bback\s*(?:ground|drop)\b\s*(?:to|into|with|=|as|color to)?\s*(?:a\s+|an\s+)?'
                            r'(?:plain\s+|solid\s+|clean\s+|pure\s+)?(?:light\s+|dark\s+)?[a-z]+\s*$|'
                            r'\b(?:plain|solid|pure|clean)?\s*[a-z]+\s+back\s*(?:ground|drop)\b', re.IGNORECASE)


def plain_color(text):
    """The color named for a plain backdrop with its shade (“light grey”, “white”), or ''."""
    lowered = (text or '').lower()
    for name in sorted(COLORS, key=len, reverse=True):
        match = re.search(rf'\b((?:dark|deep|light|pale|soft|pastel)\s+)?{name}\b', lowered)
        if match:
            return match.group(0)
    return ''


# Portrait retouching: what is found in the picture for it, and which words ask for which job.
FACES = "each person's face"
EYES = 'each eye'
TEETH = 'the teeth'
RETOUCH_JOBS = [  # (job, words); the first jobs win when words overlap (“red eye” is not “eyes”)
    ('red eye', r'red[\s-]?eyes?'),
    ('dark circles', r'dark circles?|eye bags?|bags under|under[\s-]?eyes?|puffy eyes'),
    ('teeth', r'\bteeth\b|\btooth\b'),
    ('eyes', r'\beyes?\b|\biris'),
    ('blemishes', r'pimples?|acne|blemish|zits?|\bspots?\b|\bmarks?\b|scars?|breakouts?'),
    ('wrinkles', r'wrinkles?|fine lines|crow.?s feet|age lines'),
    ('even tone', r'\beven\b.*\b(skin|tone)|redness|blotch|uneven'),
    ('shine', r'shine|shiny|oily|greasy|sweaty'),
    ('sculpt', r'dodge|burn|sculpt|contour|dimension'),
    ('smooth', r'smooth|soft(en)?\s+(?:\w+\s+)?skin|airbrush|skin|retouch|beautif|flawless|glow'),
]
IRIS_WORDS = re.compile(r'\b(eyes?|iris(es)?|eye colou?r)\b', re.IGNORECASE)
FACE_JOBS = {'smooth', 'shine', 'sculpt', 'blemishes', 'wrinkles', 'even tone'}
EYE_JOBS = {'dark circles', 'eyes', 'red eye'}
PORTRAIT_WORDS = re.compile(r'\b(face|skin|cheeks?|forehead|nose|chin|his|her|their|my|portrait|person|man|woman|'
                            r'girl|boy|model)\b', re.IGNORECASE)


def measure_levels(preview, clip=0.005):
    """Black and white points that clip `clip` of the pixels at each end, for all channels together
    and each channel alone, and the gamma that brings each channel's midtones to neutral grey."""
    rgb = preview.convert('RGB')
    rgb.thumbnail((800, 800))

    def points(histogram):
        total = sum(histogram)
        low = high = 0
        running = 0
        for value, count in enumerate(histogram):
            running += count
            if running > total * clip:
                low = value
                break
        running = 0
        for value in range(255, -1, -1):
            running += histogram[value]
            if running > total * clip:
                high = value
                break
        return min(low, 120), max(high, max(low + 30, 135))

    channels = dict(zip(('red', 'green', 'blue'), (points(band.histogram()) for band in rgb.split())))
    gray = rgb.convert('L').histogram()
    result = {'all': points(gray), **channels}
    # The cast is judged on near-neutral midtones only (what should be grey), as Auto Color's “snap
    # neutral midtones” does: averaging every pixel read the yellow walls of a lamp-lit room as a
    # cast and turned a grey cat blue (measured 2026-10-12). The correction is also limited.
    neutral = [(r, g, b) for (r, g, b), (_, s, v) in zip(rgb.getdata(), rgb.convert('HSV').getdata())
               if s < 60 and 60 < v < 230]
    result['gamma'] = {'red': 1.0, 'green': 1.0, 'blue': 1.0}
    if len(neutral) > 0.02 * rgb.width * rgb.height:
        means = {}
        for channel, name in enumerate(('red', 'green', 'blue')):
            low, high = channels[name]
            means[name] = sum(min(1, max(0.01, (p[channel] - low) / (high - low))) for p in neutral) / len(neutral)
        target = sum(means.values()) / 3
        result['gamma'] = {name: round(min(1.25, max(0.8, math.log(mean) / math.log(target))), 2)
                           for name, mean in means.items()}
    return result


def teeth_colors(preview, boxes, state):
    """The colour of the teeth in each box: the median of its palest bright pixels. Whitening is
    limited to these colours; the outline of a 15 px mouth spills onto lips and skin, and de-yellowing
    warm-lit skin left grey patches around four smiles (measured 2026-10-12)."""
    import statistics

    sx, sy = preview.width / state['width'], preview.height / state['height']
    picture = preview.convert('RGB')
    colors = []
    for x, y, w, h in boxes:
        region = picture.crop((round(x * sx), round(y * sy), round((x + w) * sx), round((y + h) * sy)))
        pixels = list(zip(region.getdata(), region.convert('HSV').getdata()))
        if not pixels:
            continue
        pixels.sort(key=lambda item: item[1][2] - item[1][1], reverse=True)  # bright and pale first
        best = [rgb for rgb, _ in pixels[:max(1, len(pixels) // 6)]]
        colors.append('#{:02x}{:02x}{:02x}'.format(*(round(statistics.median(c[i] for c in best))
                                                      for i in range(3))))
    return colors


def skin_colors(preview, boxes, state):
    """A few skin colours from each face (its shadowed, middle and lit skin). Smoothing is limited
    to these: the face outline also holds the lips, brows and lashes, which the whole-face Camera Raw
    copy softened (a difference map of a portrait, 2026-10-12; the hair lies outside the outline)."""
    import statistics

    sx, sy = preview.width / state['width'], preview.height / state['height']
    picture = preview.convert('RGB')
    colors = []
    for x, y, w, h in boxes[:4]:
        # The middle of the face: cheeks, nose and chin, clear of the hairline.
        region = picture.crop((round((x + w * 0.2) * sx), round((y + h * 0.3) * sy),
                               round((x + w * 0.8) * sx), round((y + h * 0.9) * sy)))
        skin = []
        for rgb, (hue, sat, val) in zip(region.getdata(), region.convert('HSV').getdata()):
            # Skin of every tone is a warm hue (red to orange-yellow), moderately saturated.
            if (hue <= 40 or hue >= 245) and 25 <= sat <= 190 and val >= 45:
                skin.append((val, rgb))
        if len(skin) < 20:
            continue
        skin.sort()
        for share in (0.2, 0.5, 0.85, 0.97):
            middle = round(share * (len(skin) - 1))
            band = [rgb for _, rgb in skin[max(0, middle - len(skin) // 20):middle + len(skin) // 20 + 1]]
            colors.append('#{:02x}{:02x}{:02x}'.format(*(round(statistics.median(c[i] for c in band))
                                                          for i in range(3))))
    return list(dict.fromkeys(colors))


def retouch_jobs(text):
    """The retouching jobs a request asks for, in a retoucher's order."""
    lowered = (text or '').lower()
    jobs = [job for job, words in RETOUCH_JOBS if re.search(words, lowered)]
    # “Brighten her eyes” is the eyes; “remove the dark circles under her eyes” is not also the eyes.
    if 'eyes' in jobs and ({'red eye', 'dark circles'} & set(jobs)):
        jobs.remove('eyes')
    return jobs or ['smooth']


def retouch_queries(edit):
    """What a retouch must find in the picture."""
    jobs = retouch_jobs(edit['choice'] + ' ' + edit['quote'])
    return [query for query, wanted in ((FACES, FACE_JOBS), (EYES, EYE_JOBS), (TEETH, {'teeth'}))
            if wanted & set(jobs)]


def resize_may_crop(text):
    """Whether a size request may cut the picture to a new shape (and so needs the subject)."""
    wanted = output_size(text, 1000, 1000)
    return bool(wanted and wanted['crop'])


def print_size(text):
    """(width, height, unit) of a size written in the text (“3 inch X4inch”, “35x45mm”, “600x600 px”),
    unit '' when none is written, or None."""
    match = SIZE.search(text or '')
    if not match or float(match.group(1)) <= 0 or float(match.group(3)) <= 0:
        return None
    unit = (match.group(2) or match.group(4) or '').lower()
    unit = 'in' if unit.startswith('in') or unit == '"' else 'px' if unit.startswith('p') else unit
    return float(match.group(1)), float(match.group(3)), unit


def aspect_from(text):
    """(width, height) of an aspect ratio written in the text, or a named format."""
    lowered = (text or '').lower()
    match = re.search(rf'(\d+(?:\.\d+)?)\s*{UNIT}?\s*(?::|x|×|by|/)\s*(\d+(?:\.\d+)?)', lowered)
    if match and float(match.group(1)) > 0 and float(match.group(2)) > 0:
        return float(match.group(1)), float(match.group(2))
    named = {
        r'\bsquare\b|instagram post': (1, 1), r'\bstor(y|ies)\b|\breel\b|tiktok|9:16': (9, 16),
        r'\bportrait\b': (4, 5), r'\bwidescreen\b|youtube|16:9|cinematic': (16, 9), r'\blandscape\b': (3, 2),
        r'\bpanoram': (3, 1), r'\bbanner\b': (3, 1), r'\bA4\b|\bletter\b': (1, 1.414),
    }
    for pattern, ratio in named.items():
        if re.search(pattern, lowered):
            return ratio
    return None


def normalize(edit, prompt):
    """One planner edit made trustworthy. Returns (edit, notes)."""
    notes = []
    action = edit.get('action') if edit.get('action') in ACTIONS else 'other'
    quote = (edit.get('quote') or '').strip() or prompt
    result = {
        'action': action,
        'quote': quote,
        'target': edit.get('target') if edit.get('target') in TARGETS else 'whole image',
        'object': (edit.get('object') or '').strip()[:120],
        'direction': edit.get('direction') if edit.get('direction') in DIRECTIONS else 'none',
        'strength': strength_from_words(quote, edit.get('strength')),
        'value': None,
        'text': edit.get('text') or '',
        'color': (edit.get('color') or '').strip()[:60],
        'position': edit.get('position') if edit.get('position') in POSITIONS else '',
        'size': edit.get('size') if edit.get('size') in SIZES else '',
        'aspect': (edit.get('aspect') or '').strip()[:20],
        'choice': (edit.get('choice') or '').strip()[:80],
    }
    value = edit.get('value')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Only a number written in this edit's own words: “crop to 4:5 and boost vibrance” has no
        # vibrance amount. The quote must also be the person's (a number the model put in its own
        # paraphrase does not count).
        in_prompt = numbers_in(prompt)
        written = [number for number in numbers_in(quote) if any(abs(number - n) < 1e-6 for n in in_prompt)]
        if any(abs(abs(value) - abs(number)) < 1e-6 for number in written):
            result['value'] = float(value)
        else:
            notes.append(f'Ignored a number ({value:g}) that is not in your request; used a {result["strength"]} '
                         'amount instead.')
    # Direction words in the person's text override the planner, read as a phrase: “less dark” is
    # brighter, and “brighten the darker areas” is brighter (the verb leads, “darker” names where).
    lowered = quote.lower()
    worded, sure = direction_from_words(quote, action)
    if worded and (sure or result['direction'] == 'none'):
        result['direction'] = worded
    if action == 'color_filter' and result['target'] == 'color' and re.search(
            r'\b(deepen|deeper|richer|vivid|intensif|boost|more saturated)\w*', lowered):
        result['action'], result['direction'] = 'saturation', 'increase'
    if result['value'] is not None and result['value'] < 0:
        result['direction'] = 'decrease'
    retouch_words = re.search(r'pimple|acne|blemish|\bzits?\b|wrinkle|dark circle|eye bag|bags under|teeth|tooth|'
                              r'red[\s-]?eye|airbrush', lowered)
    face_words = re.search(r'\b(spots?|marks?|scars?|shine|shiny|oily|greasy|dodge|burn)\b', lowered) and \
        PORTRAIT_WORDS.search(lowered)
    skin_words = re.search(r'\bskin\b|complexion', lowered) and not re.search(r'\btone\b.*\b(warm|cool|orange|red|'
                                                                             r'yellow|pink|colou?r)', lowered)
    if action in ('remove_object', 'texture', 'relight', 'brightness', 'highlights', 'shadows', 'exposure', 'other',
                  'look', 'blur', 'clarity', 'saturation', 'recolor', 'generate') and (retouch_words or face_words) \
            or action in ('texture', 'blur', 'other', 'look', 'clarity', 'remove_object') and skin_words:
        # A retoucher's job on faces, not a generic edit on “the teeth” or “pimples” as objects.
        action = result['action'] = 'retouch_portrait'
        result['choice'] = ', '.join(retouch_jobs(quote))
        result['target'] = 'main subject'
    if action in ('drop_shadow', 'generate', 'other', 'mirror', 'flip') and re.search(
            r'\breflect(ion|ing)?\b', lowered) and not re.search(r'\b(remove|reduce|less|get rid|glare)\b', lowered):
        action = result['action'] = 'reflection'
    if action in ('other', 'look', 'generate') and re.search(r'glitch|rgb split', lowered):
        action = result['action'] = 'artistic'
        result['choice'] = 'glitch'
    auto = re.search(r'\bauto(matic(ally)?)?[\s-]*(contrast|tone|levels|colou?r|correct|fix|enhance)|white balance|'
                     r'colou?r cast|\bcast\b', lowered)
    if auto and action in ('exposure', 'contrast', 'look', 'brightness', 'temperature', 'tint', 'color_filter',
                           'other', 'auto_fix'):
        action = result['action'] = 'auto_fix'
        words = auto.group(0)
        result['choice'] = 'color' if re.search(r'colou?r|white|cast', words) else \
            'contrast' if 'contrast' in words else 'tone'
        if 'enhance' in words:
            # “Auto enhance” is levels plus a gentle polish.
            result['choice'] = 'tone'
    if action == 'auto_fix' and not (auto or re.search(r'levels|contrast|colou?r|tone|exposure', lowered)):
        # The planner reaches for “automatic” on vague requests (“clean up the messy background”).
        if result['target'] == 'background' or 'background' in lowered:
            action = result['action'] = 'blur_background'
            result['target'] = 'background'
        else:
            action = result['action'] = 'look'
            result['choice'] = 'professional polish'
    if action in ('retouch_portrait', 'relight', 'other') and re.search(
            r'\b(smile|smiling|laugh|grin|frown|expression|open (his|her|their|the) eyes|close (his|her|their) '
            r'mouth|look(ing)? (at|into) the camera|younger|older|hair\s*style|haircut|bald|makeup|lipstick)\b',
            lowered):
        # A new expression, age or style is painted, not retouched.
        action = result['action'] = 'generate'
        result['target'] = 'main subject'
    if action in ('shadows', 'highlights', 'blacks', 'whites') and not re.search(
            r'shadow|highlight|blacks|whites|dark (areas|parts|tones)|bright (areas|parts|tones)', lowered) and \
            re.search(r'\b(darken|darker|brighten|brighter|lighten|lighter|dim)\b', lowered):
        # “Darken the background” means the whole background, not only its darkest tones.
        action = result['action'] = 'exposure'
    if action in ('canvas_border', 'crop_aspect', 'resize', 'other') and (re.search(
            r'letterbox|\bbars\b|without (cropping|cutting)|(do not|don.?t|not) (crop|cut)', lowered) or re.search(
            r'\bfit\b|\bpad', lowered) and re.search(r'square|\d\s*:\s*\d|ratio|shape|insta|story|post', lowered)):
        action = result['action'] = 'fit_canvas'
    if 'headshot' in lowered and not PASSPORT.search(lowered) and action in (
            'passport_photo', 'crop_to_object', 'crop_aspect', 'look', 'other', 'retouch_portrait', 'resize'):
        action = result['action'] = 'headshot'
    if action in ('other', 'add_text') and 'watermark' in lowered:
        action = result['action'] = 'add_text'
        result['position'] = result['position'] or 'bottom right'
        result['size'] = result['size'] or 'small'
    if action == 'dehaze' and re.search(r'\b(add|more|create|make it)\b.*\b(fog|haze|mist|foggy|hazy|misty)', lowered):
        result['direction'] = 'decrease'  # “add fog” is less dehaze, not a clearer picture
    if action in ('other', 'generate', 'artistic', 'noise_reduction') and re.search(
            r'\b(rain|raining|rainy|snow|snowing|snowfall|snowflakes)\b', lowered) and not re.search(
            r'snowman|umbrella|puddle', lowered):
        action = result['action'] = 'weather'
        result['choice'] = 'snow' if 'snow' in lowered else 'rain'
    picture_words = r'^(the\s+)?(image|picture|photo|pic|whole thing|it|canvas|file)?$'
    if action in ('resize', 'other', 'generate', 'crop_to_object') and result['object'] and \
            not re.fullmatch(picture_words, result['object'].lower()) and re.search(
            r'\b(move|bigger|larger|smaller|shrink|enlarge|duplicate|clone|copy of)\b', lowered):
        # “Make the cat bigger” resizes the cat, not the picture.
        action = result['action'] = 'transform_object'
        result['target'] = 'object'
    if re.search(r'\bcolou?ri[sz]e|add colou?rs? to (this|the|an?)? ?(old|black|b&w|grayscale|greyscale)', lowered):
        action = result['action'] = 'generate'
        result['target'] = 'whole image'
    elif action in ('other', 'look', 'noise_reduction', 'sharpen') and re.search(
            r'\brestor|old (photo|picture|image)|damaged|scratched|torn|faded photo', lowered):
        action = result['action'] = 'restore'
    if action in ('look', 'auto_fix') and re.search(r'\b(more )?natural\b', lowered) and re.search(
            r'colou?r|saturat', lowered) and not re.search(r'cast|white balance', lowered):
        action = result['action'] = 'vibrance'
        result['direction'] = 'decrease'
    if action in ('straighten', 'rotate', 'other') and re.search(
            r'perspective|keystone|leaning|upright|converg|walls?\b.*\bvertical|vertical lines', lowered):
        action = result['action'] = 'perspective'
    elif action in ('other', 'straighten', 'vignette') and re.search(
            r'lens distortion|barrel|fish\s*eye|chromatic|aberration|color fring|purple fring|lens correct', lowered):
        action = result['action'] = 'lens_correction'
    hue_words = re.search(r'\b(blu|green|redd|yellow|orang|purpl|pink)er\b|\bmore (blue|green|red|yellow|orange|'
                          r'purple|pink)\b', lowered)
    if action in ('color_filter', 'saturation', 'recolor', 'hue_shift', 'color_grade') and re.search(
            r'\b(more |into |to )?(turquoise|teal|cyan|aqua)\b', lowered) and re.search(
            r'\b(water|sea|ocean|pool|lake|sky|river|bay)\b', lowered):
        # “Make the water more turquoise”: the blues turned toward cyan with Hue/Saturation, the way an
        # editor does it; a turquoise photo filter on the parts already cyan changed little.
        action = result['action'] = 'hue_shift'
        result.update(target='color', color='blue', direction='decrease',
                      strength='subtle' if result['strength'] != 'strong' else 'moderate')
    # “More turquoise” turns blues toward cyan: a hue change, which the planner's hue_shift already is.
    if hue_words and action in ('temperature', 'tint', 'color_filter'):
        # “Make the sky bluer” is a richer blue, not a cooler white balance over everything.
        word = next(group for group in hue_words.groups() if group)
        result['color'] = {'blu': 'blue', 'redd': 'red', 'orang': 'orange', 'purpl': 'purple'}.get(word, word)
        action = result['action'] = 'saturation'
        result['direction'] = 'increase'
        if result['target'] == 'whole image':
            result['target'] = 'color'
    if action in ('recolor', 'color_filter', 'color_overlay', 'generate') and result['target'] == 'background' \
            and PLAIN_BACKDROP.search(quote) and plain_color(quote) \
            and not re.search(r'\b(warm|cool)\b', plain_color(quote)):
        # “Change the background to light grey” is a new plain backdrop, not a grey tint over the old one.
        action = result['action'] = 'remove_background'
        result['color'] = plain_color(quote)
    if PASSPORT.search(quote) and action in ('crop_aspect', 'crop_to_object', 'resize', 'remove_background', 'other'):
        # A passport photo is a framing, a backdrop and a print size; a plain 3:4 crop of a photo
        # that is already 3:4 changed nothing (2026-10-11).
        action = result['action'] = 'passport_photo'
        result['target'] = 'main subject'
    if action == 'passport_photo':
        size = print_size(quote) or print_size(result['aspect'])
        if size:
            result['aspect'] = f'{size[0]:g}:{size[1]:g}'
    if action in ('crop_aspect', 'crop_to_object', 'resize'):
        ratio = aspect_from(quote) or aspect_from(result['aspect'])
        if ratio:
            result['aspect'] = f'{ratio[0]:g}:{ratio[1]:g}'
    if ACTIONS[action][0] == 'layer' and not re.search(r'\blayers?\b', quote, re.IGNORECASE):
        result['action'] = 'keep'
        notes.append(f'Read “{quote}” as something to keep, not a layer change.')
    elif action not in ('keep', 'crop_aspect', 'crop_to_object', 'passport_photo') and KEEP_ONLY.match(quote):
        # “Keep me sharp” protects the person; sharpening them put a copy of the untouched photo
        # over the earlier shirt and skin edits.
        result['action'] = 'keep'
        notes.append(f'Read “{quote}” as something to keep unchanged, not an edit.')
    if action == 'add_text':
        result['text'] = exact_text(result['text'], quote, prompt)
        if not result['text']:
            notes.append('Which words should the text say? Put them in quotes.')
    from image_studio.pipelines import get

    pipeline = get(result['action'])
    if not result['position'] and pipeline is not None and 'position' in pipeline.summary:
        # “Move the yellow mug to the left” once came back with no position at all.
        result['position'] = position_from_words(quote)
    if result['action'] != 'keep' and pipeline is not None and not pipeline.fits(result):
        result['misfit'] = True  # the planner is asked again for this clause (photocraft_planner.understand)
    elif pipeline is not None and result['action'] != 'keep':
        # Each pipeline's own menu for its choice slot: a choice naming nothing on it is asked
        # again with that menu alone (photocraft_planner.rechoose_slot).
        result['choice'], fits = pipeline.choice_on_menu(result['choice'], quote)
        if not fits:
            result['slot_misfit'] = True
    return result, notes


def position_from_words(text):
    """A position the words name (“to the left”, “at the bottom right”, “in the top corner”), or ''."""
    # Quoted words are a title's text (“Turn Right”), not where it goes.
    lowered = re.sub(r'["“”«»][^"“”«»]*["“”«»]', ' ', (text or '').lower())
    vertical = 'top' if re.search(r'\b(top|upper|up)\b', lowered) else \
        'bottom' if re.search(r'\b(bottom|lower|down)\b', lowered) else ''
    horizontal = 'left' if re.search(r'\bleft\b', lowered) else 'right' if re.search(r'\bright\b', lowered) else ''
    if not (vertical or horizontal):
        return 'center' if re.search(r'\b(cent(er|re)|middle)\b', lowered) else ''
    return ' '.join(part for part in (vertical, horizontal) if part)


RESCUES = [  # (words, action, fields): requests too technical to misread, kept even when the planner drops them
    (r'\b\d{2,4}\s*(dpi|ppi)\b', 'resize', {}),
    (r'\bcmyk\b', 'convert_mode', {'choice': 'cmyk'}),
    (r'\b(gr[ae]yscale|gr[ae]y)\s+mode\b', 'convert_mode', {'choice': 'grayscale'}),
    (r'chromatic aberration|lens distortion|barrel distortion|colou?r fringing', 'lens_correction', {}),
    (r'red[\s-]?eyes?', 'retouch_portrait', {'choice': 'red eye', 'target': 'main subject'}),
    (r'\bcolou?ri[sz]e', 'generate', {'target': 'whole image'}),
    (r'\brestore\b.*\b(photo|picture|image|it)\b|\bold (photo|picture)\b.*\b(fix|repair|restore)', 'restore', {}),
    (r'\bauto[\s-]*(contrast|tone|levels|colou?r)\b', 'auto_fix', {}),
]


def rescue(prompt, edits):
    """Edits for unmistakable technical requests the planner left out (it once filed “set the
    resolution to 300 dpi without changing the pixels” as only a keep-note)."""
    added = []
    for words, action, fields in RESCUES:
        match = re.search(words, prompt, re.IGNORECASE)
        if match and not any(edit['action'] == action for edit in list(edits) + added):
            if action == 'resize' and any(edit['action'] in ('passport_photo', 'headshot') for edit in edits):
                continue  # a passport photo sets its own print resolution
            clause = next((part for part in re.split(r'(?<=[.!?;,])\s+|\band\b', prompt) if re.search(
                words, part, re.IGNORECASE)), prompt).strip()
            added.append(blank(action, quote=clause, **fields))
    return added


def expand_workflows(edits, prompt=''):
    """Each workflow replaced by the procedures it is made of. A part the person also asked for
    in their own words (the same pipeline on the same target) is left to their edit, so “edit
    this room for a listing and brighten it a lot” brightens once, as strongly as they asked."""
    from image_studio.pipelines import get

    explicit = [edit for edit in edits if not (get(edit['action']) and get(edit['action']).workflow)]
    result = []
    for edit in edits:
        pipeline = get(edit['action'])
        if not (pipeline and pipeline.workflow):
            result.append(edit)
            continue
        for part in pipeline.expand(edit, prompt or edit['quote']):
            if any(other['action'] == part['action'] and other['target'] == part['target'] for other in explicit):
                continue
            part['source'] = edit['quote']  # the person's words this part answers
            result.append(part)
    return result


def expand(edits, preserve=(), prompt=''):
    """Edits that one request implies: each workflow's procedures; a passport photo needs a plain
    backdrop, which is a cut-out made before the crop (white unless a color is named or the
    background is kept); a headshot is polished and lightly retouched."""
    edits = expand_workflows(edits, prompt)
    result = list(edits)
    keeps_background = any(re.search(r'\bback\s*ground|backdrop', text, re.IGNORECASE) for text in preserve)
    for edit in edits:
        if edit['action'] == 'headshot':
            # A professional headshot is framed, polished and lightly retouched.
            if not any(other['action'] == 'look' for other in result):
                result.append(blank('look', quote='Gentle professional polish for the headshot',
                                    choice='professional polish', strength='subtle', part_of='headshot'))
            if not any(other['action'] == 'retouch_portrait' for other in result):
                result.append(blank('retouch_portrait', quote='Light skin smoothing for the headshot',
                                    choice='smooth', strength='subtle', target='main subject',
                                    part_of='headshot'))
            continue
        if edit['action'] != 'passport_photo' or keeps_background:
            continue
        if any(other['action'] == 'remove_background' for other in result):
            continue
        color = edit['color'] if hex_color(edit['color']) else 'white'
        result.append(blank('remove_background', quote=f'Plain {color} passport backdrop behind the person',
                            target='main subject', color=color, part_of='passport_photo'))
    return result


def exact_text(text, quote, prompt):
    """The words exactly as the person wrote them (quoted text wins, original letter case kept)."""
    for source in (quote, prompt):
        quoted = re.findall(r'["“”‘’\'«]([^"“”‘’\'»]{1,200})["“”‘’\'»]', source)
        for item in quoted:
            if text and item.strip().lower() == text.strip().lower():
                return item.strip()
        if len(quoted) == 1 and (not text or text.strip().lower() in quoted[0].lower()):
            return quoted[0].strip()
    if text:
        # Restore the person's letter case when the words appear in their request.
        found = re.search(re.escape(text.strip()), prompt, re.IGNORECASE)
        return found.group(0) if found else text.strip()
    return ''


def uncovered_clauses(prompt, edits, preserve):
    """Parts of the request that no edit or preservation note accounts for."""
    covered = ' '.join([f'{edit["quote"]} {edit.get("source", "")}' for edit in edits] + list(preserve)).lower()
    covered_words = set(re.findall(r'[a-z0-9]{3,}', covered))
    filler = {'please', 'the', 'and', 'then', 'also', 'make', 'image', 'photo', 'picture', 'can', 'you', 'this',
              'that', 'with', 'want', 'would', 'like', 'thanks', 'thank', 'should', 'need', 'just', 'its', 'it'}
    missing = []
    for clause in re.split(r'(?<=[.!?;])\s+|\n+', prompt):
        words = set(re.findall(r'[a-z0-9]{3,}', clause.lower())) - filler
        if len(words) >= 2 and len(words & covered_words) / len(words) < 0.4:
            missing.append(clause.strip())
    return missing


# ---- Document geometry ------------------------------------------------------------------------


class Canvas:
    """The document size as edits run, and how earlier geometry moves later boxes."""

    def __init__(self, width, height, resolution=72.0):
        self.width, self.height, self.resolution = width, height, resolution or 72.0
        self.maps = []

    def place(self, box):
        """A box [x, y, w, h] in original document pixels, moved through every geometry edit."""
        x, y, w, h = box
        points = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
        for move in self.maps:
            points = [move(px, py) for px, py in points]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        x0, y0 = max(0, min(xs)), max(0, min(ys))
        x1, y1 = min(self.width, max(xs)), min(self.height, max(ys))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        return [round(x0), round(y0), round(x1 - x0), round(y1 - y0)]


def largest_crop(width, height, ratio, focus=None, position=''):
    """The largest crop of the given aspect ratio, kept on the focus box or a position."""
    aspect = ratio[0] / ratio[1]
    if width / height > aspect:
        crop_h, crop_w = height, round(height * aspect)
    else:
        crop_w, crop_h = width, round(width / aspect)
    if focus:
        cx, cy = focus[0] + focus[2] / 2, focus[1] + focus[3] / 2
    else:
        cx = crop_w / 2 if 'left' in position else width - crop_w / 2 if 'right' in position else width / 2
        cy = crop_h / 2 if 'top' in position else height - crop_h / 2 if 'bottom' in position else height / 2
    x = min(max(0, round(cx - crop_w / 2)), width - crop_w)
    y = min(max(0, round(cy - crop_h / 2)), height - crop_h)
    return x, y, crop_w, crop_h


def fit_ratio(box, ratio, width, height):
    """The box grown to an aspect ratio around its center, moved (or shrunk) to stay inside."""
    x, y, w, h = box
    aspect = ratio[0] / ratio[1]
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    if w > width or h > height:
        scale = min(width / w, height / h)
        w, h = w * scale, h * scale
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    x = min(max(0, cx - w / 2), width - w)
    y = min(max(0, cy - h / 2), height - h)
    return [x, y, w, h]


def rotation_crop(width, height, degrees):
    """The largest same-shaped rectangle that stays inside a picture rotated by `degrees`."""
    angle = math.radians(abs(degrees) % 180)
    if angle > math.pi / 2:
        angle = math.pi - angle
    scale = min(width / (width * math.cos(angle) + height * math.sin(angle)),
                height / (width * math.sin(angle) + height * math.cos(angle)))
    crop_w, crop_h = math.floor(width * scale), math.floor(height * scale)
    return (width - crop_w) // 2, (height - crop_h) // 2, crop_w, crop_h


# ---- Compiling --------------------------------------------------------------------------------


def amount(edit, base, low, high, signed=True):
    """The engine value for an edit: the person's own number, or a base scaled by strength."""
    if edit['value'] is not None:
        value = edit['value']
        if signed and edit['direction'] == 'decrease' and value > 0:
            value = -value
    else:
        value = base * LEVEL[edit['strength']]
        if signed and edit['direction'] == 'decrease':
            value = -value
    return max(low, min(high, round(value, 2)))


def text_size_pt(edit, canvas):
    """Point size of a title: the person's size, else a share of the shorter side."""
    if edit['value'] is not None and re.search(r'\d\s*(pt|point|px|pixel)', edit['quote'], re.IGNORECASE):
        px = edit['value']
        if re.search(r'\d\s*(px|pixel)', edit['quote'], re.IGNORECASE):
            return round(px * 72 / canvas.resolution, 1)
        return round(px, 1)
    share = {'small': 0.045, 'medium': 0.075, 'large': 0.11, 'huge': 0.16}.get(edit['size'] or 'medium')
    return round(min(canvas.width, canvas.height) * share * 72 / canvas.resolution, 1)


def font_choice(choice, fonts):
    """(font family or None, weight, italic, effects) from a free style description."""
    text = (choice or '').lower()
    effects = [name for name in ('shadow', 'outline', 'glow') if name in text]
    weight = 700 if re.search(r'\bbold|heavy|thick\b', text) else 300 if re.search(r'\bthin|light\b', text) else None
    italic = bool(re.search(r'\bitalic|oblique\b', text))
    by_name = {font.lower(): font for font in fonts}
    family = None
    cleaned = ' '.join(re.sub(r'\b(bold|italic|heavy|thin|light|font|typeface|shadow|outline|glow|with|and|a|in|'
                              r'style)\b', ' ', text).split())
    generic = {
        r'\bserif\b|classic|elegant|times': ['Georgia', 'Times New Roman', 'Garamond', 'Cambria'],
        r'script|handwrit|cursive|signature': ['Segoe Script', 'Brush Script MT', 'Lucida Handwriting', 'Gabriola'],
        r'\bmono|typewriter|code': ['Consolas', 'Courier New'],
        r'impact|poster|headline|display|condensed': ['Impact', 'Bahnschrift', 'Franklin Gothic Heavy'],
        r'modern|clean|minimal|sans': ['Inter', 'Segoe UI', 'Arial'],
        r'playful|fun|comic|kids': ['Comic Sans MS', 'Cooper Black'],
    }
    if cleaned in by_name:
        family = by_name[cleaned]
    elif cleaned and not any(re.fullmatch(pattern, cleaned) for pattern in generic):
        # A named font: whole-word match only, so “serif” never picks “Microsoft Sans Serif”.
        matches = sorted((font for key, font in by_name.items() if re.search(rf'\b{re.escape(cleaned)}\b', key)),
                         key=len)
        family = matches[0] if matches else None
    if family is None:
        for pattern, options in generic.items():
            if re.search(pattern, text):
                family = next((by_name[o.lower()] for o in options if o.lower() in by_name), None) or (
                    'Inter' if 'Inter' in options else None)
                break
    return family, weight, italic, effects


class Compiler:
    def __init__(self, state, fonts=(), boxes=None, ai=False, analysis=None):
        self.state = state
        self.ai = ai
        self.analysis = analysis or {}  # measured from the pixels: tilt, verticals
        self.canvas = Canvas(state['width'], state['height'], state.get('resolution', 72.0))
        self.fonts = list(fonts)
        self.boxes = boxes or {}
        self.steps, self.notes, self.blocking, self.regions = [], [], [], []
        self.raw = {}
        self.clip = False
        self.cropped_out = set()
        self.removed = []
        self.start = (state['width'], state['height'])

    # -- helpers
    def add(self, index, command, params=None, label=''):
        self.steps.append({'command': command, 'params': params or {}, 'label': label, 'requirements': [index]})

    def layer_named(self, name):
        wanted = (name or '').lower().strip()
        layers = list(flatten(self.state.get('layers', [])))
        if not wanted:
            return None
        for layer in layers:
            if layer['name'].lower() == wanted or (layer.get('text') or {}).get('text', '').lower() == wanted:
                return layer
        scored = [layer for layer in layers if wanted in layer['name'].lower() or layer['name'].lower() in wanted
                  or wanted in (layer.get('text') or {}).get('text', '').lower()]
        if not scored and wanted in ('text', 'title', 'the text', 'type', 'text layer'):
            scored = [layer for layer in layers if layer['kind'] == 'Type']
        return scored[0] if len(scored) == 1 else None

    def target_boxes(self, edit, key=None):
        """Document boxes for a subject/object target (or the query `key`), after earlier
        geometry, or None."""
        key = key or subject_query(edit)
        found = self.boxes.get(key.lower()) if key else None
        if not found:
            return key, None
        placed = [box for box in (self.canvas.place(b) for b in found) if box]
        # A sliver left at the frame's edge after a crop is not the object any more.
        whole = [b for b, p in zip(found, (self.canvas.place(b) for b in found)) if p]
        placed = [p for p in placed if p[2] * p[3] >= 0.25 * min(b[2] * b[3] for b in whole)] if whole else []
        if key == FOREGROUND:
            # Something removed earlier in this plan is background now, not something in front of it.
            placed = [p for p in placed if not any(overlap(p, gone) > 0.5 for gone in self.removed)]
        if not placed:
            self.cropped_out.add(key)
        return key, placed or None

    def spans(self, boxes, start, size, along_x):
        """The (start, end) spans of `boxes` along x (or y) that share the band [start, start + size]
        on the other axis, padded a little because found boxes are approximate."""
        pad = min(self.canvas.width, self.canvas.height) * 0.01
        found = []
        for bx, by, bw, bh in boxes:
            lo, length, at, extent = (bx, bw, by, bh) if along_x else (by, bh, bx, bw)
            shared = min(start + size, at + extent) - max(start, at)
            if shared > 0.2 * min(size, extent):
                found.append((lo - pad, lo + length + pad))
        return found

    def selection(self, index, edit, invert=False):
        """Steps that select the edit's target; False when the target cannot be selected."""
        target = edit['target']
        if edit['action'] in ('remove_background', 'blur_background') and target in ('whole image', 'background'):
            target = 'main subject'
        if target == 'whole image':
            return True
        if target in ('main subject', 'background', 'object'):
            key, boxes = self.target_boxes({**edit, 'target': target})
            if not boxes:
                if key in self.cropped_out:
                    self.blocking.append(f'{key[:1].upper() + key[1:]} is outside the picture after the crop, so '
                                         f'“{edit["quote"]}” cannot be applied.')
                else:
                    self.blocking.append(f'Could not find {key or "the object"} in the picture. Describe it '
                                         'differently.')
                return False
            # The studio traces the outline (SAM 2.1): PhotoCraft's object selection took a block of
            # the backdrop beside a man's head, cut into his hair, and for “the beard” took the
            # whole lower face, cheeks and lips included.
            self.add(index, 'studio.select_outline', {'boxes': boxes, 'what': key}, f'Select {key}')
            self.regions.append({'requirement': index, 'label': key,
                                 'boxes': [[b[0] / self.canvas.width, b[1] / self.canvas.height,
                                            b[2] / self.canvas.width, b[3] / self.canvas.height] for b in boxes]})
            # An empty selection would let the edit hit the whole picture.
            self.add(index, 'studio.require_selection', {'what': key, 'min_coverage': 0.001}, f'Check {key} was found')
            if target == 'background' or invert:
                self.add(index, 'select.inverse', {}, 'Select everything else')
        elif target == 'sky':
            self.add(index, 'select.sky', {}, 'Select the sky')
            self.add(index, 'studio.require_selection', {'what': 'sky', 'min_coverage': 0.02}, 'Check the sky')
            # PhotoCraft's sky leaves a soft band around people and buildings, which shows as a halo.
            # Grow the sky over that band, then cut everything in front back out along its outline.
            _, front = self.target_boxes({**edit, 'target': 'background', 'object': ''})
            if front:
                grow = max(4, round(min(self.canvas.width, self.canvas.height) * 0.035))
                self.add(index, 'select.modify.expand', {'radius': grow}, 'Reach the sky’s edges')
                for box in front:
                    self.add(index, 'select.object', {'rect': box, 'mode': 'subtract', 'sampleAllLayers': True},
                             'Keep what is in front of the sky')
        elif target == 'color':
            color = hex_color(edit['color'] or edit['object'])
            if not color:
                self.blocking.append(f'Which color should “{edit["quote"]}” affect?')
                return False
            self.add(index, 'select.colorRange', {'select': color_family(color), 'fuzziness': 40},
                     f'Select {color_family(color)}')
        elif target in ('shadows', 'midtones', 'highlights'):
            self.add(index, 'select.colorRange', {'select': target}, f'Select the {target}')
        elif target == 'area':
            w, h = self.canvas.width, self.canvas.height
            pos = edit['position'] or 'center'
            x0 = 0 if 'left' in pos or pos in ('top', 'bottom') else w // 2 if 'right' in pos else w // 4
            y0 = 0 if 'top' in pos or pos in ('left', 'right') else h // 2 if 'bottom' in pos else h // 4
            rw = w if pos in ('top', 'bottom') else w // 2
            rh = h if pos in ('left', 'right') else h // 2
            self.add(index, 'select.rect', {'x': x0, 'y': y0, 'width': rw, 'height': rh,
                                            'feather': round(min(w, h) * 0.08)}, f'Select the {pos} area')
            self.regions.append({'requirement': index, 'label': f'{pos} area',
                                 'boxes': [[x0 / w, y0 / h, rw / w, rh / h]]})
        elif target == 'layer':
            return True
        if invert and target not in ('main subject', 'background', 'object'):
            self.add(index, 'select.inverse', {}, 'Select everything else')
        return True

    def visible_part(self, box):
        """(the part of an original box still in the final picture, where that part ended up), both
        normalized, so a measurement compares the same pixels before and after a crop."""
        x, y, w, h = box
        kept = []
        for i in range(21):
            for j in range(21):
                px, py = x + w * i / 20, y + h * j / 20
                qx, qy = px, py
                for move in self.canvas.maps:
                    qx, qy = move(qx, qy)
                if 0 <= qx <= self.canvas.width and 0 <= qy <= self.canvas.height:
                    kept.append((px, py, qx, qy))
        if len(kept) < 4:
            return None
        ox = [k[0] for k in kept]
        oy = [k[1] for k in kept]
        fx = [k[2] for k in kept]
        fy = [k[3] for k in kept]
        if max(ox) - min(ox) < 2 or max(oy) - min(oy) < 2:
            return None
        sw, sh = self.start
        return ([min(ox) / sw, min(oy) / sh, (max(ox) - min(ox)) / sw, (max(oy) - min(oy)) / sh],
                [min(fx) / self.canvas.width, min(fy) / self.canvas.height,
                 (max(fx) - min(fx)) / self.canvas.width, (max(fy) - min(fy)) / self.canvas.height])

    def normalized(self, boxes):
        return [[b[0] / self.canvas.width, b[1] / self.canvas.height, b[2] / self.canvas.width,
                 b[3] / self.canvas.height] for b in boxes]

    def end_selection(self, index):
        self.add(index, 'select.deselect', {}, 'Deselect')

    def after_new_layer(self, index, name):
        self.add(index, 'layer.renameLayer', {'name': name[:80]}, f'Name the layer “{name[:40]}”')
        if self.clip:
            self.add(index, 'layer.setProps', {'clipped': True}, 'Clip to the cut-out')

    # -- compiling each group
    def compile(self, edits):
        """Build every edit with its pipeline, in stage order (the retoucher's order)."""
        from image_studio.pipelines import STAGES, get

        def rank(i):
            pipeline = get(edits[i]['action'])
            return (STAGES.index(pipeline.stage) if pipeline and pipeline.stage in STAGES else 99, i)

        self.edits = edits
        self.clip = any(e['action'] == 'remove_background' and hex_color(e['color']) for e in edits)
        for index in sorted(range(len(edits)), key=rank):
            edit = edits[index]
            if group(edit) != 'develop' and self.raw:
                self.flush_raw()
            marks = (len(self.steps), len(self.blocking), len(self.regions), len(self.notes))
            self.run(edit['action'], index, edit)
            if edit.get('optional') and len(self.blocking) > marks[1]:
                # A part of a workflow that does not apply to this photo is skipped, not a reason to stop.
                reasons = self.blocking[marks[1]:]
                del self.steps[marks[0]:], self.blocking[marks[1]:], self.regions[marks[2]:]
                self.raw.pop(index, None)
                self.notes.append(f'Skipped “{edit["quote"]}”: ' + ' '.join(reasons))
        self.flush_raw()
        for region in self.regions:
            final, pairs = [], []
            for x, y, w, h in region['boxes']:
                placed = self.canvas.place([x * self.start[0], y * self.start[1], w * self.start[0],
                                            h * self.start[1]])
                if placed:
                    final.append([placed[0] / self.canvas.width, placed[1] / self.canvas.height,
                                  placed[2] / self.canvas.width, placed[3] / self.canvas.height])
                visible = self.visible_part([x * self.start[0], y * self.start[1], w * self.start[0],
                                             h * self.start[1]])
                if visible:
                    pairs.append(visible)
            region['final'] = final
            region['pairs'] = pairs
            if region['boxes'] and not final:
                self.notes.append(f'{region["label"][:1].upper() + region["label"][1:]} ends up outside the cropped '
                                  'picture, so that change will not be visible.')
        return self.steps

    def run(self, pipeline_id, index, edit):
        """Build one procedure. A builder subclass may override a pipeline with a method named
        do_<pipeline id> (the marked-area builder limits removals and blurs to the marks)."""
        from image_studio.pipelines import get

        override = getattr(self, f'do_{pipeline_id}', None)
        if override is not None:
            return override(index, edit)
        pipeline = get(pipeline_id)
        if pipeline is None or pipeline.build is None:
            self.blocking.append(f'“{edit["quote"]}” is not something this workspace can do yet.')
            return None
        first = len(self.steps)
        result = pipeline.build(self, index, edit)
        for step in self.steps[first:]:
            step.setdefault('pipeline', pipeline_id)
            if edit.get('optional'):
                step['optional'] = True  # if it fails in the engine, only this part is skipped
        return result

    def flush_raw(self):
        if not self.raw:
            return
        merged, indices = {}, set()
        for index, params in self.raw.items():
            indices.add(index)
            for key, value in params.items():
                # Point curves are a shape, not an amount: the later one replaces.
                merged[key] = value if isinstance(value, list) else round(merged.get(key, 0) + value, 2)
        self.steps.append({'command': 'studio.develop', 'params': {'params': merged},
                           'label': 'Develop: ' + ', '.join(f'{k} {v:+g}' if not isinstance(v, list) else f'{k} curve'
                                                            for k, v in merged.items()),
                           'requirements': sorted(indices)})
        self.raw = {}

    def crop(self, index, x, y, w, h, label):
        self.add(index, 'image.crop', {'x': x, 'y': y, 'width': w, 'height': h}, label + f' ({w}×{h})')
        self.canvas.maps.append(lambda px, py, x=x, y=y: (px - x, py - y))
        self.canvas.width, self.canvas.height = w, h

    def local_develop(self, index, edit, params, label, description, refine=None):
        """Camera Raw settings for one area, on a masked copy of the photo. A second request for
        the same area joins that copy: two copies with one mask would hide the lower one.
        `refine(index)` adds steps that narrow the selection."""
        region = region_key(edit)
        for step in reversed(self.steps):
            settings = step['params']
            if step['command'] != 'studio.local_filter' or settings.get('region') != region or \
                    settings['command'] != 'filter.cameraRaw':
                continue
            for key, value in params.items():
                settings['params'][key] = round(settings['params'].get(key, 0) + value, 2)
            settings['label'] = merged_label(settings['label'], label)
            step['label'] = f'{settings["label"]} on its own masked layer'
            step['requirements'].append(index)
            first = step['requirements'][0]
            self.regions += [{**area, 'requirement': index} for area in self.regions
                             if area['requirement'] == first]
            return True
        if not self.selection(index, edit):
            return False
        if refine:
            refine(index)
        self.add(index, 'studio.local_filter', {'command': 'filter.cameraRaw', 'params': params,
                                                'label': label, 'region': region}, description)
        self.end_selection(index)
        return True

    def adjustment(self, index, edit, command, params, name):
        targeted = edit['target'] not in ('whole image', 'layer')
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        if targeted and not self.selection(index, edit):
            return
        self.add(index, f'layer.newAdjustmentLayer.{command}', params, name)
        self.after_new_layer(index, name)
        if targeted:
            self.end_selection(index)

    expert_requests = None
    edits = ()


KEEP_IN_FRAME = re.compile(
    r"\b(?:keep(?:ing)?|with|so that|making sure)\s+(?P<a>(?:the|my|our|his|her|their)\s+[\w\s'-]{2,40}?)\s+"
    r"(?:in (?:the )?frame|in view|visible|centered|in the center|in the middle)\b"
    r"|\b(?:around|centered on|focused on|focusing on)\s+(?P<b>(?:the|my|our|his|her|their)\s+[\w'-]+"
    r"(?:\s+[\w'-]+)?)",
    re.IGNORECASE)


def kept_in_frame(quote):
    """What a crop request says to keep in the frame (“keeping the cat in frame”), or ''."""
    match = KEEP_IN_FRAME.search(quote or '')
    return (match.group('a') or match.group('b')).strip() if match else ''


FOREGROUND = 'everything in the foreground'
BACKGROUND_WORDS = re.compile(r'^(the\s+)?(back\s*ground|backdrop|surroundings|scene|wall|rest)$', re.IGNORECASE)


def subject_query(edit):
    """The description to find in the picture for an edit's subject, object or background.

    A background is selected as “everything but what stands in front of it”, so its query is
    the foreground (named, or all of it), never the word “background” itself."""
    named = '' if BACKGROUND_WORDS.match(edit['object'] or '') else edit['object']
    if edit['action'] in ('passport_photo', 'headshot'):
        return PASSPORT_HEAD
    if edit['action'] == 'recolor' and IRIS_WORDS.search(named or ''):
        return EYES  # “her eyes” finds nothing; “each eye” boxes both (measured)
    if edit['action'] in ('crop_aspect', 'crop_to_object'):
        kept = kept_in_frame(edit['quote'])
        if kept:
            return kept
        if edit['action'] == 'crop_aspect' and edit['target'] not in ('main subject', 'object'):
            return named if named and edit['target'] != 'whole image' else ''
    if edit['action'] in ('blur_background', 'remove_background', 'drop_shadow', 'transform_object', 'center_subject',
                          'reflection'):
        # The cut-out keeps the subject; “the background” (target) is what goes.
        return named or 'the main subject'
    if edit['target'] == 'background':
        return named or FOREGROUND
    if named and edit['target'] in ('main subject', 'object'):
        return named
    if edit['target'] == 'main subject' or edit['action'] in ('remove_background', 'crop_to_object'):
        return named or 'the main subject'
    return named


def flatten(layers):
    for layer in layers:
        yield layer
        yield from flatten(layer.get('children', []))


def group(edit):
    return ACTIONS.get(edit['action'], ('expert', ''))[0]


def position_xy(position):
    x = 0.15 if 'left' in position else 0.85 if 'right' in position else 0.5
    y = 0.15 if 'top' in position else 0.85 if 'bottom' in position else 0.5
    return x, y


def short_label(edit):
    words = {'increase': 'More', 'decrease': 'Less', 'none': ''}[edit['direction']]
    action = edit['action'].replace('_', ' ')
    # The part after “ · ” names the area; a later request for the same area joins its layer.
    area = {'object': edit['object'] or 'object', 'area': f'{edit["position"] or "center"} area',
            'color': f'{edit["color"] or edit["object"]} tones'.strip()}.get(edit['target'], edit['target'])
    target = '' if edit['target'] in ('whole image', 'layer') else f' · {area}'
    value = f' {edit["value"]:g}' if edit['value'] is not None else ''
    return f'{words} {action}{value}{target}'.strip().capitalize()


def region_key(edit):
    """Which area an edit selects: edits with the same key get the same mask."""
    query = subject_query(edit) if edit['target'] in ('main subject', 'background', 'object') else ''
    return '|'.join([edit['target'], query.lower(), edit['position'] or '', edit['color'] or ''])


def merged_label(first, second):
    """“More shadows · the shirt” + “Less texture · the shirt” → “More shadows, less texture · the shirt”."""
    head, _, area = first.partition(' · ')
    extra = second.partition(' · ')[0]
    return f'{head}, {extra[:1].lower() + extra[1:]}' + (f' · {area}' if area else '')


def compile_edits(edits, state, fonts=(), boxes=None, ai=False, analysis=None):
    """(steps, notes, blocking, regions, expert edit indices, final canvas) for normalized edits."""
    compiler = Compiler(state, fonts, boxes, ai, analysis)
    compiler.expert_requests = []
    compiler.compile(edits)
    return compiler.steps, compiler.notes, compiler.blocking, compiler.regions, compiler.expert_requests, \
        compiler.canvas


def presets(name):
    """Edits for the one-click looks shown in the interface."""
    key = name.strip().lower()
    if key in RECIPES or key in [lut.lower() for lut in LUTS]:
        return [{'action': 'look', 'quote': name, 'target': 'whole image', 'object': '', 'direction': 'none',
                 'strength': 'moderate', 'value': None, 'text': '', 'color': '', 'position': '', 'size': '',
                 'aspect': '', 'choice': name}]
    return None


def blank(action, **fields):
    """A complete edit for the manual panels, which speak the same language as the planner."""
    edit = {'action': action, 'quote': fields.pop('quote', action.replace('_', ' ')), 'target': 'whole image',
            'object': '', 'direction': 'none', 'strength': 'moderate', 'value': None, 'text': '', 'color': '',
            'position': '', 'size': '', 'aspect': '', 'choice': ''}
    edit.update(fields)
    return edit


# ---- Checking the result ------------------------------------------------------------------------


def _hsv(image, box=None):
    """(hue degrees, saturation, value) arrays for a normalized box of an image."""
    import numpy as np

    picture = image.convert('RGB')
    if box:
        x, y, w, h = box
        picture = picture.crop((round(x * picture.width), round(y * picture.height),
                                round((x + w) * picture.width), round((y + h) * picture.height)))
    hsv = np.asarray(picture.convert('HSV'), dtype=np.float32) / 255
    return hsv[..., 0] * 360, hsv[..., 1], hsv[..., 2]


def overlap(a, b):
    """Intersection over union of two [x, y, w, h] boxes."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def is_duplicate(words):
    return bool(re.search(r'duplicat|clone|copy|another|second|two of', words))


def moves_among_others(edit):
    """Whether a transform puts the object somewhere new, so the other things in the picture must
    be found to keep it clear of them."""
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    return edit['action'] == 'transform_object' and bool(edit['position'] or is_duplicate(words))


def covered(a, b):
    """The share of box a that lies inside box b."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return max(0, x1 - x0) * max(0, y1 - y0) / (a[2] * a[3]) if a[2] * a[3] else 0.0


def free_spot(size, limit, blocked, wanted, allowed):
    """The free position nearest `wanted` for a span of `size` on one axis of length `limit`:
    clear of every `blocked` (start, end) span and within `allowed` (lo, hi). None when no gap
    is wide enough."""
    edges = sorted(blocked)
    gaps, cursor = [], 0.0
    for lo, hi in edges:
        if lo > cursor:
            gaps.append((cursor, lo))
        cursor = max(cursor, hi)
    gaps.append((cursor, limit))
    best = None
    for lo, hi in gaps:
        lo, hi = max(lo, allowed[0]), min(hi - size, allowed[1])
        if lo > hi:
            continue
        spot = min(max(wanted, lo), hi)
        if best is None or abs(spot - wanted) < abs(best - wanted):
            best = spot
    return best


def _pixels(box, size):
    x, y, w, h = box
    return (round(x * size[0]), round(y * size[1]), max(round(x * size[0]) + 1, round((x + w) * size[0])),
            max(round(y * size[1]) + 1, round((y + h) * size[1])))


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _core(box, share=0.5):
    """The middle of a box, where the object is rather than its surroundings."""
    x, y, w, h = box
    return [x + w * (1 - share) / 2, y + h * (1 - share) / 2, w * share, h * share]


def removal_score(before, after, box):
    """How much an object's area still stands out from its surroundings after a removal,
    relative to before (0 = blends in like the background, 1 = as distinct as the object was).
    Kontext sometimes paints a different object instead of removing; this catches that."""
    import numpy as np

    def contrast(image):
        rgb = np.asarray(image.convert('RGB'), dtype=np.float32) / 255
        height, width = rgb.shape[:2]
        x, y, w, h = box
        pad_x, pad_y = w * 0.35, h * 0.35
        outer = np.zeros((height, width), dtype=bool)
        outer[max(0, round((y - pad_y) * height)):round((y + h + pad_y) * height),
              max(0, round((x - pad_x) * width)):round((x + w + pad_x) * width)] = True
        inner = np.zeros_like(outer)
        inner[round(y * height):round((y + h) * height), round(x * width):round((x + w) * width)] = True
        core = np.zeros_like(outer)
        cx, cy, cw, ch = _core(box, 0.6)
        core[round(cy * height):round((cy + ch) * height), round(cx * width):round((cx + cw) * width)] = True
        ring = outer & ~inner
        if not ring.any() or not core.any():
            return 0.0
        return float(np.linalg.norm(rgb[core].mean(axis=0) - rgb[ring].mean(axis=0)))

    def flat(image):
        """Whether the area is far smoother than around it. A blurred grey panel matching the wall's
        average colour covered a removed mug and the shelf under it: 0.12 of the surrounding detail,
        where good fills measured 0.34 to 0.6 (2026-10-12)."""
        from PIL import ImageFilter

        gray = image.convert('L')
        sharp = np.asarray(gray, dtype=np.float32)
        detail = np.abs(sharp - np.asarray(gray.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32))
        height, width = detail.shape
        x, y, w, h = box
        inner = np.zeros((height, width), dtype=bool)
        inner[round(y * height):round((y + h) * height), round(x * width):round((x + w) * width)] = True
        outer = np.zeros_like(inner)
        outer[max(0, round((y - h / 3) * height)):round((y + h * 4 / 3) * height),
              max(0, round((x - w / 3) * width)):round((x + w * 4 / 3) * width)] = True
        ring = outer & ~inner
        if not inner.any() or not ring.any() or detail[ring].mean() < 1.0:
            return False  # a plain backdrop is smooth everywhere
        return detail[inner].mean() / detail[ring].mean() < 0.2

    after = after.resize(before.size) if after.size != before.size else after
    old, new = contrast(before), contrast(after)
    score = new / old if old > 0.04 else 0.0
    return max(score, 0.9) if flat(after) else score


LOCAL_TONE = {'brightness': 'brightness', 'exposure': 'brightness', 'shadows': 'shadow brightness',
              'highlights': 'highlight brightness', 'temperature': 'warmth', 'saturation': 'saturation',
              'vibrance': 'saturation', 'texture': 'fine detail', 'clarity': 'fine detail'}


def local_tone_check(index, edit, pairs, before, after, others=()):
    """Did a tone or color edit on one area move that area the asked way? Measured on the pixels
    that changed inside its boxes (the mask), so the rest of each box does not dilute it, leaving
    out boxes of other areas: the hands' box overlaps a shirt that was edited the other way."""
    import numpy as np

    action, name = edit['action'], LOCAL_TONE[edit['action']]
    olds, news, masks, everything = [], [], [], []
    for original, final in pairs:
        crop = _pixels(original, before.size)
        old = before.convert('RGB').crop(crop)
        new = after.convert('RGB').crop(_pixels(final, after.size)).resize(old.size)
        a = np.asarray(old, dtype=np.float32) / 255
        b = np.asarray(new, dtype=np.float32) / 255
        changed = np.abs(a - b).max(axis=2) > 1.5 / 255
        mine = changed.copy()
        for box in others:
            x0, y0, x1, y1 = _pixels(box, before.size)
            mine[max(0, y0 - crop[1]):max(0, y1 - crop[1]), max(0, x0 - crop[0]):max(0, x1 - crop[0])] = False
        olds.append(a)
        news.append(b)
        masks.append(mine)
        everything.append(changed)
    if sum(int(m.sum()) for m in masks) < 0.2 * sum(int(m.sum()) for m in everything):
        masks = everything  # the area lies almost wholly inside another one: measure it all
    share = sum(int(m.sum()) for m in masks) / max(1, sum(m.size for m in masks))
    what = edit['object'] or edit['target']
    if share < 0.01:
        return {'requirement': index, 'check': f'Measured: {what} did not change', 'passed': False,
                'measured': True}

    def value(images):
        total, weight = 0.0, 0
        if action in ('texture', 'clarity'):
            # Detail relative to brightness: darkening the same beard also shrinks its pixel
            # differences, which read as “less definition” when measured absolutely.
            light = 0.0
            for rgb, mask in zip(images, masks):
                lum = rgb.mean(axis=2)
                detail = np.abs(np.diff(lum, axis=0))[:, :-1] + np.abs(np.diff(lum, axis=1))[:-1, :]
                inside = mask[:-1, :-1]
                total += float(detail[inside].sum())
                light += float(lum[:-1, :-1][inside].sum())
            return total / max(light, 1e-6)
        for rgb, mask, reference in zip(images, masks, olds):
            lum = rgb.mean(axis=2)
            inside = mask
            if action == 'shadows':
                dark = mask & (reference.mean(axis=2) < 0.35)
                inside = dark if dark.any() else mask
            elif action == 'highlights':
                bright = mask & (reference.mean(axis=2) > 0.65)
                inside = bright if bright.any() else mask
            if action == 'temperature':
                values = rgb[..., 0] - rgb[..., 2]
            elif action in ('saturation', 'vibrance'):
                high, low = rgb.max(axis=2), rgb.min(axis=2)
                values = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0)
            else:
                values = lum
            total += float(values[inside].sum())
            weight += int(inside.sum())
        return total / max(1, weight)

    old, new = value(olds), value(news)
    rising = edit['direction'] == 'increase'
    if action in ('texture', 'clarity'):
        moved = (new - old) / max(old, 1e-6)  # detail is relative: −10% reads the same on any photo
        passed = moved > 0.02 if rising else moved < -0.02
        detail = f'{name} {moved:+.0%}'
    else:
        moved = new - old
        passed = moved > 0.004 if rising else moved < -0.004
        detail = f'{name} {old * 255:.0f} → {new * 255:.0f} of 255'
        if passed and abs(moved) < 0.012:
            detail += ' (a small change)'
    record = {'requirement': index, 'check': f'Measured: {what} {detail}', 'passed': passed, 'measured': True}
    if not passed and (moved > 0 if rising else moved < 0):
        record['weak'] = True  # the asked way, not far enough: a stronger run can fix it
    return record


def blur_checks(index, boxes, before, after):
    """A background blur: fine detail outside the subject's boxes drops, and the middle of the
    subject (away from its edge, which the soft mask touches) stays as it was."""
    import numpy as np

    def gray(img):
        return np.asarray(img.convert('L').resize(before.size), dtype=np.float32) / 255

    old, new = gray(before), gray(after)
    height, width = old.shape
    outside = np.ones_like(old, dtype=bool)
    for x, y, w, h in boxes:
        outside[round(y * height):round((y + h) * height), round(x * width):round((x + w) * width)] = False

    def detail(img):
        edges = np.abs(np.diff(img, axis=0))[:, :-1] + np.abs(np.diff(img, axis=1))[:-1, :]
        return float(edges[outside[:-1, :-1]].mean()) if outside[:-1, :-1].any() else 0.0

    checks = []
    if outside.mean() > 0.05 and detail(old) > 0:
        drop = 1 - detail(new) / detail(old)
        checks.append({'requirement': index, 'check': f'Measured: background detail {-drop:+.0%}',
                       'passed': drop > 0.1, 'measured': True})
    moved = []
    for box in boxes:
        x0, y0, x1, y1 = _pixels(_core(box, 0.5), (width, height))
        moved.append(float(np.abs(old[y0:y1, x0:x1] - new[y0:y1, x0:x1]).mean()))
    change = max(moved) * 255
    checks.append({'requirement': index, 'check': f'Measured: the subject stayed sharp (changed {change:.1f} of 255)',
                   'passed': change < 3, 'measured': True})
    return checks


# What else moves the quantity a global check measures. A plan that also neutralises a warm cast
# lowers saturation while its vibrance step raises it; comparing the whole picture before and after
# then says nothing about the vibrance step (a false failure, measured 2026-10-12).
MOVES = {
    'brightness': {'brightness', 'exposure', 'exposure_fix', 'auto_fix', 'look', 'tone_curve', 'shadows', 'highlights',
                   'whites', 'blacks', 'graduated_filter', 'window_pull', 'vignette', 'dehaze', 'black_and_white'},
    'saturation': {'saturation', 'vibrance', 'auto_fix', 'look', 'black_and_white', 'sepia', 'season', 'split_tone',
                   'color_filter', 'keep_one_color', 'duotone', 'dehaze', 'temperature'},
    'warmth': {'temperature', 'tint', 'auto_fix', 'look', 'color_filter', 'split_tone', 'color_grade', 'season'},
}
MEASURED_AS = {'brightness': 'brightness', 'exposure': 'brightness', 'saturation': 'saturation',
               'vibrance': 'saturation', 'temperature': 'warmth'}


def moved_by_others(edits, index):
    """Whether another edit in the plan also moves what this edit's global check measures."""
    quantity = MOVES[MEASURED_AS[edits[index]['action']]]
    return any(other['action'] in quantity for number, other in enumerate(edits) if number != index)


def measure(edits, regions, before, after, geometry_changed):
    """Pixel measurements of the rendered result for edits whose effect can be measured. A
    visual model can say “done” for a mug that is still grey; numbers cannot."""
    import numpy as np

    from image_studio.pipelines import checks as pipeline_checks

    checks = []
    by_requirement = {}
    originals = {}
    spots = {}
    for region in regions:
        if region.get('label') == 'spots':
            # Healed spots are checked one by one, not as the area an edit worked on.
            spots.setdefault(region['requirement'], []).extend(region.get('final', region['boxes']))
            continue
        by_requirement.setdefault(region['requirement'], []).extend(region.get('final', region['boxes']))
        pairs = region.get('pairs')
        if pairs is None:
            pairs = list(zip(region['boxes'], region.get('final', region['boxes'])))
        originals.setdefault(region['requirement'], []).extend(pairs)
    for index, edit in enumerate(edits):
        action, boxes = edit['action'], by_requirement.get(index)
        try:
            if action == 'recolor' and originals.get(index) and hex_color(edit['color']):
                target = hex_color(edit['color'])
                hue_t, _, sat_t = hls(target)
                changed_hues, changed_sats, total, moved = [], [], 0, 0
                for original, final in originals[index]:
                    old = before.convert('RGB').crop(_pixels(original, before.size))
                    new = after.convert('RGB').crop(_pixels(final, after.size)).resize(old.size)
                    a = np.asarray(old, dtype=np.float32) / 255
                    b = np.asarray(new, dtype=np.float32) / 255
                    changed = np.linalg.norm(a - b, axis=2) > 0.08
                    total += changed.size
                    moved += int(changed.sum())
                    hue, sat, _ = _hsv(new)
                    changed_hues.append(hue[changed])
                    changed_sats.append(sat[changed])
                hues, sats = np.concatenate(changed_hues), np.concatenate(changed_sats)
                share = moved / max(1, total)
                if share < 0.04:
                    passed, detail = False, f'{edit["object"]} did not change color'
                elif sat_t < 0.12:
                    passed = float(np.median(sats)) < 0.2
                    detail = f'{edit["object"]} is now neutral (saturation {float(np.median(sats)):.2f})'
                else:
                    angles = np.radians(hues[sats > 0.06]) if (sats > 0.06).any() else np.radians(hues)
                    mean = (np.degrees(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())) + 360) % 360
                    gap = min(abs(mean - hue_t * 360), 360 - abs(mean - hue_t * 360))
                    passed = gap < 35
                    detail = (f'the changed part of {edit["object"]} measures {round(mean)}° hue, {edit["color"]} is '
                              f'{round(hue_t * 360)}° ({share:.0%} of its box changed)')
                checks.append({'requirement': index, 'check': f'Measured: {detail}', 'passed': passed,
                               'measured': True})
                if not geometry_changed and sat_t >= 0.12:
                    def share_of_color(img):
                        h, s, _ = _hsv(img)
                        height, width = h.shape
                        outside = np.ones_like(h, dtype=bool)
                        for x, y, w, bh in boxes:
                            outside[round(y * height):round((y + bh) * height),
                                    round(x * width):round((x + w) * width)] = False
                        gap = np.minimum(np.abs(h - hue_t * 360), 360 - np.abs(h - hue_t * 360))
                        return float(((gap < 25) & (s > 0.2) & outside).sum() / max(1, outside.sum()))

                    spill = share_of_color(after) - share_of_color(before.resize(after.size))
                    checks.append({'requirement': index, 'check': f'Measured: the new color stayed on '
                                   f'{edit["object"]} ({max(0, spill):.0%} of the rest changed)',
                                   'passed': spill < 0.08, 'measured': True})
            elif action in ('black_and_white', 'sepia') and edit['target'] in ('whole image', 'background'):
                _, sat, _ = _hsv(after)
                if edit['target'] == 'whole image' or not boxes:
                    gray = float((sat < 0.1).mean())
                    checks.append({'requirement': index, 'check': f'Measured: {gray:.0%} of the picture is without '
                                   'color', 'passed': gray > 0.9, 'measured': True})
                else:
                    height, width = sat.shape
                    inside = np.zeros_like(sat, dtype=bool)
                    for x, y, w, h in boxes:
                        inside[round(y * height):round((y + h) * height), round(x * width):round((x + w) * width)] = True
                    outside_gray = float((sat[~inside] < 0.1).mean()) if (~inside).any() else 1.0
                    kept = []
                    for box in boxes:
                        _, before_sat, _ = _hsv(before, _core(box)) if not geometry_changed else (None, None, None)
                        _, after_sat, _ = _hsv(after, _core(box))
                        if before_sat is not None and float(np.median(before_sat)) > 0.18:
                            kept.append(float(np.median(after_sat)) > 0.12)
                    checks.append({'requirement': index, 'check': f'Measured: background {outside_gray:.0%} without '
                                   'color' + (f', {sum(kept)} of {len(kept)} colored subjects kept their color'
                                              if kept else ''),
                                   'passed': outside_gray > 0.75 and all(kept), 'measured': True})
            elif action in ('brightness', 'exposure', 'saturation', 'vibrance', 'temperature') and \
                    edit['target'] == 'whole image' and not geometry_changed and edit['direction'] != 'none' and \
                    not moved_by_others(edits, index):
                if action in ('brightness', 'exposure'):
                    old, new = (float(_hsv(img)[2].mean()) for img in (before, after))
                    name = 'brightness'
                elif action == 'temperature':
                    def warmth(img):
                        rgb = np.asarray(img.convert('RGB'), dtype=np.float32) / 255
                        return float((rgb[..., 0] - rgb[..., 2]).mean())
                    old, new, name = warmth(before), warmth(after), 'warmth'
                else:
                    old, new = (float(_hsv(img)[1].mean()) for img in (before, after))
                    name = 'saturation'
                rising = new > old + 0.004
                falling = new < old - 0.004
                passed = rising if edit['direction'] == 'increase' else falling
                checks.append({'requirement': index, 'check': f'Measured: {name} {old:.3f} → {new:.3f}',
                               'passed': passed, 'measured': True,
                               **({'weak': True} if not passed and (new > old if edit['direction'] == 'increase'
                                                                     else new < old) else {})})
            elif action in ('saturation', 'vibrance') and edit['target'] == 'color' and hex_color(edit['color']) \
                    and not geometry_changed and edit['direction'] != 'none':
                family = color_family(hex_color(edit['color']))
                ranges = {'reds': (340, 20), 'yellows': (20, 75), 'greens': (75, 160), 'cyans': (160, 200),
                          'blues': (170, 275), 'magentas': (275, 340)}
                low, high = ranges.get(family, (0, 360))

                def family_saturation(img):
                    hue, sat, _ = _hsv(img)
                    inside = ((hue >= low) | (hue < high)) if low > high else ((hue >= low) & (hue < high))
                    inside &= sat > 0.12
                    return float(sat[inside].mean()) if inside.any() else 0.0

                old, new = family_saturation(before), family_saturation(after)
                passed = new > old + 0.004 if edit['direction'] == 'increase' else new < old - 0.004
                checks.append({'requirement': index, 'check': f'Measured: {family} saturation {old:.3f} → {new:.3f}',
                               'passed': passed, 'measured': True})
            elif action in LOCAL_TONE and edit['target'] in ('object', 'main subject', 'area') and \
                    originals.get(index) and not geometry_changed and edit['direction'] != 'none':
                own = {region['label'] for region in regions if region['requirement'] == index}
                others = [box for region in regions if region['label'] not in own
                          for box in region.get('final', region['boxes'])]
                checks.append(local_tone_check(index, edit, originals[index], before, after, others))
            elif action == 'blur_background' and boxes and not geometry_changed:
                checks += blur_checks(index, boxes, before, after)
            elif action == 'remove_object' and boxes and not geometry_changed:
                score = max(removal_score(before, after, box) for box in boxes)
                checks.append({'requirement': index, 'check': f'Measured: the area now matches its surroundings '
                               f'({score:.0%} of the object’s contrast remains)', 'passed': score < 0.45,
                               'measured': True})
            elif action == 'remove_background' and hex_color(edit['color']):
                rgb = np.asarray(after.convert('RGB'), dtype=np.float32)
                corners = np.concatenate([rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3)])
                target = np.array([int(hex_color(edit['color'])[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
                distance = float(np.linalg.norm(corners.mean(axis=0) - target))
                checks.append({'requirement': index, 'check': f'Measured: backdrop color is {edit["color"]} '
                               f'(difference {distance:.0f} of 441)', 'passed': distance < 45, 'measured': True})
        except (ValueError, IndexError, ZeroDivisionError):
            continue
        # Checks the pipelines themselves declare (image_studio.pipelines.checks).
        checks += pipeline_checks.run(index, edit, before, after, boxes, originals.get(index), geometry_changed,
                                      others=[other['action'] for number, other in enumerate(edits) if number != index],
                                      spots=spots.get(index, []))
    for check in checks:
        check['passed'] = bool(check['passed'])  # numpy booleans are not JSON
    return checks


def verify(edits, before, after, canvas, outcomes):
    """Measured checks of the finished document against what was asked. Each is
    {'requirement', 'check', 'passed'}; outcomes are the macro results (text boxes)."""
    checks = []
    width, height = after['width'], after['height']
    for index, edit in enumerate(edits):
        action = edit['action']
        if action in ('crop_aspect', 'crop_to_object') and aspect_from(edit['aspect']):
            ratio = aspect_from(edit['aspect'])
            target = ratio[0] / ratio[1]
            if not any(e['action'] in ('canvas_border', 'resize', 'rotate', 'straighten') for e in edits[index + 1:]):
                checks.append({'requirement': index, 'check': f'Aspect ratio is {edit["aspect"]} '
                               f'({width}×{height})', 'passed': abs(width / height - target) / target < 0.01})
        if action == 'passport_photo' and not any(e['action'] in ('canvas_border', 'resize', 'rotate')
                                                  for e in edits[index + 1:]):
            checks.append({'requirement': index, 'check': f'Passport size is {canvas.width}×{canvas.height}'
                           + (f' at {canvas.resolution:g} ppi' if canvas.resolution != 72 else '')
                           + f' (now {width}×{height})', 'passed': (width, height) == (canvas.width, canvas.height)})
        if action == 'resize':
            checks.append({'requirement': index, 'check': f'Size is now {width}×{height}',
                           'passed': (width, height) == (canvas.width, canvas.height)})
        if action == 'rotate' and edit['value'] in (90, 270, -90):
            checks.append({'requirement': index, 'check': 'Rotated a quarter turn',
                           'passed': (width, height) == (before['height'], before['width'])})
        if action == 'add_text':
            layers = [layer for layer in flatten(after['layers']) if layer['kind'] == 'Type']
            exact = [layer for layer in layers if (layer.get('text') or {}).get('text') == edit['text']]
            checks.append({'requirement': index, 'check': f'Text reads exactly “{edit["text"]}”', 'passed': bool(exact)})
            placed = outcomes.get(('text', index))
            if exact and placed:
                x, y, w, h = placed['bounds']
                cx, cy = (x + w / 2) / width, (y + h / 2) / height
                pos = edit['position'] or 'center'
                horizontal = cx < 0.4 if 'left' in pos else cx > 0.6 if 'right' in pos else 0.4 <= cx <= 0.6
                vertical = cy < 0.4 if 'top' in pos else cy > 0.6 if 'bottom' in pos else 0.3 <= cy <= 0.7
                inside = x >= 0 and y >= 0 and x + w <= width and y + h <= height
                checks.append({'requirement': index, 'check': f'Text sits at the {pos} and fits in the picture',
                               'passed': horizontal and vertical and inside})
                if placed.get('fitted'):
                    checks.append({'requirement': index, 'check': f'Text was reduced to {placed["size"]:g} pt to fit',
                                   'passed': True})
        if action == 'remove_background':
            photo = [layer for layer in flatten(after['layers']) if layer.get('name') == 'Photo']
            checks.append({'requirement': index, 'check': 'Subject cut out with a layer mask',
                           'passed': bool(photo and photo[0].get('hasMask'))})
    return checks

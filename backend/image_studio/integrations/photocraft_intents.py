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

ACTIONS = {
    # layer housekeeping
    'layer_opacity': ('layer', 'change an existing layer’s opacity (object = layer name, value = %)'),
    'layer_visibility': ('layer', 'hide (decrease) or show (increase) an existing layer (object = layer name)'),
    'layer_delete': ('layer', 'delete an existing layer (object = layer name)'),
    'layer_rename': ('layer', 'rename an existing layer (object = old name, text = new name)'),
    'layer_blend': ('layer', 'set an existing layer’s blend mode (object = layer name, choice = mode)'),
    # geometry
    'crop_aspect': ('geometry', 'crop to an aspect ratio (aspect like 1:1, 4:5, 16:9; position or main subject/object '
                                'target says what to keep)'),
    'crop_to_object': ('geometry', 'crop tightly around a named object or the main subject'),
    'rotate': ('geometry', 'rotate by degrees (value; choice clockwise/counterclockwise)'),
    'straighten': ('geometry', 'level a tilted horizon by a small number of degrees (value)'),
    'flip': ('geometry', 'mirror the picture (choice horizontal/vertical)'),
    'resize': ('geometry', 'output size, print size or resolution: pixels (1080x1350, 2000 px wide, 50%, 2x '
                           'bigger, half), print (4x6 inch, A4, 300 dpi), formats (instagram post or story, youtube '
                           'thumbnail, linkedin or facebook cover, 4k, wallpaper)'),
    'center_subject': ('geometry', 'crop so the main subject or object sits exactly in the middle with even '
                                   'margins'),
    'perspective': ('geometry', 'make leaning walls, buildings or doors vertical (upright, keystone, perspective)'),
    'lens_correction': ('geometry', 'fix lens faults: barrel or fisheye distortion, chromatic aberration (color '
                                    'fringes), dark lens corners (choice = distortion, fringes, vignette or all)'),
    'fit_canvas': ('geometry', 'fit the whole picture into a new shape (aspect) WITHOUT cutting anything, filling the '
                               'empty sides with color (letterbox, white bars, padding to square)'),
    'convert_mode': ('output', 'convert the document color mode (choice = cmyk, grayscale, rgb, 16-bit, 8-bit)'),
    'canvas_border': ('geometry', 'add an outer border/padding around the picture (value = px, color)'),
    'passport_photo': ('geometry', 'passport, ID or visa photo: head-and-shoulders crop on a plain backdrop at the '
                                   'printed size in the quote (e.g. 35x45 mm, 2x2 inch); color = backdrop color'),
    # pixel retouching
    'remove_object': ('retouch', 'erase an object, person or thing and fill the area (object = what)'),
    'transform_object': ('retouch', 'move, resize or duplicate one object (object = what; choice = move, bigger, '
                                    'smaller or duplicate; position = where it goes)'),
    'restore': ('retouch', 'restore an old or damaged photo: scratches, dust, stains, creases, fading'),
    'retouch_portrait': ('retouch', 'portrait retouching of faces: choice = smooth skin, blemishes (pimples, acne, '
                                    'spots), wrinkles, even skin tone, dark circles, shine, whiten teeth, brighten '
                                    'eyes, red eye, sculpt (dodge and burn)'),
    # raw development (global) or a local develop layer (targeted)
    **{name: ('develop', label) for name, label in {
        'exposure': 'exposure in stops (value in EV)',
        'highlights': 'recover (decrease) or boost bright areas',
        'shadows': 'lift (increase) or deepen shadow areas',
        'whites': 'white point',
        'blacks': 'black point',
        'clarity': 'midtone local contrast, punch',
        'texture': 'fine detail and skin texture (decrease to smooth skin)',
        'dehaze': 'cut (increase) or add haze/fog',
        'temperature': 'white balance warmer (increase) or cooler (decrease)',
        'tint': 'white balance toward magenta (increase) or green (decrease)',
        'sharpen': 'sharpen details',
        'noise_reduction': 'reduce noise or grain',
        'grain': 'add film grain',
        'vignette': 'darken (decrease) or lighten (increase) the edges',
    }.items()},
    # adjustment layers (global or masked to the target)
    'auto_fix': ('adjust', 'automatic correction measured from the photo: choice = tone (auto levels), contrast, '
                           'or color (white balance, color cast)'),
    'brightness': ('adjust', 'overall brightness'),
    'contrast': ('adjust', 'contrast'),
    'saturation': ('adjust', 'color saturation'),
    'vibrance': ('adjust', 'vibrance, gentle saturation that protects skin'),
    'hue_shift': ('adjust', 'rotate hues by degrees (value)'),
    'recolor': ('adjust', 'change the color of the target to color (e.g. make the car red)'),
    'color_grade': ('adjust', 'tint shadows/midtones/highlights toward color (target = tone)'),
    'color_filter': ('adjust', 'photo filter: warm, cool, sepia or a colored filter (color or choice)'),
    'look': ('adjust', 'a named look: choice = cinematic, vintage, moody, dramatic, bright and airy, matte, '
                       'hdr, professional polish, warm portrait, pop art, golden hour, kodak portra, cyberpunk, '
                       'high key, low key, orton, bleach bypass, ' + ', '.join(LUTS)),
    'black_and_white': ('adjust', 'black and white (choice: neutral, high contrast, infrared; color = tint)'),
    'sepia': ('adjust', 'sepia toned black and white'),
    'duotone': ('adjust', 'two-color gradient map (color = "dark color and light color")'),
    'invert': ('adjust', 'invert colors (negative)'),
    'posterize': ('adjust', 'posterize into a number of levels (value)'),
    'threshold': ('adjust', 'pure black and white threshold (value 1..255)'),
    # filters and effects
    'blur': ('effect', 'soften/blur the target'),
    'blur_background': ('cutout', 'blur behind the main subject (portrait/bokeh look)'),
    'motion_blur': ('effect', 'motion blur (value = distance)'),
    'radial_blur': ('effect', 'zoom blur or spin blur from a point (choice = zoom or spin, position = center)'),
    'glow': ('effect', 'soft glow or bloom (Orton effect, glowing lights or neon); target = what glows'),
    'mirror': ('effect', 'mirror one half of the picture onto the other (choice = left, right, top or bottom = the '
                         'half that is kept)'),
    'drop_shadow': ('effect', 'soft contact shadow under the main subject or objects, as if standing on a surface'),
    'reflection': ('effect', 'a mirror reflection of the subject or objects on the surface below them'),
    'tilt_shift': ('effect', 'miniature tilt-shift blur, sharp band at position'),
    'lens_flare': ('effect', 'lens flare at position'),
    'relight': ('effect', 'add directional light coming from position (color = light color)'),
    'artistic': ('effect', 'artistic filter, choice = oil paint, watercolor, pencil, cutout, dry brush, poster edges, '
                           'ink outlines, sponge, emboss, find edges, solarize, pixelate, halftone…'),
    # cut-outs
    'remove_background': ('cutout', 'cut out the main subject; color = new backdrop color or transparent'),
    # text and graphics
    'add_text': ('graphics', 'add text: text = EXACT words, position, color, size or value in pt, choice = font '
                             'or style (bold, italic, serif, script, shadow, outline, glow)'),
    'edit_text': ('graphics', 'change the words of an existing text layer (object = current text, text = new)'),
    'frame': ('graphics', 'draw a frame line inside the edges (value = px, color)'),
    'gradient_overlay': ('graphics', 'a gradient that darkens (or tints with color) from one edge, e.g. behind '
                                     'text (position = the darkest edge)'),
    'round_corners': ('graphics', 'round the corners of the picture (color = what shows in the corners)'),
    'weather': ('effect', 'add falling rain or snow (choice = rain or snow)'),
    'headshot': ('geometry', 'professional headshot: head-and-shoulders crop with a gentle polish (aspect if '
                             'named, square for profile pictures)'),
    'picture_frame': ('graphics', 'decorative frame, choice = roses, ivy, bamboo, waves, dots, stars, hearts…'),
    'color_overlay': ('graphics', 'semi-transparent color layer over the image (color, value = opacity %)'),
    # the rest
    'other': ('expert', 'any other PhotoCraft capability not listed (describe it in choice)'),
    'generate': ('ai', 'new content painted by AI as its own layer: add an object or person, replace the sky '
                       'with a new one, change clothing or materials (target says where)'),
}
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
        written = numbers_in(quote) + numbers_in(prompt)
        if any(abs(abs(value) - abs(number)) < 1e-6 for number in written):
            result['value'] = float(value)
        else:
            notes.append(f'Ignored a number ({value:g}) that is not in your request; used a {result["strength"]} '
                         'amount instead.')
    # Direction words in the person's text override the planner.
    lowered = quote.lower()
    if re.search(r'\b(less|reduce|decrease|lower|darker|darken|cooler|tone down|remove some|soften|'
                 r'recover|desaturat|mute|dim)\w*', lowered):
        if result['direction'] == 'none' or action not in ('shadows', 'highlights', 'vignette'):
            result['direction'] = 'decrease'
    elif re.search(r'\b(more|increase|boost|raise|brighter|brighten|warmer|lift|enhance|add|stronger|pop)\w*',
                   lowered) and result['direction'] == 'none':
        result['direction'] = 'increase'
    if action in ('saturation', 'vibrance', 'contrast', 'clarity', 'dehaze', 'texture') and re.search(
            r'\b(deepen|deeper|richer|vivid|intensif|punch|pop|bolder|stronger)\w*', lowered):
        result['direction'] = 'increase'  # “deepen the blues” means more color, not less
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
    return result, notes


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


def expand(edits, preserve=()):
    """Edits that one request implies: a passport photo needs a plain backdrop, which is a
    cut-out made before the crop (white unless a color is named or the background is kept)."""
    result = list(edits)
    keeps_background = any(re.search(r'\bback\s*ground|backdrop', text, re.IGNORECASE) for text in preserve)
    for edit in edits:
        if edit['action'] == 'headshot':
            # A professional headshot is framed, polished and lightly retouched.
            if not any(other['action'] == 'look' for other in result):
                result.append(blank('look', quote='Gentle professional polish for the headshot',
                                    choice='professional polish', strength='subtle'))
            if not any(other['action'] == 'retouch_portrait' for other in result):
                result.append(blank('retouch_portrait', quote='Light skin smoothing for the headshot',
                                    choice='smooth', strength='subtle', target='main subject'))
            continue
        if edit['action'] != 'passport_photo' or keeps_background:
            continue
        if any(other['action'] == 'remove_background' for other in result):
            continue
        color = edit['color'] if hex_color(edit['color']) else 'white'
        result.append(blank('remove_background', quote=f'Plain {color} passport backdrop behind the person',
                            target='main subject', color=color))
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
    covered = ' '.join([edit['quote'] for edit in edits] + list(preserve)).lower()
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
        ordered = sorted(range(len(edits)), key=lambda i: (GROUP_ORDER.index(group(edits[i]))
                                                           if group(edits[i]) in GROUP_ORDER else 99, i))
        self.clip = any(e['action'] == 'remove_background' and hex_color(e['color']) for e in edits)
        for index in ordered:
            edit = edits[index]
            kind = group(edit)
            handler = getattr(self, f'do_{edit["action"]}', None) or getattr(self, f'group_{kind}', None)
            if handler is None:
                self.blocking.append(f'“{edit["quote"]}” is not something this workspace can do yet.')
                continue
            if kind != 'develop' and self.raw:
                self.flush_raw()
            handler(index, edit)
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

    def flush_raw(self):
        if not self.raw:
            return
        merged, indices = {}, set()
        for index, params in self.raw.items():
            indices.add(index)
            for key, value in params.items():
                merged[key] = round(merged.get(key, 0) + value, 2)
        self.steps.append({'command': 'studio.develop', 'params': {'params': merged},
                           'label': 'Develop: ' + ', '.join(f'{k} {v:+g}' for k, v in merged.items()),
                           'requirements': sorted(indices)})
        self.raw = {}

    def group_layer(self, index, edit):
        layer = self.layer_named(edit['object'] or edit['choice'])
        if layer is None:
            self.blocking.append(f'Which layer does “{edit["quote"]}” mean? Use its name from the Layers panel.')
            return
        action, lid, name = edit['action'], layer['id'], layer['name']
        if action == 'layer_opacity':
            if edit['value'] is None:
                self.blocking.append(f'What opacity should “{name}” have? Give a percentage.')
                return
            self.add(index, 'layer.setProps', {'layer': lid, 'opacity': max(0, min(100, edit['value'])) / 100},
                     f'Set “{name}” to {edit["value"]:g}% opacity')
        elif action == 'layer_visibility':
            visible = edit['direction'] == 'increase' or 'show' in edit['quote'].lower()
            self.add(index, 'layer.setProps', {'layer': lid, 'visible': visible},
                     f'{"Show" if visible else "Hide"} “{name}”')
        elif action == 'layer_delete':
            self.add(index, 'layer.delete', {'layer': lid}, f'Delete “{name}”')
        elif action == 'layer_rename':
            if not edit['text']:
                self.blocking.append('What should the new layer name be?')
                return
            self.add(index, 'layer.renameLayer', {'layer': lid, 'name': edit['text'][:80]},
                     f'Rename “{name}” to “{edit["text"][:40]}”')
        elif action == 'layer_blend':
            mode = (edit['choice'] or '').strip().title().replace(' ', '')
            if not mode:
                self.blocking.append('Which blend mode, for example Multiply, Screen, Overlay or Soft Light?')
                return
            mode = {'Softlight': 'Soft Light', 'Hardlight': 'Hard Light', 'Lineardodge': 'Linear Dodge'}.get(mode, mode)
            self.add(index, 'layer.setProps', {'layer': lid, 'blend': mode}, f'Blend “{name}” with {mode}')

    def do_crop_aspect(self, index, edit):
        ratio = aspect_from(edit['aspect'])
        if not ratio:
            self.blocking.append(f'Which shape should “{edit["quote"]}” crop to, for example 1:1 or 4:5?')
            return
        focus = None
        if subject_query(edit):
            _, boxes = self.target_boxes(edit)
            if boxes:
                xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
                ys = [b[1] for b in boxes] + [b[1] + b[3] for b in boxes]
                focus = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
        self.crop(index, *largest_crop(self.canvas.width, self.canvas.height, ratio, focus, edit['position']),
                  f'Crop to {edit["aspect"]}' + (' around the subject' if focus else ''))

    def do_crop_to_object(self, index, edit):
        if aspect_from(edit['aspect']) and re.search(r'\bcent(er|re)(e?d)?\b|\bkeep', edit['quote'], re.IGNORECASE):
            # “A square centered on her face” is the largest square around the face, not a tight crop.
            self.do_crop_aspect(index, edit)
            return
        key, boxes = self.target_boxes(edit)
        if not boxes:
            self.blocking.append(f'Could not find {key or "what to crop to"} in the picture.')
            return
        xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
        ys = [b[1] for b in boxes] + [b[1] + b[3] for b in boxes]
        margin = round(max(max(xs) - min(xs), max(ys) - min(ys)) * 0.08)
        box = [min(xs) - margin, min(ys) - margin, max(xs) - min(xs) + 2 * margin, max(ys) - min(ys) + 2 * margin]
        ratio = aspect_from(edit['aspect'])
        if ratio:
            box = fit_ratio(box, ratio, self.canvas.width, self.canvas.height)
        x0, y0 = max(0, round(box[0])), max(0, round(box[1]))
        x1 = min(self.canvas.width, round(box[0] + box[2]))
        y1 = min(self.canvas.height, round(box[1] + box[3]))
        self.crop(index, x0, y0, x1 - x0, y1 - y0, f'Crop to {key}')

    def do_passport_photo(self, index, edit):
        """Head-and-shoulders framing measured from the head box, then the print size at 300 ppi."""
        size = print_size(edit['quote']) or print_size(edit['aspect'])
        if not size and re.search(r'stamp', edit['quote'], re.IGNORECASE):
            size = STAMP_SIZE
            self.notes.append('Used the common 20×25 mm stamp size; write a size such as “25x30 mm” for another.')
        elif not size:
            size = PASSPORT_DEFAULT
            self.notes.append('Used the common 35×45 mm passport size; write a size such as “2x2 inch” for another.')
        framed = self.head_frame(index, edit, size[:2], PASSPORT_HEAD_SHARE, PASSPORT_TOP_MARGIN,
                                 'Crop head and shoulders')
        if not framed:
            return
        cw, ch = framed
        unit = size[2]
        if unit == 'px':
            tw, th = round(size[0]), round(size[1])
        elif unit in ('mm', 'cm', 'in'):
            inches = {'mm': 25.4, 'cm': 2.54, 'in': 1}[unit]
            tw, th = round(size[0] / inches * PRINT_PPI), round(size[1] / inches * PRINT_PPI)
        else:
            self.notes.append(f'Cropped to {size[0]:g}:{size[1]:g}; add mm, cm or inch to also set the print size.')
            return
        if not (1 <= tw <= 8192 and 1 <= th <= 8192):
            self.blocking.append('The size must stay between 1 and 8192 pixels on each side.')
            return
        params = {'width': tw, 'height': th, 'resample': 'preserveDetails' if tw > cw else 'bicubic'}
        label = f'Resize to {tw}×{th}'
        if unit != 'px':
            params['resolution'] = PRINT_PPI
            label += f' ({size[0]:g}×{size[1]:g} {"inch" if unit == "in" else unit} at {PRINT_PPI} ppi)'
            self.canvas.resolution = PRINT_PPI
        if tw > cw * 1.5:
            self.notes.append(f'The head-and-shoulders area is {cw}×{ch} px, so it is enlarged {tw / cw:.1f}× for '
                              'print; a sharper, closer original prints better.')
        self.add(index, 'image.imageSize', params, label)
        self.canvas.maps.append(lambda px, py, sx=tw / cw, sy=th / ch: (px * sx, py * sy))
        self.canvas.width, self.canvas.height = tw, th

    def crop(self, index, x, y, w, h, label):
        self.add(index, 'image.crop', {'x': x, 'y': y, 'width': w, 'height': h}, label + f' ({w}×{h})')
        self.canvas.maps.append(lambda px, py, x=x, y=y: (px - x, py - y))
        self.canvas.width, self.canvas.height = w, h

    def do_rotate(self, index, edit, straighten=False):
        if edit['value'] is None:
            if straighten:
                measured = self.analysis.get('tilt')
                if measured is None:
                    self.blocking.append('I could not find a clear horizon or straight edge to level. Say how many '
                                         'degrees, for example “straighten by 2 degrees clockwise”.')
                    return
                if measured == 0:
                    self.notes.append('The horizon is already level (measured), so nothing was rotated.')
                    return
                edit = {**edit, 'value': measured, 'choice': '', 'quote': ''}
            else:
                edit = {**edit, 'value': 90.0}
        if edit['value'] is None:
            degrees = 90.0
        else:
            degrees = edit['value']
        counter = re.search(r'counter|anti|ccw|left', edit['quote'] + ' ' + edit['choice'], re.IGNORECASE)
        clockwise = degrees if not counter else -abs(degrees)
        w, h = self.canvas.width, self.canvas.height
        turn = round(clockwise) % 360
        if abs(clockwise - round(clockwise)) < 1e-6 and turn in (90, 180, 270):
            command = {90: 'image.imageRotation.90cw', 180: 'image.imageRotation.180',
                       270: 'image.imageRotation.90ccw'}[turn]
            self.add(index, command, {}, f'Rotate {turn if turn != 270 else 90}° '
                                         f'{"counterclockwise" if turn == 270 else "clockwise"}')
            if turn == 90:
                self.canvas.maps.append(lambda px, py, h=h: (h - py, px))
            elif turn == 270:
                self.canvas.maps.append(lambda px, py, w=w: (py, w - px))
            else:
                self.canvas.maps.append(lambda px, py, w=w, h=h: (w - px, h - py))
            if turn != 180:
                self.canvas.width, self.canvas.height = h, w
            return
        # PhotoCraft's crop angle turns the frame; a positive frame angle turns the picture counterclockwise.
        x, y, cw, ch = rotation_crop(w, h, clockwise)
        self.add(index, 'image.crop', {'x': x, 'y': y, 'width': cw, 'height': ch, 'angle': -clockwise,
                                       'targetWidth': w, 'targetHeight': h},
                 f'{"Straighten" if straighten else "Rotate"} {abs(clockwise):g}° '
                 f'{"clockwise" if clockwise > 0 else "counterclockwise"}, cropping the empty corners')
        theta = math.radians(clockwise)

        def move(px, py, w=w, h=h, theta=theta, x=x, y=y, s=w / cw):
            cx, cy = px - w / 2, py - h / 2
            rx = cx * math.cos(theta) - cy * math.sin(theta) + w / 2
            ry = cx * math.sin(theta) + cy * math.cos(theta) + h / 2
            return (rx - x) * s, (ry - y) * s

        self.canvas.maps.append(move)

    def do_straighten(self, index, edit):
        self.do_rotate(index, edit, straighten=True)

    def do_flip(self, index, edit):
        vertical = re.search(r'vertical|upside|top to bottom', edit['quote'] + ' ' + edit['choice'], re.IGNORECASE)
        w, h = self.canvas.width, self.canvas.height
        if vertical:
            self.add(index, 'image.imageRotation.flipCanvasVertical', {}, 'Flip vertically')
            self.canvas.maps.append(lambda px, py, h=h: (px, h - py))
        else:
            self.add(index, 'image.imageRotation.flipCanvasHorizontal', {}, 'Flip horizontally (mirror)')
            self.canvas.maps.append(lambda px, py, w=w: (w - px, py))

    def do_resize(self, index, edit):
        w, h = self.canvas.width, self.canvas.height
        wanted = output_size(edit['quote'], w, h) or output_size(edit['aspect'], w, h)
        if not wanted:
            self.blocking.append('What size should the picture be? For example 1080x1350, A4, 4x6 inch, '
                                 'instagram post, 2000 px wide, or 50%.')
            return
        (tw, th), ppi = wanted['size'], wanted['ppi']
        if not (1 <= tw <= 8192 and 1 <= th <= 8192):
            self.blocking.append('The size must stay between 1 and 8192 pixels on each side.')
            return
        if (tw, th) == (w, h):
            # Only the print resolution changes; the pixels stay as they are.
            self.add(index, 'image.imageSize', {'width': w, 'height': h, 'resolution': ppi, 'resample': 'none'},
                     f'Set {ppi} ppi (pixels unchanged)')
            self.canvas.resolution = ppi
            return
        if wanted['crop'] and abs(tw / th - w / h) > 0.01:
            _, boxes = self.target_boxes({**edit, 'target': 'main subject', 'object': ''})
            focus = None
            if boxes:
                xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
                ys = [b[1] for b in boxes] + [b[1] + b[3] for b in boxes]
                focus = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            x, y, cw, ch = largest_crop(w, h, (tw, th), focus, edit['position'])
            self.crop(index, x, y, cw, ch, f'Crop to the {tw}:{th} shape' + (' around the subject' if focus else '')
                      + ' so nothing stretches')
            w, h = cw, ch
        params = {'width': tw, 'height': th, 'resample': 'preserveDetails' if tw > w else 'bicubic'}
        if ppi:
            params['resolution'] = ppi
            self.canvas.resolution = ppi
        if tw > w * 2.5:
            self.notes.append(f'This enlarges the picture {tw / w:.1f}×; fine detail cannot be invented, so it will '
                              'look soft up close.')
        self.add(index, 'image.imageSize', params, f'Resize to {tw}×{th}'
                 + (f' · {wanted["label"]}' if wanted['label'] != f'{tw}×{th}' else ''))
        self.canvas.maps.append(lambda px, py, sx=tw / w, sy=th / h: (px * sx, py * sy))
        self.canvas.width, self.canvas.height = tw, th

    def do_center_subject(self, index, edit):
        """The largest crop with the subject exactly in the middle (same shape unless one is asked)."""
        key, boxes = self.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
        if not boxes:
            self.blocking.append(f'Could not find {key or "the subject"} to center.')
            return
        xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
        ys = [b[1] for b in boxes] + [b[1] + b[3] for b in boxes]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w, h = self.canvas.width, self.canvas.height
        half_w, half_h = min(cx, w - cx), min(cy, h - cy)
        ratio = aspect_from(edit['aspect']) or aspect_from(edit['quote'])
        if ratio:
            aspect = ratio[0] / ratio[1]
            half_w, half_h = min(half_w, half_h * aspect), min(half_h, half_w / aspect)
        if half_w * 2 < (max(xs) - min(xs)) * 1.02 or half_h * 2 < (max(ys) - min(ys)) * 1.02:
            self.blocking.append(f'{key[:1].upper() + key[1:]} is too close to the edge to center by cropping; '
                                 'use “fit” or extend the background instead.')
            return
        x, y = round(cx - half_w), round(cy - half_h)
        self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized(boxes)})
        self.crop(index, x, y, round(half_w * 2), round(half_h * 2), f'Center {key}')

    def do_perspective(self, index, edit):
        """Upright from measured lines: PhotoCraft's Adaptive Wide Angle makes each given line vertical."""
        lines = self.analysis.get('verticals') or []
        # The lean from upright, whichever end of the line comes first (180° is upright too).
        leaning = [line for line in lines if abs((math.degrees(math.atan2(line[1][0] - line[0][0],
                                                                           line[1][1] - line[0][1])) + 90) % 180 - 90)
                   > 0.6]
        if lines and not leaning:
            self.notes.append('The vertical edges are already upright (measured), so the perspective was not '
                              'changed.')
            return
        if len(lines) < 2:
            self.blocking.append('I could not find two long vertical edges (walls, door frames, poles) to straighten '
                                 'the perspective against.')
            return
        self.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
        self.add(index, 'filter.adaptiveWideAngle', {
            'model': 'perspective', 'constraints': [{'a': a, 'b': b, 'orientation': 'vertical'} for a, b in lines]},
            f'Make {len(lines)} measured edges vertical')
        self.add(index, 'studio.crop_empty', {}, 'Crop away the empty edges the correction leaves')

    def do_lens_correction(self, index, edit):
        words = (edit['choice'] + ' ' + edit['quote']).lower()
        fringes = bool(re.search(r'chromatic|aberration|fring|purple edge|color edge', words))
        corners = bool(re.search(r'vignett|dark corner', words))
        distortion = bool(re.search(r'distort|barrel|fish|bulg|pincushion|curved', words))
        if not (fringes or corners or distortion):
            fringes = corners = distortion = True
        params = {'profile': 'auto', 'correctDistortion': distortion, 'correctCA': fringes,
                  'correctVignette': corners, 'autoScale': True, 'edge': 'edgeExtension'}
        fixed = [name for name, on in (('distortion', distortion), ('color fringes', fringes),
                                       ('lens vignetting', corners)) if on]
        self.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
        self.add(index, 'filter.lensCorrection', params, 'Correct ' + ', '.join(fixed))

    def do_fit_canvas(self, index, edit):
        """Pad the picture out to a shape, keeping every pixel (letterbox, white bars)."""
        w, h = self.canvas.width, self.canvas.height
        wanted = output_size(edit['quote'], w, h) if not aspect_from(edit['aspect']) else None
        ratio = aspect_from(edit['aspect']) or aspect_from(edit['quote']) or (wanted['size'] if wanted else (1, 1))
        aspect = ratio[0] / ratio[1]
        tw, th = (round(h * aspect), h) if w / h < aspect else (w, round(w / aspect))
        color = hex_color(edit['color']) or '#ffffff'
        self.add(index, 'image.canvasSize', {'width': tw, 'height': th, 'anchor': 'center', 'extensionColor': color},
                 f'Fit into {ratio[0]:g}:{ratio[1]:g} with {edit["color"] or "white"} bars ({tw}×{th})')
        self.canvas.maps.append(lambda px, py, dx=(tw - w) / 2, dy=(th - h) / 2: (px + dx, py + dy))
        self.canvas.width, self.canvas.height = tw, th
        if wanted and wanted['size'] != (tw, th) and not aspect_from(edit['aspect']):
            sw, sh = wanted['size']
            self.add(index, 'image.imageSize', {'width': sw, 'height': sh, 'resample':
                                                'preserveDetails' if sw > tw else 'bicubic'}, f'Resize to {sw}×{sh}')
            self.canvas.maps.append(lambda px, py, sx=sw / tw, sy=sh / th: (px * sx, py * sy))
            self.canvas.width, self.canvas.height = sw, sh

    def do_convert_mode(self, index, edit):
        words = (edit['choice'] + ' ' + edit['quote']).lower()
        if '16' in words or '8' in words and 'bit' in words:
            bits = '16' if '16' in words else '8'
            self.add(index, f'image.mode.bits{bits}', {}, f'Convert to {bits} bits per channel')
            return
        mode = 'cmyk' if 'cmyk' in words else 'grayscale' if re.search(r'gr[ae]y|monochrome', words) else \
            'rgb' if 'rgb' in words else None
        if not mode:
            self.blocking.append('Which color mode: CMYK, grayscale or RGB?')
            return
        self.add(index, f'image.mode.{mode}', {'intent': 'perceptual' if mode == 'cmyk' else 'relative'},
                 f'Convert to {mode.upper() if mode != "grayscale" else "grayscale"} mode')
        if mode == 'cmyk':
            self.notes.append('CMYK is for the print shop; screens and the web expect RGB.')

    def do_canvas_border(self, index, edit):
        size = round(edit['value']) if edit['value'] else round(min(self.canvas.width, self.canvas.height) * 0.04)
        color = hex_color(edit['color']) or '#ffffff'
        self.add(index, 'image.canvasSize', {'width': size * 2, 'height': size * 2, 'relative': True,
                                             'anchor': 'center', 'extensionColor': color},
                 f'Add a {size}px border')
        self.canvas.maps.append(lambda px, py, s=size: (px + s, py + s))
        self.canvas.width += size * 2
        self.canvas.height += size * 2

    def do_remove_object(self, index, edit):
        key, boxes = self.target_boxes({**edit, 'target': 'object'})
        if not boxes:
            self.blocking.append(f'Could not find {key or "the object to remove"} in the picture.')
            return
        area = sum(b[2] * b[3] for b in boxes) / (self.canvas.width * self.canvas.height)
        self.removed += boxes
        if area >= AI_REMOVAL_AREA and self.ai:
            # Content-aware fill copies nearby patches and smears anything this size; AI rebuilds what
            # was behind it, limited to the object's box, on its own masked layer.
            noun = key.split()[-1]
            # Kontext tends to paint a different object into the gap when asked to “remove”; describing
            # the empty result works better, and the step retries when the measured area still stands out.
            self.add(index, 'studio.ai_layer', {
                'instruction': f'Remove {key}. In its place show only the empty background that was behind it, '
                               f'continuing the surroundings seamlessly. There is no {noun} there any more. '
                               'Change nothing else.',
                'retry': f'Erase {key} completely and paint the plain surface and background that continue around '
                         f'it. Do not add any {noun} or any other object. Change nothing else.',
                'boxes': boxes, 'label': f'Removed {key}'[:80]}, f'Remove {key} with AI (its own layer, checked)')
            self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized(boxes)})
            return
        if area >= AI_REMOVAL_AREA:
            self.notes.append(f'{key[:1].upper() + key[1:]} covers {area:.0%} of the picture; content-aware fill may '
                              'smear it. Install AI content editing for clean removal of larger objects.')
        if not self.selection(index, {**edit, 'target': 'object', 'object': key}):
            return
        pad = max(4, round(min(self.canvas.width, self.canvas.height) * 0.008))
        self.add(index, 'select.modify.expand', {'radius': pad}, 'Include the edges')
        self.add(index, 'studio.retouch_fill', {'label': f'Removed {key}'[:80]}, f'Fill where {key} was')
        self.end_selection(index)

    def do_transform_object(self, index, edit):
        key, boxes = self.target_boxes({**edit, 'target': 'object'})
        if not boxes:
            self.blocking.append(f'Could not find {key or "the object"} to move.')
            return
        x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
        width, height = self.canvas.width, self.canvas.height
        words = (edit['choice'] + ' ' + edit['quote']).lower()
        duplicate = is_duplicate(words)
        # Other things standing level with it (their bases within 10% of the height), so a moved or
        # copied object lands in free space. Things further back, like the chair behind a cat, are
        # simply covered, the way a nearer object hides them.
        _, around = self.target_boxes(edit, FOREGROUND)
        others = [b for b in around or [] if covered(b, [x, y, w, h]) < 0.5 and covered([x, y, w, h], b) < 0.5
                  and abs(b[1] + b[3] - y - h) < 0.1 * height]
        overlap_ok = bool(re.search(r'\b(in front of|on top of|over|overlap\w*|cover\w*|anyway)\b', words))
        factor = 1.0
        if re.search(r'bigger|larger|enlarge|grow|increase|scale up', words):
            factor = 1 + (edit['value'] / 100 if edit['value'] and edit['value'] < 300 else
                          {'subtle': 0.15, 'moderate': 0.3, 'strong': 0.6}[edit['strength']])
        elif re.search(r'smaller|shrink|reduce|decrease|scale down', words):
            factor = 1 - (min(edit['value'], 90) / 100 if edit['value'] else
                          {'subtle': 0.15, 'moderate': 0.25, 'strong': 0.45}[edit['strength']])
        tw, th = w * factor, h * factor
        # Things stand on something: scaling keeps the base where it was, centered.
        tx, ty = x + w / 2 - tw / 2, y + h - th
        absolute = re.search(r'\b(edge|corner|side of the (picture|photo|image|frame)|far (left|right)|center|'
                             r'centre|middle)\b', words)
        if edit['position'] and absolute:
            cx, _ = position_xy(edit['position'])
            tx = cx * width - tw / 2
            if 'top' in edit['position'] or 'bottom' in edit['position']:
                ty = position_xy(edit['position'])[1] * height - th / 2
        elif edit['position']:
            # “Move the mug to the left” is a shift by about its own width; sending it to the frame's
            # edge dropped it on top of the next mug (measured on a row of four).
            # A shift by its own width put the yellow mug on top of the blue one in a row of four, so
            # it goes to the nearest free gap that way instead, or the person is asked.
            step = {'subtle': 0.5, 'moderate': 1.0, 'strong': 1.8}[edit['strength']]
            position = edit['position']
            if 'left' in position or 'right' in position:
                sign = -1 if 'left' in position else 1
                wanted = tx + sign * tw * step
                if others and not overlap_ok:
                    allowed = (0, x - tw * step / 2) if sign < 0 else (x + tw * step / 2, width - tw)
                    tx = free_spot(tw, width, self.spans(others, ty, th, 1), wanted, allowed)
                else:
                    tx = wanted
            if tx is not None and ('top' in position or 'bottom' in position):
                sign = -1 if 'top' in position else 1
                wanted = ty + sign * th * step
                if others and not overlap_ok:
                    allowed = (0, y - th * step / 2) if sign < 0 else (y + th * step / 2, height - th)
                    ty = free_spot(th, height, self.spans(others, tx, tw, 0), wanted, allowed)
                else:
                    ty = wanted
            if tx is None or ty is None:
                self.blocking.append(
                    f'There is no free space {position.replace("top", "up").replace("bottom", "down")} of {key}: '
                    'it would cover something else. Say "in front of" to let it overlap, or say where it should go.')
                return
        elif duplicate:
            # Beside the original, in the nearest free space (on the side with more room when nothing
            # else is known).
            tx = x + w * 1.1 if x + w / 2 < width / 2 else x - tw * 1.1
            if others and not overlap_ok:
                gap = tw * 0.1
                tx = free_spot(tw + 2 * gap, width, self.spans(others + [[x, y, w, h]], ty, th, 1), tx - gap,
                               (0, width - tw - 2 * gap))
                if tx is None:
                    self.blocking.append(f'There is no free space beside {key} for a copy. Say where it should '
                                         'go, or "in front of" to let it overlap.')
                    return
                tx += gap
        tx = min(max(0, tx), width - tw)
        ty = min(max(0, ty), height - th)
        if factor == 1 and abs(tx - x) < 2 and abs(ty - y) < 2 and not duplicate:
            self.blocking.append(f'Where should {key} go, or how much bigger or smaller should it be?')
            return
        verb = 'Duplicate' if duplicate else 'Resize' if factor != 1 and abs(tx - x) < w * 0.5 else 'Move'
        self.add(index, 'studio.transform_object', {
            'box': [x, y, w, h], 'to': [round(tx), round(ty), round(tw), round(th)], 'what': key,
            'duplicate': duplicate, 'label': f'{verb}d {key}'[:80]},
            f'{verb} {key}' + (f' to {factor:.0%}' if factor != 1 else '') + ' (lifted onto its own layer)')
        self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized([[x, y, w, h]])})

    def do_restore(self, index, edit):
        """Old-photo restoration: damage repaired (AI when installed), then tone and noise."""
        if self.ai:
            self.add(index, 'studio.ai_layer', {
                'instruction': 'Restore this old damaged photograph: remove scratches, dust, spots, stains, creases '
                               'and tears, and repair faded areas. Keep every face, person, object and the original '
                               'colors (or black and white) exactly the same. Do not add or remove anything.',
                'label': 'Restored'}, 'Repair scratches, dust and creases with AI (its own layer)')
        else:
            self.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
            radius = max(1, round(min(self.canvas.width, self.canvas.height) / 900))
            self.add(index, 'filter.noise.dustAndScratches', {'radius': radius, 'threshold': 14},
                     'Clear dust and fine scratches')
            self.notes.append('Install AI content editing for repairing large scratches, stains and tears.')
        self.raw[index] = {'contrast': 12, 'dehaze': 10, 'clarity': 8, 'noiseLuminance': 25, 'noiseColor': 30}

    def do_retouch_portrait(self, index, edit):
        """A retoucher's jobs on faces, each done the way it is done by hand and each on its own layer."""
        scale = LEVEL[edit['strength']]
        for job in retouch_jobs(edit['choice'] + ' ' + edit['quote']):
            if job in FACE_JOBS:
                _, faces = self.target_boxes({**edit, 'target': 'object', 'object': FACES})
                if not faces:
                    self.blocking.append('Could not find a face to retouch.')
                    return
                self.face_job(index, edit, job, faces, scale)
            elif job in EYE_JOBS:
                _, eyes = self.target_boxes({**edit, 'target': 'object', 'object': EYES})
                if not eyes:
                    self.blocking.append('Could not find the eyes.')
                    return
                self.eye_job(index, job, eyes, scale)
            elif job == 'teeth':
                _, teeth = self.target_boxes({**edit, 'target': 'object', 'object': TEETH})
                if not teeth or self.analysis.get('teeth') is False:
                    self.blocking.append('Could not find any teeth showing in the picture.')
                    return
                self.whiten_teeth(index, edit, teeth, scale)

    def whiten_teeth(self, index, edit, teeth, scale):
        """De-yellow and lift only tooth-coloured pixels inside the mouths."""
        colors = self.analysis.get('teeth_colors')
        if not colors:
            self.blocking.append('Could not measure the teeth to whiten them.')
            return
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        self.add(index, 'studio.select_outline', {'boxes': teeth, 'what': 'the teeth'}, 'Select the mouths')
        self.add(index, 'studio.require_selection', {'what': 'the teeth', 'min_coverage': 0.00001},
                 'Check the teeth were found')
        self.add(index, 'select.colorRange', {'colors': colors, 'fuzziness': 35, 'mode': 'intersect',
                                              'sampleAllLayers': True}, 'Keep only tooth-coloured pixels')
        self.add(index, 'studio.require_selection', {'what': 'the teeth', 'min_coverage': 0.000005},
                 'Check some teeth are left')
        self.add(index, 'select.modify.feather', {'radius': 1}, 'Soften the edge')
        self.add(index, 'layer.newAdjustmentLayer.hueSaturation',
                 {'yellows': {'saturation': round(-45 * min(scale, 1.4)), 'lightness': round(10 * scale)},
                  'lightness': round(5 * scale)}, 'Whiten teeth')
        self.after_new_layer(index, 'Whiten teeth')
        self.end_selection(index)
        self.regions.append({'requirement': index, 'label': 'teeth', 'boxes': self.normalized(teeth)})

    def face_job(self, index, edit, job, faces, scale):
        face = {**edit, 'target': 'object', 'object': FACES}
        raw = {
            'smooth': {'texture': -45, 'clarity': -12},
            'shine': {'highlights': -45, 'whites': -20},
            'sculpt': {'clarity': 15, 'contrast': 10, 'highlights': 10, 'shadows': -8},
            'even tone': {'saturation': -8, 'texture': -20},
            'wrinkles': {'texture': -60, 'clarity': -20},
            'blemishes': {'texture': -20},
        }[job]
        prompts = {
            'blemishes': 'Retouch the skin: remove pimples, acne, spots and blemishes. Keep the natural skin texture, '
                         'pores, facial hair, eyes, lips, expression and the person’s identity exactly the same.',
            'wrinkles': 'Softly reduce wrinkles and fine lines on the face so it looks naturally rested, not '
                        'plastic. Keep the identity, expression, eyes and hair exactly the same.',
            'even tone': 'Even out the skin tone: reduce redness, blotches and uneven patches while keeping natural '
                         'skin texture, identity and expression exactly the same.',
        }
        if job in prompts and self.ai:
            self.add(index, 'studio.ai_layer', {'instruction': prompts[job] + ' Change nothing else.',
                                                'boxes': faces, 'label': f'Retouch: {job}'},
                     f'Retouch {job} with AI on the face only (its own layer)')
            self.regions.append({'requirement': index, 'label': 'face', 'boxes': self.normalized(faces)})
            return
        if job == 'blemishes':
            # Without AI: Dust & Scratches clears small spots and keeps edges above its threshold.
            width = max(b[2] for b in faces)
            if not self.selection(index, face):
                return
            self.only_skin(index)
            self.add(index, 'studio.local_filter', {
                'command': 'filter.noise.dustAndScratches',
                'params': {'radius': max(2, round(width / 90)), 'threshold': 8},
                'label': 'Blemishes cleared · face'}, 'Clear small blemishes on the face (masked)')
            self.end_selection(index)
        params = {key: round(value * min(scale, 1.6), 2) for key, value in raw.items()}
        label = {'smooth': 'Smoother skin', 'shine': 'Less shine', 'sculpt': 'Sculpted', 'even tone': 'Even tone',
                 'wrinkles': 'Softer lines', 'blemishes': 'Softer skin'}[job] + ' · face'
        self.local_develop(index, face, params, label, f'{label.split(" · ")[0]} on the face (masked layer)',
                           refine=self.only_skin)

    def only_skin(self, index):
        """Narrow the face selection to its measured skin colours, leaving hair, brows and lashes."""
        colors = self.analysis.get('skin_colors')
        if not colors:
            return
        self.add(index, 'select.colorRange', {'colors': colors, 'fuzziness': 45, 'mode': 'intersect',
                                              'sampleAllLayers': True}, 'Keep only the skin')
        self.add(index, 'studio.require_selection', {'what': 'the skin', 'min_coverage': 0.0005},
                 'Check the skin was found')

    def eye_job(self, index, job, eyes, scale):
        if job == 'red eye':
            points = [[round(x + w / 2), round(y + h / 2)] for x, y, w, h in eyes]
            self.add(index, 'studio.select_photo', {}, 'Select the photo')
            self.add(index, 'paint.redEye', {'points': points, 'pupilSize': 50, 'darken': 50},
                     f'Fix red eye on {len(points)} eye{"s" if len(points) > 1 else ""}')
            return
        if job == 'dark circles':
            # The soft area just below each eye, lifted gently; a hard mask would show as a patch.
            areas = [[x - w * 0.1, y + h * 0.75, w * 1.2, h * 0.8] for x, y, w, h in eyes]
            params = {'shadows': 35, 'exposure': 0.2, 'temperature': 4}
            label = 'Brighter under the eyes · under-eyes'
        else:
            areas = [[x - w * 0.1, y - h * 0.1, w * 1.2, h * 1.2] for x, y, w, h in eyes]
            params = {'exposure': 0.25, 'clarity': 20, 'vibrance': 10, 'sharpenAmount': 40}
            label = 'Brighter eyes · eyes'
        params = {key: round(value * min(scale, 1.6), 2) for key, value in params.items()}
        for number, (x, y, w, h) in enumerate(areas):
            self.add(index, 'select.rect', {'x': round(x), 'y': round(y), 'width': max(2, round(w)),
                                            'height': max(2, round(h)), 'ellipse': True,
                                            'mode': 'replace' if number == 0 else 'add',
                                            'feather': max(2, round(min(w, h) * 0.3))},
                     'Select under the eye' if job == 'dark circles' else 'Select the eye')
        self.add(index, 'studio.require_selection', {'what': label.split(' · ')[1], 'min_coverage': 0.00001},
                 'Check the area')
        self.add(index, 'studio.local_filter', {'command': 'filter.cameraRaw', 'params': params, 'label': label},
                 f'{label.split(" · ")[0]} (masked layer)')
        self.end_selection(index)
        self.regions.append({'requirement': index, 'label': label.split(' · ')[1],
                             'boxes': self.normalized([[round(v) for v in area] for area in areas])})

    def group_develop(self, index, edit):
        name, base, low, high = RAW[edit['action']]
        signed = edit['action'] not in ('sharpen', 'noise_reduction', 'grain')
        if edit['action'] == 'vignette':
            lighten = edit['direction'] == 'increase' and re.search(r'white|light', edit['quote'], re.IGNORECASE)
            value = amount({**edit, 'direction': 'increase' if lighten else 'decrease'}, abs(base), low, high)
            params = {name: value}
        elif edit['action'] == 'shadows' and edit['direction'] == 'none':
            params = {name: amount({**edit, 'direction': 'increase'}, base, low, high)}
        elif edit['action'] == 'highlights' and edit['direction'] == 'none':
            params = {name: amount({**edit, 'direction': 'decrease'}, base, low, high)}
        elif edit['action'] == 'noise_reduction':
            level = amount(edit, base, low, high, signed=False)
            params = {'noiseLuminance': level, 'noiseColor': min(100, round(level * 0.8))}
        elif edit['action'] == 'grain':
            params = {name: amount(edit, base, low, high, signed=False),
                      'grainSize': 35 if 'coarse' in edit['quote'].lower() else 25}
        elif edit['action'] == 'texture' and re.search(r'smooth|soften|skin', edit['quote'], re.IGNORECASE):
            params = {name: -abs(amount(edit, base, low, high, signed=False))}
        else:
            params = {name: amount(edit, base, low, high, signed)}
        if edit['target'] in ('whole image', 'layer'):
            current = self.raw.setdefault(index, {})
            for key, value in params.items():
                current[key] = current.get(key, 0) + value
            return
        self.local_develop(index, edit, params, short_label(edit), f'{short_label(edit)} on its own masked layer')

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

    def group_adjust(self, index, edit):
        action = edit['action']
        color = hex_color(edit['color'] or edit['object'])
        if edit['target'] == 'color' and color and action in ('saturation', 'vibrance', 'hue_shift', 'brightness'):
            family = color_family(color)
            if family in ('highlights', 'midtones', 'shadows'):
                edit = {**edit, 'target': family}
            else:
                neighbours = {'blues': ['blues', 'cyans'], 'cyans': ['cyans', 'blues'], 'reds': ['reds'],
                              'yellows': ['yellows'], 'greens': ['greens'], 'magentas': ['magentas']}[family]
                key = {'hue_shift': 'hue', 'brightness': 'lightness'}.get(action, 'saturation')
                base, low, high = (30, -180, 180) if key == 'hue' else (40, -100, 100)
                value = amount(edit, base, low, high)
                self.adjustment(index, {**edit, 'target': 'whole image'}, 'hueSaturation',
                                {name: {key: value} for name in neighbours},
                                f'{"More" if value > 0 else "Less"} {key} in the {family}')
                return
        if action in ADJUST:
            command, param, base, low, high = ADJUST[action]
            signed = action not in ('posterize', 'threshold')
            if signed:
                value = amount(edit, base, low, high)
            else:
                value = round(max(low, min(high, edit['value'] if edit['value'] is not None else base)))
            self.adjustment(index, edit, command, {param: value}, short_label(edit))
        elif action == 'recolor':
            color = hex_color(edit['color'])
            if not color:
                self.blocking.append(f'Which color for “{edit["quote"]}”?')
                return
            if edit['target'] == 'whole image' and not edit['object']:
                self.blocking.append(f'What should become {edit["color"]}? Name the object.')
                return
            if edit['target'] == 'whole image':
                edit = {**edit, 'target': 'object'}
            if IRIS_WORDS.search(edit['object']):
                self.eye_color(index, edit, color)
                return
            hue, light, sat = hls(color)
            params = {'colorize': True, 'hue': round(hue * 360), 'saturation': round(min(100, 25 + sat * 60)),
                      'lightness': round(max(-60, min(60, (light - 0.5) * 70)))}
            if sat < 0.12:
                params = {'saturation': -100, 'lightness': round(max(-80, min(80, (light - 0.5) * 120)))}
            self.adjustment(index, edit, 'hueSaturation', params, f'Recolor {edit["object"] or "the area"} '
                                                                   f'{edit["color"]}'.strip())
        elif action == 'color_grade':
            color = hex_color(edit['color']) or '#ff9d3c'
            r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
            scale = 18 * LEVEL[edit['strength']]
            shift = [round((r - (g + b) / 2) * scale), round((g - (r + b) / 2) * scale),
                     round((b - (r + g) / 2) * scale)]
            tone = edit['target'] if edit['target'] in ('shadows', 'midtones', 'highlights') else 'midtones'
            self.adjustment(index, {**edit, 'target': 'whole image'}, 'colorBalance', {tone: shift},
                            f'Tint the {tone} {edit["color"] or "warm"}')
        elif action == 'color_filter':
            words = (edit['choice'] + ' ' + edit['color'] + ' ' + edit['quote']).lower()
            chosen = next((FILTERS[key] for key in FILTERS if re.search(rf'\b{key}', words)), None)
            density = round(amount({**edit, 'direction': 'increase'}, 25, 1, 100))
            params = {'filter': chosen, 'density': density} if chosen else {
                'color': hex_color(edit['color']) or '#ff9d3c', 'density': density}
            self.adjustment(index, edit, 'photoFilter', params, short_label(edit))
        elif action == 'look':
            self.look(index, edit)
        elif action == 'auto_fix':
            self.auto_fix(index, edit)
        elif action == 'black_and_white':
            mix = {'high contrast': {'reds': 70, 'yellows': 90, 'greens': 10, 'cyans': 20, 'blues': -20,
                                     'magentas': 60},
                   'infrared': {'reds': 10, 'yellows': 160, 'greens': 200, 'cyans': 40, 'blues': -60,
                                'magentas': 30}}
            style = next((key for key in mix if key in (edit['choice'] + ' ' + edit['quote']).lower()), None)
            params = dict(mix.get(style, {}))
            tint = hex_color(edit['color'])
            if tint and tint not in ('#000000', '#ffffff'):
                params.update(tint=True, tintColor=tint)
            self.adjustment(index, edit, 'blackWhite', params, 'Black & white' + (f' ({style})' if style else ''))
        elif action == 'sepia':
            self.adjustment(index, edit, 'blackWhite', {'tint': True, 'tintColor': '#a3845c'}, 'Sepia tone')
        elif action == 'duotone':
            names = re.split(r'\band\b|,|/|\bto\b', edit['color'] or edit['choice'])
            colors = [c for c in (hex_color(n) for n in names) if c]
            if len(colors) < 2:
                colors = (colors + ['#14213d', '#fcd116'])[:2]
            colors.sort(key=luminance)
            self.adjustment(index, edit, 'gradientMap', {'stops': [[0, colors[0]], [1, colors[1]]]}, 'Duotone')
        elif action == 'invert':
            self.adjustment(index, edit, 'invert', {}, 'Invert')

    def auto_fix(self, index, edit):
        """Auto Tone, Auto Contrast and Auto Color as an editable Levels layer, from the measured histogram."""
        levels = self.analysis.get('levels')
        if not levels:
            self.blocking.append('The photo could not be measured for an automatic correction.')
            return
        words = (edit['choice'] + ' ' + edit['quote']).lower()
        kind = 'color' if re.search(r'colou?r|white balance|cast|tint', words) else \
            'contrast' if 'contrast' in words else 'tone'
        if kind == 'contrast':
            black, white = levels['all']
            params, name = {'inBlack': black, 'inWhite': white}, 'Auto contrast'
        else:
            params = {channel: {'inBlack': levels[channel][0], 'inWhite': levels[channel][1],
                                **({'gamma': levels['gamma'][channel]} if kind == 'color' else {})}
                      for channel in ('red', 'green', 'blue')}
            name = 'Auto color' if kind == 'color' else 'Auto tone'
        self.adjustment(index, edit, 'levels', params, name)

    def eye_color(self, index, edit, color):
        """New iris color: a soft circle on each iris, so the whites and skin keep their color."""
        _, eyes = self.target_boxes({**edit, 'target': 'object', 'object': EYES})
        if not eyes:
            self.blocking.append('Could not find the eyes.')
            return
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        circles = []
        for number, (x, y, w, h) in enumerate(eyes):
            size = min(w * 0.36, h * 0.75)
            cx, cy = x + w / 2, y + h / 2
            circles.append([round(cx - size / 2), round(cy - size / 2), round(size), round(size)])
            self.add(index, 'select.rect', {'x': circles[-1][0], 'y': circles[-1][1], 'width': max(2, round(size)),
                                            'height': max(2, round(size)), 'ellipse': True,
                                            'mode': 'replace' if number == 0 else 'add',
                                            'feather': max(1, round(size * 0.15))}, 'Select the iris')
        hue, _, sat = hls(color)
        self.add(index, 'layer.newAdjustmentLayer.hueSaturation',
                 {'colorize': True, 'hue': round(hue * 360), 'saturation': round(min(70, 25 + sat * 40))},
                 f'{edit["color"].capitalize()} eyes')
        self.add(index, 'layer.setProps', {'blend': 'Color', 'opacity': 0.75}, 'Blend as color only')
        self.after_new_layer(index, f'{edit["color"].capitalize()} eyes')
        self.end_selection(index)
        self.regions.append({'requirement': index, 'label': 'irises', 'boxes': self.normalized(circles)})

    def look(self, index, edit):
        words = (edit['choice'] + ' ' + edit['quote']).lower()
        lut = next((name for name in LUTS if name.lower() in words.replace(' ', '').replace('-', '')), None)
        recipe = next((RECIPES[name] for name in sorted(RECIPES, key=len, reverse=True) if name in words), None)
        if edit['target'] == 'sky' and recipe in (RECIPES['dramatic'], RECIPES['moody'], RECIPES['hdr'], None):
            recipe = RECIPES['dramatic sky']
        if lut is None and recipe is None:
            lut_words = {'teal': 'tealOrange', 'film': 'fadedFilm', 'faded': 'fadedFilm', 'bleach': 'bleachBypass',
                         'night': 'dayForNight', 'cross': 'crossProcess', 'noir': 'monoContrast'}
            lut = next((value for key, value in lut_words.items() if key in words), None)
        if lut is None and recipe is None:
            recipe = RECIPES['professional polish']
        scale = LEVEL[edit['strength']]
        local = edit['target'] not in ('whole image', 'layer')
        if recipe and 'raw' in recipe:
            params = {key: round(value * min(scale, 1.6), 2) for key, value in recipe['raw'].items()}
            if local:
                # “Make the sky dramatic” develops only the sky, on a masked copy of the photo.
                params.pop('vignetteAmount', None)
                if not self.local_develop(index, edit, params, short_label(edit),
                                          'Develop: ' + ', '.join(f'{k} {v:+g}' for k, v in params.items())
                                          + f' · {edit["target"]}'):
                    return
            else:
                self.raw[index] = params
                self.flush_raw()
        lut = lut or (recipe or {}).get('lut')
        layers = []
        if lut:
            layers.append(('colorLookup', {'lut': lut}, f'Look: {lut}'))
        if recipe and 'curves' in recipe:
            layers.append(('curves', {'points': recipe['curves']}, 'Matte curve'))
        if recipe and 'posterize' in recipe:
            layers.append(('posterize', {'levels': recipe['posterize']}, 'Posterize'))
        for command, params, name in layers:
            self.adjustment(index, edit, command, params, name)
            opacity = {'subtle': 0.5, 'moderate': 0.8, 'strong': 1.0}[edit['strength']]
            if command == 'colorLookup' and opacity < 1:
                self.add(index, 'layer.setProps', {'opacity': opacity}, f'Look strength {opacity:.0%}')

    def group_effect(self, index, edit):
        action, w, h = edit['action'], self.canvas.width, self.canvas.height
        cx, cy = position_xy(edit['position'] or 'center')
        if action == 'blur':
            command, params = 'filter.blur.gaussianBlur', {'radius': amount({**edit, 'direction': 'increase'},
                                                                             max(2, min(w, h) * 0.006), 0.1, 250)}
        elif action == 'motion_blur':
            command, params = 'filter.blur.motionBlur', {
                'distance': round(amount({**edit, 'direction': 'increase'}, 20, 1, 2000)),
                'angle': 90 if re.search(r'vertical|falling|up|down', edit['quote'], re.IGNORECASE) else 0}
        elif action == 'radial_blur':
            spin = re.search(r'spin|twirl|rotat|circular', edit['choice'] + ' ' + edit['quote'], re.IGNORECASE)
            command, params = 'filter.blur.radialBlur', {
                'amount': round(amount({**edit, 'direction': 'increase'}, 8 if spin else 12, 1, 100)),
                'method': 'spin' if spin else 'zoom', 'quality': 'best', 'centerX': cx, 'centerY': cy}
        elif action == 'glow':
            self.glow(index, edit)
            return
        elif action == 'weather':
            self.weather(index, edit)
            return
        elif action == 'mirror':
            words = (edit['choice'] + ' ' + edit['quote']).lower()
            keep = next((side for side in ('left', 'right', 'top', 'bottom') if side in words), 'left')
            self.add(index, 'studio.mirror', {'keep': keep}, f'Mirror the {keep} half onto the other side')
            return
        elif action == 'drop_shadow':
            self.contact_shadow(index, edit)
            return
        elif action == 'reflection':
            key, boxes = self.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
            if not boxes:
                self.blocking.append(f'Could not find {key or "the subject"} to reflect.')
                return
            opacity = {'subtle': 0.2, 'moderate': 0.3, 'strong': 0.45}[edit['strength']]
            self.add(index, 'studio.reflection', {'boxes': boxes, 'what': key, 'opacity': opacity},
                     f'Reflect {key} on the surface below ({opacity:.0%})')
            self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized(boxes)})
            return
        elif action == 'tilt_shift':
            command, params = 'filter.blurGallery.tiltShift', {
                'centerY': cy, 'blur': round(amount({**edit, 'direction': 'increase'}, 15, 0, 500))}
        elif action == 'lens_flare':
            command, params = 'filter.render.lensFlare', {
                'centerX': cx if edit['position'] else 0.2, 'centerY': cy if edit['position'] else 0.2,
                'brightness': round(amount({**edit, 'direction': 'increase'}, 100, 10, 300))}
        elif action == 'relight':
            angles = {'right': 0, 'top right': 45, 'top': 90, 'top left': 135, 'left': 180, 'bottom left': -135,
                      'bottom': -90, 'bottom right': -45, 'center': 90, '': 135}
            color = hex_color(edit['color'])
            warmth = 0
            if color:
                hue = hls(color)[0] * 360
                warmth = 40 if hue < 70 or hue > 330 else -40 if 160 < hue < 280 else 0
            command, params = 'filter.render.relight', {
                'angle': angles[edit['position']], 'warmth': warmth,
                'intensity': round(amount({**edit, 'direction': 'increase'}, 40, 0, 100))}
        elif re.search(r'glitch|rgb split|channel (split|shift)', edit['choice'] + ' ' + edit['quote'],
                       re.IGNORECASE):
            # RGB split: copies that show only the red or only the blue channel, nudged apart.
            shift = max(2, round(w * 0.006 * LEVEL[edit['strength']]))
            self.add(index, 'studio.select_insert', {}, 'Choose where the layers go')
            for channels, dx, name in (([True, False, False], shift, 'Glitch red'),
                                       ([False, False, True], -shift, 'Glitch blue')):
                self.add(index, 'layer.stampVisible', {}, f'Copy the picture for {name.lower()}')
                self.add(index, 'layer.setProps', {'channels': channels, 'name': name}, f'{name}: one channel only')
                self.add(index, 'layer.translate', {'dx': dx, 'dy': 0}, f'Shift it {dx:+d}px')
            return
        else:  # artistic
            words = (edit['choice'] + ' ' + edit['quote']).lower()
            found = next((ARTISTIC[key] for key in sorted(ARTISTIC, key=len, reverse=True) if key in words), None)
            if found is None:
                self.expert_requests.append(index)
                return
            command, params = found
        if edit['target'] in ('whole image', 'layer'):
            self.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
            self.add(index, command, params, short_label(edit))
        elif self.selection(index, edit):
            self.add(index, 'studio.local_filter', {'command': command, 'params': params,
                                                    'label': short_label(edit)}, f'{short_label(edit)} (masked)')
            self.end_selection(index)

    def glow(self, index, edit):
        """Orton glow: a blurred copy of the picture screened over it, limited to what glows when named."""
        radius = round(min(self.canvas.width, self.canvas.height) * 0.02 * LEVEL[edit['strength']], 1)
        opacity = {'subtle': 0.35, 'moderate': 0.55, 'strong': 0.8}[edit['strength']]
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        self.add(index, 'layer.stampVisible', {}, 'Copy the picture for the glow')
        self.add(index, 'filter.blur.gaussianBlur', {'radius': max(2, radius)}, f'Blur it ({radius:g} px)')
        self.add(index, 'layer.setProps', {'blend': 'Screen', 'opacity': opacity, 'name': 'Glow'},
                 f'Screen it at {opacity:.0%} as a glow')
        if edit['target'] in ('object', 'main subject'):
            if not self.selection(index, edit):
                return
            self.add(index, 'select.modify.expand', {'radius': max(4, round(radius * 2))}, 'Let the glow spill out')
            self.add(index, 'select.modify.feather', {'radius': max(2, round(radius))}, 'Soften it')
            self.add(index, 'layer.layerMask.revealSelection', {}, 'Glow only there')
            self.end_selection(index)

    def weather(self, index, edit):
        """Rain or snow the way it is made by hand: sparse noise on a black layer, shaped, then screened."""
        snow = bool(re.search(r'snow', edit['choice'] + ' ' + edit['quote'], re.IGNORECASE))
        side = min(self.canvas.width, self.canvas.height)
        scale = LEVEL[edit['strength']]
        name = 'Snow' if snow else 'Rain'
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        self.add(index, 'layer.new.layer', {'name': name}, f'New {name.lower()} layer')
        self.add(index, 'edit.fill', {'contents': 'color', 'color': '#000000'}, 'Fill it black')
        # Measured in PhotoCraft: Add Noise on black is half-normal with sigma ≈ 0.64 × amount, so the
        # Levels cut-off decides how many specks survive (amount 100: 0.085% reach level 200).
        level = edit['strength']
        if snow:
            self.add(index, 'filter.noise.addNoise', {'amount': 100, 'distribution': 'gaussian',
                                                      'monochromatic': True}, 'Scatter specks')
            self.add(index, 'image.adjustments.levels', {'inBlack': {'subtle': 210, 'moderate': 200,
                                                                     'strong': 185}[level], 'inWhite': 255},
                     'Keep only a few as flakes')
            self.add(index, 'filter.other.maximum', {'radius': max(1, round(side / 1100))}, 'Grow them into flakes')
            self.add(index, 'filter.blur.gaussianBlur', {'radius': max(0.8, round(side / 1200, 1))},
                     'Soften the flakes')
            self.add(index, 'image.adjustments.levels', {'inBlack': 0, 'inWhite': 50}, 'Make the flakes white')
        else:
            self.add(index, 'filter.noise.addNoise', {'amount': 150, 'distribution': 'gaussian',
                                                      'monochromatic': True}, 'Scatter specks')
            self.add(index, 'image.adjustments.levels', {'inBlack': {'subtle': 140, 'moderate': 120,
                                                                     'strong': 100}[level], 'inWhite': 255},
                     'Keep only some drops')
            self.add(index, 'filter.blur.motionBlur', {'distance': max(10, round(side * 0.04)), 'angle': 75},
                     'Streak them as falling rain')
            self.add(index, 'image.adjustments.levels', {'inBlack': 5, 'inWhite': 60}, 'Brighten the streaks')
        opacity = 0.9 if snow else 0.6
        self.add(index, 'layer.setProps', {'blend': 'Screen', 'opacity': opacity}, f'Screen at {opacity:.0%}')

    def contact_shadow(self, index, edit):
        """A soft shadow where each object meets the surface, under the objects, not over them."""
        query_edit = {**edit, 'target': 'object' if edit['object'] else 'main subject'}
        key, boxes = self.target_boxes(query_edit)
        if not boxes:
            self.blocking.append(f'Could not find {key or "the subject"} to put a shadow under.')
            return
        strength = LEVEL[edit['strength']]
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        self.add(index, 'layer.new.layer', {'name': 'Shadow'}, 'New shadow layer')
        heights = []
        for number, (x, y, w, h) in enumerate(boxes):
            sh = max(6, round(h * 0.07))
            heights.append(sh)
            self.add(index, 'select.rect', {'x': round(x + w * 0.06), 'y': round(y + h - sh * 0.6),
                                            'width': max(2, round(w * 0.88)), 'height': sh, 'ellipse': True,
                                            'mode': 'replace' if number == 0 else 'add'}, 'Where it touches down')
        self.add(index, 'edit.fill', {'contents': 'color', 'color': '#000000'}, 'Fill the shadow')
        self.end_selection(index)
        self.add(index, 'filter.blur.gaussianBlur', {'radius': max(3, round(max(heights) * 0.45))}, 'Soften it')
        self.add(index, 'layer.setProps', {'blend': 'Multiply', 'opacity': min(0.85, round(0.45 * strength, 2))},
                 'Multiply the shadow onto the surface')
        self.add(index, 'studio.select_outline', {'boxes': boxes, 'what': key}, f'Select {key}')
        self.add(index, 'layer.layerMask.hideSelection', {}, f'Keep the shadow behind {key}')
        self.end_selection(index)
        self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized(boxes)})

    def do_blur_background(self, index, edit):
        edit = {**edit, 'target': 'main subject'}
        if not self.selection(index, edit, invert=True):
            return
        self.add(index, 'select.modify.feather', {'radius': max(1, round(min(self.canvas.width,
                                                                             self.canvas.height) * 0.003))},
                 'Soften the mask edge')
        radius = round(amount({**edit, 'direction': 'increase'}, 15, 1, 100))
        self.add(index, 'studio.local_filter', {'command': 'filter.blur.lensBlur', 'params': {'radius': radius},
                                                'label': 'Background blur'}, f'Lens blur the background ({radius})')
        self.end_selection(index)

    def do_remove_background(self, index, edit):
        if not self.selection(index, {**edit, 'target': 'main subject'}):
            return
        self.add(index, 'studio.select_photo', {'smart': True, 'keep_selection': True}, 'Select the photo')
        self.add(index, 'layer.layerMask.revealSelection', {}, 'Hide everything but the subject (layer mask)')
        self.end_selection(index)
        color = hex_color(edit['color'])
        if color and re.search(r'gradient|studio', edit['quote'], re.IGNORECASE):
            # A studio backdrop: lighter behind the subject, falling off toward the edges.
            self.add(index, 'layer.newFillLayer.gradient', {'from': mix(color, '#ffffff', 0.25),
                                                            'to': mix(color, '#000000', 0.35), 'style': 'radial'},
                     f'New {edit["color"]} gradient backdrop')
        elif color:
            self.add(index, 'layer.newFillLayer.solidColor', {'color': color}, f'New {edit["color"]} backdrop')
        if color:
            self.add(index, 'layer.renameLayer', {'name': 'Backdrop'}, 'Name the layer “Backdrop”')
            self.add(index, 'layer.arrange.sendToBack', {}, 'Put the backdrop behind the subject')

    def do_add_text(self, index, edit):
        if not edit['text']:
            self.blocking.append('Which words should the text say? Put them in quotes.')
            return
        family, weight, italic, effects = font_choice(edit['choice'], self.fonts)
        params = {
            'text': edit['text'], 'position': edit['position'] or 'center', 'size': text_size_pt(edit, self.canvas),
            'color': hex_color(edit['color']) or 'auto', 'effects': effects, 'name': edit['text'][:60],
        }
        if family:
            params['font'] = family
        if weight:
            params['weight'] = weight
        if italic:
            params['italic'] = True
        if edit['choice'] and not family and not (weight or italic or effects):
            self.notes.append(f'Font “{edit["choice"]}” is not installed; using the default font.')
        detail = [f'{params["size"]:g} pt', edit['position'] or 'center',
                  edit['color'] or 'readable color', family or '']
        self.add(index, 'studio.text', params, f'Add “{edit["text"][:40]}” · ' + ', '.join(d for d in detail if d))
        if re.search(r'watermark|semi[\s-]?transparent|transparent|faint|see[\s-]?through|ghost', edit['quote'],
                     re.IGNORECASE):
            opacity = edit['value'] / 100 if edit['value'] and 1 <= edit['value'] <= 100 and \
                re.search(r'\d\s*%', edit['quote']) else 0.5
            self.add(index, 'layer.setProps', {'opacity': opacity}, f'Text at {opacity:.0%} opacity')

    def do_edit_text(self, index, edit):
        layer = self.layer_named(edit['object'])
        if layer is None or layer['kind'] != 'Type':
            self.blocking.append(f'Which text layer does “{edit["quote"]}” mean?')
            return
        if not edit['text']:
            self.blocking.append('What should the text say instead?')
            return
        self.add(index, 'type.edit', {'layer': layer['id'], 'text': edit['text']},
                 f'Change “{layer["name"][:30]}” to “{edit["text"][:30]}”')

    def do_frame(self, index, edit):
        width = round(edit['value']) if edit['value'] else max(2, round(min(self.canvas.width,
                                                                            self.canvas.height) * 0.015))
        color = hex_color(edit['color']) or '#ffffff'
        inset = round(min(self.canvas.width, self.canvas.height) * 0.03)
        self.add(index, 'studio.select_top', {}, 'Work above everything')
        self.add(index, 'layer.new.layer', {'name': 'Frame'}, 'New frame layer')
        self.add(index, 'select.rect', {'x': inset, 'y': inset, 'width': self.canvas.width - inset * 2,
                                        'height': self.canvas.height - inset * 2}, 'Frame area')
        self.add(index, 'edit.stroke', {'width': min(250, width), 'color': color, 'location': 'inside'},
                 f'Draw a {width}px frame line')
        self.end_selection(index)

    def do_gradient_overlay(self, index, edit):
        """A gradient multiplied over the picture: the named color at one edge fading to nothing."""
        color = hex_color(edit['color']) or '#000000'
        edge = edit['position'] or next((side for side in ('top', 'left', 'right', 'bottom')
                                         if side in edit['quote'].lower()), 'bottom')
        angle = {'bottom': 90, 'top': -90, 'left': 0, 'right': 180}.get(edge.split()[-1], 90)
        opacity = {'subtle': 0.45, 'moderate': 0.7, 'strong': 0.9}[edit['strength']]
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        self.add(index, 'layer.newFillLayer.gradient', {'from': color, 'to': '#ffffff', 'angle': angle,
                                                        'style': 'linear'}, f'Gradient from the {edge}')
        self.add(index, 'layer.setProps', {'blend': 'Multiply', 'opacity': opacity,
                                           'name': f'{edit["color"] or "Dark"} gradient'.capitalize()},
                 f'Multiply it at {opacity:.0%} (white leaves the rest unchanged)')

    def do_round_corners(self, index, edit):
        w, h = self.canvas.width, self.canvas.height
        radius = round(edit['value']) if edit['value'] else round(min(w, h) * {'subtle': 0.03, 'moderate': 0.06,
                                                                             'strong': 0.12}[edit['strength']])
        color = hex_color(edit['color']) or '#ffffff'
        self.add(index, 'studio.select_top', {}, 'Work above everything')
        self.add(index, 'layer.new.layer', {'name': 'Rounded corners'}, 'New corners layer')
        self.add(index, 'select.rect', {'x': 0, 'y': 0, 'width': w, 'height': h}, 'Select the picture')
        self.add(index, 'select.modify.smooth', {'radius': max(1, min(500, radius)), 'applyAtCanvasBounds': True},
                 f'Round the corners ({radius}px)')
        self.add(index, 'select.inverse', {}, 'Select the corners')
        self.add(index, 'edit.fill', {'contents': 'color', 'color': color}, f'Fill them {edit["color"] or "white"}')
        self.end_selection(index)

    def do_headshot(self, index, edit):
        ratio = aspect_from(edit['aspect']) or aspect_from(edit['quote'])
        if not ratio:
            ratio = (1, 1) if re.search(r'linked\s*in|profile|avatar|\bdp\b|square', edit['quote'], re.IGNORECASE) \
                else (4, 5)
        self.head_frame(index, edit, ratio, head_share=0.52, top_margin=0.1, label='Crop to a headshot')

    def head_frame(self, index, edit, ratio, head_share, top_margin, label):
        """Frame measured from the head box: the head is `head_share` of the height, its top
        `top_margin` below the frame's top, centered across. Returns the crop size or None."""
        _, boxes = self.target_boxes({**edit, 'target': 'object', 'object': PASSPORT_HEAD})
        if not boxes:
            self.blocking.append('Could not find the person’s head to frame.')
            return None
        hx, hy, hw, hh = max(boxes, key=lambda b: b[2] * b[3])
        w, h = self.canvas.width, self.canvas.height
        frame_h = hh / head_share
        frame_w = frame_h * ratio[0] / ratio[1]
        scale = min(1.0, w / frame_w, h / frame_h)
        if scale < 1:
            self.notes.append('The photo is framed too tightly for the usual crop, so the head fills more of the '
                              'picture than usual.')
        cw, ch = min(w, round(frame_w * scale)), min(h, round(frame_h * scale))
        x = min(max(0, round(hx + hw / 2 - cw / 2)), w - cw)
        y = min(max(0, round(hy - ch * top_margin)), h - ch)
        self.crop(index, x, y, cw, ch, label)
        return cw, ch

    def do_picture_frame(self, index, edit):
        choice = (edit['choice'] or 'doubleLine').lower()
        frames = ['vineWithFlowers', 'vineWithLeaves', 'ivy', 'roses', 'daisies', 'berries', 'bamboo', 'waves',
                  'zigzag', 'dots', 'rope', 'scallops', 'doubleLine', 'snowflakes', 'stars', 'hearts']
        frame = next((name for name in frames if name.lower() in choice.replace(' ', '')), 'doubleLine')
        self.add(index, 'studio.select_top', {}, 'Work above everything')
        self.add(index, 'filter.render.pictureFrame', {'frame': frame, 'newLayer': True}, f'{frame} frame')

    def do_color_overlay(self, index, edit):
        color = hex_color(edit['color'])
        if not color:
            self.blocking.append('Which color should the overlay be?')
            return
        opacity = max(1, min(100, edit['value'] if edit['value'] is not None else
                             {'subtle': 15, 'moderate': 30, 'strong': 50}[edit['strength']]))
        self.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
        if edit['target'] != 'whole image' and not self.selection(index, edit):
            return
        self.add(index, 'layer.newFillLayer.solidColor', {'color': color}, f'{edit["color"]} overlay')
        blend = (edit['choice'] or '').title() if edit['choice'].lower() in (
            'multiply', 'screen', 'overlay', 'soft light', 'color', 'hard light') else 'Normal'
        self.add(index, 'layer.setProps', {'opacity': opacity / 100, 'blend': blend, 'name': f'{edit["color"]} overlay'},
                 f'{opacity:g}% opacity, {blend}')
        if edit['target'] != 'whole image':
            self.end_selection(index)

    def group_expert(self, index, edit):
        self.expert_requests.append(index)

    def group_ai(self, index, edit):
        """New content painted by AI as its own layer, masked to the target."""
        if not self.ai:
            self.blocking.append(f'“{edit["quote"]}” needs new content painted by AI. Install AI content editing '
                                 '(Download editing model.bat) for this part.')
            return
        params = {'instruction': edit['quote'][:400] + '. Keep everything else exactly the same.',
                  'label': f'AI: {edit["quote"]}'[:80]}
        adding = re.search(r'\b(add|put|place|insert)\b', edit['quote'], re.IGNORECASE)
        if edit['target'] in ('object', 'main subject') and not (adding and not edit['object']):
            key, boxes = self.target_boxes(edit)
            if not boxes:
                self.blocking.append(f'Could not find {key or "where to paint"} in the picture.')
                return
            params['boxes'] = boxes
            self.regions.append({'requirement': index, 'label': key, 'boxes': self.normalized(boxes)})
            if adding:
                # New things go next to what was named; the box only says where to look.
                params.pop('boxes')
            elif not self.selection(index, edit):
                return
        elif edit['target'] not in ('whole image', 'layer', 'object', 'main subject'):
            if not self.selection(index, edit):
                return
        self.add(index, 'studio.ai_layer', params, f'Paint with AI: {edit["quote"][:60]}')

    expert_requests = None


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
    return {'requirement': index, 'check': f'Measured: {what} {detail}', 'passed': passed, 'measured': True}


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


def measure(edits, regions, before, after, geometry_changed):
    """Pixel measurements of the rendered result for edits whose effect can be measured. A
    visual model can say “done” for a mug that is still grey; numbers cannot."""
    import numpy as np

    checks = []
    by_requirement = {}
    originals = {}
    for region in regions:
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
                    edit['target'] == 'whole image' and not geometry_changed and edit['direction'] != 'none':
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
                               'passed': passed, 'measured': True})
            elif action in ('saturation', 'vibrance') and edit['target'] == 'color' and hex_color(edit['color'])                     and not geometry_changed and edit['direction'] != 'none':
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

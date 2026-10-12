"""Adjustment layers: tone, color and monochrome, each an editable layer, masked when targeted.

Colors named in words become hex values and Hue/Saturation ranges here; the planner never
writes a hue angle or a curve point.
"""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure

SUMMARIES = {
    'brightness': ('light', 'overall brightness'),
    'contrast': ('light', 'contrast'),
    'saturation': ('color', 'color saturation'),
    'vibrance': ('color', 'vibrance, gentle saturation that protects skin'),
    'hue_shift': ('color', 'rotate hues by degrees (value)'),
    'posterize': ('effect', 'posterize into a number of levels (value)'),
    'threshold': ('effect', 'pure black and white threshold (value 1..255)'),
}
NEIGHBOURS = {'blues': ['blues', 'cyans'], 'cyans': ['cyans', 'blues'], 'reds': ['reds'], 'yellows': ['yellows'],
              'greens': ['greens'], 'magentas': ['magentas']}


def basic(b, index, edit):
    action = edit['action']
    color = lang.hex_color(edit['color'] or edit['object'])
    if edit['target'] == 'color' and color and action in ('saturation', 'vibrance', 'hue_shift', 'brightness'):
        family = lang.color_family(color)
        if family in ('highlights', 'midtones', 'shadows'):
            edit = {**edit, 'target': family}
        else:
            # Hue/Saturation's own per-colour ranges, blues with cyans: a selected “blues” range
            # missed a turquoise sea completely (measured).
            key = {'hue_shift': 'hue', 'brightness': 'lightness'}.get(action, 'saturation')
            base, low, high = (30, -180, 180) if key == 'hue' else (40, -100, 100)
            value = lang.amount(edit, base, low, high)
            b.adjustment(index, {**edit, 'target': 'whole image'}, 'hueSaturation',
                         {name: {key: value} for name in NEIGHBOURS[family]},
                         f'{"More" if value > 0 else "Less"} {key} in the {family}')
            return
    command, param, base, low, high = lang.ADJUST[action]
    if action in ('posterize', 'threshold'):
        value = round(max(low, min(high, edit['value'] if edit['value'] is not None else base)))
    else:
        value = lang.amount(edit, base, low, high)
    b.adjustment(index, edit, command, {param: value}, lang.short_label(edit))


for _action, (_category, _summary) in SUMMARIES.items():
    procedure(_action, _action.replace('_', ' ').capitalize(), _category, 'adjust', _summary, area_safe=True)(basic)


def recolor_finds(edit):
    """The named thing, whatever target the planner chose: “change her eye color” planned with the
    whole image as target once found no eyes, because nothing asked for them (2026-10-12)."""
    if edit['target'] in ('main subject', 'background', 'object'):
        return [lang.subject_query(edit)]
    if edit['target'] == 'whole image' and edit['object']:
        return [lang.subject_query({**edit, 'target': 'object'})]
    return []


def names_a_color(edit):
    return bool(lang.hex_color(edit['color']) or lang.hex_color(edit['quote']))


def tints_tones(edit):
    """A tint of a tonal range is asked in those words (“a blue tint in the shadows”, “grade the
    highlights warm”); “make the sunset colors more vivid” is not one (it came back as one)."""
    return names_a_color(edit) and bool(re.search(r'tint|tone|grad|cast|shadow|highlight|midtone|wash',
                                                  edit['quote'], re.IGNORECASE))


@procedure('recolor', 'Recolor', 'color', 'adjust', 'change the color of the target to color (e.g. make the car red)',
           area_safe=True, finds=recolor_finds, requires=names_a_color,
           examples=('make the red mug green', 'change his shirt to black'))
def recolor(b, index, edit):
    color = lang.hex_color(edit['color'])
    if not color:
        b.blocking.append(f'Which color for “{edit["quote"]}”?')
        return
    if edit['target'] == 'whole image' and not edit['object']:
        b.blocking.append(f'What should become {edit["color"]}? Name the object.')
        return
    if edit['target'] == 'whole image':
        edit = {**edit, 'target': 'object'}
    if lang.IRIS_WORDS.search(edit['object']):
        eye_color(b, index, edit, color)
        return
    hue, light, sat = lang.hls(color)
    params = {'colorize': True, 'hue': round(hue * 360), 'saturation': round(min(100, 25 + sat * 60)),
              'lightness': round(max(-60, min(60, (light - 0.5) * 70)))}
    if sat < 0.12:
        params = {'saturation': -100, 'lightness': round(max(-80, min(80, (light - 0.5) * 120)))}
    b.adjustment(index, edit, 'hueSaturation', params, f'Recolor {edit["object"] or "the area"} {edit["color"]}'.strip())


def eye_color(b, index, edit, color):
    """New iris color: a soft circle on each iris, so the whites and skin keep their color."""
    _, eyes = b.target_boxes({**edit, 'target': 'object', 'object': lang.EYES})
    if not eyes:
        b.blocking.append('Could not find the eyes.')
        return
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    circles = []
    for number, (x, y, w, h) in enumerate(eyes):
        size = min(w * 0.36, h * 0.75)
        cx, cy = x + w / 2, y + h / 2
        circles.append([round(cx - size / 2), round(cy - size / 2), round(size), round(size)])
        b.add(index, 'select.rect', {'x': circles[-1][0], 'y': circles[-1][1], 'width': max(2, round(size)),
                                     'height': max(2, round(size)), 'ellipse': True,
                                     'mode': 'replace' if number == 0 else 'add',
                                     'feather': max(1, round(size * 0.15))}, 'Select the iris')
    hue, _, sat = lang.hls(color)
    b.add(index, 'layer.newAdjustmentLayer.hueSaturation',
          {'colorize': True, 'hue': round(hue * 360), 'saturation': round(min(70, 25 + sat * 40))},
          f'{edit["color"].capitalize()} eyes')
    b.add(index, 'layer.setProps', {'blend': 'Color', 'opacity': 0.75}, 'Blend as color only')
    b.after_new_layer(index, f'{edit["color"].capitalize()} eyes')
    b.end_selection(index)
    b.regions.append({'requirement': index, 'label': 'irises', 'boxes': b.normalized(circles)})


@procedure('color_grade', 'Tint a tonal range', 'color', 'adjust',
           'tint shadows/midtones/highlights toward color (target = tone)', area_safe=True, requires=tints_tones,
           examples=('give the shadows a blue tint',))
def color_grade(b, index, edit):
    color = lang.hex_color(edit['color']) or '#ff9d3c'
    r, g, bl = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    scale = 18 * lang.LEVEL[edit['strength']]
    shift = [round((r - (g + bl) / 2) * scale), round((g - (r + bl) / 2) * scale), round((bl - (r + g) / 2) * scale)]
    tone = edit['target'] if edit['target'] in ('shadows', 'midtones', 'highlights') else 'midtones'
    b.adjustment(index, {**edit, 'target': 'whole image'}, 'colorBalance', {tone: shift},
                 f'Tint the {tone} {edit["color"] or "warm"}')


def balance(color, scale, normalize=False):
    """Color Balance offsets [cyan-red, magenta-green, yellow-blue] that tint toward a color. With
    `normalize`, the strongest offset is `scale` whatever the color's own saturation: teal at its raw
    strength moved the shadows by 8 of 100 and the split tone could not be seen (2026-10-12)."""
    r, g, bl = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    offsets = [r - (g + bl) / 2, g - (r + bl) / 2, bl - (r + g) / 2]
    if normalize:
        top = max(abs(value) for value in offsets) or 1
        offsets = [value / top for value in offsets]
    return [round(value * scale) for value in offsets]


@procedure('split_tone', 'Split toning', 'color', 'adjust',
           'split toning: one color in the shadows and another in the highlights (color = “shadow color and '
           'highlight color”, e.g. “teal and orange”; cool shadows and warm highlights when none are named)',
           area_safe=True, examples=('split tone with teal shadows and orange highlights',),
           requires=r'split|shadows?\b.*\bhighlights?|highlights?\b.*\bshadows?|teal and orange|toning')
def split_tone(b, index, edit):
    names = [name for name in re.split(r'\band\b|,|/|\bwith\b', edit['color'] or edit['choice']) if name.strip()]
    colors = [c for c in (lang.hex_color(n) for n in names) if c]
    words = edit['quote'].lower()
    if len(colors) < 2:
        # The person's wording names which tone gets which colour (“orange highlights”).
        found = {tone: lang.hex_color(match.group(1)) for tone in ('shadows', 'highlights')
                 for match in [re.search(rf'([a-z]+(?:\s[a-z]+)?)\s+{tone}', words)] if match}
        colors = [found.get('shadows') or '#1d7874', found.get('highlights') or '#f0a04b']
    scale = min(60, 25 * lang.LEVEL[edit['strength']])
    b.adjustment(index, {**edit, 'target': 'whole image'}, 'colorBalance',
                 {'shadows': balance(colors[0], scale, True), 'highlights': balance(colors[1], scale, True),
                  'preserveLuminosity': True}, 'Split tone')


@procedure('keep_one_color', 'Keep one color (color splash)', 'color', 'adjust',
           'black and white everywhere except one color, which stays (color = the color that stays, e.g. “keep only '
           'the red”)', area_safe=True, measures=('palette',),
           examples=('make everything black and white except the red',),
           requires=r'black (and|&) white|b&w|gr[ae]y|monochrome|desaturat|in colou?r|colou?r splash|splash|except|only|keep')
def keep_one_color(b, index, edit):
    color = lang.hex_color(edit['color'] or edit['object'])
    if not color or lang.color_family(color) in ('highlights', 'midtones', 'shadows'):
        b.blocking.append('Which color should stay, for example red or yellow?')
        return
    family = lang.color_family(color)
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'select.colorRange', {'select': family}, f'Select the {family}')
    sampled = (b.analysis.get('palette') or {}).get(family)
    if sampled:
        # The preset range selects strong reds only partly; the photo's own red, sampled where it
        # is most saturated, is added so it keeps its full colour (58% of it was kept without).
        b.add(index, 'select.colorRange', {'colors': sampled, 'fuzziness': 50, 'mode': 'add'},
              f'Add the photo’s own {family}')
    b.add(index, 'studio.require_selection', {'what': family, 'min_coverage': 0.001}, f'Check there are {family}')
    b.add(index, 'select.modify.feather', {'radius': 1}, 'Soften the edge')
    b.add(index, 'select.inverse', {}, 'Select every other color')
    b.add(index, 'layer.newAdjustmentLayer.blackWhite', {}, f'Black and white except the {family}')
    b.after_new_layer(index, f'Only the {family} in color')
    b.end_selection(index)


# Curve shapes a retoucher reaches for, as [input, output] points on 0..255.
CURVES = {
    's-curve': [[0, 0], [64, 52], [128, 128], [192, 204], [255, 255]],
    'strong s-curve': [[0, 0], [64, 44], [128, 128], [192, 212], [255, 255]],
    'faded': [[0, 30], [64, 72], [128, 130], [192, 190], [255, 238]],
    'brighter midtones': [[0, 0], [128, 150], [255, 255]],
    'darker midtones': [[0, 0], [128, 108], [255, 255]],
    'inverted s-curve': [[0, 0], [64, 76], [128, 128], [192, 180], [255, 255]],
}


@procedure('tone_curve', 'Tone curve', 'light', 'adjust',
           'a tone curve (choice = s-curve for punch, strong s-curve, faded/matte blacks, brighter midtones, darker '
           'midtones, inverted s-curve for a flat log look)', options=tuple(CURVES), area_safe=True,
           examples=('add an S curve', 'fade the blacks'))
def tone_curve(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    if re.search(r'fad|matte|lift(ed)? (the )?blacks|milky', words):
        shape = 'faded'
    elif re.search(r'invert|flat|log\b', words):
        shape = 'inverted s-curve'
    elif re.search(r'(bright|lift|open)\w* (the )?mid', words):
        shape = 'brighter midtones'
    elif re.search(r'dark\w* (the )?mid|deepen (the )?mid', words):
        shape = 'darker midtones'
    else:
        shape = 'strong s-curve' if edit['strength'] == 'strong' else 's-curve'
    b.adjustment(index, edit, 'curves', {'points': CURVES[shape]}, f'Tone curve: {shape}')


@procedure('color_filter', 'Photo filter', 'color', 'adjust',
           'photo filter: warm, cool, sepia or a colored filter (color or choice)', area_safe=True,
           options=tuple(lang.FILTERS), examples=('add a warming filter',))
def color_filter(b, index, edit):
    words = (edit['choice'] + ' ' + edit['color'] + ' ' + edit['quote']).lower()
    chosen = next((lang.FILTERS[key] for key in lang.FILTERS if re.search(rf'\b{key}', words)), None)
    density = round(lang.amount({**edit, 'direction': 'increase'}, 25, 1, 100))
    params = {'filter': chosen, 'density': density} if chosen else {
        'color': lang.hex_color(edit['color']) or '#ff9d3c', 'density': density}
    b.adjustment(index, edit, 'photoFilter', params, lang.short_label(edit))


@procedure('auto_fix', 'Automatic correction (measured)', 'correct', 'adjust',
           'automatic correction measured from the photo: choice = tone (auto levels), contrast, or color (white '
           'balance, color cast)', options=('tone', 'contrast', 'color'), measures=('levels',), area_safe=True,
           examples=('auto levels', 'remove the yellow color cast'))
def auto_fix(b, index, edit):
    """Auto Tone, Auto Contrast and Auto Color as an editable Levels layer, from the measured histogram."""
    levels = b.analysis.get('levels')
    if not levels:
        b.blocking.append('The photo could not be measured for an automatic correction.')
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
    b.adjustment(index, edit, 'levels', params, name)


BW_MIX = {'high contrast': {'reds': 70, 'yellows': 90, 'greens': 10, 'cyans': 20, 'blues': -20, 'magentas': 60},
          'infrared': {'reds': 10, 'yellows': 160, 'greens': 200, 'cyans': 40, 'blues': -60, 'magentas': 30},
          # A red filter on black-and-white film: dark skies, bright skin.
          'red filter': {'reds': 120, 'yellows': 110, 'greens': -10, 'cyans': -50, 'blues': -60, 'magentas': 80}}


@procedure('black_and_white', 'Black and white', 'look', 'adjust',
           'black and white (choice: neutral, high contrast, infrared, red filter; color = tint)',
           options=('neutral',) + tuple(BW_MIX), area_safe=True, examples=('make it black and white',))
def black_and_white(b, index, edit):
    style = next((key for key in BW_MIX if key in (edit['choice'] + ' ' + edit['quote']).lower()), None)
    params = dict(BW_MIX.get(style, {}))
    tint = lang.hex_color(edit['color'])
    if tint and tint not in ('#000000', '#ffffff'):
        params.update(tint=True, tintColor=tint)
    b.adjustment(index, edit, 'blackWhite', params, 'Black & white' + (f' ({style})' if style else ''))


@procedure('sepia', 'Sepia', 'look', 'adjust', 'sepia toned black and white', area_safe=True)
def sepia(b, index, edit):
    b.adjustment(index, edit, 'blackWhite', {'tint': True, 'tintColor': '#a3845c'}, 'Sepia tone')


@procedure('duotone', 'Duotone', 'look', 'adjust', 'two-color gradient map (color = "dark color and light color")',
           area_safe=True)
def duotone(b, index, edit):
    names = re.split(r'\band\b|,|/|\bto\b', edit['color'] or edit['choice'])
    colors = [c for c in (lang.hex_color(n) for n in names) if c]
    if len(colors) < 2:
        colors = (colors + ['#14213d', '#fcd116'])[:2]
    colors.sort(key=lang.luminance)
    b.adjustment(index, edit, 'gradientMap', {'stops': [[0, colors[0]], [1, colors[1]]]}, 'Duotone')


@procedure('invert', 'Invert', 'effect', 'adjust', 'invert colors (negative)', area_safe=True)
def invert(b, index, edit):
    b.adjustment(index, edit, 'invert', {}, 'Invert')


# Seasons by Hue/Saturation ranges: hue moves (degrees) and saturation changes per color range.
SEASONS = {
    # Foliage greens turn to gold and orange; yellows only a little, or warm rock and sand turn red
    # (a −18° yellows shift did, measured 2026-10-12).
    'autumn': {'greens': {'hue': -50, 'saturation': 15}, 'yellows': {'hue': -6, 'saturation': 8}},
    'spring': {'greens': {'hue': -8, 'saturation': 25}, 'yellows': {'hue': 8, 'saturation': 15}},
    'summer': {'greens': {'saturation': 20}, 'blues': {'saturation': 25}, 'yellows': {'saturation': 10}},
    'winter': {'greens': {'saturation': -35}, 'yellows': {'saturation': -30}, 'blues': {'hue': 5, 'saturation': 10},
               'reds': {'saturation': -15}},
}


FOLIAGE = 'the trees, bushes and plants'
# Inside the foliage's own outline, olive leaves (the yellow-green end of the yellows) can turn too;
# over the whole picture the same yellows shift turned warm rock red (measured 2026-10-12).
FOLIAGE_SEASONS = {
    # Rock caught at the edge of a bush's outline reddened at a −22° yellows shift (2026-10-12).
    'autumn': {'greens': {'hue': -55, 'saturation': 15}, 'yellows': {'hue': -12, 'saturation': 12}},
    'spring': {'greens': {'hue': -8, 'saturation': 25}, 'yellows': {'hue': 10, 'saturation': 15}},
}


def season_finds(edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    return [FOLIAGE] if edit['target'] == 'whole image' and re.search(r'autumn|fall|spring', words) else []


@procedure('season', 'Change the season’s colors', 'color', 'adjust',
           'shift the foliage and sky colors toward a season (choice = autumn, spring, summer or winter)',
           options=tuple(SEASONS), area_safe=True, finds=season_finds, examples=('make the trees look autumnal',),
           requires=r'autumn|fall|spring|summer|winter|season|foliage')
def season(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    name = next((key for key in SEASONS if key in words), 'autumn' if re.search(r'fall|autumn', words) else None)
    if name is None:
        b.blocking.append('Which season: autumn, spring, summer or winter?')
        return
    scale = min(lang.LEVEL[edit['strength']], 1.5)
    recipe = SEASONS[name]
    if name in FOLIAGE_SEASONS and edit['target'] == 'whole image':
        _, foliage = b.target_boxes({**edit, 'target': 'object', 'object': FOLIAGE})
        if foliage:
            # The foliage is found and outlined, and only it changes season.
            edit, recipe = {**edit, 'target': 'object', 'object': FOLIAGE}, FOLIAGE_SEASONS[name]
    params = {family: {key: max(-180, min(180, round(value * scale))) for key, value in change.items()}
              for family, change in recipe.items()}
    b.adjustment(index, edit, 'hueSaturation', params, f'{name.capitalize()} colors')
    if name == 'winter':
        b.adjustment(index, {**edit, 'target': 'whole image'}, 'photoFilter', {'filter': 'cooling80', 'density': 15},
                     'Winter cool')

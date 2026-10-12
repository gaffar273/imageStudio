"""Raw development: Camera Raw settings on the whole photo (one merged, editable smart filter) or
on a masked copy for one area, plus measured exposure correction and graduated filters.

PhotoCraft's Camera Raw scales are gentle (temperature 7.5 moved skin by 2.6 of 255), so the
base amounts in photocraft_intents.RAW were measured to be visible at “slightly”.
"""

import math
import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure

LABELS = {
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
}
CATEGORY = {'exposure': 'light', 'highlights': 'light', 'shadows': 'light', 'whites': 'light', 'blacks': 'light',
            'clarity': 'light', 'texture': 'correct', 'dehaze': 'light', 'temperature': 'color', 'tint': 'color',
            'sharpen': 'correct', 'noise_reduction': 'correct', 'grain': 'effect', 'vignette': 'effect'}


def develop(b, index, edit):
    name, base, low, high = lang.RAW[edit['action']]
    signed = edit['action'] not in ('sharpen', 'noise_reduction', 'grain')
    action = edit['action']
    if action == 'vignette':
        lighten = edit['direction'] == 'increase' and re.search(r'white|light', edit['quote'], re.IGNORECASE)
        value = lang.amount({**edit, 'direction': 'increase' if lighten else 'decrease'}, abs(base), low, high)
        params = {name: value}
    elif action == 'shadows' and edit['direction'] == 'none':
        params = {name: lang.amount({**edit, 'direction': 'increase'}, base, low, high)}
    elif action == 'highlights' and edit['direction'] == 'none':
        params = {name: lang.amount({**edit, 'direction': 'decrease'}, base, low, high)}
    elif action == 'noise_reduction':
        level = lang.amount(edit, base, low, high, signed=False)
        noise = b.analysis.get('noise')
        if edit['value'] is None and edit['strength'] == 'moderate' and noise is not None:
            # Measured: the grain left after removing the picture's own detail, in levels of 255.
            level = round(max(15, min(70, noise * 9)))
        params = {'noiseLuminance': level, 'noiseColor': min(100, round(level * 0.8))}
    elif action == 'grain':
        params = {name: lang.amount(edit, base, low, high, signed=False),
                  'grainSize': 35 if 'coarse' in edit['quote'].lower() else 25}
    elif action == 'texture' and re.search(r'smooth|soften|skin', edit['quote'], re.IGNORECASE):
        params = {name: -abs(lang.amount(edit, base, low, high, signed=False))}
    else:
        params = {name: lang.amount(edit, base, low, high, signed)}
    apply(b, index, edit, params)


def apply(b, index, edit, params, label=None):
    """Whole picture: joins the one Camera Raw filter on the photo. A part: a masked copy."""
    if edit['target'] in ('whole image', 'layer'):
        current = b.raw.setdefault(index, {})
        for key, value in params.items():
            current[key] = current.get(key, 0) + value
        return True
    label = label or lang.short_label(edit)
    return b.local_develop(index, edit, params, label, f'{label} on its own masked layer')


for _action, _label in LABELS.items():
    procedure(_action, _action.replace('_', ' ').capitalize(), CATEGORY[_action], 'develop', _label,
              area_safe=True, measures=('noise',) if _action == 'noise_reduction' else ())(develop)


def exposure_correction(stats, target=0.45):
    """Camera Raw settings that bring a badly exposed photo back, from its measured luminance:
    the exposure that moves the median to `target` (in linear light, so one stop is a doubling),
    highlight recovery when a real share of the top is clipped, and shadow lift when the bottom is
    crushed. Empty when the photo is already well exposed.

    A lamp or a window in shot is a few percent of clipped pixels and is not a reason to pull every
    highlight down: a −39 highlights pull for a 1% lamp greyed a lamp-lit wall (measured 2026-10-12)."""
    median, low, high = stats['median'], stats['p02'], stats['p98']
    linear = lambda v: ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92  # noqa: E731
    stops = math.log2(linear(target) / max(linear(median), 1e-4))
    stops = max(-2.0, min(2.0, stops * 0.8))  # a little short of the full way: medians of dark scenes are low
    params = {}
    if abs(stops) >= 0.15:
        params['exposure'] = round(stops, 2)
    if stats['clipped_high'] > 0.04 or (stops > 0.5 and high > 0.92):
        params['highlights'] = -round(min(70, 20 + stats['clipped_high'] * 400))
    if stats['clipped_low'] > 0.03 or (stops < -0.3 and low < 0.06):
        params['shadows'] = round(min(60, 20 + stats['clipped_low'] * 500))
    if not params and high - low < 0.55:
        # Exposed fine but flat (fog, a backlit haze): spread the tones instead.
        params = {'contrast': 15, 'dehaze': 10, 'blacks': -10, 'whites': 10}
    return params


# Where the middle tone of a well-exposed photo sits: a normal photo, and the bright, open look
# of interiors, high-key portraits and product shots.
EXPOSURE_TARGETS = {'normal': 0.45, 'bright': 0.56}


@procedure('exposure_fix', 'Fix the exposure (measured)', 'correct', 'develop',
           'fix a photo that is too dark, too bright, underexposed, overexposed or flat: the correction is measured '
           'from its histogram (choice = normal, or bright for interiors and high-key)',
           options=tuple(EXPOSURE_TARGETS), measures=('exposure',), area_safe=True,
           examples=('this photo is too dark', 'fix the overexposed photo'))
def exposure_fix(b, index, edit):
    stats = b.analysis.get('exposure')
    if not stats:
        b.blocking.append('The photo could not be measured for an exposure correction.')
        return
    words = edit['quote'].lower()
    bright = 'bright' in edit['choice'].lower() or re.search(r'high[\s-]?key|bright and airy', words)
    params = exposure_correction(stats, EXPOSURE_TARGETS['bright' if bright else 'normal'])
    # The person's own direction wins when the measurement disagrees (“make it darker” on a mid photo).
    if re.search(r'too (dark|dim)|underexposed|brighter|lighten', words) and params.get('exposure', 0) <= 0:
        params['exposure'] = 0.5 * lang.LEVEL[edit['strength']]
        params.pop('highlights', None)
    elif re.search(r'too (bright|light)|overexposed|blown|darker', words) and params.get('exposure', 0) >= 0:
        params['exposure'] = -0.5 * lang.LEVEL[edit['strength']]
        params['highlights'] = min(params.get('highlights', 0), -40)
    if not params:
        b.notes.append(f'The exposure is already balanced (measured: middle tone {stats["median"]:.0%}, little '
                       'clipping), so it was not changed.')
        return
    apply(b, index, edit, params, 'Exposure corrected (measured)')


def soft_band(b, index, edge, depth=0.5):
    """Select a band from one edge of the frame that fades out toward the middle. The rectangle
    reaches past the frame on the outer sides, so the feather fades only inward. Returns the band
    (x, y, w, h) inside the frame."""
    w, h = b.canvas.width, b.canvas.height
    x, y, rw, rh = {'top': (0, 0, w, h * depth), 'bottom': (0, h * (1 - depth), w, h * depth),
                    'left': (0, 0, w * depth, h), 'right': (w * (1 - depth), 0, w * depth, h)}[edge]
    f = round((rh if edge in ('top', 'bottom') else rw) * 0.45)
    gx, gy, gw, gh = {'top': (-f, -f, w + 2 * f, rh + f), 'bottom': (-f, y, w + 2 * f, rh + f),
                      'left': (-f, -f, rw + f, h + 2 * f), 'right': (x, -f, rw + f, h + 2 * f)}[edge]
    b.add(index, 'select.rect', {'x': round(gx), 'y': round(gy), 'width': round(gw), 'height': round(gh),
                                 'feather': f}, f'Soft band from the {edge}')
    b.add(index, 'studio.require_selection', {'what': f'{edge} band', 'min_coverage': 0.02}, 'Check the band')
    return x, y, rw, rh


@procedure('graduated_filter', 'Graduated filter', 'light', 'adjust',
           'a graduated (ND) filter: darken and deepen one edge of the frame, usually the sky at the top (position = '
           'the edge; strength)', area_safe=False, examples=('add a graduated filter to darken the sky',),
           requires=r'graduat|\bnd\b|gradient|sky|top|edge|darken')
def graduated_filter(b, index, edit):
    """A real ND grad darkens evenly through its band and adds nothing else, so this is an Exposure
    adjustment layer masked by a soft band. Camera Raw's local operators (highlights, dehaze) on a
    masked copy were tried first: barely visible at −0.45 EV and they bend tones near hard edges."""
    w, h = b.canvas.width, b.canvas.height
    edge = (edit['position'] or 'top').split()[-1]
    if edge not in ('top', 'bottom', 'left', 'right'):
        edge = 'top'
    scale = min(lang.LEVEL[edit['strength']], 1.6)
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    x, y, rw, rh = soft_band(b, index, edge)
    stops = round(-0.9 * scale, 2)
    b.add(index, 'layer.newAdjustmentLayer.exposure', {'exposure': stops, 'gamma': 0.95},
          f'Graduated filter ({stops:g} EV from the {edge})')
    b.after_new_layer(index, f'Graduated filter · {edge}')
    b.end_selection(index)
    b.regions.append({'requirement': index, 'label': f'{edge} band', 'boxes': [[x / w, y / h, rw / w, rh / h]]})


@procedure('window_pull', 'Recover bright windows and highlights', 'light', 'adjust',
           'bring back detail in the brightest parts: blown windows, a white sky, lamps (real estate “window pull”)',
           examples=('the windows are blown out, bring back the view',),
           requires=r'window|blown|bright|highlight|view|lamp|recover|white')
def window_pull(b, index, edit):
    """A luminosity mask of the brightest tones carrying a Curves layer that bends only the top of
    the tonal range down. The curve is a global operation, so nothing glows around dark edges: a
    Camera Raw copy (highlights, dehaze) on the same mask left a bright ring around a cat in front
    of a lit wall (measured 2026-10-12)."""
    scale = min(lang.LEVEL[edit['strength']], 1.6)
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'select.colorRange', {'select': 'highlights'}, 'Select the brightest tones')
    b.add(index, 'studio.require_selection', {'what': 'bright area', 'min_coverage': 0.002},
          'Check there are bright areas')
    pull = round(28 * scale)
    b.add(index, 'layer.newAdjustmentLayer.curves',
          {'points': [[0, 0], [150, 150], [215, 215 - round(pull * 0.6)], [255, 255 - pull]]},
          f'Pull the brightest tones down (white point {255 - pull})')
    b.after_new_layer(index, 'Recovered highlights')
    b.end_selection(index)


@procedure('backlit_fix', 'Fix a backlit subject', 'correct', 'develop',
           'a subject in shadow against a bright background (backlit, against the light, silhouette that should not '
           'be): lift the subject, hold the background', whole_picture=True,
           finds=lambda edit: [lang.subject_query({**edit, 'target': 'main subject'})],
           examples=('the person is too dark against the bright sky',),
           requires=r'backlit|back-lit|against the|silhouette|too dark|in (the )?shadow|dark')
def backlit_fix(b, index, edit):
    """Two masked Camera Raw layers, the way a retoucher balances a backlit shot: the subject's
    outline is lifted (exposure and shadows), everything else has its highlights held back."""
    scale = min(lang.LEVEL[edit['strength']], 1.6)
    subject = {**edit, 'target': 'object' if edit['object'] else 'main subject'}
    if not b.local_develop(index, subject, {'exposure': round(0.55 * scale, 2), 'shadows': round(45 * scale),
                                            'blacks': round(8 * scale), 'clarity': round(6 * scale)},
                           'Lifted from the backlight · subject', 'Lift the subject out of the shadow (masked layer)'):
        return
    b.local_develop(index, {**subject, 'target': 'background', 'object': lang.subject_query(subject)},
                    {'highlights': round(-45 * scale), 'whites': round(-15 * scale), 'dehaze': round(8 * scale)},
                    'Held highlights · background', 'Hold back the bright background (masked layer)')

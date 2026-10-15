"""Developing a camera photo the way a retoucher does, every setting measured from the photo.

A DSLR or raw file comes off the camera flat, a little dark, with the light's colour cast, grain
and soft capture. A retoucher reads it (the greys, the ends of the histogram, the colour, the
grain, the horizon) and develops it in a fixed order: white balance, black and white points and
midtones, contrast, colour, noise, sharpening, then a level horizon and a subtle vignette. Each
step here reads one reading of the photo (``read``) and does nothing, with a note saying what it
measured, when the photo does not need it. The settings of consecutive steps join one editable
Camera Raw filter, as one develop in Lightroom would. PhotoCraft does every pixel edit; ``read``
only previews the white balance and the curve on a small copy to decide the colour and contrast
that follow them.

What the measurements showed (PhotoCraft, 2026-10-15; nine photos given a camera file's faults
of known size: 0.6 EV under, flat, a cast, washed out, soft, grainy):

- Whites +40 moved a flat photo's brightest tones from 0.694 to 0.697: the slider only reaches
  tones already near the top. Camera Raw's point curve sets black and white points exactly
  ([[40, 0], [175, 255]] put the 98th percentile at 0.96 as computed) and runs after exposure.
- Aiming every photo's middle tone at 45% darkened white-backdrop shots by up to 0.8 EV, so the
  midtones are only ever lifted, never pulled down unless highlights clip.
- White balance: of six ways to read the light's colour, the greyest midtones, the brightest
  near-neutrals and the white patch each misread some originals by up to 16° (warm skin, sand).
  Combining the three and correcting less when they disagree left 1.65° of cast on average
  (the greyest midtones alone: 2.49°) and misread no original by more than 2.3°.
- Grain adds false colour to grey pixels, so colour is judged on a 256 px copy.
- Sharpening 80 without masking raised the grain of a noisy photo by half; with masking 50 the
  edges gained as much and the grain did not rise.
- Vignette −25 darkened the corners by 29% and the ring halfway out by 23%; −10 at midpoint 25
  darkened the corners by about 13% and left the middle alone.
"""

import math

import numpy as np

from image_studio.pipelines.core import procedure

CONTRAST_PER_UNIT = 0.0006  # luminance spread per Camera Raw contrast unit (contrast 30 → +0.018)
VIBRANCE_PER_UNIT = 0.0012  # saturation of the coloured pixels per vibrance unit
AIMS = {'mid': 0.40, 'spread': 0.21, 'colour': 0.38}


def _luma(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _saturation(a):
    high = a.max(axis=-1)
    return (high - a.min(axis=-1)) / np.maximum(high, 1e-3)


def _unit(e):
    return e / np.linalg.norm(e)


def _angle(u, v):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(_unit(u), _unit(v)))))))


def light_colour(a):
    """The colour of the light, three ways: the greyest quarter of the midtones, the brightest
    near-neutrals, the brightest 1% (white patch). None for a reading without enough pixels."""
    luma, sat = _luma(a), _saturation(a)
    unclipped = a.max(axis=-1) < 0.98
    readings = []
    mid = (luma > 0.15) & (luma < 0.9)
    if mid.sum() > 0.05 * luma.size:
        greys = mid & (sat <= max(0.04, float(np.percentile(sat[mid], 25))))
        readings.append(np.median(a[greys], axis=0) if greys.sum() > 0.03 * luma.size else None)
    bright = unclipped & (luma > np.percentile(luma, 60))
    if bright.sum() > 0.02 * luma.size:
        neutral = bright & (sat <= np.percentile(sat[bright], 30))
        readings.append(a[neutral].mean(axis=0))
    pixels = a[unclipped]
    if len(pixels) > 0.2 * luma.size:
        total = pixels.sum(axis=1)
        readings.append(pixels[total >= np.percentile(total, 99)].mean(axis=0))
    return [r for r in readings if r is not None and r.min() > 0.02]


def white_balance(a):
    """(gains for red, green, blue with green 1, how far the readings disagree in degrees, the
    share of the correction applied, the cast in words). The readings are averaged; when they
    disagree by more than 3° the scene's own colours are ambiguous and less is corrected, none past
    10°. The cast is split the way a white-balance control is: temperature (blue to amber), of which
    40% of a warm cast is kept as lamp light and late sun are part of the picture, and tint (green
    to magenta), which is always corrected (a green cast once read as warm and was only 60% fixed)."""
    readings = [_unit(r) for r in light_colour(a)]
    if len(readings) < 2:
        return None
    red, green, blue = np.mean(np.log(readings), axis=0)
    spread = max(_angle(u, v) for u in readings for v in readings)
    share = max(0.0, min(1.0, (10 - spread) / 7))
    temperature = (red - blue) / 2  # > 0: warm light
    tint = green - (red + blue) / 2  # > 0: green light
    kept = share * (0.6 if temperature > 0 else 1.0)
    t, m = temperature * kept, tint * share
    light = np.exp([t - m / 3, 2 * m / 3, -t - m / 3])
    gains = light[1] / light
    words = [word for word, size in (('warm' if temperature > 0 else 'cool', abs(temperature)),
                                     ('green' if tint > 0 else 'magenta', abs(tint))) if size > 0.01]
    return [round(float(g), 4) for g in gains], round(spread, 2), round(kept, 2), ' and '.join(words) or 'neutral'


def curve(points):
    """A Camera Raw point curve (0..255) as a function on 0..1."""
    xs, ys = zip(*points)
    return lambda v: np.interp(v * 255, xs, ys) / 255


def channel_curve(gain):
    """A channel's curve that multiplies it by gain (what a white-balance dropper does)."""
    return [[0, 0], [255, round(255 * gain)]] if gain <= 1 else [[0, 0], [round(255 / gain), 255]]


def read(image):
    """Every decision of the develop, from one look at the photo: {step: (settings, note)}. Kept on
    the image, as the plan and each step's check read the same photo (half the apply time went on
    reading it again, measured)."""
    if '_develop' not in image.info:
        image.info['_develop'] = _read(image)
    return image.info['_develop']


def _read(image):
    small = image.convert('RGB')
    small.thumbnail((512, 512))
    a = np.asarray(small, dtype=np.float32) / 255
    plan = {}

    found = white_balance(a)
    if found is None:
        plan['white_balance'] = ({}, 'White balance: too few grey or white areas to read the light from, so it '
                                     'was left as shot.')
    else:
        gains, spread, share, cast = found
        if max(abs(g - 1) for g in gains) < 0.015:
            plan['white_balance'] = ({}, 'White balance: the greys and whites read neutral, so it was left as '
                                         'shot.')
        else:
            settings = {f'pointCurve{name}': channel_curve(gain)
                        for name, gain in zip(('Red', 'Green', 'Blue'), gains) if abs(gain - 1) >= 0.005}
            reason = (f'the readings disagreed by {spread:.0f}°' if spread > 3 else 'some warmth is the light’s '
                      'mood') if share < 0.99 else ''
            note = (f'White balance: the light read {cast} → red ×{gains[0]:.3f}, blue ×{gains[2]:.3f} against '
                    'green' + (f' ({share:.0%} of the warm shift corrected: {reason})' if reason else '') + '.')
            plan['white_balance'] = (settings, note)
            a = np.clip(a * np.array(gains, dtype=np.float32), 0, 1)

    luma = _luma(a)
    low, high, middle = (float(v) for v in np.percentile(luma, [0.5, 99.5, 50]))
    black = low if low > 0.04 else 0.0  # blacks at 2-4% are a finished photo's, not a fault
    white = high if high < 0.95 else 1.0
    if white - black < 1 / 1.8:  # never stretch the tones more than 1.8 times
        extra = (1 / 1.8 - (white - black)) / 2
        black, white = max(0.0, black - extra), min(1.0, white + extra)
    points = [[round(black * 255), 0], [round(white * 255), 255]]
    lifted = (middle - black) / max(white - black, 1e-3)
    said = []
    if black > 0:
        said.append(f'the darkest tones stopped at {low:.0%}')
    if white < 1:
        said.append(f'the brightest at {high:.0%}')
    if 0.12 <= lifted < AIMS['mid'] - 0.04:
        # Midtones lifted to about 40%: a dark night or low-key photo (middle under 12%) stays dark.
        points.insert(1, [round((black + lifted * (white - black)) * 255), round(AIMS['mid'] * 255)])
        said.append(f'the middle tone sat at {lifted:.0%}')
    tone = {'pointCurve': points} if said else {}
    clipped = float((luma >= 0.98).mean())
    if clipped > 0.02:
        tone['highlights'] = -round(min(70, 20 + clipped * 400))
        said.append(f'{clipped:.1%} is clipped white')
    if tone.get('pointCurve'):
        a = np.clip(np.stack([curve(points)(a[..., c]) for c in range(3)], axis=-1), 0, 1)
    spread = float(_luma(a).std())
    if spread < AIMS['spread'] - 0.02:
        tone['contrast'] = round(max(5, min(20, (AIMS['spread'] - spread) / CONTRAST_PER_UNIT)))
        said.append(f'the tones were still flat (spread {spread:.2f})')
    plan['tone'] = (tone, ('Tones: ' + '; '.join(said) + ' → ' + _describe(tone) + '.') if tone else
                    f'Tones: the black point, white point and midtones are already right (middle tone '
                    f'{middle:.0%}).')

    colour = small.copy()
    colour.thumbnail((256, 256))
    c = np.asarray(colour, dtype=np.float32) / 255
    if found is not None:
        c = np.clip(c * np.array(found[0], dtype=np.float32), 0, 1)
    if tone.get('pointCurve'):
        c = np.clip(np.stack([curve(points)(c[..., k]) for k in range(3)], axis=-1), 0, 1)
    sat, visible = _saturation(c), (_luma(c) > 0.1) & (_luma(c) < 0.95)
    coloured = visible & (sat > 0.1)
    if coloured.mean() < 0.05:
        plan['colour'] = ({}, 'Colour: the photo is almost without colour, so no vibrance was added.')
    else:
        level = float(sat[coloured].mean())
        if level >= AIMS['colour'] - 0.03:
            plan['colour'] = ({}, f'Colour: already rich (the coloured parts at {level:.0%} saturation), so no '
                                  'vibrance was added.')
        else:
            vibrance = round(max(5, min(25, (AIMS['colour'] - level) / VIBRANCE_PER_UNIT)))
            plan['colour'] = ({'vibrance': vibrance}, f'Colour: the coloured parts at {level:.0%} saturation → '
                                                      f'vibrance +{vibrance} (protects skin tones).')

    rows = luma.shape[0] // 4
    plan['sky'] = {'top': float(luma[:rows].mean()), 'rest': float(luma[rows:].mean())}
    # The frame's edge after the white balance and curve: a seamless studio backdrop is plain (its
    # tones spread 0.06 to 0.12 on the puppy and the mugs; every real scene measured 0.24 or more),
    # and a vignette on it shows as a spotlight behind the subject (seen on both, 2026-10-15).
    corrected = _luma(a)
    edge = max(2, round(min(corrected.shape) * 0.08))
    border = np.concatenate([corrected[:edge].ravel(), corrected[-edge:].ravel(), corrected[:, :edge].ravel(),
                             corrected[:, -edge:].ravel()])
    plan['border'] = {'spread': float(border.std()), 'white': float((border > 0.9).mean())}
    return plan


def preview(image, steps):
    """A small copy of the photo with only the named steps' white balance and curve, as the
    yardstick a check compares the developed photo against: a step is judged on what it added,
    not on the brightening the curve gave the whole picture."""
    plan = read(image)
    small = image.convert('RGB')
    small.thumbnail((512, 512))
    a = np.asarray(small, dtype=np.float32) / 255
    if 'white_balance' in steps:
        for channel, name in enumerate(('Red', 'Green', 'Blue')):
            points = plan['white_balance'][0].get(f'pointCurve{name}')
            if points:
                a[..., channel] = curve(points)(a[..., channel])
    points = plan['tone'][0].get('pointCurve') if 'tone' in steps else None
    if points:
        a = np.stack([curve(points)(a[..., c]) for c in range(3)], axis=-1)
    from PIL import Image

    return Image.fromarray(np.clip(a * 255, 0, 255).astype('uint8'))


def _describe(params):
    def one(key, value):
        if isinstance(value, list):
            return f'{key} {value}'
        return f'{key} {value:+g}'

    return ', '.join(one(key, value) for key, value in params.items())


def reading(b):
    found = b.analysis.get('develop')
    if not found:
        b.blocking.append('The photo could not be measured.')
    return found


def raw(b, index, params):
    """Join the develop's one Camera Raw filter (see develop.apply); curves replace, numbers add."""
    current = b.raw.setdefault(index, {})
    for key, value in params.items():
        current[key] = value if isinstance(value, list) else round(current.get(key, 0) + value, 2)


# How much of each measured correction is applied. Moderate is the measured develop; a “too much”
# or “more” afterwards (photocraft_followup) moves a step down or up, as a retoucher dials a whole
# develop back or pushes it.
SHARE = {'subtle': 0.6, 'moderate': 1.0, 'strong': 1.4}
AMOUNTS = ('contrast', 'vibrance', 'highlights', 'noiseLuminance', 'noiseColor', 'sharpenAmount', 'vignetteAmount')


def scaled(settings, share):
    """Settings with `share` of their correction: amounts scaled, curves blended toward no change."""
    if share == 1:
        return settings
    result = {}
    for key, value in settings.items():
        if isinstance(value, list):
            result[key] = [[x, max(0, min(255, round(x + share * (y - x))))] for x, y in value]
        elif key in AMOUNTS:
            result[key] = round(value * share, 2)
        else:
            result[key] = value
    return result


def _share(edit):
    return SHARE.get(edit.get('strength'), 1.0)


def _step(b, index, name, edit):
    found = reading(b)
    if not found:
        return
    settings, note = found[name]
    if settings:
        raw(b, index, scaled(settings, _share(edit)))
    b.notes.append(note if _share(edit) == 1 or not settings else f'{note} ({_share(edit):.0%} of it, as asked)')


@procedure('develop_white_balance', 'White balance (measured from the greys and whites)', 'correct', 'develop',
           'neutral white balance read from the greys and whites of the photo', measures=('develop',), menu=False)
def develop_white_balance(b, index, edit):
    _step(b, index, 'white_balance', edit)


@procedure('develop_tone', 'Black point, white point and midtones (measured)', 'correct', 'develop',
           'set the black and white points, lift dark midtones and add contrast to a flat photo, from its histogram',
           measures=('develop',), menu=False)
def develop_tone(b, index, edit):
    _step(b, index, 'tone', edit)


@procedure('develop_color', 'Colour (measured)', 'color', 'develop',
           'bring a washed-out photo’s colour to life with vibrance, measured after its white balance and tones',
           measures=('develop',), menu=False)
def develop_color(b, index, edit):
    _step(b, index, 'colour', edit)


@procedure('develop_noise', 'Noise reduction (measured)', 'correct', 'develop',
           'reduce sensor noise by as much as was measured, keeping detail', measures=('develop',), menu=False)
def develop_noise(b, index, edit):
    found = reading(b)
    if not found:
        return
    noise = found.get('noise')
    if noise is None or noise < 1.8:
        b.notes.append('Noise: the flat areas measured clean' + (f' (grain {noise:.1f} of 255)' if noise else '')
                       + ', so no noise reduction (it would only soften detail).')
        return
    luminance = round(max(15, min(50, 10 * noise)))
    color = round(max(20, min(50, 12 * noise)))
    raw(b, index, scaled({'noiseLuminance': luminance, 'noiseColor': color}, _share(edit)))
    b.notes.append(f'Noise: grain measured {noise:.1f} of 255 in the flat areas → luminance noise reduction '
                   f'{luminance}, colour {color}.')


@procedure('develop_sharpen', 'Capture sharpening (masked)', 'correct', 'develop',
           'capture sharpening on the edges only, masked away from flat areas so grain is not sharpened',
           measures=('develop',), menu=False)
def develop_sharpen(b, index, edit):
    found = reading(b)
    if not found:
        return
    noise = found.get('noise') or 0
    # Grainier photos are masked more, so the edges are sharpened and the grain is not. The amount
    # stays: the grain is already reduced before sharpening, and turning it down as well left a
    # grainy photo's edges only 1.5% crisper (measured).
    masking = round(max(40, min(80, 40 + 10 * noise)))
    amount = 40
    raw(b, index, scaled({'sharpenAmount': amount, 'sharpenRadius': 1.0, 'sharpenDetail': 25,
                          'sharpenMasking': masking}, _share(edit)))
    b.notes.append(f'Sharpening: amount {amount}, masking {masking} (edges only, so the grain stays down).')


@procedure('develop_vignette', 'Finishing vignette (subtle)', 'effect', 'develop',
           'a subtle darkening of the corners that keeps the eye in the picture', measures=('develop',), menu=False)
def develop_vignette(b, index, edit):
    found = reading(b)
    if not found:
        return
    border = found['border']
    if border['spread'] < 0.15 or border['white'] > 0.3:
        b.notes.append('Vignette: the edges are a plain backdrop, so none was added (it would show as a spotlight '
                       'behind the subject).')
        return
    raw(b, index, scaled({'vignetteAmount': -10, 'vignetteMidpoint': 25}, _share(edit)))
    b.notes.append('Vignette: corners 10 darker, the middle untouched, to hold the eye in the picture.')


@procedure('develop_sky', 'Balance a bright sky (measured)', 'light', 'adjust',
           'a soft graduated filter when the top of the frame is much brighter than the rest',
           measures=('develop',), menu=False)
def develop_sky(b, index, edit):
    from image_studio.pipelines.library.develop import graduated_filter

    found = reading(b)
    if not found:
        return
    top, rest = found['sky']['top'], found['sky']['rest']
    if top - rest < 0.15 or top < 0.6 or found['border']['spread'] < 0.15:
        b.notes.append(f'Sky: the top of the frame is not much brighter than the rest ({top:.0%} against {rest:.0%}), '
                       'so no graduated filter.')
        return
    # One step gentler than the develop: subtle for the measured develop, moderate when pushed.
    gentler = {'strong': 'moderate'}.get(edit['strength'], 'subtle')
    graduated_filter(b, index, {**edit, 'position': 'top', 'strength': gentler})
    b.notes.append(f'Sky: the top of the frame measured {top:.0%} against {rest:.0%} below, so a soft graduated '
                   'filter brings it down.')


@procedure('develop_level', 'Level the horizon (measured)', 'framing', 'geometry',
           'level a horizon that is measurably tilted (between half a degree and four degrees)',
           measures=('tilt',), menu=False)
def develop_level(b, index, edit):
    from image_studio.pipelines.library.framing import rotate

    tilt = b.analysis.get('tilt')
    if tilt is None:
        b.notes.append('Horizon: no long straight horizontal line to measure, so the frame was left as shot.')
        return
    if abs(tilt) < 0.5:
        b.notes.append(f'Horizon: level within half a degree ({tilt:+.1f}°), so the frame was left as shot.')
        return
    if abs(tilt) > 4:
        b.notes.append(f'Horizon: the strongest lines lean {tilt:+.1f}°, more than a camera tilt usually is, so it '
                       'was left as shot. Ask to straighten it if it should be level.')
        return
    rotate(b, index, {**edit, 'value': tilt, 'choice': '', 'quote': ''}, straighten=True)  # tilt = clockwise turn
    b.notes.append(f'Horizon: measured {tilt:+.1f}° off level, so it was straightened and the empty corners cropped.')

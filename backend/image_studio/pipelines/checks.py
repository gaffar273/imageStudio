"""Measured checks: after a pipeline runs, numbers from the rendered pixels say whether it did
what it promised. The language model's visual review comes second and is labelled fallible.

Each check reads the before and after renders and the boxes of what the pipeline worked on
(normalized 0..1 in the final picture, plus pairs mapping original to final positions), and
returns {'requirement', 'check', 'passed', 'measured'} records.
"""

import numpy as np


def _rgb(image):
    return np.asarray(image.convert('RGB'), dtype=np.float32) / 255


def _luma(image):
    rgb = _rgb(image)
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _hsv(image):
    hsv = np.asarray(image.convert('RGB').convert('HSV'), dtype=np.float32)
    return hsv[..., 0] * 360 / 255, hsv[..., 1] / 255, hsv[..., 2] / 255


def _mask(shape, boxes):
    height, width = shape
    inside = np.zeros(shape, dtype=bool)
    for x, y, w, h in boxes:
        inside[max(0, round(y * height)):round((y + h) * height), max(0, round(x * width)):round((x + w) * width)] = True
    return inside


def _record(index, text, passed):
    return {'requirement': index, 'check': f'Measured: {text}', 'passed': bool(passed), 'measured': True}


def exposure_fix(index, edit, before, after, boxes, pairs, geometry):
    import re

    old, new = float(np.median(_luma(before))), float(np.median(_luma(after)))
    if abs(old - new) < 0.004:
        return []  # left alone as already balanced; the plan says so
    words = edit['quote'].lower()
    if re.search(r'too (dark|dim)|underexposed|brighter|lighten', words):
        return [_record(index, f'middle tone {old:.0%} → {new:.0%} (asked brighter)', new > old + 0.01)]
    if re.search(r'too (bright|light)|overexposed|blown|darker', words):
        return [_record(index, f'middle tone {old:.0%} → {new:.0%} (asked darker)', new < old - 0.01)]
    target = 0.56 if 'bright' in edit['choice'].lower() else 0.45
    return [_record(index, f'middle tone {old:.0%} → {new:.0%} (the aim is about {target:.0%})',
                    abs(new - target) < abs(old - target))]


def tone_curve(index, edit, before, after, boxes, pairs, geometry, others=()):
    if geometry or set(others) & {'black_and_white', 'look', 'exposure_fix', 'auto_fix', 'contrast', 'brightness',
                                  'exposure', 'shadows', 'highlights', 'whites', 'blacks', 'clarity', 'dehaze'}:
        return []
    old, new = _luma(before), _luma(after)
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    if any(word in words for word in ('fad', 'matte', 'flat', 'invert', 'log')):
        return [_record(index, f'shadows lifted, contrast {old.std():.3f} → {new.std():.3f}',
                        new.std() < old.std() and np.percentile(new, 2) > np.percentile(old, 2))]
    if 'mid' in words:
        rising = 'bright' in words or 'lift' in words or 'open' in words
        a, b = float(np.median(old)), float(np.median(new))
        return [_record(index, f'midtones {a:.0%} → {b:.0%}', b > a if rising else b < a)]
    return [_record(index, f'contrast {old.std():.3f} → {new.std():.3f}', new.std() > old.std() + 0.003)]


def graduated_filter(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    edge = (edit['position'] or 'top').split()[-1]
    old, new = _luma(before), _luma(after)
    height, width = old.shape
    band = {'top': np.s_[:height // 4], 'bottom': np.s_[-height // 4:], 'left': np.s_[:, :width // 4],
            'right': np.s_[:, -width // 4:]}.get(edge, np.s_[:height // 4])
    far = {'top': np.s_[-height // 4:], 'bottom': np.s_[:height // 4], 'left': np.s_[:, -width // 4:],
           'right': np.s_[:, :width // 4]}.get(edge, np.s_[-height // 4:])
    near_change = float(new[band].mean() - old[band].mean())
    far_change = float(new[far].mean() - old[far].mean())
    # Relative to the opposite edge: other edits in the plan may brighten or darken everything.
    return [_record(index, f'the {edge} edge darkened by {-near_change:.1%}, the opposite edge by {-far_change:.1%}',
                    near_change < far_change - 0.015)]


def window_pull(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    old, new = _luma(before), _luma(after)
    brightest = old >= np.percentile(old, 97)
    a, b = float(old[brightest].mean()), float(new[brightest].mean())
    return [_record(index, f'the brightest 3% went {a:.0%} → {b:.0%}', b < a - 0.01)]


FAMILIES = {'reds': (340, 20), 'yellows': (20, 75), 'greens': (75, 160), 'cyans': (160, 200), 'blues': (170, 275),
            'magentas': (275, 340)}


def _in_family(hue, family):
    low, high = FAMILIES[family]
    return ((hue >= low) | (hue < high)) if low > high else ((hue >= low) & (hue < high))


def keep_one_color(index, edit, before, after, boxes, pairs, geometry):
    from image_studio.integrations import photocraft_intents as lang

    color = lang.hex_color(edit['color'] or edit['object'])
    if geometry or not color:
        return []
    family = lang.color_family(color)
    if family not in FAMILIES:
        return []
    hue_b, sat_b, _ = _hsv(before)
    hue_a, sat_a, _ = _hsv(after)
    kept = _in_family(hue_b, family) & (sat_b > 0.3)
    others = ~_in_family(hue_b, family) & (sat_b > 0.2)
    rest = float((sat_a[others] > 0.15).mean()) if others.any() else 0.0
    stayed = float(np.median(sat_a[kept]) / max(1e-3, np.median(sat_b[kept]))) if kept.any() else 1.0
    return [_record(index, f'{rest:.0%} of the other colors still show color; the {family} keep {stayed:.0%} of '
                           'their saturation', rest < 0.15 and stayed > 0.6)]


def split_tone(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    old, new = _rgb(before), _rgb(after)
    luma = _luma(before)
    shift = new - old
    warm = shift[..., 0] - shift[..., 2]  # toward red/orange is positive, toward blue/teal negative
    shadows, highlights = luma < np.percentile(luma, 30), luma > np.percentile(luma, 70)
    a, b = float(warm[shadows].mean()), float(warm[highlights].mean())
    return [_record(index, f'shadows and highlights were tinted apart (warmth change {a:+.3f} in the shadows, '
                           f'{b:+.3f} in the highlights)', abs(a - b) > 0.01)]


def season(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    hue_b, sat_b, _ = _hsv(before)
    hue_a, sat_a, _ = _hsv(after)
    greens_b = float((_in_family(hue_b, 'greens') & (sat_b > 0.15)).mean())
    greens_a = float((_in_family(hue_a, 'greens') & (sat_a > 0.15)).mean())
    if 'autumn' in words or 'fall' in words:
        # Foliage is often olive (the yellow-green edge of the yellows), so count both.
        def leafy(hue, sat, value):
            return float((((hue >= 50) & (hue < 160)) & (sat > 0.15) & (value < 0.75)).mean())

        hue_b, sat_b, val_b = _hsv(before)
        hue_a, sat_a, val_a = _hsv(after)
        area = _mask(hue_b.shape, boxes) if boxes else np.ones(hue_b.shape, dtype=bool)
        green_b = ((hue_b >= 50) & (hue_b < 160) & (sat_b > 0.15) & (val_b < 0.75))[area].mean()
        green_a = ((hue_a >= 50) & (hue_a < 160) & (sat_a > 0.15) & (val_a < 0.75))[area].mean()
        where = 'of the foliage' if boxes else 'of the picture'
        return [_record(index, f'green and olive leaves {green_b:.1%} → {green_a:.1%} {where}',
                        green_a < green_b * 0.8 or green_b < 0.01)]
    if 'winter' in words:
        return [_record(index, f'saturation {sat_b.mean():.3f} → {sat_a.mean():.3f}', sat_a.mean() < sat_b.mean())]
    return [_record(index, f'saturation {sat_b.mean():.3f} → {sat_a.mean():.3f}', sat_a.mean() > sat_b.mean())]


def light_leak(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    old, new = _rgb(before), _rgb(after)
    height, width = old.shape[:2]
    position = edit['position'] or 'top right'
    rows = np.s_[:height // 3] if 'top' in position else np.s_[-height // 3:] if 'bottom' in position else \
        np.s_[height // 3:2 * height // 3]
    cols = np.s_[:width // 3] if 'left' in position else np.s_[-width // 3:] if 'right' in position else \
        np.s_[width // 3:2 * width // 3]
    corner = float((new[rows, cols, 0] - old[rows, cols, 0]).mean())
    whole = float((new[..., 0] - old[..., 0]).mean())
    return [_record(index, f'the {position} glows (red light +{corner:.1%} there, +{whole:.1%} overall)',
                    corner > 0.03 and corner > whole * 1.5)]


def letterbox(index, edit, before, after, boxes, pairs, geometry):
    rgb = _rgb(after)
    height = rgb.shape[0]
    top, bottom = rgb[:max(1, height // 20)], rgb[-max(1, height // 20):]
    dark = float(max(top.mean(), bottom.mean()))
    return [_record(index, f'bars at the top and bottom (brightness {dark:.0%})', dark < 0.05)]


def polaroid(index, edit, before, after, boxes, pairs, geometry):
    rgb = _rgb(after)
    height = rgb.shape[0]
    bottom = rgb[-max(1, height // 12):]
    return [_record(index, f'a deep light frame edge at the bottom (brightness {bottom.mean():.0%}, picture now '
                           f'{after.width}×{after.height})', after.size != before.size and bottom.mean() > 0.85)]


def high_pass_sharpen(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []

    def detail(image):
        luma = _luma(image)
        return np.abs(np.diff(luma, axis=0))[:, :-1] + np.abs(np.diff(luma, axis=1))[:-1]

    old, new = detail(before), detail(after)
    area = _mask(old.shape, boxes) if boxes else np.ones(old.shape, dtype=bool)
    a, b = float(old[area].mean()), float(new[area].mean())
    return [_record(index, f'fine detail {a:.4f} → {b:.4f} ({b / max(a, 1e-6) - 1:+.0%})', b > a * 1.03)]


def backlit_fix(index, edit, before, after, boxes, pairs, geometry):
    if geometry or not boxes:
        return []
    old, new = _luma(before), _luma(after)
    boxed = _mask(old.shape, boxes)
    # A box around a backlit person also holds the bright sky behind them: the subject is the
    # darker half of what the box holds.
    inside = boxed & (old < np.median(old[boxed]))
    lift = float(new[inside].mean() - old[inside].mean())
    brightest = (~boxed) & (old >= np.percentile(old[~boxed], 95)) if (~boxed).any() else boxed
    held = float(new[brightest].mean() - old[brightest].mean())
    return [_record(index, f'the subject brightened by {lift:.1%}; the brightest background {held:+.1%}',
                    lift > 0.02 and held < 0.01)]


def product_frame(index, edit, before, after, boxes, pairs, geometry):
    if not boxes:
        return []
    x, y, w, h = boxes[0] if len(boxes) == 1 else (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[0] + b[2] for b in boxes) - min(b[0] for b in boxes),
        max(b[1] + b[3] for b in boxes) - min(b[1] for b in boxes))
    fill = max(w, h)  # the limiting side, as a share of the frame
    wanted = (edit['value'] or 85) / 100
    centred = abs(x + w / 2 - 0.5) < 0.03 and abs(y + h / 2 - 0.5) < 0.03
    return [_record(index, f'the product fills {max(w, h):.0%} of the frame (asked {wanted:.0%}) and sits '
                           f'{"in the centre" if centred else "off centre"}', abs(fill - wanted) < 0.06 and centred)]


def compose(index, edit, before, after, boxes, pairs, geometry):
    if not boxes:
        return []
    x, y, w, h = boxes[0]
    cx, cy = x + w / 2, y + h / 2
    lines = (0.382, 0.618) if 'golden' in (edit['choice'] + edit['quote']).lower() else (1 / 3, 2 / 3)
    gap = min(abs(cx - line) for line in lines)
    return [_record(index, f'the subject’s centre is {gap:.1%} of the width from a {"golden" if lines[0] > 0.35 else "thirds"} '
                           'line', gap < 0.04)]


CHECKS = {check.__name__: check for check in (
    exposure_fix, tone_curve, graduated_filter, window_pull, keep_one_color, split_tone, season, light_leak, letterbox,
    polaroid, high_pass_sharpen, backlit_fix, product_frame, compose)}


def run(index, edit, before, after, boxes, pairs, geometry, others=()):
    """The checks for one requirement. `others` are the other pipelines in the plan, for checks
    that a second edit moving the same quantity would confound."""
    import inspect

    check = CHECKS.get(edit['action'])
    if check is None:
        return []
    try:
        if 'others' in inspect.signature(check).parameters:
            return check(index, edit, before, after, boxes or [], pairs or [], geometry, others=others)
        return check(index, edit, before, after, boxes or [], pairs or [], geometry)
    except (ValueError, IndexError, ZeroDivisionError):
        return []

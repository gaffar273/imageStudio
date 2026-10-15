"""Measured checks: after a pipeline runs, numbers from the rendered pixels say whether it did
what it promised. The language model's visual review comes second and is labelled fallible.

Each check reads the before and after renders and the boxes of what the pipeline worked on
(normalized 0..1 in the final picture, plus pairs mapping original to final positions), and
returns {'requirement', 'check', 'passed', 'measured'} records. A failed record carries
``weak: True`` when the change went the asked way but not far enough: the one failure a second run
at a higher strength can fix (photocraft_workspace.apply does that once).
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


def _record(index, text, passed, weak=False):
    record = {'requirement': index, 'check': f'Measured: {text}', 'passed': bool(passed), 'measured': True}
    if not passed and weak:
        record['weak'] = True
    return record


def exposure_fix(index, edit, before, after, boxes, pairs, geometry):
    import re

    old, new = float(np.median(_luma(before))), float(np.median(_luma(after)))
    if abs(old - new) < 0.004:
        return []  # left alone as already balanced; the plan says so
    words = edit['quote'].lower()
    if re.search(r'too (dark|dim)|underexposed|brighter|lighten', words):
        return [_record(index, f'middle tone {old:.0%} → {new:.0%} (asked brighter)', new > old + 0.01, new > old)]
    if re.search(r'too (bright|light)|overexposed|blown|darker', words):
        return [_record(index, f'middle tone {old:.0%} → {new:.0%} (asked darker)', new < old - 0.01, new < old)]
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
    return [_record(index, f'contrast {old.std():.3f} → {new.std():.3f}', new.std() > old.std() + 0.003,
                    new.std() > old.std())]


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
                    near_change < far_change - 0.015, near_change < far_change)]


def window_pull(index, edit, before, after, boxes, pairs, geometry):
    if geometry:
        return []
    old, new = _luma(before), _luma(after)
    brightest = old >= np.percentile(old, 97)
    a, b = float(old[brightest].mean()), float(new[brightest].mean())
    return [_record(index, f'the brightest 3% went {a:.0%} → {b:.0%}', b < a - 0.01, b < a)]


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
                           f'{b:+.3f} in the highlights)', abs(a - b) > 0.01, abs(a - b) > 0.002)]


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
                        green_a < green_b * 0.8 or green_b < 0.01, green_a < green_b)]
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
                    corner > 0.03 and corner > whole * 1.5, corner > 0.005 and corner > whole)]


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
    return [_record(index, f'fine detail {a:.4f} → {b:.4f} ({b / max(a, 1e-6) - 1:+.0%})', b > a * 1.03, b > a)]


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
                    lift > 0.02 and held < 0.01, 0 < lift and held < 0.01)]


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


# ---- Checks for the effect, detail and colour pipelines -------------------------------------


def _detail(image):
    """Local contrast between neighbouring pixels: rises when sharpened or grained, falls when blurred."""
    luma = _luma(image)
    return np.abs(np.diff(luma, axis=0))[:, :-1] + np.abs(np.diff(luma, axis=1))[:-1]


def _area(shape, boxes):
    return _mask(shape, boxes) if boxes else np.ones(shape, dtype=bool)


def _same_frame(before, after, geometry):
    return not geometry and before.size == after.size


def sharpen(index, edit, before, after, boxes, pairs, geometry):
    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    area = _area(old.shape, boxes)
    a, b = float(old[area].mean()), float(new[area].mean())
    # 5%: rounding alone moves this measure by a few per cent; real sharpening moves it far more.
    return [_record(index, f'fine detail {a:.4f} → {b:.4f} ({b / max(a, 1e-6) - 1:+.0%})', b > a * 1.05, b > a)]


def texture(index, edit, before, after, boxes, pairs, geometry):
    import re

    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    area = _area(old.shape, boxes)
    a, b = float(old[area].mean()), float(new[area].mean())
    softer = edit['direction'] == 'decrease' or re.search(r'smooth|soft', edit['quote'], re.IGNORECASE)
    if softer:
        return [_record(index, f'fine detail {a:.4f} → {b:.4f} (asked smoother)', b < a * 0.97, b < a)]
    return [_record(index, f'fine detail {a:.4f} → {b:.4f} (asked more texture)', b > a * 1.03, b > a)]


def noise_reduction(index, edit, before, after, boxes, pairs, geometry):
    """Noise lives in the flat parts: their pixel-to-pixel jitter must fall."""
    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    flat = old < np.percentile(old, 50)
    a, b = float(old[flat].mean()), float(new[flat].mean())
    return [_record(index, f'jitter in the flat areas {a:.4f} → {b:.4f}', b < a * 0.95, b < a)]


def grain(index, edit, before, after, boxes, pairs, geometry):
    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    flat = old < np.percentile(old, 50)
    a, b = float(old[flat].mean()), float(new[flat].mean())
    return [_record(index, f'grain in the flat areas {a:.4f} → {b:.4f}', b > a * 1.05, b > a)]


def _blurred(index, edit, before, after, boxes, geometry, what):
    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    area = _area(old.shape, boxes)
    a, b = float(old[area].mean()), float(new[area].mean())
    return [_record(index, f'fine detail {what} {a:.4f} → {b:.4f} ({b / max(a, 1e-6) - 1:+.0%})', b < a * 0.9, b < a)]


def blur(index, edit, before, after, boxes, pairs, geometry):
    return _blurred(index, edit, before, after, boxes, geometry, 'where it was blurred')


def motion_blur(index, edit, before, after, boxes, pairs, geometry):
    return _blurred(index, edit, before, after, boxes, geometry, 'after the motion blur')


def radial_blur(index, edit, before, after, boxes, pairs, geometry):
    return _blurred(index, edit, before, after, [], geometry, 'after the radial blur')


def tilt_shift(index, edit, before, after, boxes, pairs, geometry):
    """A miniature look keeps a sharp band and blurs the top and bottom."""
    if not _same_frame(before, after, geometry):
        return []
    old, new = _detail(before), _detail(after)
    height = old.shape[0]
    edges = np.zeros(old.shape, dtype=bool)
    edges[:height // 6] = edges[-height // 6:] = True
    a, b = float(old[edges].mean()), float(new[edges].mean())
    return [_record(index, f'detail at the top and bottom {a:.4f} → {b:.4f}', b < a * 0.85, b < a)]


def vignette(index, edit, before, after, boxes, pairs, geometry, others=()):
    import re

    if not _same_frame(before, after, geometry) or set(others) & {'light_leak', 'graduated_filter', 'relight'}:
        return []
    old, new = _luma(before), _luma(after)
    height, width = old.shape
    y, x = np.ogrid[:height, :width]
    radius = np.hypot((x - width / 2) / (width / 2), (y - height / 2) / (height / 2))
    rim, middle = radius > 1.0, radius < 0.4
    change = float((new[rim] - old[rim]).mean() - (new[middle] - old[middle]).mean())
    lighter = edit['direction'] == 'increase' and re.search(r'white|light', edit['quote'], re.IGNORECASE)
    if lighter:
        return [_record(index, f'the corners lightened by {change:+.1%} against the middle', change > 0.01, change > 0)]
    return [_record(index, f'the corners darkened by {-change:.1%} against the middle', change < -0.01, change < 0)]


def tint(index, edit, before, after, boxes, pairs, geometry, others=()):
    if not _same_frame(before, after, geometry) or set(others) & {'look', 'color_grade', 'color_filter', 'temperature'}:
        return []
    old, new = _rgb(before), _rgb(after)
    area = _area(old.shape[:2], boxes)

    def magenta(rgb):
        return float(((rgb[..., 0] + rgb[..., 2]) / 2 - rgb[..., 1])[area].mean())

    a, b = magenta(old), magenta(new)
    if edit['direction'] == 'none':
        return []
    toward = 'magenta' if edit['direction'] == 'increase' else 'green'
    moved = b - a if toward == 'magenta' else a - b
    return [_record(index, f'tint moved {moved:+.3f} toward {toward}', moved > 0.004, moved > 0)]


def hue_shift(index, edit, before, after, boxes, pairs, geometry):
    """The asked colours (or the boxed area) changed hue; their brightness is not the test."""
    from image_studio.integrations import photocraft_intents as lang

    if not _same_frame(before, after, geometry):
        return []
    hue_b, sat_b, _ = _hsv(before)
    hue_a, _, _ = _hsv(after)
    color = lang.hex_color(edit['color'])
    family = lang.color_family(color) if color else None
    if family in FAMILIES:
        area = _in_family(hue_b, family) & (sat_b > 0.15)
    else:
        area = _area(hue_b.shape, boxes) & (sat_b > 0.15)
    if area.sum() < 50:
        return []
    turned = np.abs((hue_a - hue_b + 180) % 360 - 180)[area]
    return [_record(index, f'hue of {family or "the area"} turned by {float(np.median(turned)):.0f}° (median)',
                    float(np.median(turned)) > 4, float(np.median(turned)) > 1)]


def posterize(index, edit, before, after, boxes, pairs, geometry):
    if not _same_frame(before, after, geometry):
        return []
    levels = lambda image: len(np.unique((_luma(image) * 255).round()))  # noqa: E731
    a, b = levels(before), levels(after)
    return [_record(index, f'tone levels {a} → {b}', b < a * 0.5)]


def threshold(index, edit, before, after, boxes, pairs, geometry):
    luma = _luma(after)
    middle = float(((luma > 0.08) & (luma < 0.92)).mean())
    return [_record(index, f'{middle:.1%} of the picture is neither black nor white', middle < 0.05)]


def invert(index, edit, before, after, boxes, pairs, geometry):
    if not _same_frame(before, after, geometry):
        return []
    old, new = _luma(before), _luma(after)
    error = float(np.abs((1 - old) - new).mean())
    return [_record(index, f'the picture is the negative of the original (mean difference {error:.3f})', error < 0.08)]


def flip(index, edit, before, after, boxes, pairs, geometry):
    import re

    if before.size != after.size:
        return []
    old, new = _luma(before), _luma(after)
    vertical = re.search(r'vertical|upside|top|bottom', f'{edit["quote"]} {edit["choice"]}', re.IGNORECASE)
    mirrored = old[::-1] if vertical else old[:, ::-1]
    error, unchanged = float(np.abs(mirrored - new).mean()), float(np.abs(old - new).mean())
    return [_record(index, f'the picture matches its mirror image (difference {error:.3f}, '
                           f'{unchanged:.3f} from the original)', error < 0.05 and error < unchanged)]


def _toward_color(index, edit, before, after, boxes, geometry, what):
    from image_studio.integrations import photocraft_intents as lang

    color = lang.hex_color(edit['color'] or edit['choice'])
    if not color or not _same_frame(before, after, geometry):
        return []
    target = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32) / 255
    target = target - target.mean()
    old, new = _rgb(before), _rgb(after)
    area = _area(old.shape[:2], boxes)
    shift = (new - old)[area].mean(axis=0)
    shift = shift - shift.mean()  # the colour of the change, not its brightness
    toward = float(np.dot(shift, target) / max(1e-6, np.linalg.norm(target)))
    return [_record(index, f'{what} moved the colours {toward:+.3f} toward {edit["color"] or edit["choice"]}',
                    toward > 0.01, toward > 0)]


def color_filter(index, edit, before, after, boxes, pairs, geometry):
    return _toward_color(index, edit, before, after, boxes, geometry, 'the filter')


def color_overlay(index, edit, before, after, boxes, pairs, geometry):
    return _toward_color(index, edit, before, after, boxes, geometry, 'the overlay')


def duotone(index, edit, before, after, boxes, pairs, geometry):
    """Two inks: nearly every coloured pixel sits on one of two hues."""
    hue, sat, _ = _hsv(after)
    coloured = sat > 0.12
    if coloured.sum() < 100:
        return [_record(index, 'the picture has almost no colour left', False)]
    counts = np.bincount((hue[coloured] // 20).astype(int) % 18, minlength=18)
    top_two = float(np.sort(counts)[-2:].sum() / counts.sum())
    neighbours = float(sum(sorted(counts)[-4:]) / counts.sum())
    return [_record(index, f'{neighbours:.0%} of the coloured pixels sit in the two inks’ hues', neighbours > 0.8 or
                    top_two > 0.7)]


def retouch_portrait(index, edit, before, after, boxes, pairs, geometry, spots=()):
    """Healed spots: each spot's difference from the skin around it must mostly go."""
    if not spots or not _same_frame(before, after, geometry):
        return []
    old, new = _luma(before), _luma(after)
    height, width = old.shape
    faded = []
    for x, y, w, h in spots:
        cx, cy, radius = (x + w / 2) * width, (y + h / 2) * height, w * width / 4
        x0, y0 = max(0, int(cx - 4 * radius)), max(0, int(cy - 4 * radius))
        x1, y1 = min(width, int(cx + 4 * radius) + 1), min(height, int(cy + 4 * radius) + 1)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        distance = np.hypot(xx - cx, yy - cy)
        core, ring = distance <= max(radius, 1), (distance >= 2 * radius) & (distance <= 3.5 * radius)
        if not core.any() or not ring.any():
            continue
        contrast = [abs(float(image[y0:y1, x0:x1][core].mean() - image[y0:y1, x0:x1][ring].mean()))
                    for image in (old, new)]
        if contrast[0] > 0.01:
            faded.append(contrast[1] / contrast[0])
    if not faded:
        return []
    healed = sum(1 for share in faded if share < 0.5)
    return [_record(index, f'{healed} of {len(faded)} spots lost at least half their difference from the skin '
                           f'around them', healed >= 0.7 * len(faded))]


# ---- A camera develop: each step is checked on what it promised, and only when it changed anything.
# These read whole-picture statistics, so a horizon straightened in the same develop does not stop them.


def _planned(before, step):
    from image_studio.pipelines.library.camera_develop import read

    return read(before)[step][0]


def _yardstick(before, after, steps):
    """`before` with only the named develop steps, at the size of `after`."""
    from image_studio.pipelines.library.camera_develop import preview

    return preview(before, steps).resize(after.size)


def _small(image, side=512):
    picture = image.convert('RGB')
    picture.thumbnail((side, side))
    return np.asarray(picture, dtype=np.float32) / 255


def _reduced(image, side):
    picture = image.convert('RGB')
    picture.thumbnail((side, side))
    return picture


def _tonal_range(image):
    luma = _luma(_reduced(image, 512))
    low, high = np.percentile(luma, [0.5, 99.5])
    return float(low), float(high)


def develop_white_balance(index, edit, before, after, boxes, pairs, geometry):
    from image_studio.pipelines.library import camera_develop as cd

    if not _planned(before, 'white_balance'):
        return []

    def off_neutral(image):
        readings = [cd._unit(r) for r in cd.light_colour(_small(image))]
        return cd._angle(np.exp(np.mean(np.log(readings), axis=0)), np.ones(3)) if readings else None

    # Against the photo with only the develop's curve: on a dark night shot the curve alone moved
    # the reading by 4° (measured on a neon sign), which is not the white balance's doing.
    old, new = off_neutral(_yardstick(before, after, {'tone'})), off_neutral(after)
    if old is None or new is None:
        return []
    return [_record(index, f'the light read {old:.1f}° from neutral → {new:.1f}°', new < old or new < 1.5)]


def develop_tone(index, edit, before, after, boxes, pairs, geometry):
    planned = _planned(before, 'tone')
    if not planned:
        return []
    records = []
    if 'pointCurve' in planned:
        (a0, a1), (b0, b1) = _tonal_range(before), _tonal_range(after)
        records.append(_record(index, f'tonal range {a0:.0%}–{a1:.0%} → {b0:.0%}–{b1:.0%}', b1 - b0 > a1 - a0 + 0.03))
    if 'highlights' in planned:
        old, new = float((_luma(before) >= 0.98).mean()), float((_luma(after) >= 0.98).mean())
        records.append(_record(index, f'clipped white {old:.1%} → {new:.1%}', new < old))
    if 'contrast' in planned and 'pointCurve' not in planned:
        old, new = float(_luma(before).std()), float(_luma(after).std())
        records.append(_record(index, f'tonal spread {old:.3f} → {new:.3f}', new > old))
    return records


def develop_color(index, edit, before, after, boxes, pairs, geometry):
    if not _planned(before, 'colour'):
        return []

    def colour(image):
        a = _small(image, 256)
        high = a.max(axis=-1)
        sat = (high - a.min(axis=-1)) / np.maximum(high, 1e-3)
        luma = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        coloured = (luma > 0.1) & (luma < 0.95) & (sat > 0.1)
        return float(sat[coloured].mean()) if coloured.any() else 0.0

    old, new = colour(before), colour(after)
    return [_record(index, f'saturation of the coloured parts {old:.0%} → {new:.0%}', new > old)]


def _per_range(image, value):
    low, high = _tonal_range(image)
    return value / max(high - low, 0.05)


def develop_noise(index, edit, before, after, boxes, pairs, geometry):
    """Grain against the photo's tonal range: stretching the tones stretches the grain with them."""
    from image_studio.pipelines.measure import noise

    old, new = noise(before, None, None, []), noise(after, None, None, [])
    if old is None or new is None or old < 1.8:
        return []
    a, b = _per_range(before, old), _per_range(after, new)
    return [_record(index, f'grain for the tonal range {a:.1f} → {b:.1f}', b < a)]


def develop_sharpen(index, edit, before, after, boxes, pairs, geometry):
    """The strongest 5% of edges, against the tonal range (the curve steepens every edge too)."""
    def edges(image):
        luma = _luma(_reduced(image, 1024))
        gy, gx = np.gradient(luma)
        strength = np.hypot(gx, gy)
        return float(strength[strength >= np.percentile(strength, 95)].mean())

    a, b = _per_range(before, edges(before)), _per_range(after, edges(after))
    return [_record(index, f'edge crispness for the tonal range {a:.4f} → {b:.4f} ({b / max(a, 1e-6) - 1:+.0%})',
                    b > a * 1.02)]


def develop_vignette(index, edit, before, after, boxes, pairs, geometry):
    from image_studio.pipelines.library.camera_develop import read

    border = read(before)['border']
    if border['spread'] < 0.15 or border['white'] > 0.3:
        return []

    def corners_to_middle(image):
        luma = _luma(_reduced(image, 256))
        height, width = luma.shape
        yy, xx = np.mgrid[0:height, 0:width]
        r = np.hypot((xx - width / 2) / (width / 2), (yy - height / 2) / (height / 2)) / np.sqrt(2)
        return float(luma[r > 0.8].mean() / max(luma[r < 0.4].mean(), 1e-3))

    old, new = corners_to_middle(_yardstick(before, after, {'white_balance', 'tone'})), corners_to_middle(after)
    return [_record(index, f'corners against the middle {old:.2f} → {new:.2f}', new < old - 0.01)]


def develop_sky(index, edit, before, after, boxes, pairs, geometry):
    from image_studio.pipelines.library.camera_develop import read

    sky, border = read(before)['sky'], read(before)['border']
    if sky['top'] - sky['rest'] < 0.15 or sky['top'] < 0.6 or border['spread'] < 0.15:
        return []
    return graduated_filter(index, {**edit, 'position': 'top'}, _yardstick(before, after, {'white_balance', 'tone'}),
                            after, boxes, pairs, False)


CHECKS = {check.__name__: check for check in (
    exposure_fix, tone_curve, graduated_filter, window_pull, keep_one_color, split_tone, season, light_leak, letterbox,
    polaroid, high_pass_sharpen, backlit_fix, product_frame, compose, sharpen, texture, noise_reduction, grain, blur,
    motion_blur, radial_blur, tilt_shift, vignette, tint, hue_shift, posterize, threshold, invert, flip,
    color_filter, color_overlay, duotone, retouch_portrait, develop_white_balance, develop_tone, develop_color,
    develop_noise, develop_sharpen, develop_vignette, develop_sky)}


def run(index, edit, before, after, boxes, pairs, geometry, others=(), spots=()):
    """The checks for one requirement. `others` are the other pipelines in the plan, for checks
    that a second edit moving the same quantity would confound; `spots` the boxes of healed spots."""
    import inspect

    check = CHECKS.get(edit['action'])
    if check is None:
        return []
    try:
        wanted = inspect.signature(check).parameters
        extra = {name: value for name, value in (('others', others), ('spots', spots)) if name in wanted}
        return check(index, edit, before, after, boxes or [], pairs or [], geometry, **extra)
    except (ValueError, IndexError, ZeroDivisionError):
        return []

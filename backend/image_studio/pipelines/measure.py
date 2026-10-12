"""Facts measured from the pixels before a plan is built.

Pipelines declare which analyses they read (``Pipeline.measures``); only those are run. Every
number a pipeline derives from the photo (an exposure correction, a white balance, a horizon
angle, the colours of the skin) comes from here, never from the language model.
"""

from image_studio.integrations import photocraft_intents as lang


def exposure(preview, state, boxes, edits):
    """Luminance statistics on 0..1: median, 2nd and 98th percentiles, and the shares of
    clipped highlights (≥ 250) and crushed shadows (≤ 5)."""
    gray = preview.convert('L')
    gray.thumbnail((800, 800))
    histogram = gray.histogram()
    total = sum(histogram)

    def percentile(share):
        running = 0
        for value, count in enumerate(histogram):
            running += count
            if running >= total * share:
                return value / 255
        return 1.0

    return {'median': percentile(0.5), 'p02': percentile(0.02), 'p98': percentile(0.98),
            'clipped_high': sum(histogram[250:]) / total, 'clipped_low': sum(histogram[:6]) / total}


def noise(preview, state, boxes, edits):
    """The grain level in levels of 255: the spread of what a 3×3 median removes, measured only
    where the picture is flat (fine detail would otherwise read as noise)."""
    import numpy as np
    from PIL import ImageFilter

    gray = preview.convert('L')
    gray.thumbnail((1024, 1024))
    pixels = np.asarray(gray, dtype=np.float32)
    residual = pixels - np.asarray(gray.filter(ImageFilter.MedianFilter(3)), dtype=np.float32)
    smooth = np.asarray(gray.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    gy, gx = np.gradient(smooth)
    flat = np.hypot(gx, gy) < 2.0
    if flat.sum() < 500:
        return None
    values = residual[flat]
    return round(float(1.4826 * np.median(np.abs(values - np.median(values)))), 2)


def levels(preview, state, boxes, edits):
    return lang.measure_levels(preview)


def tilt(preview, state, boxes, edits):
    from image_studio.integrations.photocraft_lines import tilt as measure_tilt

    if not any(edit['action'] == 'straighten' and edit['value'] is None for edit in edits):
        return None
    return measure_tilt(preview)


def verticals(preview, state, boxes, edits):
    from image_studio.integrations.photocraft_lines import verticals as measure_verticals

    sx, sy = state['width'] / preview.width, state['height'] / preview.height
    return [[[round(x * sx), round(y * sy)] for x, y in line] for line in measure_verticals(preview)]


def skin_colors(preview, state, boxes, edits):
    faces = (boxes or {}).get(lang.FACES)
    return lang.skin_colors(preview, faces, state) if faces else None


def teeth(preview, state, boxes, edits):
    """Whether teeth really show: the box finder boxes closed lips as “the teeth”."""
    if not (boxes or {}).get(lang.TEETH):
        return None
    from image_studio.integrations import photocraft_planner

    return photocraft_planner.teeth_showing(preview)


def teeth_colors(preview, state, boxes, edits):
    found = (boxes or {}).get(lang.TEETH)
    return lang.teeth_colors(preview, found, state) if found else None


def palette(preview, state, boxes, edits):
    """For each colour family, the photo's own most saturated shades (up to three), sampled where
    that colour is strongest."""
    import numpy as np

    rgb = preview.convert('RGB')
    rgb.thumbnail((400, 400))
    hsv = np.asarray(rgb.convert('HSV'), dtype=np.float32)
    pixels = np.asarray(rgb).reshape(-1, 3)
    hue, sat, val = hsv[..., 0].ravel() * 360 / 255, hsv[..., 1].ravel() / 255, hsv[..., 2].ravel() / 255
    families = {'reds': (340, 20), 'yellows': (20, 75), 'greens': (75, 160), 'cyans': (160, 200),
                'blues': (200, 275), 'magentas': (275, 340)}
    result = {}
    for family, (low, high) in families.items():
        inside = ((hue >= low) | (hue < high)) if low > high else ((hue >= low) & (hue < high))
        inside &= (sat > 0.35) & (val > 0.2)
        if inside.sum() < 50:
            continue
        chosen = pixels[inside][np.argsort(-sat[inside])[: max(50, int(inside.sum() * 0.3))]]
        shades = [np.median(part, axis=0) for part in np.array_split(chosen[np.argsort(chosen.sum(axis=1))], 3)]
        result[family] = ['#{:02x}{:02x}{:02x}'.format(*(int(v) for v in shade)) for shade in shades]
    return result


ANALYSES = {'exposure': exposure, 'noise': noise, 'levels': levels, 'tilt': tilt, 'verticals': verticals,
            'skin_colors': skin_colors, 'teeth': teeth, 'teeth_colors': teeth_colors, 'palette': palette}


def analyse(edits, preview, state, boxes=None):
    """Every analysis the planned pipelines read, measured once."""
    from image_studio.pipelines import get

    wanted = []
    for edit in edits:
        pipeline = get(edit['action'])
        for name in pipeline.measures if pipeline else ():
            if name not in wanted:
                wanted.append(name)
    result = {}
    for name in wanted:
        value = ANALYSES[name](preview, state, boxes, edits)
        if value is not None:
            result[name] = value
    return result

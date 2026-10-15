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
    # The mean absolute deviation (as a Gaussian σ), trimmed of the stray edges the flat mask lets
    # through. A median of whole-level residuals only moved in steps of 1.48 (0, 1.48, 2.97…),
    # too coarse to choose a noise reduction from (measured 2026-10-15).
    deviation = np.abs(residual[flat] - np.median(residual[flat]))
    deviation = deviation[deviation <= np.percentile(deviation, 99)]
    return round(float(1.2533 * deviation.mean()), 2)


def levels(preview, state, boxes, edits):
    return lang.measure_levels(preview)


def tilt(preview, state, boxes, edits):
    from image_studio.integrations.photocraft_lines import tilt as measure_tilt

    if not any(edit['action'] in ('straighten', 'develop_level') and edit['value'] is None for edit in edits):
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


def blemishes(preview, state, boxes, edits):
    """Spots a retoucher would heal on each face, as [x, y, radius] in document pixels: small, round
    marks darker or redder than the skin right around them (pimples, spots, small marks), whole
    skin all round them, so eyes, brows, nostrils, lips, beard edges and glasses frames, which
    border something that is not skin, are left alone."""
    faces = (boxes or {}).get(lang.FACES)
    if not faces:
        return None
    return find_spots(preview, faces, state)


def find_spots(preview, faces, state, limit=40):
    import cv2
    import numpy as np

    sx, sy = preview.width / state['width'], preview.height / state['height']
    rgb = np.ascontiguousarray(np.asarray(preview.convert('RGB')))
    spots = []
    for x, y, w, h in faces[:4]:
        x0, y0 = max(0, round(x * sx)), max(0, round(y * sy))
        x1, y1 = min(rgb.shape[1], round((x + w) * sx)), min(rgb.shape[0], round((y + h) * sy))
        width = x1 - x0
        if width < 80 or y1 - y0 < 80:
            continue  # too small in the picture for spots to show
        face = rgb[y0:y1, x0:x1]
        lab = cv2.cvtColor(face, cv2.COLOR_RGB2LAB)
        hsv = cv2.cvtColor(face, cv2.COLOR_RGB2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        # Skin of every tone: a warm hue (OpenCV's 0..179), moderately saturated, not too dark.
        skin = ((hue <= 28) | (hue >= 172)) & (sat >= 25) & (sat <= 190) & (val >= 45)
        light, red = lab[..., 0].astype(np.float32), lab[..., 1].astype(np.float32)
        if skin.sum() < 200:
            continue
        # Dark brown hair has skin's warm hue: a beard, brows and the hairline are much darker than
        # the face's own skin (they all read as spots before this, 2026-10-15).
        skin &= light > np.median(light[skin]) - 40
        skin = cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        texture = cv2.blur((light - cv2.blur(light, (5, 5))) ** 2, (5, 5)) ** 0.5
        window = max(5, round(width * 0.06)) | 1
        darker = cv2.medianBlur(lab[..., 0], window).astype(np.float32) - light
        redder = red - cv2.medianBlur(lab[..., 1], window).astype(np.float32)
        score = np.maximum(darker / 9, redder / 6)
        # A dark mark is itself darker than the skin test allows; it needs skin around it, not under it.
        size = max(3, round(width * 0.04)) | 1
        within = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
        candidates = ((score >= 1) & (within > 0)).astype(np.uint8)
        # One mark often comes out in pieces (a dark core, a lighter rim): they are joined.
        join = max(3, round(width * 0.025)) | 1
        candidates = cv2.morphologyEx(candidates, cv2.MORPH_CLOSE,
                                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (join, join)))
        count, labels, stats, centres = cv2.connectedComponentsWithStats(candidates, connectivity=8)
        smallest, largest = width * 0.004, width * 0.018
        yy, xx = np.mgrid[0:face.shape[0], 0:face.shape[1]]
        found = []
        for number in range(1, count):
            area = stats[number, cv2.CC_STAT_AREA]
            box_w, box_h = stats[number, cv2.CC_STAT_WIDTH], stats[number, cv2.CC_STAT_HEIGHT]
            radius = (area / np.pi) ** 0.5
            if not smallest <= radius <= largest or max(box_w, box_h) > 2.2 * min(box_w, box_h) + 2:
                continue  # pores are smaller; lines (frames, creases, lashes) are long
            cx, cy = centres[number]
            distance = np.hypot(xx - cx, yy - cy)
            # The skin around it, leaving out other marks nearby (their dark pixels are not skin).
            ring = (distance >= radius * 1.8 + 1) & (distance <= radius * 3 + 2) & (candidates == 0)
            if not ring.any() or skin[ring].mean() < 0.85:
                continue  # it borders something that is not skin: an eye, a brow, a nostril, the beard
            if float(np.median(texture[ring])) > 6:
                continue  # coarse all round (stubble, hair): a blemish sits on smooth skin
            low, high = np.percentile(light[ring], [25, 75])
            if high - low > 10:
                continue  # in a shadow's gradient (beside the nose, a mouth corner): a feature, not a mark
            inside = labels == number
            found.append({'dark': float(darker[inside].max()), 'red': float(redder[inside].max()),
                          'strength': float(score[inside].max()),
                          'spot': [round(x0 / sx + cx / sx), round(y0 / sy + cy / sy), round(max(radius, 1) / sx, 1)]})
        brown = [spot for spot in found if spot['red'] < 6]
        if len(brown) >= 12:
            # Many small brown spots of a kind are freckles, which a retoucher keeps: only the red
            # (inflamed) ones and the clearly darker marks among them are healed.
            typical = float(np.median([spot['dark'] for spot in brown]))
            found = [spot for spot in found if spot['red'] >= 6 or spot['dark'] >= 2 * typical]
        spots += [spot['spot'] for spot in sorted(found, key=lambda spot: -spot['strength'])[:limit]]
    return spots


def photo_stats(image):
    """What a retoucher reads off a photo before developing it, in one pass over a 1024 px copy.

    Tones on 0..1 (luminance percentiles, clipping, contrast as the luminance spread); colour as
    the mean saturation of the visible tones; the cast as the median red−blue and green−magenta of
    the photo's greyest midtones, in levels of 255 (what a white-balance dropper reads); detail as
    the mean edge strength of its sharpest 5% (soft lenses and missed focus read low); the top band
    and the frame's border for a bright sky and a white backdrop."""
    import numpy as np

    rgb = image.convert('RGB')
    rgb.thumbnail((1024, 1024))
    a = np.asarray(rgb, dtype=np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    high, low = a.max(axis=-1), a.min(axis=-1)
    sat = (high - low) / np.maximum(high, 1e-3)
    p01, p02, p50, p98, p99 = (float(v) for v in np.percentile(luma, [1, 2, 50, 98, 99]))
    visible = (luma > 0.1) & (luma < 0.95)
    stats = {'p01': p01, 'p02': p02, 'median': p50, 'p98': p98, 'p99': p99,
             'clipped_high': float((luma >= 250 / 255).mean()), 'clipped_low': float((luma <= 5 / 255).mean()),
             'contrast': float(luma.std()), 'saturation': float(sat[visible].mean()) if visible.any() else 0.0}
    # The cast: the greyest quarter of the midtones (what should be neutral), when there is enough of it.
    mid = (luma > 0.15) & (luma < 0.9)
    stats['cast'] = None
    if mid.sum() > 0.05 * luma.size:
        greys = mid & (sat <= max(0.04, float(np.percentile(sat[mid], 25))))
        if greys.sum() > 0.03 * luma.size and float(sat[greys].mean()) < 0.3:
            stats['cast'] = {'warm': float(np.median(r[greys] - b[greys]) * 255),
                             'green': float(np.median(g[greys] - (r[greys] + b[greys]) / 2) * 255),
                             'share': float(greys.mean())}
    gy, gx = np.gradient(luma)
    edges = np.hypot(gx, gy)
    stats['detail'] = float(edges[edges >= np.percentile(edges, 95)].mean() * 255)
    top = luma[: luma.shape[0] // 4]
    stats['top'] = {'luma': float(top.mean()), 'rest': float(luma[luma.shape[0] // 4:].mean()),
                    'saturation': float(sat[: luma.shape[0] // 4].mean()),
                    'clipped': float((top >= 245 / 255).mean())}
    edge = max(2, round(min(luma.shape) * 0.08))
    border = np.concatenate([luma[:edge].ravel(), luma[-edge:].ravel(), luma[:, :edge].ravel(), luma[:, -edge:].ravel()])
    stats['border'] = {'luma': float(border.mean()), 'white': float((border > 0.93).mean())}
    return stats


def develop(preview, state, boxes, edits):
    """Every decision of a camera develop (see library.camera_develop.read), plus the grain level."""
    from image_studio.pipelines.library.camera_develop import read

    found = dict(read(preview))
    found['noise'] = noise(preview, state, boxes, edits)
    return found


ANALYSES = {'exposure': exposure, 'noise': noise, 'levels': levels, 'tilt': tilt, 'verticals': verticals,
            'skin_colors': skin_colors, 'teeth': teeth, 'teeth_colors': teeth_colors, 'palette': palette,
            'develop': develop, 'blemishes': blemishes}


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

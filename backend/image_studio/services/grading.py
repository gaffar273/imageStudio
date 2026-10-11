"""Professional photo grading: the adjustments of a raw developer and a color-grading suite,
computed in floating point and handed to Krita as a layer (Krita's own curves filters cannot
be configured from its Python API, which was checked in a headless Krita).

A grade is a JSON recipe; every key is optional and 0 / missing means "unchanged":

    exposure      -3..3 stops            temperature  -100..100 (+ warmer)
    contrast      -100..100              tint         -100..100 (+ magenta)
    highlights    -100..100              vibrance     -100..100
    shadows       -100..100              saturation   -100..100
    whites        -100..100              clarity      -100..100 (midtone local contrast)
    blacks        -100..100              texture      -100..100 (fine detail)
    dehaze        -100..100              fade         0..100    (matte, lifted blacks)
    curve, curve_red, curve_green, curve_blue: [[in, out], ...] points on 0..255
    hsl: {band: {"hue": -100..100, "saturation": -100..100, "luminance": -100..100}} for
         red, orange, yellow, green, aqua, blue, purple, magenta
    shadows_color, midtones_color, highlights_color: {"hue": 0..360, "amount": 0..100,
         "luminance": -100..100}  (color wheels: lift, gamma, gain)
    split_toning: {"shadow_hue", "shadow_saturation", "highlight_hue",
         "highlight_saturation", "balance": -100..100}
    glow          0..100 (bloom on bright areas)   halation  0..100 (warm film glow)
    vignette      -100..100 (+ darker corners)       grain     0..100
    mask: where the grade applies (see MASK in make_mask); default the whole picture
    amount        0..100, overall strength (default 100)

Order follows a raw developer: white balance, exposure and dehaze on linear light; tone;
color; local contrast; finishing effects."""

import math

import cv2
import numpy as np
from PIL import Image

BANDS = {'red': 0, 'orange': 30, 'yellow': 60, 'green': 120, 'aqua': 180, 'blue': 225, 'purple': 275,
         'magenta': 320}
LIMITS = dict(exposure=(-3, 3), fade=(0, 100), glow=(0, 100), halation=(0, 100), grain=(0, 100),
              amount=(0, 100))


# ---- Color space helpers -----------------------------------------------------------------

def to_linear(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def to_srgb(v):
    v = np.clip(v, 0, None)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def blur(channel, sigma):
    sigma = max(0.5, float(sigma))
    return cv2.GaussianBlur(channel, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REFLECT)


def hue_color(hue):
    """A unit color direction for a hue (degrees) whose luma is zero, for tinting."""
    rgb = np.array([max(0.0, min(1.0, abs(((hue / 60 + offset) % 6) - 3) - 1)) for offset in (0, 4, 2)],
                   dtype=np.float32)
    rgb = rgb - (rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722)
    return rgb / max(1e-6, float(np.abs(rgb).max()))


def rgb_to_hsl(rgb):
    high, low = rgb.max(-1), rgb.min(-1)
    light = (high + low) / 2
    delta = high - low
    sat = np.where(delta < 1e-6, 0, delta / np.maximum(1e-6, 1 - np.abs(2 * light - 1)))
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    safe = np.maximum(delta, 1e-6)
    hue = np.where(high == r, ((g - b) / safe) % 6, np.where(high == g, (b - r) / safe + 2, (r - g) / safe + 4))
    hue = np.where(delta < 1e-6, 0, hue * 60)
    return hue.astype(np.float32), np.clip(sat, 0, 1).astype(np.float32), light.astype(np.float32)


def hsl_to_rgb(hue, sat, light):
    c = (1 - np.abs(2 * light - 1)) * sat
    h = (hue % 360) / 60
    x = c * (1 - np.abs(h % 2 - 1))
    zeros = np.zeros_like(c)
    sector = np.floor(h).astype(np.int32) % 6
    r = np.choose(sector, [c, x, zeros, zeros, x, c])
    g = np.choose(sector, [x, c, c, x, zeros, zeros])
    b = np.choose(sector, [zeros, zeros, x, c, c, x])
    m = light - c / 2
    return np.stack([r + m, g + m, b + m], -1)


def curve_lut(points, size=1024):
    """A monotone cubic curve through [[in, out], ...] on 0..255, as a lookup table."""
    from scipy.interpolate import PchipInterpolator

    pts = sorted((max(0.0, min(255.0, float(x))), max(0.0, min(255.0, float(y)))) for x, y in points)
    if not pts or pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1] if pts and pts[0][0] < 8 else 0.0))
    if pts[-1][0] < 255:
        pts.append((255.0, pts[-1][1] if pts[-1][0] > 247 else 255.0))
    xs, ys = [], []
    for x, y in pts:
        if xs and x - xs[-1] < 1e-3:
            ys[-1] = y
        else:
            xs.append(x)
            ys.append(y)
    grid = np.linspace(0, 255, size)
    if len(xs) < 2:
        return grid / 255
    return np.clip(PchipInterpolator(xs, ys)(grid) / 255, 0, 1).astype(np.float32)


def apply_lut(values, lut):
    index = np.clip(values, 0, 1) * (len(lut) - 1)
    low = np.floor(index).astype(np.int32)
    high = np.minimum(low + 1, len(lut) - 1)
    t = index - low
    return lut[low] * (1 - t) + lut[high] * t


def number(recipe, key, default=0.0):
    low, high = LIMITS.get(key, (-100, 100))
    try:
        return max(low, min(high, float(recipe.get(key, default) or 0)))
    except (TypeError, ValueError):
        return default


# ---- The grade ----------------------------------------------------------------------------

def tone(v, recipe, scale):
    """Contrast, highlights, shadows, whites and blacks on luminance, colors kept."""
    contrast = number(recipe, 'contrast') / 100
    highlights = number(recipe, 'highlights') / 100
    shadows = number(recipe, 'shadows') / 100
    whites = number(recipe, 'whites') / 100
    blacks = number(recipe, 'blacks') / 100
    if not any((contrast, highlights, shadows, whites, blacks)):
        return v
    lum = np.clip(luma(v), 0, 1)
    # Local average light, so recovering highlights or lifting shadows keeps local contrast.
    base = 0.5 * lum + 0.5 * blur(lum, scale * 0.02)
    new = lum.copy()
    if blacks or whites:
        black = -blacks * 0.08
        white = 1 - whites * 0.15
        new = np.clip((new - black) / max(0.05, white - black), 0, None)
        new = np.where(new > 1, 1 + (new - 1) * 0.3, new)
    if shadows:
        weight = 1 - smoothstep(0.0, 0.55, base)
        new = new + shadows * 0.45 * weight * (np.sqrt(np.clip(new, 0, 1)) - new + 0.04 * (shadows > 0))
    if highlights:
        weight = smoothstep(0.4, 1.0, base)
        target = new ** (1.6 if highlights < 0 else 0.7)
        new = new + abs(highlights) * 0.8 * weight * (target - new)
    if contrast:
        # An S-curve around middle grey that never clips.
        k = 1 + contrast * (1.2 if contrast > 0 else 0.6)
        x = np.clip(new, 0, 1)
        s = np.where(x < 0.5, 0.5 * (2 * x) ** k, 1 - 0.5 * (2 * (1 - x)) ** k)
        new = s + (new - x)
    gain = new / np.maximum(lum, 1e-4)
    out = v * gain[..., None]
    # Very dark pixels have unreliable ratios: lift them as grey instead.
    dark = (lum < 0.02)[..., None]
    return np.where(dark, v + (new - lum)[..., None], out)


def color_balance(v, recipe):
    """HSL mixer, vibrance and saturation."""
    hsl = recipe.get('hsl') or {}
    vibrance = number(recipe, 'vibrance') / 100
    saturation = number(recipe, 'saturation') / 100
    bands = {name: hsl.get(name) or {} for name in BANDS}
    if any(any(float(b.get(k, 0) or 0) for k in ('hue', 'saturation', 'luminance')) for b in bands.values()):
        hue, sat, light = rgb_to_hsl(np.clip(v, 0, 1))
        shift = np.zeros_like(hue)
        sat_gain = np.zeros_like(hue)
        lum_gain = np.zeros_like(hue)
        centers = sorted(BANDS.items(), key=lambda item: item[1])
        for index, (name, center) in enumerate(centers):
            previous = centers[index - 1][1]
            following = centers[(index + 1) % len(centers)][1]
            width_left = (center - previous) % 360
            width_right = (following - center) % 360
            distance = (hue - center + 180) % 360 - 180
            width = np.where(distance < 0, width_left, width_right)
            weight = np.clip(1 - np.abs(distance) / width, 0, 1)
            weight = weight * weight * (3 - 2 * weight)
            band = bands[name]
            shift += weight * float(band.get('hue', 0) or 0) / 100 * 30
            sat_gain += weight * float(band.get('saturation', 0) or 0) / 100
            lum_gain += weight * float(band.get('luminance', 0) or 0) / 100
        colorful = smoothstep(0.04, 0.2, sat)
        hue = hue + shift * colorful
        sat = np.clip(sat * (1 + sat_gain * colorful), 0, 1)
        lum_gain = lum_gain * colorful
        light = np.where(lum_gain < 0, light * (1 + 0.6 * lum_gain), light + (1 - light) * 0.5 * lum_gain)
        v = hsl_to_rgb(hue, sat, np.clip(light, 0, 1)).astype(np.float32)
    if vibrance or saturation:
        lum = luma(v)[..., None]
        chroma = v.max(-1, keepdims=True) - v.min(-1, keepdims=True)
        factor = 1 + saturation
        if vibrance:
            hue, _, _ = rgb_to_hsl(np.clip(v, 0, 1))
            skin = 1 - 0.5 * (smoothstep(5, 20, hue) * (1 - smoothstep(40, 55, hue)))[..., None]
            weight = (1 - np.clip(chroma * 1.4, 0, 1)) * (skin if vibrance > 0 else 1)
            factor = factor + vibrance * weight
        v = lum + (v - lum) * factor
    return v


def wheels(v, recipe):
    """Lift / gamma / gain color wheels and split toning, luminance kept."""
    lum = np.clip(luma(v), 0, 1)
    out = v
    for key, region in (('shadows_color', 'lift'), ('midtones_color', 'gamma'), ('highlights_color', 'gain')):
        wheel = recipe.get(key) or {}
        amount = float(wheel.get('amount', 0) or 0) / 100
        brightness = float(wheel.get('luminance', 0) or 0) / 100
        if not amount and not brightness:
            continue
        direction = hue_color(float(wheel.get('hue', 0) or 0)) * amount
        if region == 'lift':
            weight = (1 - smoothstep(0.0, 0.6, lum))[..., None]
            out = out + (direction * 0.12 + brightness * 0.1) * weight
        elif region == 'gamma':
            weight = (4 * lum * (1 - lum))[..., None]
            out = out + (direction * 0.1 + brightness * 0.12) * weight
        else:
            weight = smoothstep(0.4, 1.0, lum)[..., None]
            out = out * (1 + (direction * 0.15 + brightness * 0.2) * weight)
    split = recipe.get('split_toning') or {}
    if split:
        balance = float(split.get('balance', 0) or 0) / 100
        middle = 0.5 + balance * 0.25
        low = (1 - smoothstep(0.0, middle, lum))[..., None]
        high = smoothstep(middle, 1.0, lum)[..., None]
        for weight, hue_key, sat_key in ((low, 'shadow_hue', 'shadow_saturation'),
                                         (high, 'highlight_hue', 'highlight_saturation')):
            strength = float(split.get(sat_key, 0) or 0) / 100
            if strength:
                out = out + hue_color(float(split.get(hue_key, 0) or 0)) * strength * 0.18 * weight
    return out


def local_contrast(v, recipe, scale):
    clarity = number(recipe, 'clarity') / 100
    texture = number(recipe, 'texture') / 100
    if not clarity and not texture:
        return v
    lum = np.clip(luma(v), 0, 1)
    new = lum.copy()
    if clarity:
        detail = lum - blur(lum, scale * 0.015)
        new = new + clarity * 1.2 * detail * (4 * lum * (1 - lum) + 0.15)
    if texture:
        detail = lum - blur(lum, scale * 0.0025)
        new = new + texture * 1.5 * detail
    return v * (np.clip(new, 0, 1.2) / np.maximum(lum, 1e-3))[..., None]


def dehaze(linear, amount, scale):
    """Dark-channel haze removal (+) or added haze (-), on linear light."""
    if not amount:
        return linear
    small = cv2.resize(linear, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    dark = cv2.erode(small.min(-1), np.ones((7, 7), np.uint8))
    dark = cv2.resize(blur(dark, 4), (linear.shape[1], linear.shape[0]), interpolation=cv2.INTER_LINEAR)
    air = np.percentile(linear.reshape(-1, 3), 99.7, axis=0).astype(np.float32)
    air = np.maximum(air, 0.2)
    if amount > 0:
        transmission = np.clip(1 - 0.95 * amount * dark / float(air.mean()), 0.25, 1)[..., None]
        return (linear - air) / transmission + air
    return linear * (1 + 0.6 * amount) - air * 0.6 * amount * (0.5 + 0.5 * (1 - dark[..., None]))


def finishing(v, recipe, scale, seed=7):
    height, width = v.shape[:2]
    fade = number(recipe, 'fade') / 100
    if fade:
        v = v * (1 - 0.14 * fade) + 0.1 * fade
    glow = number(recipe, 'glow') / 100
    halation = number(recipe, 'halation') / 100
    if glow or halation:
        lum = np.clip(luma(v), 0, 1)
        bright = (v * smoothstep(0.65, 1.0, lum)[..., None]).astype(np.float32)
        if glow:
            soft = np.stack([blur(bright[..., c], scale * 0.03) for c in range(3)], -1)
            v = 1 - (1 - v) * (1 - soft * glow * 0.8)
        if halation:
            red = blur(bright.max(-1), scale * 0.012)
            v = v + red[..., None] * np.array([0.9, 0.35, 0.1], np.float32) * halation * 0.5
    vignette = number(recipe, 'vignette') / 100
    if vignette:
        y, x = np.mgrid[0:height, 0:width].astype(np.float32)
        distance = np.sqrt(((x - width / 2) / (width / 2)) ** 2 + ((y - height / 2) / (height / 2)) ** 2) / math.sqrt(2)
        weight = smoothstep(0.35, 1.05, distance)[..., None]
        v = v * (1 - 0.75 * vignette * weight) if vignette > 0 else v + (1 - v) * (-vignette) * 0.6 * weight
    grain = number(recipe, 'grain') / 100
    if grain:
        noise = np.random.default_rng(seed).normal(0, 1, (height, width)).astype(np.float32)
        noise = blur(noise, max(0.6, scale / 2500))
        noise = noise / max(1e-6, float(noise.std()))
        lum = np.clip(luma(v), 0, 1)
        v = v + (noise * grain * 0.045 * (0.35 + 4 * lum * (1 - lum)))[..., None]
    return v


def grade_array(rgb, recipe):
    """The graded picture for float sRGB values (H x W x 3, 0..1)."""
    scale = float(max(rgb.shape[:2]))
    linear = to_linear(rgb.astype(np.float32))
    temperature = number(recipe, 'temperature') / 100
    tint = number(recipe, 'tint') / 100
    if temperature or tint:
        gains = np.array([1 + 0.28 * temperature, 1 - 0.22 * tint, 1 - 0.32 * temperature], np.float32)
        before = luma(linear)
        linear = linear * gains
        linear = linear * (before / np.maximum(luma(linear), 1e-5))[..., None]
    exposure = number(recipe, 'exposure')
    if exposure:
        linear = linear * (2 ** exposure)
    linear = dehaze(linear, number(recipe, 'dehaze') / 100, scale)
    v = to_srgb(linear).astype(np.float32)
    # Highlights pushed past white by exposure roll off instead of clipping.
    over = v.max(-1, keepdims=True)
    v = np.where(over > 1, luma(v)[..., None] + (v - luma(v)[..., None]) / np.maximum(over, 1), v)
    v = np.where(v > 0.9, 0.9 + (1 - np.exp(-(v - 0.9) * 10)) * 0.1, v)
    v = tone(v, recipe, scale)
    for key, channel in (('curve', None), ('curve_red', 0), ('curve_green', 1), ('curve_blue', 2)):
        points = recipe.get(key)
        if isinstance(points, list) and len(points) >= 2:
            lut = curve_lut(points)
            if channel is None:
                v = apply_lut(v, lut)
            else:
                v[..., channel] = apply_lut(v[..., channel], lut)
    v = color_balance(v, recipe)
    v = wheels(v, recipe)
    v = local_contrast(v, recipe, scale)
    v = finishing(v, recipe, scale)
    return np.clip(v, 0, 1)


# ---- Masks --------------------------------------------------------------------------------

MASK = """mask kinds: {"kind": "everything"} | {"kind": "object", "target": "the sky"} (AI selection) |
{"kind": "luminance", "from": 0..100, "to": 0..100} (shadows 0-35, highlights 65-100) |
{"kind": "color", "hue": 0..360, "range": 10..90} | {"kind": "linear", "from": "top"|"bottom"|"left"|"right",
"start": 0..100, "end": 0..100} (graduated filter) | {"kind": "radial", "x": 0..100, "y": 0..100,
"size": 5..150, "inside": true} ; plus "invert": bool, "feather": 0..100"""


def percent(value, limit=100):
    """A position in percent. Vision models often answer on a 0..1000 scale instead."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and limit < value <= 1000:
        return value / 10
    return value


def make_mask(rgb, spec, segment=None):
    """A float mask (H x W, 0..1) for `spec`; `segment(target) -> PIL L mask` does object masks."""
    height, width = rgb.shape[:2]
    if not spec:
        return None
    spec = {key: percent(value, 200 if key == 'size' else 100)
            if key in ('from', 'to', 'start', 'end', 'x', 'y', 'size') else value for key, value in spec.items()}
    kind = str(spec.get('kind', 'everything')).lower()
    if kind == 'everything':
        mask = np.ones((height, width), np.float32)
    elif kind == 'object':
        if segment is None:
            raise ValueError('Selecting objects needs the selection model.')
        picture = segment(str(spec.get('target') or 'the subject'))
        mask = np.asarray(picture.convert('L').resize((width, height)), np.float32) / 255
    elif kind == 'luminance':
        lum = np.clip(luma(rgb), 0, 1) * 100
        low, high = sorted((float(spec.get('from', 0)), float(spec.get('to', 100))))
        soft = max(4.0, (high - low) * 0.25)
        mask = smoothstep(low - soft, low + soft, lum) * (1 - smoothstep(high - soft, high + soft, lum))
        if low <= 0:
            mask = 1 - smoothstep(high - soft, high + soft, lum)
        if high >= 100:
            mask = smoothstep(low - soft, low + soft, lum) if low > 0 else np.ones_like(lum)
    elif kind == 'color':
        hue, sat, _ = rgb_to_hsl(np.clip(rgb, 0, 1))
        distance = np.abs((hue - float(spec.get('hue', 0)) + 180) % 360 - 180)
        span = max(5.0, float(spec.get('range', 30)))
        mask = (1 - smoothstep(span * 0.6, span, distance)) * smoothstep(0.06, 0.25, sat)
    elif kind == 'linear':
        side = str(spec.get('from', 'top')).lower()
        y, x = np.mgrid[0:height, 0:width].astype(np.float32)
        position = {'top': y / height, 'bottom': 1 - y / height, 'left': x / width,
                    'right': 1 - x / width}.get(side, y / height) * 100
        start, end = float(spec.get('start', 0)), float(spec.get('end', 50))
        mask = 1 - smoothstep(start, max(start + 1, end), position)
    elif kind == 'radial':
        y, x = np.mgrid[0:height, 0:width].astype(np.float32)
        cx, cy = float(spec.get('x', 50)) / 100 * width, float(spec.get('y', 50)) / 100 * height
        radius = float(spec.get('size', 60)) / 100 * max(width, height) / 2
        distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max(1.0, radius)
        mask = 1 - smoothstep(0.55, 1.0, distance)
        if spec.get('inside') is False:
            mask = 1 - mask
    else:
        raise ValueError(f'Unknown mask kind "{kind}".')
    feather = float(spec.get('feather', 0) or 0)
    if feather:
        mask = blur(mask.astype(np.float32), max(width, height) * feather / 100 * 0.03)
    if spec.get('invert'):
        mask = 1 - mask
    return np.clip(mask, 0, 1).astype(np.float32)


# ---- Entry points -------------------------------------------------------------------------

def to_array(image):
    return np.asarray(image.convert('RGB'), np.float32) / 255


def to_image(array):
    return Image.fromarray((np.clip(array, 0, 1) * 255 + 0.5).astype(np.uint8))


def grade(image, recipe, segment=None):
    """(graded RGB image, mask as an L image or None) for a PIL image and a recipe."""
    rgb = to_array(image)
    out = grade_array(rgb, recipe or {})
    mask = make_mask(rgb, recipe.get('mask'), segment) if isinstance(recipe.get('mask'), dict) else None
    amount = number(recipe, 'amount', 100) / 100
    if mask is not None or amount < 1:
        weight = (np.ones(rgb.shape[:2], np.float32) if mask is None else mask) * amount
        out = rgb + (out - rgb) * weight[..., None]
    return to_image(out), (to_image(np.repeat(mask[..., None], 3, -1)).convert('L') if mask is not None else None)


def render_layers(image, layers, segment=None):
    """Grade layers applied in order, each on the result of the ones below it, like Krita
    layers in a group. Returns ([(name, full graded RGB image, mask L image or None,
    opacity 0..100)], final RGB image)."""
    current = image.convert('RGB')
    out = []
    for index, layer in enumerate(layers or []):
        if not isinstance(layer, dict):
            continue
        name = str(layer.get('name') or f'Grade {index + 1}')[:60]
        rgb = to_array(current)
        graded = grade_array(rgb, layer)
        mask = make_mask(rgb, layer.get('mask'), segment) if isinstance(layer.get('mask'), dict) else None
        opacity = number(layer, 'amount', 100)
        weight = (np.ones(rgb.shape[:2], np.float32) if mask is None else mask) * opacity / 100
        current = to_image(rgb + (graded - rgb) * weight[..., None])
        out.append((name, to_image(graded), to_image(np.repeat(mask[..., None], 3, -1)).convert('L')
                    if mask is not None else None, opacity))
    return out, current


# Looks as grade layers. Masks may name the light source's position ('light_x', 'light_y') and
# the horizon height ('horizon'), which build_layers fills in for the photo at hand.
LOOKS = {
    'sunset': [
        dict(name='Sunset light', temperature=38, tint=10, exposure=-0.3, contrast=12, highlights=-30, shadows=8,
             hsl=dict(blue=dict(saturation=-10, hue=25), aqua=dict(saturation=-12), orange=dict(saturation=12)),
             split_toning=dict(shadow_hue=255, shadow_saturation=28, highlight_hue=28, highlight_saturation=40),
             halation=15),
        dict(name='Deep upper sky', mask=dict(kind='linear', **{'from': 'top'}, start=0, end='horizon'), exposure=-0.35,
             temperature=-10, tint=25, saturation=15, midtones_color=dict(hue=262, amount=40)),
        dict(name='Horizon glow', mask=dict(kind='radial', x='light_x', y='light_y', size=130), temperature=45, tint=12,
             highlights_color=dict(hue=24, amount=60), midtones_color=dict(hue=18, amount=30), glow=30, amount=85),
        dict(name='Darker edges', vignette=35),
    ],
    'golden hour': [
        dict(name='Golden light', temperature=28, tint=6, exposure=0.05, highlights=-15, shadows=18, vibrance=18,
             highlights_color=dict(hue=40, amount=30), halation=18),
        dict(name='Warm horizon', mask=dict(kind='radial', x='light_x', y='light_y', size=120), temperature=20, tint=12,
             highlights_color=dict(hue=36, amount=35), glow=15, amount=80),
    ],
    'sunrise': [
        dict(name='Sunrise light', temperature=18, tint=14, exposure=-0.1, highlights=-20, shadows=12,
             split_toning=dict(shadow_hue=220, shadow_saturation=22, highlight_hue=345, highlight_saturation=28)),
        dict(name='Pink sky', mask=dict(kind='linear', **{'from': 'top'}, start=0, end='horizon'), tint=25,
             temperature=15, highlights_color=dict(hue=340, amount=35)),
    ],
    'blue hour': [
        dict(name='Blue hour', temperature=-35, exposure=-0.9, contrast=8, highlights=-20, saturation=-10,
             shadows_color=dict(hue=225, amount=40), midtones_color=dict(hue=230, amount=25)),
        dict(name='Deep sky', mask=dict(kind='linear', **{'from': 'top'}, start=0, end='horizon'), exposure=-0.2,
             midtones_color=dict(hue=250, amount=30)),
    ],
    'night': [
        dict(name='Night', temperature=-45, exposure=-1.8, contrast=15, highlights=-35, saturation=-35,
             shadows_color=dict(hue=225, amount=50), midtones_color=dict(hue=220, amount=35), vignette=40),
    ],
    'overcast': [
        dict(name='Overcast', temperature=-8, contrast=-18, highlights=-25, shadows=15, saturation=-25,
             dehaze=-15, fade=10),
    ],
    'midday': [dict(name='Midday sun', temperature=-4, contrast=12, whites=10, vibrance=10, clarity=10)],
    'teal and orange': [
        dict(name='Teal and orange', contrast=18, shadows_color=dict(hue=190, amount=45),
             highlights_color=dict(hue=32, amount=35), hsl=dict(orange=dict(saturation=15), blue=dict(hue=-20)),
             vibrance=12, clarity=12),
    ],
    'film': [
        dict(name='Film look', fade=40, contrast=-8, curve=[[0, 16], [64, 60], [128, 132], [192, 200], [255, 246]],
             saturation=-15, split_toning=dict(shadow_hue=200, shadow_saturation=18, highlight_hue=45,
                                               highlight_saturation=20), halation=12, grain=30),
    ],
    'black and white': [
        dict(name='Black and white', saturation=-100, contrast=25, clarity=20, hsl=dict(blue=dict(luminance=-35)),
             vignette=25),
    ],
}


ADJUST = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks', 'temperature', 'tint', 'vibrance',
          'saturation', 'clarity', 'texture', 'dehaze', 'fade', 'glow', 'halation', 'vignette', 'grain')


def scale_layer(layer, factor):
    """A look layer with every adjustment scaled by `factor` (hue angles, masks, curves and
    the layer's opacity kept)."""
    def scale(key, value, angles):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (angles and 'hue' in key):
            return value
        return round(value * factor, 3)

    out = {}
    for key, value in layer.items():
        if key in ('name', 'mask', 'amount') or key.startswith('curve'):
            out[key] = value
        elif key == 'hsl':
            out[key] = {band: {k: scale(k, v, False) for k, v in values.items()} for band, values in value.items()}
        elif isinstance(value, dict):
            out[key] = {k: scale(k, v, True) for k, v in value.items()}
        else:
            out[key] = scale(key, value, False)
    if isinstance(layer.get('curve'), list):
        out['curve'] = [[x, x + (y - x) * factor] for x, y in layer['curve']]
    return out


def build_layers(look=None, strength=100, light_x=None, light_y=None, horizon=None, adjust=None, local=None):
    """The grade layers for a look placed on this photo, then global adjustments, then local
    layers. strength 0..150 scales the look; positions are percent (x from the left, y from
    the top) of the light source and the horizon."""
    horizon = percent(horizon) if isinstance(horizon, (int, float)) else 35
    places = dict(horizon=horizon,
                  light_x=percent(light_x) if isinstance(light_x, (int, float)) else 25,
                  light_y=percent(light_y) if isinstance(light_y, (int, float)) else horizon)
    factor = max(0.0, min(1.5, float(strength if strength is not None else 100) / 100))
    layers = []
    for template in LOOKS.get(look or '', []):
        layer = scale_layer(template, factor)
        if isinstance(layer.get('mask'), dict):
            layer['mask'] = {k: places.get(v, v) if isinstance(v, str) and k != 'kind' and k != 'from' else v
                             for k, v in layer['mask'].items()}
        layers.append(layer)
    adjust = {key: value for key, value in (adjust or {}).items() if key in ADJUST and value}
    if adjust:
        layers.append(dict(name='Adjustments', **adjust))
    layers += [layer for layer in local or [] if isinstance(layer, dict)]
    return layers


def stats(image):
    """Measurements a colorist looks at, for the planner: exposure, clipping, contrast,
    color cast, saturation, and the light of the top, middle and bottom of the picture."""
    small = image.convert('RGB')
    small.thumbnail((512, 512))
    rgb = to_array(small)
    lum = luma(rgb)
    hue, sat, _ = rgb_to_hsl(rgb)
    mean = rgb.reshape(-1, 3).mean(0)
    p = np.percentile(lum, [1, 5, 50, 95, 99])
    neutral = (sat < 0.25) & (lum > 0.15) & (lum < 0.9)
    cast = rgb[neutral].mean(0) - rgb[neutral].mean() if neutral.sum() > 100 else mean - mean.mean()
    thirds = np.array_split(lum, 3, axis=0)
    return dict(
        median_brightness=round(float(p[2]) * 100),
        darkest_1pct=round(float(p[0]) * 100),
        brightest_1pct=round(float(p[4]) * 100),
        clipped_highlights_pct=round(float((lum > 0.985).mean()) * 100, 1),
        crushed_shadows_pct=round(float((lum < 0.015).mean()) * 100, 1),
        contrast_5_95=round(float(p[3] - p[1]) * 100),
        average_saturation=round(float(sat.mean()) * 100),
        color_cast_rgb=[round(float(c) * 255) for c in cast],
        brightness_top_middle_bottom=[round(float(t.mean()) * 100) for t in thirds],
    )

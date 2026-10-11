"""Layout sketches: simple shaded shapes that pin down what goes where.

SDXL often gets counts, colors and positions wrong from words alone. Starting
from a sketch of the right shapes in the right places (image-to-image) fixes
those, and the model only has to make the sketch look real."""

import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter

SUPERSAMPLE = 2


def color(name, fallback=(150, 150, 150)):
    """An RGB color from a name such as 'red', 'light grey' or '#ff0000'."""
    name = ' '.join(str(name or '').strip().lower().replace('gray', 'grey').replace('-', ' ').split())
    candidates = [name, name.replace(' ', ''), name.split()[-1] if name.split() else '']
    for candidate in candidates:
        try:
            return ImageColor.getrgb(candidate.replace('grey', 'gray'))
        except ValueError:
            continue
    return fallback


def shade(rgb, factor):
    """Darker below 1, toward white above 1."""
    if factor <= 1:
        return tuple(round(c * factor) for c in rgb)
    return tuple(round(c + (255 - c) * (factor - 1)) for c in rgb)


def percent_boxes(objects):
    """Each object's (x, y, w, h) in percent. A plan that runs past an edge is scaled
    back inside as a whole, so objects keep their order and gaps instead of piling up."""

    def number(obj, key, default):
        try:
            return min(max(float(obj.get(key, default)), 0), 100)
        except (TypeError, ValueError):
            return default

    boxes = [
        [
            number(obj, 'x', 40),
            number(obj, 'y', 40),
            max(number(obj, 'w', 20), 3),
            max(number(obj, 'h', 20), 3),
        ]
        for obj in objects
    ]
    for start, size in ((0, 2), (1, 3)):
        low = min(b[start] for b in boxes)
        high = max(b[start] + b[size] for b in boxes)
        if high > 98:
            scale = (98 - low) / (high - low)
            for b in boxes:
                b[start], b[size] = low + (b[start] - low) * scale, b[size] * scale
                if start == 0:
                    # Shrink the height too, standing on the same ground line, to keep proportions.
                    b[1], b[3] = b[1] + b[3] * (1 - scale), b[3] * scale
    return boxes


def box(percent, width, height):
    """A percent box in pixels, kept inside the picture."""
    x, y, w, h = percent
    x, y = min(x, 100 - w), min(y, 100 - h)
    return x * width / 100, y * height / 100, w * width / 100, h * height / 100


def draw_sphere(canvas, x, y, w, h, rgb):
    size = min(w, h)
    left, top = int(x + (w - size) / 2), int(y + h - size)
    r = size / 2
    patch = canvas.crop((left, top, left + int(size) + 1, top + int(size) + 1))
    yy, xx = np.mgrid[0 : patch.height, 0 : patch.width].astype(np.float32)
    inside = (xx - r) ** 2 + (yy - r) ** 2 <= r * r
    # Light from the upper left: brightest near the highlight, darker toward the far edge.
    distance = np.sqrt((xx - r * 0.65) ** 2 + (yy - r * 0.65) ** 2) / (r * 1.6)
    factor = np.clip(1.35 - distance, 0.45, 1.35)[..., None]
    base = np.array(rgb, dtype=np.float32)
    lit = np.where(factor <= 1, base * factor, base + (255 - base) * (factor - 1))
    pixels = np.asarray(patch, dtype=np.float32).copy()
    pixels[inside] = lit[inside]
    canvas.paste(Image.fromarray(pixels.clip(0, 255).astype(np.uint8)), (left, top))


def draw_cube(draw, x, y, w, h, rgb):
    # Percent boxes on a wide or tall canvas are not square in pixels; a cube must be.
    size = min(w, h)
    draw_box(draw, x + (w - size) / 2, y + h - size, size, size, rgb)


def draw_box(draw, x, y, w, h, rgb):
    d = min(w, h) * 0.28
    front = [(x, y + d), (x + w - d, y + d), (x + w - d, y + h), (x, y + h)]
    top = [(x, y + d), (x + d, y), (x + w, y), (x + w - d, y + d)]
    side = [(x + w - d, y + d), (x + w, y), (x + w, y + h - d), (x + w - d, y + h)]
    draw.polygon(front, fill=rgb)
    draw.polygon(top, fill=shade(rgb, 1.3))
    draw.polygon(side, fill=shade(rgb, 0.65))


def draw_pyramid(draw, x, y, w, h, rgb):
    apex, split = (x + w * 0.45, y), (x + w * 0.62, y + h)
    draw.polygon([apex, (x, y + h * 0.94), split], fill=rgb)
    draw.polygon([apex, split, (x + w, y + h * 0.9)], fill=shade(rgb, 0.62))


def draw_cone(draw, x, y, w, h, rgb):
    apex = (x + w / 2, y)
    draw.ellipse([x, y + h * 0.9, x + w, y + h], fill=shade(rgb, 0.7))
    draw.polygon([apex, (x, y + h * 0.95), (x + w / 2, y + h)], fill=shade(rgb, 1.1))
    draw.polygon([apex, (x + w / 2, y + h), (x + w, y + h * 0.95)], fill=shade(rgb, 0.7))


def draw_cylinder(draw, x, y, w, h, rgb):
    cap = min(h * 0.25, w * 0.35)
    draw.ellipse([x, y + h - cap, x + w, y + h], fill=shade(rgb, 0.7))
    draw.rectangle([x, y + cap / 2, x + w / 2, y + h - cap / 2], fill=rgb)
    draw.rectangle([x + w / 2, y + cap / 2, x + w, y + h - cap / 2], fill=shade(rgb, 0.75))
    draw.ellipse([x, y, x + w, y + cap], fill=shade(rgb, 1.25))


def draw_bottle(draw, x, y, w, h, rgb):
    neck = w * 0.32
    draw.rectangle([x + (w - neck) / 2, y, x + (w + neck) / 2, y + h * 0.35], fill=shade(rgb, 0.85))
    draw.rounded_rectangle([x, y + h * 0.3, x + w, y + h], radius=w * 0.25, fill=rgb)
    draw.rectangle([x + w * 0.6, y + h * 0.4, x + w * 0.85, y + h * 0.95], fill=shade(rgb, 0.75))


def draw_person(draw, x, y, w, h, rgb):
    head = min(w * 0.45, h * 0.16)
    draw.ellipse([x + w / 2 - head / 2, y, x + w / 2 + head / 2, y + head], fill=(200, 160, 130))
    draw.rounded_rectangle([x + w * 0.1, y + head * 1.1, x + w * 0.9, y + h * 0.6], radius=w * 0.2, fill=rgb)
    draw.rectangle([x + w * 0.2, y + h * 0.58, x + w * 0.8, y + h], fill=shade(rgb, 0.6))


SHAPES = {
    'cube': draw_cube,
    'box': draw_box,
    'pyramid': draw_pyramid,
    'cone': draw_cone,
    'cylinder': draw_cylinder,
    'bottle': draw_bottle,
    'person': draw_person,
}


def draw(plan, width, height, seed=0):
    """Render a layout plan ({'background', 'objects': [...]}) as an RGB sketch."""
    W, H = width * SUPERSAMPLE, height * SUPERSAMPLE
    background = color(plan.get('background'), (236, 236, 236))
    # A soft vertical gradient reads as a wall meeting a surface rather than a flat card.
    ramp = np.linspace(1.04, 0.9, H, dtype=np.float32)[:, None, None]
    canvas = Image.fromarray(
        np.clip(np.array(background, np.float32) * ramp, 0, 255).astype(np.uint8).repeat(W, axis=1)
    )
    objects = [obj for obj in plan.get('objects', []) if isinstance(obj, dict)]
    boxes = [box(percent, W, H) for percent in percent_boxes(objects)] if objects else []
    # Contact shadows first, so every object sits on them.
    shadows = Image.new('L', (W, H), 0)
    shadow_draw = ImageDraw.Draw(shadows)
    for x, y, w, h in boxes:
        shadow_draw.ellipse([x - w * 0.05, y + h - h * 0.06, x + w * 1.15, y + h + h * 0.08], fill=120)
    shadows = shadows.filter(ImageFilter.GaussianBlur(W / 120))
    canvas = Image.composite(Image.new('RGB', (W, H), shade(background, 0.55)), canvas, shadows)
    # Far objects (higher up) first, so nearer ones overlap them.
    for obj, (x, y, w, h) in sorted(zip(objects, boxes), key=lambda item: item[1][1] + item[1][3]):
        rgb = color(obj.get('color'))
        shape = str(obj.get('shape', '')).lower()
        if shape in ('sphere', 'ball'):
            draw_sphere(canvas, x, y, w, h, rgb)
        else:
            painter = SHAPES.get(shape)
            if painter:
                painter(ImageDraw.Draw(canvas), x, y, w, h, rgb)
            else:
                ImageDraw.Draw(canvas).rounded_rectangle(
                    [x, y, x + w, y + h], radius=min(w, h) * 0.2, fill=rgb
                )
    canvas = canvas.resize((width, height), Image.LANCZOS)
    # Light grain gives the photo model texture to build on instead of flat paint.
    noise = np.random.default_rng(seed).normal(0, 6, (height, width, 1)).astype(np.float32)
    return Image.fromarray(np.clip(np.asarray(canvas, np.float32) + noise, 0, 255).astype(np.uint8))


def from_editor(value):
    """The sketch from the layout editor as RGB on white, or None when it is empty."""
    if not value or value.get('composite') is None:
        return None
    image = value['composite']
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        flat = Image.new('RGB', image.size, 'white')
        flat.paste(image, mask=image.getchannel('A'))
        image = flat
    image = image.convert('RGB')
    if ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox() is None:
        return None
    return image

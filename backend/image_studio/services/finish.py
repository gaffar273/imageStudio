"""Photo finish: the small flaws a real camera adds, which generated images lack.

Generated pictures are noise-free, evenly saturated and perfectly sharp to the corners,
which reads as artificial even when the content is right. This adds, lightly:
- slightly muted colours and lifted blacks (real sensors and film do not reach pure black),
- a faint darkening toward the corners (lens vignetting),
- a sub-pixel colour fringe toward the edges (lateral chromatic aberration),
- grain that is strongest in the midtones, as in real sensor noise and film.
Everything is seeded, so the same image and seed give the same result."""

import numpy as np
from PIL import Image, ImageFilter

FINISHES = ['Off', 'Light', 'Film']
DEFAULT_FINISH = 'Light'
SETTINGS = {
    # saturation, black lift, vignette, colour fringe (share of the half-diagonal), grain, grain size (pixels)
    'Light': dict(saturation=0.94, lift=0.012, vignette=0.07, fringe=0.0007, grain=0.014, grain_size=1.0),
    'Film': dict(saturation=0.86, lift=0.03, vignette=0.14, fringe=0.0012, grain=0.022, grain_size=1.6),
}


def fringe(image, amount):
    """Red slightly larger and blue slightly smaller than green, around the centre."""
    if amount <= 0:
        return image
    red, green, blue = image.split()
    width, height = image.size

    def scaled(channel, factor):
        size = (round(width * factor), round(height * factor))
        resized = channel.resize(size, Image.BICUBIC)
        left, top = (size[0] - width) // 2, (size[1] - height) // 2
        if factor >= 1:
            return resized.crop((left, top, left + width, top + height))
        canvas = channel.copy()
        canvas.paste(resized, (-left, -top))
        return canvas

    return Image.merge('RGB', (scaled(red, 1 + amount), green, scaled(blue, 1 - amount)))


def finish(image, level='Light', seed=0):
    """The picture with a photo finish; 'Off' returns it unchanged."""
    if level not in SETTINGS:
        return image
    s = SETTINGS[level]
    image = fringe(image.convert('RGB'), s['fringe'])
    pixels = np.asarray(image, dtype=np.float32) / 255
    height, width = pixels.shape[:2]
    luma = pixels @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    pixels = luma[..., None] + (pixels - luma[..., None]) * s['saturation']
    pixels = s['lift'] + pixels * (1 - s['lift'])
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    radius = ((x - width / 2) ** 2 + (y - height / 2) ** 2) / ((width / 2) ** 2 + (height / 2) ** 2)
    pixels *= (1 - s['vignette'] * radius**1.5)[..., None]

    # Grain: mostly brightness noise with a little colour, made at a coarser size and smoothed.
    rng = np.random.default_rng(seed)
    small = (max(1, round(width / s['grain_size'])), max(1, round(height / s['grain_size'])))
    noise = rng.standard_normal((small[1], small[0], 3)).astype(np.float32)
    noise = noise[..., :1] * 0.85 + noise * 0.15
    grain = Image.fromarray(np.clip(noise * 40 + 128, 0, 255).astype(np.uint8))
    grain = grain.resize((width, height), Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.4))
    grain = (np.asarray(grain, dtype=np.float32) - 128) / 40
    midtones = 0.35 + 2.6 * luma * (1 - luma)
    pixels += grain * s['grain'] * midtones[..., None]
    return Image.fromarray(np.clip(pixels * 255 + 0.5, 0, 255).astype(np.uint8))

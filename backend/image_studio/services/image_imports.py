"""Bounded image imports shared by the two layered editors."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILES = 16
MAX_BYTES = 100_000_000


async def read_files(files):
    """Read one batch with a total byte limit, closing every upload even on failure."""
    try:
        if not 1 <= len(files) <= MAX_FILES:
            raise ValueError(f'Choose between 1 and {MAX_FILES} images at a time.')
        result, total = [], 0
        for file in files:
            contents = await file.read(MAX_BYTES - total + 1)
            total += len(contents)
            if not contents or total > MAX_BYTES:
                raise ValueError('Choose nonempty files totaling at most 100 MB.')
            result.append((file.filename or 'image.png', contents))
        return result
    finally:
        for file in files:
            await file.close()


def decode_layer(contents):
    """Normalize orientation and preserve alpha; reject oversized images before decoding."""
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Each image layer must be at most 40 megapixels.')
            return ImageOps.exif_transpose(image).convert('RGBA')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Use PNG, JPEG, WebP, TIFF or BMP images for layers.') from exc

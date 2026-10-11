"""Select by description ("the dog", "the woman on the left", "sky", "background").

1. The prompt assistant (Qwen3-VL-2B) finds each matching thing and answers with boxes.
   Measured on saved pictures: a cat, a suitcase, a dog, the sky, "the person on the far
   left" and "her shirt" were all boxed correctly, in about 7 s each.
2. SAM 2.1 large outlines what is inside each box, so the selection follows the edge of
   the object instead of being a rectangle.

"background" is everything except the main subjects; "subject" is the main subjects."""

import json
import re
from PIL import Image, ImageChops, ImageFilter
from image_studio.core.catalog import SEGMENT

WHOLE = {
    'all',
    'everything',
    'whole picture',
    'the whole picture',
    'entire image',
    'the image',
    'image',
    'picture',
}
SUBJECT = {
    'subject',
    'the subject',
    'main subject',
    'the main subject',
    'foreground',
    'the foreground',
    'person',
    'the person',
    'subjects',
    'the subjects',
}
BACKGROUND = {'background', 'the background', 'backdrop', 'the backdrop'}
SUBJECT_QUERY = 'the main subjects (the people, animals or objects the photo is about)'
LONGEST = 1536  # pictures are looked at and outlined at most this large


def available():
    path = SEGMENT['folder'] / SEGMENT['file']
    return path.exists() and path.stat().st_size == SEGMENT['size']


def parse_boxes(answer, width, height):
    """Pixel boxes from Qwen3-VL's answer ([{"bbox_2d": [x0, y0, x1, y1]}], 0-1000 scale)."""
    text = re.sub(r'<think>.*?</think>', '', answer, flags=re.S)
    match = re.search(r'\[.*\]', text, flags=re.S)
    boxes = []
    if match:
        try:
            items = json.loads(match.group(0))
        except ValueError:
            items = [
                {'bbox_2d': [float(v) for v in found]}
                for found in re.findall(
                    r'\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', text
                )
            ]
        for item in items if isinstance(items, list) else []:
            box = item.get('bbox_2d') if isinstance(item, dict) else item
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                x0, y0, x1, y1 = (float(v) for v in box)
            except (TypeError, ValueError):
                continue
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            box = (x0 * width / 1000, y0 * height / 1000, x1 * width / 1000, y1 * height / 1000)
            if box[2] - box[0] >= 2 and box[3] - box[1] >= 2:
                boxes.append(tuple(round(v) for v in box))
    return boxes


def find_boxes(image, target, session):
    answer = session.ask(
        None,
        [],
        f'Locate {target} in the image. Output the bounding box of each one as JSON: '
        '[{"bbox_2d": [x1, y1, x2, y2], "label": "..."}].',
        image=image,
        max_new_tokens=400,
        repetition_penalty=1.0,
        image_size=1024,
        prefix='',
    )
    return parse_boxes(answer, *image.size)


BOXES_SCHEMA = {
    'type': 'object',
    'properties': {'boxes': {'type': 'array', 'maxItems': 24, 'items': {
        'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4}}},
    'required': ['boxes'], 'additionalProperties': False,
}


def find_boxes_brain(image, target):
    """Boxes from the editing brain (Qwen3.5-9B), which finds every separate object: on a
    town photo it boxed the buildings one by one, where the 2B assistant gave one box. The wording
    is measured: with “(each building, each person...)” it found no box for the hair of a
    portrait, and adding a line about parts of a person to that lost the beard and glasses too;
    this one found hair, beard, glasses, chairs, a plant and three separate curtains."""
    from image_studio.services import brain

    answer = brain.chat(
        'You locate objects in photos precisely. Coordinates are on a 0-1000 scale: x from the left, '
        'y from the top.',
        [brain.image_part(image), {'type': 'text', 'text':
            f'Locate {target}. Give one tight box [x1, y1, x2, y2] for each separate one, or one box when it '
            'is a single thing. Parts of a person (hair, face, hands, beard, clothing) count. '
            'JSON: {"boxes": [...]}'}],
        schema=BOXES_SCHEMA, max_tokens=800, temperature=0.0)
    return parse_boxes(json.dumps([{'bbox_2d': box} for box in answer.get('boxes') or []]), *image.size)


def tidy(mask):
    """Close cracks and fill small holes (windows, gaps between tiles) in a selection."""
    import cv2
    import numpy as np

    array = (np.asarray(mask) > 127).astype(np.uint8)
    size = max(3, round(max(array.shape) / 200)) | 1
    array = cv2.morphologyEx(array, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1 - array, connectivity=4)
    small = array.size * 0.002
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        touches_edge = x == 0 or y == 0 or x + w == array.shape[1] or y + h == array.shape[0]
        if area < small and not touches_edge:
            array[labels == index] = 1
    return Image.fromarray(array * 255)


def outline(image, boxes, missing=None):
    """One mask (L) covering what SAM finds inside each box; a box SAM cannot outline
    is used as it is, or, given a `missing` list, left out and its index added there."""
    import numpy as np
    import os

    os.environ.setdefault('YOLO_OFFLINE', '1')
    from ultralytics import SAM, settings
    from image_studio.services import assistant

    settings.update({'sync': False})
    mask = Image.new('L', image.size, 0)
    model = SAM(str(SEGMENT['folder'] / SEGMENT['file']))
    # The editing brain fills most of the GPU while it is kept; SAM then runs on the processor
    # rather than stopping the brain, which takes about 20 s to start again.
    device = 'cpu' if assistant.kept_kind() == 'brain' else None
    pixels = np.asarray(image.convert('RGB'))
    found = []
    try:
        # One box per call: ultralytics' SAM 2 fails an assertion when given several boxes at
        # once (image_embeddings.shape[0] == tokens.shape[0]).
        for box in boxes:
            result = model(pixels, bboxes=[list(box)], verbose=False, device=device)[0]
            masks = result.masks.data.cpu().numpy() if result.masks is not None else []
            found.append(masks[0] if len(masks) else np.zeros(pixels.shape[:2], dtype=bool))
    finally:
        del model
        import torch

        torch.cuda.empty_cache()
    for index, box in enumerate(boxes):
        if index < len(found) and found[index].any():
            piece = Image.fromarray((found[index] > 0.5).astype('uint8') * 255).resize(
                image.size, Image.NEAREST
            )
        elif missing is not None:
            missing.append(index)
            continue
        else:
            piece = Image.new('L', image.size, 0)
            piece.paste(255, box)
        mask = ImageChops.lighter(mask, piece)
    return mask


def select(image, target, status=print):
    """(mask L at the image's size, note). Raises ValueError when nothing matches."""
    from image_studio.services import assistant

    key = ' '.join(target.lower().split())
    if key in WHOLE:
        return Image.new('L', image.size, 255), 'Selected the whole picture.'
    invert = key in BACKGROUND
    query = SUBJECT_QUERY if invert or key in SUBJECT else target
    small = image.convert('RGB')
    small.thumbnail((LONGEST, LONGEST), Image.LANCZOS)
    status(f'Finding {target}...')
    from image_studio.services import brain

    if brain.available():
        boxes = find_boxes_brain(small, query)
    else:
        with assistant.Session(keep=True) as session:
            boxes = find_boxes(small, query, session)
    if not boxes:
        raise ValueError(f'Could not find {target} in the picture.')
    if available():
        status(f'Outlining {target}...')
        mask = tidy(outline(small, boxes))
    else:
        mask = Image.new('L', small.size, 0)
        for box in boxes:
            mask.paste(255, box)
    # Close pinholes and smooth the edge a little.
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    if invert:
        mask = ImageChops.invert(mask)
    found = 'the background' if invert else f'{len(boxes)} match' + ('es' if len(boxes) > 1 else '')
    return mask.resize(image.size, Image.BILINEAR), f'Selected {found}.'

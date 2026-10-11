"""Face and hand repair (the "ADetailer" technique).

Small faces and hands get few pixels when the whole picture is drawn, so they come
out soft or malformed. Each one found by a detector is cropped with some surroundings,
enlarged to about 1024 pixels, redrawn lightly by the same model with a face- or
hand-specific prompt, shrunk back and blended in with a soft edge.

Every face gets its own prompt and its own seed. With one shared prompt and seed (and the
whole group's description in the prompt), each face was pulled toward the same face."""

import os
from PIL import Image, ImageDraw, ImageFilter
from image_studio.core.catalog import REPAIR

# No beauty words ("detailed", "sharp eyes"): they pull every face toward the same polished face.
PROMPTS = {
    'face': "close-up photo of a real person's face, natural skin texture with pores and small imperfections",
    'hand': 'close-up photo of a hand with five well-formed fingers, natural pose, realistic',
}
HAND_EXTRA = 0.1  # hands are redrawn this much more than faces: fingers need bigger changes
CONFIDENCE = 0.35
MAX_ITEMS = 12  # the most confident faces and hands
TARGET = 1024  # crops are redrawn at about this size
LARGEST = 1280  # larger crops (only faces that must change) are redrawn at up to this size
MIN_ENLARGE = 1.25  # a face already this large gains little from a redraw
PAD = 0.4  # surroundings included around each box, as a share of its size
_detectors = {}


def available():
    return (REPAIR['folder'] / 'download-complete.json').exists()


def detectors():
    """The face and hand detectors, loaded once and run on the CPU (about 0.4 s a picture)."""
    if not _detectors:
        # No update checks or usage reporting from the detector library.
        os.environ.setdefault('YOLO_OFFLINE', '1')
        from ultralytics import YOLO, settings

        settings.update({'sync': False})
        for kind in PROMPTS:
            _detectors[kind] = YOLO(str(REPAIR['folder'] / REPAIR[kind]))
    return _detectors


def detect(image):
    """[{'kind', 'box': (x0, y0, x1, y1), 'confidence'}], most confident first."""
    found = []
    for kind, model in detectors().items():
        result = model.predict(image.convert('RGB'), conf=CONFIDENCE, device='cpu', verbose=False)[0]
        for box in result.boxes:
            found.append(
                dict(
                    kind=kind,
                    box=tuple(round(v) for v in box.xyxy[0].tolist()),
                    confidence=round(float(box.conf[0]), 3),
                )
            )
    return sorted(found, key=lambda item: -item['confidence'])[:MAX_ITEMS]


def crop_area(box, size):
    """A square around the box with surroundings, kept inside the picture."""
    x0, y0, x1, y1 = box
    side = min(round(max(x1 - x0, y1 - y0) * (1 + 2 * PAD)), *size)
    left = min(max(round((x0 + x1 - side) / 2), 0), size[0] - side)
    top = min(max(round((y0 + y1 - side) / 2), 0), size[1] - side)
    return left, top, left + side, top + side


def blend_mask(box, area):
    """Opaque over the detected box, fading out softly toward the crop's edge."""
    left, top, right, bottom = area
    mask = Image.new('L', (right - left, bottom - top), 0)
    x0, y0, x1, y1 = box
    grow = 0.12 * max(x1 - x0, y1 - y0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [x0 - left - grow, y0 - top - grow, x1 - left + grow, y1 - top + grow],
        radius=0.3 * max(x1 - x0, y1 - y0),
        fill=255,
    )
    return mask.filter(ImageFilter.GaussianBlur(max(2.0, 0.08 * max(x1 - x0, y1 - y0))))


def left_to_right(items):
    return sorted(items, key=lambda item: item['box'][0] + item['box'][2])


def repair(image, items, redraw, status=print, start=0, total=None):
    """Redraw each detected face or hand, in the order given. `redraw(crop, item, index)`
    returns the crop redrawn at the same size. Returns the repaired picture and a note per item.
    Large faces are left alone unless the item says `always` (a face given a reference face
    must be redrawn to change); those are worked on at up to LARGEST pixels."""
    image = image.convert('RGB')
    notes = []
    total = total or len(items)
    for index, item in enumerate(items, start):
        area = crop_area(item['box'], image.size)
        side = area[2] - area[0]
        work = TARGET if side <= TARGET else min(round(side / 64) * 64, LARGEST)
        enlarge = work / side
        if enlarge < MIN_ENLARGE and not item.get('always'):
            notes.append(dict(item, repaired=False, reason='already large'))
            continue
        status(f'Repairing {item["kind"]} {index + 1} of {total}...')
        crop = image.crop(area).resize((work, work), Image.LANCZOS)
        redrawn = redraw(crop, item, index).resize((side, side), Image.LANCZOS)
        image.paste(redrawn, area[:2], blend_mask(item['box'], area))
        notes.append(dict(item, repaired=True, enlarged=round(enlarge, 2)))
    return image, notes

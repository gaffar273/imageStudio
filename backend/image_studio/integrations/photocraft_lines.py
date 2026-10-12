"""Straight lines measured in a photo: the tilt of a horizon, and the verticals of buildings.

A retoucher levels a horizon and squares up walls by eye; here long straight edges are found with
a Hough transform, and the angle every number depends on is measured, never guessed. PhotoCraft's
own Adaptive Wide Angle then corrects the perspective from the vertical lines it is given, the way
Upright Guided works in Camera Raw.
"""

import math

MAX_SIDE = 1024
TILT_LIMIT = 12  # degrees; a steeper “horizon” is a diagonal subject line, not a tilt


def _segments(image):
    """Long straight segments [(x0, y0, x1, y1, length)] in the image's own pixels, or None
    when OpenCV is not installed."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    picture = image.convert('L')
    scale = min(1.0, MAX_SIDE / max(picture.size))
    if scale < 1:
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)))
    gray = cv2.GaussianBlur(np.asarray(picture), (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    shortest = round(min(picture.size) * 0.18)
    found = cv2.HoughLinesP(edges, 1, math.pi / 720, threshold=80, minLineLength=shortest,
                            maxLineGap=round(shortest * 0.08))
    if found is None:
        return []
    return [(x0 / scale, y0 / scale, x1 / scale, y1 / scale, math.hypot(x1 - x0, y1 - y0) / scale)
            for x0, y0, x1, y1 in found.reshape(-1, 4).tolist()]


def _angle(segment):
    """Degrees of a segment from horizontal, -90..90, positive when it rises to the right."""
    x0, y0, x1, y1, _ = segment
    if x1 < x0:
        x0, y0, x1, y1 = x1, y1, x0, y0
    return -math.degrees(math.atan2(y1 - y0, x1 - x0))


def tilt(image):
    """Degrees to turn the picture clockwise so its horizon is level, None when no clear
    horizontal line is found (0 when it is already level)."""
    segments = _segments(image)
    if not segments:
        return None
    flat = [(segment, _angle(segment)) for segment in segments if abs(_angle(segment)) < TILT_LIMIT]
    if not flat:
        return None
    # The horizon is the strongest family of lines that agree within a degree. Measured on a coastal
    # town: a length-weighted median let three short coastline edges (4-9°) outvote the 0° horizon.
    best, best_length = None, 0.0
    for _, seed in flat:
        family = [(segment, angle) for segment, angle in flat if abs(angle - seed) <= 1.0]
        length = sum(segment[4] for segment, _ in family)
        if length > best_length:
            best, best_length = family, length
    if best_length < image.width * 0.35:
        return None
    angle = sum(segment[4] * angle for segment, angle in best) / best_length
    # A line rising to the right needs a clockwise turn to level it.
    return round(angle, 2) if abs(angle) >= 0.15 else 0.0


def _lean(segment):
    """Degrees a near-vertical segment leans from upright, positive when its top is further right."""
    return 90 - abs(_angle(segment)) if _angle(segment) > 0 else abs(_angle(segment)) - 90


def _converging(segments, width):
    """The segments that agree with one camera tilt. Tilting the camera makes upright edges lean
    towards a point above (or below) the middle: little near the centre, more towards the sides,
    and the same way on each side. A splayed chair leg leaning 7° just off-centre fits no tilt
    (measured in a living room), so it is dropped, as is the minority leaning the other way."""
    kept = []
    for segment in segments:
        offset = ((segment[0] + segment[2]) / 2 - width / 2) / width
        if abs(_lean(segment)) <= 1.0 + 20 * abs(offset):
            kept.append((segment, offset))
    votes = [math.copysign(1, _lean(s) * offset) for s, offset in kept if abs(_lean(s)) > 0.6 and abs(offset) > 0.05]
    if votes:
        way = 1 if sum(votes) >= 0 else -1
        kept = [(s, offset) for s, offset in kept
                if abs(_lean(s)) <= 0.6 or abs(offset) <= 0.05 or math.copysign(1, _lean(s) * offset) == way]
    return [segment for segment, _ in kept]


def verticals(image, limit=4):
    """The longest near-vertical lines [[x0, y0], [x1, y1]] (image pixels) that should be upright,
    spread across the frame, or [] when there are none."""
    segments = _segments(image) or []
    # Converging walls lean a few degrees; a chair leg at 12° is not a wall. Building edges in a
    # street scene are short (166 px of an 832 px café photo, broken by arches and windows), so any
    # edge the line finder keeps counts.
    upright = [segment for segment in segments if abs(abs(_angle(segment)) - 90) < 10
               and segment[4] >= min(image.size) * 0.18]
    upright = _converging(upright, image.width)
    upright.sort(key=lambda segment: segment[4], reverse=True)
    chosen = []
    for segment in upright:
        middle = (segment[0] + segment[2]) / 2
        # Two edges of one pillar say the same thing; keep lines from different parts of the frame.
        if all(abs(middle - (other[0] + other[2]) / 2) > image.width * 0.08 for other in chosen):
            chosen.append(segment)
        if len(chosen) == limit:
            break
    # Top end first, so a line's lean reads the same whichever way the finder traced it.
    return [sorted([[round(s[0]), round(s[1])], [round(s[2]), round(s[3])]], key=lambda point: point[1])
            for s in chosen]

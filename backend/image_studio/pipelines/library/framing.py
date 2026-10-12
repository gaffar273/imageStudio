"""Framing and geometry: crops, rotation, perspective, lens faults, canvas shape.

Every rectangle is computed from the document size and measured boxes; the planner only names
the shape, the side or what to keep in frame. The builder's canvas records each geometry change
so later boxes and checks land on the same pixels.
"""

import math
import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


def fill_margin(b, index, color, name):
    """A solid layer at the very bottom in the margin's colour. Extending the canvas only colours
    the new margin on a locked Background layer; the studio's photo is a smart object, so the
    margin stayed transparent and rendered black (an instant-film frame, measured 2026-10-12)."""
    b.add(index, 'layer.newFillLayer.solidColor', {'color': color}, f'{name} colour')
    b.add(index, 'layer.renameLayer', {'name': name}, f'Name the layer “{name}”')
    b.add(index, 'layer.arrange.sendToBack', {}, f'Put the {name.lower()} behind the picture')


def subject_or_named(edit):
    """What a framing works around: the named object, else the main subject."""
    return [edit['object'] or 'the main subject']


def union(boxes):
    xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
    ys = [b[1] for b in boxes] + [b[1] + b[3] for b in boxes]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


@procedure('crop_aspect', 'Crop to a shape', 'framing', 'geometry',
           'crop to an aspect ratio (aspect like 1:1, 4:5, 16:9; position or main subject/object target says what to '
           'keep)', whole_picture=True, examples=('crop to a centered square', 'crop to 4:5 keeping the cat in frame'))
def crop_aspect(b, index, edit):
    ratio = lang.aspect_from(edit['aspect'])
    if not ratio:
        b.blocking.append(f'Which shape should “{edit["quote"]}” crop to, for example 1:1 or 4:5?')
        return
    focus = None
    if lang.subject_query(edit):
        _, boxes = b.target_boxes(edit)
        if boxes:
            focus = union(boxes)
    b.crop(index, *lang.largest_crop(b.canvas.width, b.canvas.height, ratio, focus, edit['position']),
           f'Crop to {edit["aspect"]}' + (' around the subject' if focus else ''))


@procedure('crop_to_object', 'Crop to an object', 'framing', 'geometry',
           'crop tightly around a named object or the main subject', whole_picture=True,
           examples=('crop tightly around the dog',))
def crop_to_object(b, index, edit):
    if lang.aspect_from(edit['aspect']) and re.search(r'\bcent(er|re)(e?d)?\b|\bkeep', edit['quote'], re.IGNORECASE):
        # “A square centered on her face” is the largest square around the face, not a tight crop.
        crop_aspect(b, index, edit)
        return
    key, boxes = b.target_boxes(edit)
    if not boxes:
        b.blocking.append(f'Could not find {key or "what to crop to"} in the picture.')
        return
    x, y, w, h = union(boxes)
    margin = round(max(w, h) * 0.08)
    box = [x - margin, y - margin, w + 2 * margin, h + 2 * margin]
    ratio = lang.aspect_from(edit['aspect'])
    if ratio:
        box = lang.fit_ratio(box, ratio, b.canvas.width, b.canvas.height)
    x0, y0 = max(0, round(box[0])), max(0, round(box[1]))
    x1 = min(b.canvas.width, round(box[0] + box[2]))
    y1 = min(b.canvas.height, round(box[1] + box[3]))
    b.crop(index, x0, y0, x1 - x0, y1 - y0, f'Crop to {key}')


# Where the eye rests in a composition: the four crossings of the thirds lines, or of the golden
# sections (0.382 / 0.618).
COMPOSITION_RULES = {'rule of thirds': 1 / 3, 'golden ratio': 0.382}


@procedure('compose', 'Recompose by a composition rule', 'framing', 'geometry',
           'improve the composition by cropping so the main subject (or object) sits on a rule-of-thirds or golden '
           'ratio point (choice = rule of thirds or golden ratio; aspect if named)',
           options=tuple(COMPOSITION_RULES), whole_picture=True, finds=subject_or_named,
           examples=('crop it using the rule of thirds', 'improve the composition'),
           requires=r'compos|thirds|golden|balance|reframe|framing|placement')
def compose(b, index, edit):
    """The largest crop (of the asked or current shape) that puts the subject's centre on the
    nearest strong point, keeping all of the subject in frame."""
    key, boxes = b.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the subject"} to compose around.')
        return
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    share = COMPOSITION_RULES['golden ratio' if re.search(r'golden|phi|fibonacci', words) else 'rule of thirds']
    sx, sy, sw, sh = union(boxes)
    cx, cy = sx + sw / 2, sy + sh / 2
    w, h = b.canvas.width, b.canvas.height
    ratio = lang.aspect_from(edit['aspect']) or lang.aspect_from(edit['quote']) or (w, h)
    aspect = ratio[0] / ratio[1]
    rule ='golden ratio' if share > 0.35 else 'thirds'

    def largest(points):
        """The largest crop putting the subject's centre on one of the points with all of it inside."""
        found = None
        for px, py in points:
            for step in range(60):
                scale = 1 - step * 0.01
                cw = min(w, h * aspect) * scale
                ch = cw / aspect
                x, y = cx - px * cw, cy - py * ch
                if x < 0 or y < 0 or x + cw > w or y + ch > h:
                    continue  # a smaller crop may fit inside the photo
                if x <= sx and y <= sy and sx + sw <= x + cw and sy + sh <= y + ch and (
                        found is None or cw * ch > found[2] * found[3]):
                    found = [x, y, cw, ch]
                break  # smaller crops would only cut more of the subject
        return found

    # A strong point (a crossing of the lines); a tall subject that cannot sit on one is placed on
    # a vertical line, centred up and down, the way portraits are usually framed.
    best = largest([(px, py) for px in (share, 1 - share) for py in (share, 1 - share)]) or \
        largest([(share, 0.5), (1 - share, 0.5)])
    if best is None:
        b.blocking.append(f'{key[:1].upper() + key[1:]} is too large or too close to the edge to place on a {rule} '
                          'line by cropping.')
        return
    x, y, cw, ch = (round(v) for v in best)
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})
    b.crop(index, x, y, cw, ch, f'Place {key} on a {rule} line')


@procedure('product_frame', 'Frame a product', 'framing', 'geometry',
           'frame the product (or main subject) centred so it fills a set share of the frame (value = % of the frame, '
           '85 by default; aspect, square by default; color = backdrop for any added margin)', whole_picture=True,
           finds=subject_or_named,
           examples=('center the product so it fills 85% of a square frame',))
def product_frame(b, index, edit):
    """Marketplace framing: the product's box, centred, filling `value`% of the frame's limiting
    side. When the frame reaches past the photo, the canvas is first extended in the backdrop
    color (on a cut-out, the backdrop layer covers the new margin)."""
    key, boxes = b.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the product"} to frame.')
        return
    fill = max(30, min(98, edit['value'] or 85)) / 100
    ratio = lang.aspect_from(edit['aspect']) or (1, 1)
    aspect = ratio[0] / ratio[1]
    x, y, w, h = union(boxes)
    frame_h = max(h, w / aspect) / fill
    frame_w = frame_h * aspect
    x0, y0 = x + w / 2 - frame_w / 2, y + h / 2 - frame_h / 2
    width, height = b.canvas.width, b.canvas.height
    pad_x = math.ceil(max(0, -x0, x0 + frame_w - width))
    pad_y = math.ceil(max(0, -y0, y0 + frame_h - height))
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})
    if pad_x or pad_y:
        color = lang.hex_color(edit['color']) or '#ffffff'
        b.add(index, 'image.canvasSize', {'width': width + 2 * pad_x, 'height': height + 2 * pad_y,
                                          'anchor': 'center', 'extensionColor': color},
              f'Extend the canvas for even margins ({edit["color"] or "white"})')
        fill_margin(b, index, color, 'Margin')
        b.canvas.maps.append(lambda px, py, dx=pad_x, dy=pad_y: (px + dx, py + dy))
        b.canvas.width, b.canvas.height = width + 2 * pad_x, height + 2 * pad_y
        x0, y0 = x0 + pad_x, y0 + pad_y
    b.crop(index, max(0, round(x0)), max(0, round(y0)), round(frame_w), round(frame_h),
           f'Center {key}, filling {fill:.0%} of the frame')


@procedure('passport_photo', 'Passport or ID photo', 'output', 'geometry',
           'passport, ID or visa photo: head-and-shoulders crop on a plain backdrop at the printed size in the quote '
           '(e.g. 35x45 mm, 2x2 inch); color = backdrop color', whole_picture=True,
           finds=lambda edit: [lang.PASSPORT_HEAD],
           examples=('make a passport size photo', 'US visa photo 2x2 inch with white background'))
def passport_photo(b, index, edit):
    """Head-and-shoulders framing measured from the head box, then the print size at 300 ppi."""
    size = lang.print_size(edit['quote']) or lang.print_size(edit['aspect'])
    if not size and re.search(r'stamp', edit['quote'], re.IGNORECASE):
        size = lang.STAMP_SIZE
        b.notes.append('Used the common 20×25 mm stamp size; write a size such as “25x30 mm” for another.')
    elif not size:
        size = lang.PASSPORT_DEFAULT
        b.notes.append('Used the common 35×45 mm passport size; write a size such as “2x2 inch” for another.')
    framed = head_frame(b, index, edit, size[:2], lang.PASSPORT_HEAD_SHARE, lang.PASSPORT_TOP_MARGIN,
                        'Crop head and shoulders')
    if not framed:
        return
    cw, ch = framed
    unit = size[2]
    if unit == 'px':
        tw, th = round(size[0]), round(size[1])
    elif unit in ('mm', 'cm', 'in'):
        inches = {'mm': 25.4, 'cm': 2.54, 'in': 1}[unit]
        tw, th = round(size[0] / inches * lang.PRINT_PPI), round(size[1] / inches * lang.PRINT_PPI)
    else:
        b.notes.append(f'Cropped to {size[0]:g}:{size[1]:g}; add mm, cm or inch to also set the print size.')
        return
    if not (1 <= tw <= 8192 and 1 <= th <= 8192):
        b.blocking.append('The size must stay between 1 and 8192 pixels on each side.')
        return
    params = {'width': tw, 'height': th, 'resample': 'preserveDetails' if tw > cw else 'bicubic'}
    label = f'Resize to {tw}×{th}'
    if unit != 'px':
        params['resolution'] = lang.PRINT_PPI
        label += f' ({size[0]:g}×{size[1]:g} {"inch" if unit == "in" else unit} at {lang.PRINT_PPI} ppi)'
        b.canvas.resolution = lang.PRINT_PPI
    if tw > cw * 1.5:
        b.notes.append(f'The head-and-shoulders area is {cw}×{ch} px, so it is enlarged {tw / cw:.1f}× for print; '
                       'a sharper, closer original prints better.')
    b.add(index, 'image.imageSize', params, label)
    b.canvas.maps.append(lambda px, py, sx=tw / cw, sy=th / ch: (px * sx, py * sy))
    b.canvas.width, b.canvas.height = tw, th


@procedure('headshot', 'Professional headshot', 'portrait', 'geometry',
           'professional headshot: head-and-shoulders crop with a gentle polish (aspect if named, square for profile '
           'pictures)', whole_picture=True, finds=lambda edit: [lang.PASSPORT_HEAD],
           examples=('turn this into a LinkedIn headshot',))
def headshot(b, index, edit):
    ratio = lang.aspect_from(edit['aspect']) or lang.aspect_from(edit['quote'])
    if not ratio:
        ratio = (1, 1) if re.search(r'linked\s*in|profile|avatar|\bdp\b|square', edit['quote'], re.IGNORECASE) \
            else (4, 5)
    head_frame(b, index, edit, ratio, head_share=0.52, top_margin=0.1, label='Crop to a headshot')


def head_frame(b, index, edit, ratio, head_share, top_margin, label):
    """Frame measured from the head box: the head is `head_share` of the height, its top
    `top_margin` below the frame's top, centered across. Returns the crop size or None."""
    _, boxes = b.target_boxes({**edit, 'target': 'object', 'object': lang.PASSPORT_HEAD})
    if not boxes:
        b.blocking.append('Could not find the person’s head to frame.')
        return None
    hx, hy, hw, hh = max(boxes, key=lambda box: box[2] * box[3])
    w, h = b.canvas.width, b.canvas.height
    frame_h = hh / head_share
    frame_w = frame_h * ratio[0] / ratio[1]
    scale = min(1.0, w / frame_w, h / frame_h)
    if scale < 1:
        b.notes.append('The photo is framed too tightly for the usual crop, so the head fills more of the picture '
                       'than usual.')
    cw, ch = min(w, round(frame_w * scale)), min(h, round(frame_h * scale))
    x = min(max(0, round(hx + hw / 2 - cw / 2)), w - cw)
    y = min(max(0, round(hy - ch * top_margin)), h - ch)
    b.crop(index, x, y, cw, ch, label)
    return cw, ch


@procedure('rotate', 'Rotate', 'framing', 'geometry', 'rotate by degrees (value; choice clockwise/counterclockwise)',
           examples=('rotate 90 degrees clockwise',))
def rotate(b, index, edit, straighten=False):
    if edit['value'] is None:
        if straighten:
            measured = b.analysis.get('tilt')
            if measured is None:
                b.blocking.append('I could not find a clear horizon or straight edge to level. Say how many degrees, '
                                  'for example “straighten by 2 degrees clockwise”.')
                return
            if measured == 0:
                b.notes.append('The horizon is already level (measured), so nothing was rotated.')
                return
            edit = {**edit, 'value': measured, 'choice': '', 'quote': ''}
        else:
            edit = {**edit, 'value': 90.0}
    degrees = edit['value']
    counter = re.search(r'counter|anti|ccw|left', edit['quote'] + ' ' + edit['choice'], re.IGNORECASE)
    clockwise = degrees if not counter else -abs(degrees)
    w, h = b.canvas.width, b.canvas.height
    turn = round(clockwise) % 360
    if abs(clockwise - round(clockwise)) < 1e-6 and turn in (90, 180, 270):
        command = {90: 'image.imageRotation.90cw', 180: 'image.imageRotation.180',
                   270: 'image.imageRotation.90ccw'}[turn]
        b.add(index, command, {}, f'Rotate {turn if turn != 270 else 90}° '
                                  f'{"counterclockwise" if turn == 270 else "clockwise"}')
        if turn == 90:
            b.canvas.maps.append(lambda px, py, h=h: (h - py, px))
        elif turn == 270:
            b.canvas.maps.append(lambda px, py, w=w: (py, w - px))
        else:
            b.canvas.maps.append(lambda px, py, w=w, h=h: (w - px, h - py))
        if turn != 180:
            b.canvas.width, b.canvas.height = h, w
        return
    # PhotoCraft's crop angle turns the frame; a positive frame angle turns the picture counterclockwise.
    x, y, cw, ch = lang.rotation_crop(w, h, clockwise)
    b.add(index, 'image.crop', {'x': x, 'y': y, 'width': cw, 'height': ch, 'angle': -clockwise,
                                'targetWidth': w, 'targetHeight': h},
          f'{"Straighten" if straighten else "Rotate"} {abs(clockwise):g}° '
          f'{"clockwise" if clockwise > 0 else "counterclockwise"}, cropping the empty corners')
    theta = math.radians(clockwise)

    def move(px, py, w=w, h=h, theta=theta, x=x, y=y, s=w / cw):
        cx, cy = px - w / 2, py - h / 2
        rx = cx * math.cos(theta) - cy * math.sin(theta) + w / 2
        ry = cx * math.sin(theta) + cy * math.cos(theta) + h / 2
        return (rx - x) * s, (ry - y) * s

    b.canvas.maps.append(move)


@procedure('straighten', 'Straighten the horizon', 'framing', 'geometry',
           'level a tilted horizon by a small number of degrees (value)', measures=('tilt',),
           examples=('straighten the horizon',))
def straighten(b, index, edit):
    rotate(b, index, edit, straighten=True)


@procedure('flip', 'Flip', 'framing', 'geometry', 'mirror the picture (choice horizontal/vertical)',
           examples=('flip it horizontally',))
def flip(b, index, edit):
    vertical = re.search(r'vertical|upside|top to bottom', edit['quote'] + ' ' + edit['choice'], re.IGNORECASE)
    w, h = b.canvas.width, b.canvas.height
    if vertical:
        b.add(index, 'image.imageRotation.flipCanvasVertical', {}, 'Flip vertically')
        b.canvas.maps.append(lambda px, py, h=h: (px, h - py))
    else:
        b.add(index, 'image.imageRotation.flipCanvasHorizontal', {}, 'Flip horizontally (mirror)')
        b.canvas.maps.append(lambda px, py, w=w: (w - px, py))


def resize_finds(edit):
    # A format with another shape is cut around the subject.
    return ['the main subject'] if lang.resize_may_crop(edit['quote']) else []


@procedure('resize', 'Resize or set print size', 'output', 'geometry',
           'output size, print size or resolution: pixels (1080x1350, 2000 px wide, 50%, 2x bigger, half), print (4x6 '
           'inch, A4, 300 dpi), formats (instagram post or story, youtube thumbnail, linkedin or facebook cover, 4k, '
           'wallpaper)', finds=resize_finds,
           examples=('make it an instagram post', 'prepare this for a 4x6 inch print at 300 dpi'))
def resize(b, index, edit):
    w, h = b.canvas.width, b.canvas.height
    wanted = lang.output_size(edit['quote'], w, h) or lang.output_size(edit['aspect'], w, h)
    if not wanted:
        b.blocking.append('What size should the picture be? For example 1080x1350, A4, 4x6 inch, instagram post, '
                          '2000 px wide, or 50%.')
        return
    (tw, th), ppi = wanted['size'], wanted['ppi']
    if not (1 <= tw <= 8192 and 1 <= th <= 8192):
        b.blocking.append('The size must stay between 1 and 8192 pixels on each side.')
        return
    if (tw, th) == (w, h):
        # Only the print resolution changes; the pixels stay as they are.
        b.add(index, 'image.imageSize', {'width': w, 'height': h, 'resolution': ppi, 'resample': 'none'},
              f'Set {ppi} ppi (pixels unchanged)')
        b.canvas.resolution = ppi
        return
    if wanted['crop'] and abs(tw / th - w / h) > 0.01:
        _, boxes = b.target_boxes({**edit, 'target': 'main subject', 'object': ''})
        focus = union(boxes) if boxes else None
        x, y, cw, ch = lang.largest_crop(w, h, (tw, th), focus, edit['position'])
        b.crop(index, x, y, cw, ch, f'Crop to the {tw}:{th} shape' + (' around the subject' if focus else '')
               + ' so nothing stretches')
        w, h = cw, ch
    params = {'width': tw, 'height': th, 'resample': 'preserveDetails' if tw > w else 'bicubic'}
    if ppi:
        params['resolution'] = ppi
        b.canvas.resolution = ppi
    if tw > w * 2.5:
        b.notes.append(f'This enlarges the picture {tw / w:.1f}×; fine detail cannot be invented, so it will look '
                       'soft up close.')
    b.add(index, 'image.imageSize', params, f'Resize to {tw}×{th}'
          + (f' · {wanted["label"]}' if wanted['label'] != f'{tw}×{th}' else ''))
    b.canvas.maps.append(lambda px, py, sx=tw / w, sy=th / h: (px * sx, py * sy))
    b.canvas.width, b.canvas.height = tw, th


@procedure('center_subject', 'Center the subject', 'framing', 'geometry',
           'crop so the main subject or object sits exactly in the middle with even margins', whole_picture=True,
           examples=('center the product with even margins',))
def center_subject(b, index, edit):
    """The largest crop with the subject exactly in the middle (same shape unless one is asked)."""
    key, boxes = b.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the subject"} to center.')
        return
    sx, sy, sw, sh = union(boxes)
    cx, cy = sx + sw / 2, sy + sh / 2
    w, h = b.canvas.width, b.canvas.height
    half_w, half_h = min(cx, w - cx), min(cy, h - cy)
    ratio = lang.aspect_from(edit['aspect']) or lang.aspect_from(edit['quote'])
    if ratio:
        aspect = ratio[0] / ratio[1]
        half_w, half_h = min(half_w, half_h * aspect), min(half_h, half_w / aspect)
    if half_w * 2 < sw * 1.02 or half_h * 2 < sh * 1.02:
        b.blocking.append(f'{key[:1].upper() + key[1:]} is too close to the edge to center by cropping; use “fit” or '
                          'extend the background instead.')
        return
    x, y = round(cx - half_w), round(cy - half_h)
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})
    b.crop(index, x, y, round(half_w * 2), round(half_h * 2), f'Center {key}')


@procedure('perspective', 'Upright perspective', 'framing', 'geometry',
           'make leaning walls, buildings or doors vertical (upright, keystone, perspective)', measures=('verticals',),
           examples=('fix the leaning walls',))
def perspective(b, index, edit):
    """Upright from measured lines: PhotoCraft's Adaptive Wide Angle makes each given line vertical."""
    lines = b.analysis.get('verticals') or []
    # The lean from upright, whichever end of the line comes first (180° is upright too).
    leaning = [line for line in lines if abs((math.degrees(math.atan2(line[1][0] - line[0][0],
                                                                       line[1][1] - line[0][1])) + 90) % 180 - 90)
               > 0.6]
    if lines and not leaning:
        b.notes.append('The vertical edges are already upright (measured), so the perspective was not changed.')
        return
    if len(lines) < 2:
        b.blocking.append('I could not find two long vertical edges (walls, door frames, poles) to straighten the '
                          'perspective against.')
        return
    b.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
    b.add(index, 'filter.adaptiveWideAngle', {
        'model': 'perspective', 'constraints': [{'a': a, 'b': z, 'orientation': 'vertical'} for a, z in lines]},
        f'Make {len(lines)} measured edges vertical')
    b.add(index, 'studio.crop_empty', {}, 'Crop away the empty edges the correction leaves')


@procedure('lens_correction', 'Lens correction', 'correct', 'geometry',
           'fix lens faults: barrel or fisheye distortion, chromatic aberration (color fringes), dark lens corners '
           '(choice = distortion, fringes, vignette or all)', options=('distortion', 'fringes', 'vignette', 'all'),
           examples=('remove the purple fringes',))
def lens_correction(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    fringes = bool(re.search(r'chromatic|aberration|fring|purple edge|color edge', words))
    corners = bool(re.search(r'vignett|dark corner', words))
    distortion = bool(re.search(r'distort|barrel|fish|bulg|pincushion|curved', words))
    if not (fringes or corners or distortion):
        fringes = corners = distortion = True
    params = {'profile': 'auto', 'correctDistortion': distortion, 'correctCA': fringes,
              'correctVignette': corners, 'autoScale': True, 'edge': 'edgeExtension'}
    fixed = [name for name, on in (('distortion', distortion), ('color fringes', fringes),
                                   ('lens vignetting', corners)) if on]
    b.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
    b.add(index, 'filter.lensCorrection', params, 'Correct ' + ', '.join(fixed))


@procedure('fit_canvas', 'Fit into a shape', 'framing', 'geometry',
           'fit the whole picture into a new shape (aspect) WITHOUT cutting anything, filling the empty sides with '
           'color (letterbox, white bars, padding to square)',
           examples=('fit the whole photo in a square with white bars, do not cut anything',))
def fit_canvas(b, index, edit):
    """Pad the picture out to a shape, keeping every pixel (letterbox, white bars)."""
    w, h = b.canvas.width, b.canvas.height
    wanted = lang.output_size(edit['quote'], w, h) if not lang.aspect_from(edit['aspect']) else None
    ratio = lang.aspect_from(edit['aspect']) or lang.aspect_from(edit['quote']) or (wanted['size'] if wanted else (1, 1))
    aspect = ratio[0] / ratio[1]
    tw, th = (round(h * aspect), h) if w / h < aspect else (w, round(w / aspect))
    color = lang.hex_color(edit['color']) or '#ffffff'
    b.add(index, 'image.canvasSize', {'width': tw, 'height': th, 'anchor': 'center', 'extensionColor': color},
          f'Fit into {ratio[0]:g}:{ratio[1]:g} with {edit["color"] or "white"} bars ({tw}×{th})')
    fill_margin(b, index, color, 'Bars')
    b.canvas.maps.append(lambda px, py, dx=(tw - w) / 2, dy=(th - h) / 2: (px + dx, py + dy))
    b.canvas.width, b.canvas.height = tw, th
    if wanted and wanted['size'] != (tw, th) and not lang.aspect_from(edit['aspect']):
        sw, sh = wanted['size']
        b.add(index, 'image.imageSize', {'width': sw, 'height': sh, 'resample':
                                         'preserveDetails' if sw > tw else 'bicubic'}, f'Resize to {sw}×{sh}')
        b.canvas.maps.append(lambda px, py, sx=sw / tw, sy=sh / th: (px * sx, py * sy))
        b.canvas.width, b.canvas.height = sw, sh


@procedure('convert_mode', 'Color mode', 'output', 'output',
           'convert the document color mode (choice = cmyk, grayscale, rgb, 16-bit, 8-bit)',
           options=('cmyk', 'grayscale', 'rgb', '16-bit', '8-bit'), examples=('convert to CMYK for the print shop',))
def convert_mode(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    if '16' in words or '8' in words and 'bit' in words:
        bits = '16' if '16' in words else '8'
        b.add(index, f'image.mode.bits{bits}', {}, f'Convert to {bits} bits per channel')
        return
    mode = 'cmyk' if 'cmyk' in words else 'grayscale' if re.search(r'gr[ae]y|monochrome', words) else \
        'rgb' if 'rgb' in words else None
    if not mode:
        b.blocking.append('Which color mode: CMYK, grayscale or RGB?')
        return
    b.add(index, f'image.mode.{mode}', {'intent': 'perceptual' if mode == 'cmyk' else 'relative'},
          f'Convert to {mode.upper() if mode != "grayscale" else "grayscale"} mode')
    if mode == 'cmyk':
        b.notes.append('CMYK is for the print shop; screens and the web expect RGB.')


@procedure('canvas_border', 'Border', 'graphics', 'geometry',
           'add an outer border/padding around the picture (value = px, color)',
           examples=('add a white border',))
def canvas_border(b, index, edit):
    size = round(edit['value']) if edit['value'] else round(min(b.canvas.width, b.canvas.height) * 0.04)
    color = lang.hex_color(edit['color']) or '#ffffff'
    b.add(index, 'image.canvasSize', {'width': size * 2, 'height': size * 2, 'relative': True,
                                      'anchor': 'center', 'extensionColor': color}, f'Add a {size}px border')
    fill_margin(b, index, color, 'Border')
    b.canvas.maps.append(lambda px, py, s=size: (px + s, py + s))
    b.canvas.width += size * 2
    b.canvas.height += size * 2


@procedure('polaroid', 'Instant-film border', 'graphics', 'geometry',
           'an instant photo (polaroid) frame: even white sides and top, a deep bottom edge (color = frame color)',
           examples=('make it look like a polaroid',),
           requires=r'polaroid|instant|frame|border')
def polaroid(b, index, edit):
    """The classic instant print: a square-ish picture area, a thin even border, and a bottom
    edge about 3.5 times as deep, all in one canvas extension anchored at the top."""
    w, h = b.canvas.width, b.canvas.height
    side = round(min(w, h) * 0.06)
    bottom = round(side * 3.5)
    color = lang.hex_color(edit['color']) or '#fbfaf5'
    b.add(index, 'image.canvasSize', {'width': w + side * 2, 'height': h + side, 'anchor': 'bottom',
                                      'extensionColor': color}, 'Even border on the sides and top')
    b.add(index, 'image.canvasSize', {'width': w + side * 2, 'height': h + side + bottom, 'anchor': 'top',
                                      'extensionColor': color}, 'Deep bottom edge')
    fill_margin(b, index, color, 'Instant frame')
    b.canvas.maps.append(lambda px, py, s=side: (px + s, py + s))
    b.canvas.width, b.canvas.height = w + side * 2, h + side + bottom

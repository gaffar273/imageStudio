"""Pixel retouching: removing and moving objects, restoring old photos, and portrait work.

Portrait jobs are each done the way a retoucher does them by hand, each on its own masked layer:
Camera Raw on the face outline narrowed to the skin colours measured mid-face (so lips, brows and
lashes stay sharp), feathered ellipses under and on the eyes, a de-yellowing layer on tooth-coloured
pixels, PhotoCraft's red-eye tool on each pupil. Blemishes, wrinkles and uneven tone go to the AI
model on the face only when it is installed.
"""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


def remove_finds(edit):
    return [edit['object']] if edit['object'] else []


@procedure('remove_object', 'Remove an object', 'retouch', 'retouch',
           'erase an object, person or thing and fill the area (object = what)', finds=remove_finds, area_safe=True,
           examples=('remove the trash can on the left', 'remove the second mug from the right'))
def remove_object(b, index, edit):
    key, boxes = b.target_boxes({**edit, 'target': 'object'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the object to remove"} in the picture.')
        return
    area = sum(box[2] * box[3] for box in boxes) / (b.canvas.width * b.canvas.height)
    b.removed += boxes
    if area >= lang.AI_REMOVAL_AREA and b.ai:
        # Content-aware fill copies nearby patches and smears anything this size; AI rebuilds what
        # was behind it, limited to the object's box, on its own masked layer.
        noun = key.split()[-1]
        # Kontext tends to paint a different object into the gap when asked to “remove”; describing
        # the empty result works better, and the step retries when the measured area still stands out.
        b.add(index, 'studio.ai_layer', {
            'instruction': f'Remove {key}. In its place show only the empty background that was behind it, '
                           f'continuing the surroundings seamlessly. There is no {noun} there any more. '
                           'Change nothing else.',
            'retry': f'Erase {key} completely and paint the plain surface and background that continue around it. '
                     f'Do not add any {noun} or any other object. Change nothing else.',
            'boxes': boxes, 'label': f'Removed {key}'[:80]}, f'Remove {key} with AI (its own layer, checked)')
        b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})
        return
    if area >= lang.AI_REMOVAL_AREA:
        b.notes.append(f'{key[:1].upper() + key[1:]} covers {area:.0%} of the picture; content-aware fill may smear '
                       'it. Install AI content editing for clean removal of larger objects.')
    if not b.selection(index, {**edit, 'target': 'object', 'object': key}):
        return
    pad = max(4, round(min(b.canvas.width, b.canvas.height) * 0.008))
    b.add(index, 'select.modify.expand', {'radius': pad}, 'Include the edges')
    b.add(index, 'studio.retouch_fill', {'label': f'Removed {key}'[:80]}, f'Fill where {key} was')
    b.end_selection(index)


def transform_finds(edit):
    query = lang.subject_query({**edit, 'target': 'object'})
    return [query, lang.FOREGROUND] if lang.moves_among_others(edit) else [query]


@procedure('transform_object', 'Move, resize or duplicate an object', 'retouch', 'retouch',
           'move, resize or duplicate one object (object = what; choice = move, bigger, smaller or duplicate; position '
           '= where it goes)', options=('move', 'bigger', 'smaller', 'duplicate'), whole_picture=True,
           finds=transform_finds, examples=('move the yellow mug to the left', 'make the cat bigger'))
def transform_object(b, index, edit):
    key, boxes = b.target_boxes({**edit, 'target': 'object'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the object"} to move.')
        return
    x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
    width, height = b.canvas.width, b.canvas.height
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    duplicate = lang.is_duplicate(words)
    # Other things standing level with it (their bases within 10% of the height), so a moved or
    # copied object lands in free space. Things further back, like the chair behind a cat, are
    # simply covered, the way a nearer object hides them.
    _, around = b.target_boxes(edit, lang.FOREGROUND)
    others = [o for o in around or [] if lang.covered(o, [x, y, w, h]) < 0.5 and lang.covered([x, y, w, h], o) < 0.5
              and abs(o[1] + o[3] - y - h) < 0.1 * height]
    overlap_ok = bool(re.search(r'\b(in front of|on top of|over|overlap\w*|cover\w*|anyway)\b', words))
    factor = 1.0
    if re.search(r'bigger|larger|enlarge|grow|increase|scale up', words):
        factor = 1 + (edit['value'] / 100 if edit['value'] and edit['value'] < 300 else
                      {'subtle': 0.15, 'moderate': 0.3, 'strong': 0.6}[edit['strength']])
    elif re.search(r'smaller|shrink|reduce|decrease|scale down', words):
        factor = 1 - (min(edit['value'], 90) / 100 if edit['value'] else
                      {'subtle': 0.15, 'moderate': 0.25, 'strong': 0.45}[edit['strength']])
    tw, th = w * factor, h * factor
    # Things stand on something: scaling keeps the base where it was, centered.
    tx, ty = x + w / 2 - tw / 2, y + h - th
    absolute = re.search(r'\b(edge|corner|side of the (picture|photo|image|frame)|far (left|right)|center|centre|'
                         r'middle)\b', words)
    if edit['position'] and absolute:
        cx, _ = lang.position_xy(edit['position'])
        tx = cx * width - tw / 2
        if 'top' in edit['position'] or 'bottom' in edit['position']:
            ty = lang.position_xy(edit['position'])[1] * height - th / 2
    elif edit['position']:
        # A shift by its own width put the yellow mug on top of the blue one in a row of four, so
        # it goes to the nearest free gap that way instead, or the person is asked.
        step = {'subtle': 0.5, 'moderate': 1.0, 'strong': 1.8}[edit['strength']]
        position = edit['position']
        if 'left' in position or 'right' in position:
            sign = -1 if 'left' in position else 1
            wanted = tx + sign * tw * step
            if others and not overlap_ok:
                allowed = (0, x - tw * step / 2) if sign < 0 else (x + tw * step / 2, width - tw)
                tx = lang.free_spot(tw, width, b.spans(others, ty, th, 1), wanted, allowed)
            else:
                tx = wanted
        if tx is not None and ('top' in position or 'bottom' in position):
            sign = -1 if 'top' in position else 1
            wanted = ty + sign * th * step
            if others and not overlap_ok:
                allowed = (0, y - th * step / 2) if sign < 0 else (y + th * step / 2, height - th)
                ty = lang.free_spot(th, height, b.spans(others, tx, tw, 0), wanted, allowed)
            else:
                ty = wanted
        if tx is None or ty is None:
            b.blocking.append(
                f'There is no free space {position.replace("top", "up").replace("bottom", "down")} of {key}: it would '
                'cover something else. Say "in front of" to let it overlap, or say where it should go.')
            return
    elif duplicate:
        # Beside the original, in the nearest free space (on the side with more room when nothing
        # else is known).
        tx = x + w * 1.1 if x + w / 2 < width / 2 else x - tw * 1.1
        if others and not overlap_ok:
            gap = tw * 0.1
            tx = lang.free_spot(tw + 2 * gap, width, b.spans(others + [[x, y, w, h]], ty, th, 1), tx - gap,
                                (0, width - tw - 2 * gap))
            if tx is None:
                b.blocking.append(f'There is no free space beside {key} for a copy. Say where it should go, or "in '
                                  'front of" to let it overlap.')
                return
            tx += gap
    tx = min(max(0, tx), width - tw)
    ty = min(max(0, ty), height - th)
    if factor == 1 and abs(tx - x) < 2 and abs(ty - y) < 2 and not duplicate:
        b.blocking.append(f'Where should {key} go, or how much bigger or smaller should it be?')
        return
    verb = 'Duplicate' if duplicate else 'Resize' if factor != 1 and abs(tx - x) < w * 0.5 else 'Move'
    b.add(index, 'studio.transform_object', {
        'box': [x, y, w, h], 'to': [round(tx), round(ty), round(tw), round(th)], 'what': key,
        'duplicate': duplicate, 'label': f'{verb}d {key}'[:80]},
        f'{verb} {key}' + (f' to {factor:.0%}' if factor != 1 else '') + ' (lifted onto its own layer)')
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized([[x, y, w, h]])})


@procedure('restore', 'Restore an old photo', 'retouch', 'retouch',
           'restore an old or damaged photo: scratches, dust, stains, creases, fading', area_safe=True,
           examples=('restore this old damaged photo',))
def restore(b, index, edit):
    """Old-photo restoration: damage repaired (AI when installed), then tone and noise."""
    if b.ai:
        b.add(index, 'studio.ai_layer', {
            'instruction': 'Restore this old damaged photograph: remove scratches, dust, spots, stains, creases and '
                           'tears, and repair faded areas. Keep every face, person, object and the original colors '
                           '(or black and white) exactly the same. Do not add or remove anything.',
            'label': 'Restored'}, 'Repair scratches, dust and creases with AI (its own layer)')
    else:
        dust_and_scratches(b, index)
        b.notes.append('Install AI content editing for repairing large scratches, stains and tears.')
    b.raw[index] = {'contrast': 12, 'dehaze': 10, 'clarity': 8, 'noiseLuminance': 25, 'noiseColor': 30}


def dust_and_scratches(b, index):
    b.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
    radius = max(1, round(min(b.canvas.width, b.canvas.height) / 900))
    b.add(index, 'filter.noise.dustAndScratches', {'radius': radius, 'threshold': 14}, 'Clear dust and fine scratches')


@procedure('dust_cleanup', 'Clean dust and specks', 'retouch', 'retouch',
           'clear dust, sensor spots and fine specks (scanned film, a dusty product, sensor dust in a sky)',
           area_safe=True, examples=('clean the dust spots off the scan',))
def dust_cleanup(b, index, edit):
    if edit['target'] in ('whole image', 'layer'):
        dust_and_scratches(b, index)
        return
    if not b.selection(index, edit):
        return
    radius = max(1, round(min(b.canvas.width, b.canvas.height) / 900))
    b.add(index, 'studio.local_filter', {'command': 'filter.noise.dustAndScratches',
                                         'params': {'radius': radius, 'threshold': 14},
                                         'label': lang.short_label({**edit, 'action': 'dust_cleanup'})},
          'Clear dust and specks (masked)')
    b.end_selection(index)


@procedure('retouch_portrait', 'Portrait retouch', 'portrait', 'retouch',
           'portrait retouching of faces: choice = smooth skin, blemishes (pimples, acne, spots), wrinkles, even skin '
           'tone, dark circles, shine, whiten teeth, brighten eyes, red eye, sculpt (dodge and burn)',
           options=tuple(job for job, _ in lang.RETOUCH_JOBS), many=True, whole_picture=True,
           finds=lambda edit: lang.retouch_queries(edit), measures=('skin_colors', 'teeth', 'teeth_colors'),
           examples=('smooth her skin a little', 'whiten their teeth', 'remove the dark circles under her eyes'))
def retouch_portrait(b, index, edit):
    """A retoucher's jobs on faces, each done the way it is done by hand and each on its own layer."""
    scale = lang.LEVEL[edit['strength']]
    for job in lang.retouch_jobs(edit['choice'] + ' ' + edit['quote']):
        if job in lang.FACE_JOBS:
            _, faces = b.target_boxes({**edit, 'target': 'object', 'object': lang.FACES})
            if not faces:
                b.blocking.append('Could not find a face to retouch.')
                return
            face_job(b, index, edit, job, faces, scale)
        elif job in lang.EYE_JOBS:
            _, eyes = b.target_boxes({**edit, 'target': 'object', 'object': lang.EYES})
            if not eyes:
                b.blocking.append('Could not find the eyes.')
                return
            eye_job(b, index, job, eyes, scale)
        elif job == 'teeth':
            _, teeth = b.target_boxes({**edit, 'target': 'object', 'object': lang.TEETH})
            if not teeth or b.analysis.get('teeth') is False:
                b.blocking.append('Could not find any teeth showing in the picture.')
                return
            whiten_teeth(b, index, edit, teeth, scale)


def whiten_teeth(b, index, edit, teeth, scale):
    """De-yellow and lift only tooth-coloured pixels inside the mouths."""
    colors = b.analysis.get('teeth_colors')
    if not colors:
        b.blocking.append('Could not measure the teeth to whiten them.')
        return
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'studio.select_outline', {'boxes': teeth, 'what': 'the teeth'}, 'Select the mouths')
    b.add(index, 'studio.require_selection', {'what': 'the teeth', 'min_coverage': 0.00001},
          'Check the teeth were found')
    b.add(index, 'select.colorRange', {'colors': colors, 'fuzziness': 35, 'mode': 'intersect', 'sampleAllLayers': True},
          'Keep only tooth-coloured pixels')
    b.add(index, 'studio.require_selection', {'what': 'the teeth', 'min_coverage': 0.000005},
          'Check some teeth are left')
    b.add(index, 'select.modify.feather', {'radius': 1}, 'Soften the edge')
    b.add(index, 'layer.newAdjustmentLayer.hueSaturation',
          {'yellows': {'saturation': round(-45 * min(scale, 1.4)), 'lightness': round(10 * scale)},
           'lightness': round(5 * scale)}, 'Whiten teeth')
    b.after_new_layer(index, 'Whiten teeth')
    b.end_selection(index)
    b.regions.append({'requirement': index, 'label': 'teeth', 'boxes': b.normalized(teeth)})


FACE_RAW = {
    'smooth': {'texture': -45, 'clarity': -12},
    'shine': {'highlights': -45, 'whites': -20},
    'sculpt': {'clarity': 15, 'contrast': 10, 'highlights': 10, 'shadows': -8},
    'even tone': {'saturation': -8, 'texture': -20},
    'wrinkles': {'texture': -60, 'clarity': -20},
    'blemishes': {'texture': -20},
}
FACE_PROMPTS = {
    'blemishes': 'Retouch the skin: remove pimples, acne, spots and blemishes. Keep the natural skin texture, pores, '
                 'facial hair, eyes, lips, expression and the person’s identity exactly the same.',
    'wrinkles': 'Softly reduce wrinkles and fine lines on the face so it looks naturally rested, not plastic. Keep '
                'the identity, expression, eyes and hair exactly the same.',
    'even tone': 'Even out the skin tone: reduce redness, blotches and uneven patches while keeping natural skin '
                 'texture, identity and expression exactly the same.',
}
FACE_LABELS = {'smooth': 'Smoother skin', 'shine': 'Less shine', 'sculpt': 'Sculpted', 'even tone': 'Even tone',
               'wrinkles': 'Softer lines', 'blemishes': 'Softer skin'}


def face_job(b, index, edit, job, faces, scale):
    face = {**edit, 'target': 'object', 'object': lang.FACES}
    if job in FACE_PROMPTS and b.ai:
        b.add(index, 'studio.ai_layer', {'instruction': FACE_PROMPTS[job] + ' Change nothing else.',
                                         'boxes': faces, 'label': f'Retouch: {job}'},
              f'Retouch {job} with AI on the face only (its own layer)')
        b.regions.append({'requirement': index, 'label': 'face', 'boxes': b.normalized(faces)})
        return
    if job == 'blemishes':
        # Without AI: Dust & Scratches clears small spots and keeps edges above its threshold.
        width = max(box[2] for box in faces)
        if not b.selection(index, face):
            return
        only_skin(b, index)
        b.add(index, 'studio.local_filter', {
            'command': 'filter.noise.dustAndScratches', 'params': {'radius': max(2, round(width / 90)), 'threshold': 8},
            'label': 'Blemishes cleared · face'}, 'Clear small blemishes on the face (masked)')
        b.end_selection(index)
    params = {key: round(value * min(scale, 1.6), 2) for key, value in FACE_RAW[job].items()}
    label = FACE_LABELS[job] + ' · face'
    b.local_develop(index, face, params, label, f'{label.split(" · ")[0]} on the face (masked layer)',
                    refine=lambda at: only_skin(b, at))


def only_skin(b, index):
    """Narrow the face selection to its measured skin colours, leaving hair, brows and lashes."""
    colors = b.analysis.get('skin_colors')
    if not colors:
        return
    b.add(index, 'select.colorRange', {'colors': colors, 'fuzziness': 45, 'mode': 'intersect',
                                       'sampleAllLayers': True}, 'Keep only the skin')
    b.add(index, 'studio.require_selection', {'what': 'the skin', 'min_coverage': 0.0005}, 'Check the skin was found')


def eye_job(b, index, job, eyes, scale):
    if job == 'red eye':
        points = [[round(x + w / 2), round(y + h / 2)] for x, y, w, h in eyes]
        b.add(index, 'studio.select_photo', {}, 'Select the photo')
        b.add(index, 'paint.redEye', {'points': points, 'pupilSize': 50, 'darken': 50},
              f'Fix red eye on {len(points)} eye{"s" if len(points) > 1 else ""}')
        return
    if job == 'dark circles':
        # The soft area just below each eye, lifted gently; a hard mask would show as a patch.
        areas = [[x - w * 0.1, y + h * 0.75, w * 1.2, h * 0.8] for x, y, w, h in eyes]
        params = {'shadows': 35, 'exposure': 0.2, 'temperature': 4}
        label = 'Brighter under the eyes · under-eyes'
    else:
        areas = [[x - w * 0.1, y - h * 0.1, w * 1.2, h * 1.2] for x, y, w, h in eyes]
        params = {'exposure': 0.25, 'clarity': 20, 'vibrance': 10, 'sharpenAmount': 40}
        label = 'Brighter eyes · eyes'
    params = {key: round(value * min(scale, 1.6), 2) for key, value in params.items()}
    for number, (x, y, w, h) in enumerate(areas):
        b.add(index, 'select.rect', {'x': round(x), 'y': round(y), 'width': max(2, round(w)),
                                     'height': max(2, round(h)), 'ellipse': True,
                                     'mode': 'replace' if number == 0 else 'add',
                                     'feather': max(2, round(min(w, h) * 0.3))},
              'Select under the eye' if job == 'dark circles' else 'Select the eye')
    b.add(index, 'studio.require_selection', {'what': label.split(' · ')[1], 'min_coverage': 0.00001},
          'Check the area')
    b.add(index, 'studio.local_filter', {'command': 'filter.cameraRaw', 'params': params, 'label': label},
          f'{label.split(" · ")[0]} (masked layer)')
    b.end_selection(index)
    b.regions.append({'requirement': index, 'label': label.split(' · ')[1],
                      'boxes': b.normalized([[round(v) for v in area] for area in areas])})

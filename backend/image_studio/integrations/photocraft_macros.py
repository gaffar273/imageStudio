"""Studio steps that need the live document: they inspect it, measure, then act.

A compiled plan cannot know layer IDs created while it runs (converting the photo to a smart
object gives it a new ID) or how wide a title renders in a font. These steps look at the
document at that moment instead of guessing. They are run by the workspace in place of a
PhotoCraft command whose ID starts with ``studio.``.
"""

from PIL import Image, ImageStat

from .photocraft_area import select_marked

PHOTO = 'Photo'
RETOUCH_PREFIXES = ('Removed ', 'Content-Aware Fill')
GRAPHIC_KINDS = {'Type', 'Shape'}
GRAPHIC_NAMES = {'Frame'}
NAMES = {
    'studio.select_photo', 'studio.select_insert', 'studio.select_top', 'studio.require_selection',
    'studio.develop', 'studio.retouch_fill', 'studio.local_filter', 'studio.text', 'studio.ai_layer',
    'studio.select_outline', 'studio.select_marked', 'studio.mirror', 'studio.transform_object',
    'studio.reflection', 'studio.crop_empty',
}


def inspect(engine):
    return engine.call('doc.inspect')


def photo_layer(state):
    """The photograph: the layer named Photo, else the lowest pixel or smart object layer."""
    top = state['layers']
    for layer in top:
        if layer['name'] == PHOTO and layer['kind'] in ('Smart Object', 'Pixel'):
            return layer
    candidates = [layer for layer in top if layer['kind'] in ('Pixel', 'Smart Object')
                  and not layer['name'].startswith(RETOUCH_PREFIXES)]
    if not candidates:
        raise ValueError('This document has no photo layer to edit.')
    return candidates[-1]


def select_photo(engine, folder, params, context):
    state = inspect(engine)
    photo = photo_layer(state)
    if params.get('smart') and photo['kind'] == 'Pixel':
        top = state['layers']
        position = next(i for i, layer in enumerate(top) if layer['id'] == photo['id'])
        patches = []
        for layer in reversed(top[:position]):
            if layer['kind'] == 'Pixel' and layer['name'].startswith(RETOUCH_PREFIXES):
                patches.append(layer['id'])
            else:
                break
        engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': photo['id']}})
        for layer_id in patches:
            engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': layer_id, 'mode': 'add'}})
        result = engine.call('engine.execute', {'command': 'layer.smartObjects.convertToSmartObject', 'params': {}})
        engine.call('engine.execute', {'command': 'layer.renameLayer',
                                       'params': {'layer': result['layer'], 'name': PHOTO}})
        return {'layer': result['layer']}
    engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': photo['id']}})
    return {'layer': photo['id']}


def select_insert(engine, folder, params, context):
    """Select the highest layer that is not text or graphics, so new adjustment layers go
    above the photo and earlier adjustments but stay below titles."""
    state = inspect(engine)
    for layer in state['layers']:
        if layer['kind'] not in GRAPHIC_KINDS and layer['name'] not in GRAPHIC_NAMES:
            engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': layer['id']}})
            return {'layer': layer['id']}
    engine.call('engine.execute', {'command': 'layer.selectBottom', 'params': {}})
    return {}


def select_top(engine, folder, params, context):
    engine.call('engine.execute', {'command': 'layer.selectTop', 'params': {}})
    return {}


def require_selection(engine, folder, params, context):
    state = inspect(engine)
    coverage = (context.get('last') or {}).get('coverage')
    if coverage is None and state.get('selectionBounds'):
        x, y, w, h = state['selectionBounds']
        coverage = w * h / (state['width'] * state['height'])
    if not state.get('hasSelection') or (coverage or 0) < params.get('min_coverage', 0.01):
        raise ValueError(f'No {params.get("what", "area")} was found in this picture, so that part was not applied.')
    return {'coverage': coverage}


def develop(engine, folder, params, context):
    """Camera Raw settings on the photo as one editable smart filter; repeated requests
    add to the existing settings instead of stacking another filter."""
    select_photo(engine, folder, {'smart': True}, context)
    state = inspect(engine)
    photo = photo_layer(state)
    wanted = dict(params['params'])
    filters = photo.get('smartFilters') or []
    for index, item in enumerate(filters):
        if item.get('command') == 'filter.cameraRaw':
            merged = dict(item.get('params') or {})
            for key, value in wanted.items():
                low, high = (-5, 5) if key == 'exposure' else (0, 150) if key == 'sharpenAmount' else \
                    (0, 100) if key in ('noiseLuminance', 'noiseColor', 'grainAmount', 'grainSize') else (-100, 100)
                merged[key] = max(low, min(high, round(merged.get(key, 0) + value, 2)))
            engine.call('engine.execute', {'command': 'layer.smartFilter.setParams',
                                           'params': {'layer': photo['id'], 'index': index, 'params': merged}})
            return {'layer': photo['id'], 'merged': True}
    engine.call('engine.execute', {'command': 'filter.cameraRaw', 'params': wanted})
    return {'layer': photo['id']}


def retouch_fill(engine, folder, params, context):
    """Content-aware fill of the current selection onto its own layer above the photo."""
    state = inspect(engine)
    photo = photo_layer(state)
    if photo['kind'] != 'Pixel':
        engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': photo['id']}})
        copy = engine.call('engine.execute', {'command': 'layer.duplicate', 'params': {}})
        engine.call('engine.execute', {'command': 'layer.rasterize.smartObject', 'params': {'layer': copy['layer']}})
        result = engine.call('engine.execute', {'command': 'edit.contentAwareFill', 'params': {'output': 'new'}})
        engine.call('engine.execute', {'command': 'layer.delete', 'params': {'layer': copy['layer']}})
    else:
        engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': photo['id']}})
        result = engine.call('engine.execute', {'command': 'edit.contentAwareFill', 'params': {'output': 'new'}})
    copies = local_copies(state, photo)
    if copies:
        # Below a masked copy of the original photo, the removed object would show again.
        engine.call('engine.execute', {'command': 'layer.moveTo', 'params': {
            'layer': result['layer'], 'target': copies[0]['id'], 'position': 'above'}})
    engine.call('engine.execute', {'command': 'layer.renameLayer',
                                   'params': {'layer': result['layer'], 'name': params['label'][:80]}})
    return {'layer': result['layer']}


def local_copies(state, photo):
    """Masked smart objects above the photo that carry a local filter (one per area), top first."""
    top = state['layers']
    position = next(i for i, layer in enumerate(top) if layer['id'] == photo['id'])
    return [layer for layer in top[:position] if layer['kind'] == 'Smart Object' and layer.get('hasMask')
            and layer.get('smartFilters')]


def ex(engine, command, params=None):
    return engine.call('engine.execute', {'command': command, 'params': params or {}})


def deselect(engine):
    """Deselect when something is selected; PhotoCraft refuses to deselect nothing, and Layer via
    Copy already drops the selection."""
    if inspect(engine).get('hasSelection'):
        ex(engine, 'select.deselect')


def fresh_copy(engine, state, photo, copies):
    """A smart object to carry a new local filter. Over earlier copies it is a merged copy of the
    photo and those copies: a plain copy of the photo would cover their edits wherever the masks
    overlap (sharpening the person hid the shirt and skin grading beneath it)."""
    if not copies:
        return ex(engine, 'layer.duplicate', {'layer': photo['id']})['layer']
    selected = state.get('hasSelection')
    if selected:
        ex(engine, 'select.saveSelection', {'name': 'Studio area'})
        ex(engine, 'select.deselect')
    ex(engine, 'layer.select', {'layer': photo['id']})
    for layer in copies:
        ex(engine, 'layer.select', {'layer': layer['id'], 'mode': 'add'})
    stamp = ex(engine, 'layer.stampDown')['layer']
    ex(engine, 'layer.select', {'layer': stamp})
    smart = ex(engine, 'layer.smartObjects.convertToSmartObject')['layer']
    ex(engine, 'layer.moveTo', {'layer': smart, 'target': copies[0]['id'], 'position': 'above'})
    if selected:
        ex(engine, 'select.loadSelection', {'channel': 'Studio area'})
        ex(engine, 'channel.delete', {'channel': 'Studio area'})
    return smart


def area_of(name):
    return name.partition(' · ')[2].strip().lower()


def merge_camera_raw(engine, layer, wanted, label):
    """Add Camera Raw settings to a copy's existing filter; False if it has none."""
    for index, item in enumerate(layer.get('smartFilters') or []):
        if item.get('command') == 'filter.cameraRaw':
            merged = dict(item.get('params') or {})
            for key, value in wanted.items():
                merged[key] = max(-100, min(100, round(merged.get(key, 0) + value, 2)))
            engine.call('engine.execute', {'command': 'layer.smartFilter.setParams',
                                           'params': {'layer': layer['id'], 'index': index, 'params': merged}})
            head, _, area = label.partition(' · ')
            name = layer['name'] if head.lower() in layer['name'].lower() else \
                f'{layer["name"].partition(" · ")[0]}, {head[:1].lower() + head[1:]} · {area}'
            engine.call('engine.execute', {'command': 'layer.renameLayer',
                                           'params': {'layer': layer['id'], 'name': name[:80]}})
            return True
    return False


def local_filter(engine, folder, params, context):
    """A filter limited to the current selection: a masked copy of the photo carries it, so
    the original stays untouched and the effect can be hidden, faded or repainted.

    Camera Raw for an area that already has a copy is added to that copy's filter. A new area
    gets a copy above the earlier ones, made from them, so neither edit hides the other."""
    select_photo(engine, folder, {'smart': True}, context)
    state = inspect(engine)
    photo = photo_layer(state)
    copies = local_copies(state, photo)
    area = area_of(params['label'])
    if params['command'] == 'filter.cameraRaw' and params.get('region') and area:
        for layer in copies:
            if area_of(layer['name']) == area and merge_camera_raw(engine, layer, params.get('params', {}),
                                                                   params['label']):
                engine.call('engine.execute', {'command': 'select.deselect', 'params': {}})
                return {'layer': layer['id'], 'merged': True}
    copy = fresh_copy(engine, state, photo, copies)
    ex(engine, 'layer.select', {'layer': copy})
    ex(engine, 'layer.layerMask.revealSelection')
    ex(engine, 'layer.renameLayer', {'layer': copy, 'name': params['label'][:80]})
    ex(engine, 'select.deselect')
    ex(engine, params['command'], params.get('params', {}))
    if photo.get('hasMask') and any(layer['name'] == 'Backdrop' for layer in state['layers']):
        ex(engine, 'layer.setProps', {'layer': copy, 'clipped': True})
    return {'layer': copy}


def select_outline(engine, folder, params, context):
    """Select what is inside the boxes along its real outline. PhotoCraft's own object and
    subject selections took a rectangular block of curtain beside a man's head and cut into his
    hair; SAM 2.1 (the studio's outliner) traces him cleanly, and its outline is handed to
    PhotoCraft as lasso selections. Without SAM, PhotoCraft's object selection is used."""
    import numpy as np

    from image_studio.services import segment

    state = inspect(engine)
    width, height = state['width'], state['height']
    boxes = [box for box in params['boxes'] if box[2] > 1 and box[3] > 1]
    mode = params.get('mode', 'replace')
    if segment.available() and boxes:
        if context.get('progress'):
            context['progress'](desc=f'Outlining {params.get("what", "the subject")}…')
        probe = folder / '_outline.png'
        engine.call('doc.render', {'path': str(probe), 'maxSide': min(1536, max(width, height))})
        with Image.open(probe) as picture:
            image = picture.convert('RGB')
        probe.unlink(missing_ok=True)
        scale = image.width / width
        missing = []
        mask = segment.tidy(segment.outline(image, [
            (round(x * scale), round(y * scale), round((x + w) * scale), round((y + h) * scale))
            for x, y, w, h in boxes], missing))
        rings = outline_rings(np.asarray(mask) > 127, 1 / scale)
        if rings:
            for number, (points, cut) in enumerate(rings):
                ex(engine, 'select.lasso', {'points': points, 'antiAlias': True,
                                            'mode': 'subtract' if cut else mode if number == 0 else 'add'})
            # A box SAM found nothing in falls back to PhotoCraft's own selection, not a rectangle.
            for index in missing:
                ex(engine, 'select.object', {'rect': boxes[index], 'mode': 'add', 'sampleAllLayers': True})
            return {'coverage': float((np.asarray(mask) > 127).mean()), 'outlined': True}
    for number, box in enumerate(boxes):
        ex(engine, 'select.object', {'rect': box, 'mode': mode if number == 0 else 'add', 'sampleAllLayers': True})
    return {}


def outline_rings(mask, scale):
    """[(points in document pixels, is_hole)] for a boolean mask, outer shapes before the holes
    inside them, then islands inside holes, so applying them in order rebuilds the mask."""
    import cv2
    import numpy as np

    found, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    smallest = mask.size * 0.0003
    depth = []
    for index in range(len(found)):
        level, parent = 0, hierarchy[0][index][3]
        while parent >= 0:
            level, parent = level + 1, hierarchy[0][parent][3]
        depth.append(level)
    rings = []
    for index in sorted(range(len(found)), key=lambda i: depth[i]):
        if cv2.contourArea(found[index]) < smallest:
            continue
        simple = cv2.approxPolyDP(found[index], 0.8, True).reshape(-1, 2)
        if len(simple) >= 3:
            rings.append(([[round(float(x) * scale, 1), round(float(y) * scale, 1)] for x, y in simple],
                          depth[index] % 2 == 1))
    if rings and rings[0][1]:
        return []
    return rings


def _layer(state, layer_id):
    for layer in state['layers']:
        if layer['id'] == layer_id:
            return layer
    raise RuntimeError('The new text layer disappeared.')


def _region_tone(engine, folder, state, box):
    """(mean luminance 0..1, spread) of the composite under a document box."""
    probe = folder / '_tone.png'
    engine.call('doc.render', {'path': str(probe), 'maxSide': 640})
    with Image.open(probe) as picture:
        scale = picture.width / state['width']
        x, y, w, h = (round(v * scale) for v in box)
        region = picture.convert('L').crop((max(0, x), max(0, y), min(picture.width, x + max(1, w)),
                                            min(picture.height, y + max(1, h))))
        stat = ImageStat.Stat(region)
    probe.unlink(missing_ok=True)
    return stat.mean[0] / 255, stat.stddev[0] / 255


def text(engine, folder, params, context):
    """Create a title, fit it inside the margins, place its measured box exactly at the asked
    position, and pick a readable color (with a soft shadow on busy backgrounds) when the
    person did not choose one."""
    state = inspect(engine)
    width, height, resolution = state['width'], state['height'], state.get('resolution') or 72.0
    margin = round(min(width, height) * 0.05)
    size = float(params['size'])
    size_px = size * resolution / 72
    position = params.get('position') or 'center'
    estimate_w = min(width - 2 * margin, len(params['text']) * size_px * 0.58)
    estimate_h = size_px * 0.8
    estimate_x = margin if 'left' in position else width - margin - estimate_w if 'right' in position else (
        width - estimate_w) / 2
    estimate_y = margin if 'top' in position else height - margin - estimate_h if 'bottom' in position else (
        height - estimate_h) / 2
    color, shadow = params.get('color'), False
    tone, spread = _region_tone(engine, folder, state, (estimate_x, estimate_y, estimate_w, estimate_h))
    if color in (None, '', 'auto'):
        color = '#ffffff' if tone < 0.6 else '#141414'
        shadow = spread > 0.18 or 0.4 < tone < 0.7
    engine.call('engine.execute', {'command': 'layer.selectTop', 'params': {}})
    create = {'text': params['text'], 'x': round(width / 2), 'y': round(height / 2), 'size': size,
              'color': color, 'align': 'center', 'name': params.get('name') or params['text'][:60]}
    if params.get('font'):
        create['font'] = params['font']
    layer_id = engine.call('engine.execute', {'command': 'type.create', 'params': create})['layer']
    style = {key: params[key] for key in ('weight', 'italic') if params.get(key)}
    if style:
        engine.call('engine.execute', {'command': 'type.setStyle', 'params': {'layer': layer_id, **style}})
    fitted = False
    for _ in range(3):
        bounds = _layer(inspect(engine), layer_id)['bounds']
        if bounds[2] <= width - 2 * margin and bounds[3] <= height - 2 * margin:
            break
        ratio = min((width - 2 * margin) / bounds[2], (height - 2 * margin) / bounds[3]) * 0.97
        size = round(size * ratio, 1)
        engine.call('engine.execute', {'command': 'type.setStyle', 'params': {'layer': layer_id, 'size': size}})
        fitted = True
    x, y, w, h = _layer(inspect(engine), layer_id)['bounds']
    target_x = margin if 'left' in position else width - margin - w if 'right' in position else (width - w) / 2
    target_y = margin if 'top' in position else height - margin - h if 'bottom' in position else (height - h) / 2
    dx, dy = round(target_x - x), round(target_y - y)
    if dx or dy:
        engine.call('engine.execute', {'command': 'type.edit', 'params': {'layer': layer_id, 'move': [dx, dy]}})
    effects = list(params.get('effects') or [])
    if shadow and 'shadow' not in effects:
        effects.append('shadow')
    size_px = size * resolution / 72
    for effect in effects:
        if effect == 'shadow':
            engine.call('engine.execute', {'command': 'layer.layerStyle.dropShadow', 'params': {
                'layer': layer_id, 'color': '#000000', 'opacity': 55, 'angle': 120,
                'distance': max(2, round(size_px * 0.04)), 'size': max(3, round(size_px * 0.12)), 'add': True}})
        elif effect == 'outline':
            outline = '#000000' if color.lower() in ('#ffffff', '#fffff0') or tone > 0.5 else '#ffffff'
            engine.call('engine.execute', {'command': 'layer.layerStyle.stroke', 'params': {
                'layer': layer_id, 'size': max(1, round(size_px * 0.035)), 'position': 'outside',
                'color': outline, 'add': True}})
        elif effect == 'glow':
            engine.call('engine.execute', {'command': 'layer.layerStyle.outerGlow', 'params': {
                'layer': layer_id, 'color': color, 'opacity': 60, 'size': max(4, round(size_px * 0.25)),
                'add': True}})
    final = _layer(inspect(engine), layer_id)
    return {'bounds': final['bounds'], 'size': size, 'fitted': fitted, 'color': color,
            'auto_shadow': shadow and 'shadow' not in (params.get('effects') or []), 'layer': layer_id}


def ai_available():
    from image_studio.core.catalog import KONTEXT

    return (KONTEXT['folder'] / 'model_index.json').exists()


def keep_changes_only(original, painted):
    """The painted image where it really differs from the original, the original everywhere
    else. Kontext re-renders the whole frame and drifts fine detail; this keeps “change
    nothing else” literally true outside what it was asked to add."""
    import numpy as np
    from PIL import ImageChops, ImageFilter

    difference = ImageChops.difference(original, painted).convert('L')
    small = max(1, round(min(original.size) * 0.004)) | 1
    changed = difference.filter(ImageFilter.MedianFilter(small if small >= 3 else 3)).point(
        lambda value: 255 if value > 30 else 0)
    grow = max(3, round(min(original.size) * 0.012)) | 1
    changed = changed.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(grow / 2))
    if np.asarray(changed).max() == 0:
        return painted
    return Image.composite(painted, original, changed)


def ai_layer(engine, folder, params, context):
    """New content painted by FLUX.1 Kontext, placed as its own layer above the photo.

    PhotoCraft retouches and adjusts what is in the picture; it cannot paint new things or
    rebuild what is hidden behind a large object. Kontext does that on a render of the current
    document, limited to the boxes when given, and the result comes back as an embedded layer
    masked by the current selection (the object outline, the sky…) or by the soft boxes. The
    original photo stays untouched underneath.
    """
    from PIL import ImageDraw

    from image_studio.core.catalog import EDIT_QUALITY
    from image_studio.core.engine import EDIT_GUIDANCE, EDIT_STEPS
    from image_studio.services import workflows

    if not ai_available():
        raise ValueError('AI content editing is not installed. Run Download editing model.bat first.')
    state = inspect(engine)
    width, height = state['width'], state['height']
    source, result_path = folder / '_ai_source.png', folder / '_ai_layer.png'
    keep_selection = state.get('hasSelection')
    if keep_selection:
        engine.call('engine.execute', {'command': 'select.saveSelection', 'params': {'name': 'AI area'}})
        engine.call('engine.execute', {'command': 'select.deselect', 'params': {}})
    engine.call('doc.render', {'path': str(source), 'maxSide': max(width, height)})
    with Image.open(source) as rendered:
        picture = rendered.convert('RGB').resize((width, height), Image.LANCZOS)
    mask = None
    boxes = params.get('boxes') or []
    if params.get('area'):
        from .photocraft_area import mask_for
        mask = mask_for(params['area'], width, height)
    elif boxes:
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        for x, y, w, h in boxes:
            pad = round(max(w, h) * 0.12) + 4
            draw.rectangle((x - pad, y - pad, x + w + pad, y + h + pad), fill=255)
    progress = context.get('progress') or (lambda *a, **k: None)
    instructions = [params['instruction']] + ([params['retry']] if params.get('retry') else [])
    best, best_score, details = None, None, {}
    for attempt, instruction in enumerate(instructions):
        progress(desc='Painting with AI content editing (the first edit loads the model)…' if attempt == 0
                 else 'The object was replaced, not removed; trying again with a different approach…')
        with workflows.lock:
            path, details = workflows.engine.edit(
                picture, instruction, None, EDIT_STEPS, EDIT_GUIDANCE, mask=mask,
                quality=next(iter(EDIT_QUALITY)), status=lambda text: None, request=instruction,
                on_step=lambda step, total: progress(desc=f'AI content editing: step {step} of {total}'),
            )
        with Image.open(path) as painted:
            result = painted.convert('RGB').resize((width, height), Image.LANCZOS)
        # The intermediate render belongs to this document, not to the person's library.
        for leftover in (path, path.with_suffix('.json')):
            leftover.unlink(missing_ok=True)
        if not boxes and not keep_selection:
            result = keep_changes_only(picture, result)
        if not params.get('retry'):
            best = result
            break
        # Removal is checked: the area must blend with its surroundings, not hold a new object.
        from image_studio.integrations.photocraft_intents import removal_score

        score = max(removal_score(picture, result, [x / width, y / height, w / width, h / height])
                    for x, y, w, h in boxes)
        if best_score is None or score < best_score:
            best, best_score = result, score
        if score < 0.45:
            break
    best.save(result_path)
    select_photo(engine, folder, {'smart': True}, context)
    # Placing files is disabled in automation; open the result beside the document instead,
    # copy it, and paste it in place above the photo.
    engine.call('doc.open', {'path': str(result_path)})
    engine.call('engine.execute', {'command': 'select.all', 'params': {}})
    engine.call('engine.execute', {'command': 'edit.copy', 'params': {}})
    engine.call('doc.close', {})
    pasted = engine.call('engine.execute', {'command': 'edit.pasteSpecial.pasteInPlace', 'params': {}})
    layer_id = pasted.get('layer') if isinstance(pasted, dict) else inspect(engine)['activeLayer']
    engine.call('engine.execute', {'command': 'layer.renameLayer',
                                   'params': {'layer': layer_id, 'name': params['label'][:80]}})
    if keep_selection:
        engine.call('engine.execute', {'command': 'select.loadSelection', 'params': {'channel': 'AI area'}})
    elif boxes:
        for number, (x, y, w, h) in enumerate(boxes):
            pad = round(max(w, h) * 0.08) + 3
            engine.call('engine.execute', {'command': 'select.rect', 'params': {
                'x': x - pad, 'y': y - pad, 'width': w + 2 * pad, 'height': h + 2 * pad,
                'mode': 'replace' if number == 0 else 'add', 'feather': max(2, round(pad * 0.6))}})
    if keep_selection or boxes:
        engine.call('engine.execute', {'command': 'layer.layerMask.revealSelection', 'params': {}})
        engine.call('engine.execute', {'command': 'select.deselect', 'params': {}})
    if keep_selection:
        engine.call('engine.execute', {'command': 'channel.delete', 'params': {'channel': 'AI area'}})
    source.unlink(missing_ok=True)
    result_path.unlink(missing_ok=True)
    return {'layer': layer_id, 'seconds': details.get('total_seconds'), 'removal_score': best_score}


def crop_empty(engine, folder, params, context):
    """Crop away the empty edges a warp leaves (Adaptive Wide Angle pulls the frame inwards): the
    largest centred rectangle of the picture's own shape holding no empty pixel."""
    import numpy as np

    state = inspect(engine)
    width, height = state['width'], state['height']
    probe = folder / '_edges.png'
    engine.call('doc.render', {'path': str(probe), 'maxSide': 800})
    with Image.open(probe) as picture:
        rgba = np.asarray(picture.convert('RGBA'))
    probe.unlink(missing_ok=True)
    # Empty is transparent in the render (pure black is not: the café photo held 156 black pixels).
    empty = rgba[..., 3] < 250
    rows, cols = empty.shape
    total = np.pad(empty.cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def clear(scale):
        h, w = rows * scale, cols * scale
        top, left = round((rows - h) / 2), round((cols - w) / 2)
        bottom, right = top + round(h), left + round(w)
        return total[bottom, right] - total[top, right] - total[bottom, left] + total[top, left] == 0

    if clear(1.0):
        return {'cropped': False}
    low, high = 0.5, 1.0
    if not clear(low):
        return {'cropped': False}  # empty pixels inside the picture itself, not a warp's edges
    for _ in range(14):
        middle = (low + high) / 2
        low, high = (middle, high) if clear(middle) else (low, middle)
    w, h = round(width * low) - 2, round(height * low) - 2
    x, y = (width - w) // 2, (height - h) // 2
    ex(engine, 'image.crop', {'x': x, 'y': y, 'width': w, 'height': h})
    return {'cropped': True, 'size': [w, h]}


def mirror(engine, folder, params, context):
    """Copy the kept half of the picture as it looks now, flip it onto the other half as its own
    layer named Mirror. The merged copy it is cut from is removed again."""
    state = inspect(engine)
    width, height = state['width'], state['height']
    keep = params.get('keep', 'left')
    ex(engine, 'layer.selectTop')
    stamp = ex(engine, 'layer.stampVisible')['layer']
    if keep in ('left', 'right'):
        half = width // 2
        x0 = 0 if keep == 'left' else width - half
        rect = [x0, 0, x0 + half, height]
        # Where each corner of the kept half lands (clockwise from top-left): flipped across the middle.
        x1, x2 = width - x0, width - x0 - half
        quad = [[x1, 0], [x2, 0], [x2, height], [x1, height]]
    else:
        half = height // 2
        y0 = 0 if keep == 'top' else height - half
        rect = [0, y0, width, y0 + half]
        y1, y2 = height - y0, height - y0 - half
        quad = [[0, y1], [width, y1], [width, y2], [0, y2]]
    ex(engine, 'select.rect', {'x': rect[0], 'y': rect[1], 'width': rect[2] - rect[0], 'height': rect[3] - rect[1]})
    copied = ex(engine, 'layer.new.layerViaCopy')
    layer = copied.get('layer') if isinstance(copied, dict) else inspect(engine)['activeLayer']
    deselect(engine)
    ex(engine, 'edit.transform', {'layer': layer, 'rect': rect, 'quad': quad})
    ex(engine, 'layer.delete', {'layer': stamp})
    ex(engine, 'layer.renameLayer', {'layer': layer, 'name': 'Mirror'})
    return {'layer': layer}


def transform_object(engine, folder, params, context):
    """Move, scale or duplicate one object the way a retoucher does: lift it onto its own layer
    from the picture as it looks now, rebuild what was behind it (unless it is a duplicate), then
    put the lifted copy in its new place. `box` is the object, `to` its new box [x, y, w, h]."""
    x, y, w, h = params['box']
    what = params.get('what', 'the object')
    select_outline(engine, folder, {'boxes': [params['box']], 'what': what}, context)
    require_selection(engine, folder, {'what': what, 'min_coverage': 0.0005}, context)
    ex(engine, 'select.saveSelection', {'name': 'Studio object'})
    # Lifted on the traced outline with a soft pixel: growing it took a red line of the suitcase
    # along with a cat's paws (measured 2026-10-12). The hole below is filled from a grown copy.
    ex(engine, 'select.modify.feather', {'radius': 1})
    ex(engine, 'layer.selectTop')
    stamp = ex(engine, 'layer.stampVisible')['layer']
    lifted = ex(engine, 'layer.new.layerViaCopy')
    layer = lifted.get('layer') if isinstance(lifted, dict) else inspect(engine)['activeLayer']
    ex(engine, 'layer.delete', {'layer': stamp})
    ex(engine, 'layer.renameLayer', {'layer': layer, 'name': f'{params.get("label", what)}'[:80]})
    if not params.get('duplicate'):
        # The hole it leaves: AI rebuilds large areas, content-aware fill copes with small ones.
        state = inspect(engine)
        if ai_available() and w * h >= 0.015 * state['width'] * state['height']:
            deselect(engine)
            ai_layer(engine, folder, {
                'instruction': f'Remove {what}. In its place show only the empty background that was behind it, '
                               'continuing the surroundings seamlessly. Change nothing else.',
                'retry': f'Erase {what} completely and paint the plain surface and background around it. '
                         'Do not add any object. Change nothing else.',
                'boxes': [params['box']], 'label': f'Behind {what}'[:80]}, context)
        else:
            ex(engine, 'select.loadSelection', {'channel': 'Studio object'})
            ex(engine, 'select.modify.expand', {'radius': max(4, round(min(w, h) * 0.04))})
            retouch_fill(engine, folder, {'label': f'Removed {what}'[:80]}, context)
        ex(engine, 'layer.moveTo', {'layer': layer, 'target': inspect(engine)['layers'][0]['id'],
                                    'position': 'above'})
    deselect(engine)
    ex(engine, 'channel.delete', {'channel': 'Studio object'})
    tx, ty, tw, th = params['to']
    ex(engine, 'edit.transform', {'layer': layer, 'rect': [x, y, x + w, y + h],
                                  'quad': [[tx, ty], [tx + tw, ty], [tx + tw, ty + th], [tx, ty + th]]})
    return {'layer': layer}


def reflection(engine, folder, params, context):
    """A product reflection: the objects as they look now, flipped below their shared baseline,
    softened and faded on their own layer under the objects."""
    boxes = params['boxes']
    what = params.get('what', 'the objects')
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    select_outline(engine, folder, {'boxes': boxes, 'what': what}, context)
    require_selection(engine, folder, {'what': what, 'min_coverage': 0.0005}, context)
    ex(engine, 'layer.selectTop')
    stamp = ex(engine, 'layer.stampVisible')['layer']
    lifted = ex(engine, 'layer.new.layerViaCopy')
    layer = lifted.get('layer') if isinstance(lifted, dict) else inspect(engine)['activeLayer']
    ex(engine, 'layer.delete', {'layer': stamp})
    deselect(engine)
    # Mirrored about the baseline: the top edge lands one object-height below it.
    depth = y1 - y0
    ex(engine, 'edit.transform', {'layer': layer, 'rect': [x0, y0, x1, y1],
                                  'quad': [[x0, y1 + depth], [x1, y1 + depth], [x1, y1], [x0, y1]]})
    ex(engine, 'filter.blur.gaussianBlur', {'radius': max(1, round(depth * 0.01))})
    ex(engine, 'layer.setProps', {'layer': layer, 'opacity': params.get('opacity', 0.3),
                                  'name': f'Reflection of {what}'[:80]})
    # Behind the objects, so it only shows on the surface below them.
    ex(engine, 'layer.moveTo', {'layer': layer, 'target': photo_layer(inspect(engine))['id'], 'position': 'above'})
    return {'layer': layer}


HANDLERS = {
    'studio.reflection': reflection,
    'studio.crop_empty': crop_empty,
    'studio.transform_object': transform_object,
    'studio.mirror': mirror,
    'studio.select_marked': select_marked,
    'studio.ai_layer': ai_layer,
    'studio.select_photo': select_photo,
    'studio.select_insert': select_insert,
    'studio.select_top': select_top,
    'studio.require_selection': require_selection,
    'studio.develop': develop,
    'studio.retouch_fill': retouch_fill,
    'studio.local_filter': local_filter,
    'studio.select_outline': select_outline,
    'studio.text': text,
}


def run(engine, folder, command, params, context):
    return HANDLERS[command](engine, folder, params, context)

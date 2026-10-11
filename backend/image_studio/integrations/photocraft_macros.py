"""Studio steps that need the live document: they inspect it, measure, then act.

A compiled plan cannot know layer IDs created while it runs (converting the photo to a smart
object gives it a new ID) or how wide a title renders in a font. These steps look at the
document at that moment instead of guessing. They are run by the workspace in place of a
PhotoCraft command whose ID starts with ``studio.``.
"""

from PIL import Image, ImageStat

PHOTO = 'Photo'
RETOUCH_PREFIXES = ('Removed ', 'Content-Aware Fill')
GRAPHIC_KINDS = {'Type', 'Shape'}
GRAPHIC_NAMES = {'Frame'}
NAMES = {
    'studio.select_photo', 'studio.select_insert', 'studio.select_top', 'studio.require_selection',
    'studio.develop', 'studio.retouch_fill', 'studio.local_filter', 'studio.text', 'studio.ai_layer',
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
    engine.call('engine.execute', {'command': 'layer.renameLayer',
                                   'params': {'layer': result['layer'], 'name': params['label'][:80]}})
    return {'layer': result['layer']}


def local_filter(engine, folder, params, context):
    """A filter limited to the current selection: a masked copy of the photo carries it, so
    the original stays untouched and the effect can be hidden, faded or repainted."""
    select_photo(engine, folder, {'smart': True}, context)
    state = inspect(engine)
    photo = photo_layer(state)
    copy = engine.call('engine.execute', {'command': 'layer.duplicate', 'params': {'layer': photo['id']}})
    engine.call('engine.execute', {'command': 'layer.select', 'params': {'layer': copy['layer']}})
    engine.call('engine.execute', {'command': 'layer.layerMask.revealSelection', 'params': {}})
    engine.call('engine.execute', {'command': 'layer.renameLayer',
                                   'params': {'layer': copy['layer'], 'name': params['label'][:80]}})
    engine.call('engine.execute', {'command': 'select.deselect', 'params': {}})
    engine.call('engine.execute', {'command': params['command'], 'params': params.get('params', {})})
    if photo.get('hasMask') and any(layer['name'] == 'Backdrop' for layer in state['layers']):
        engine.call('engine.execute', {'command': 'layer.setProps', 'params': {'layer': copy['layer'],
                                                                                'clipped': True}})
    return {'layer': copy['layer']}


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
    if boxes:
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


HANDLERS = {
    'studio.ai_layer': ai_layer,
    'studio.select_photo': select_photo,
    'studio.select_insert': select_insert,
    'studio.select_top': select_top,
    'studio.require_selection': require_selection,
    'studio.develop': develop,
    'studio.retouch_fill': retouch_fill,
    'studio.local_filter': local_filter,
    'studio.text': text,
}


def run(engine, folder, command, params, context):
    return HANDLERS[command](engine, folder, params, context)

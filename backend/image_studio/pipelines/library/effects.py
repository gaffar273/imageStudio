"""Filters and effects, each built the way it is made by hand in an editor: a screened blurred
copy for a glow, noise streaked by motion blur for rain, a flipped half for a mirror, a
high-pass copy in Overlay for local-contrast sharpening."""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


def filtered(b, index, edit, command, params):
    """A filter on the whole photo (a smart filter) or on the target only (a masked copy)."""
    if edit['target'] in ('whole image', 'layer'):
        b.add(index, 'studio.select_photo', {'smart': True}, 'Select the photo')
        b.add(index, command, params, lang.short_label(edit))
    elif b.selection(index, edit):
        b.add(index, 'studio.local_filter', {'command': command, 'params': params, 'label': lang.short_label(edit)},
              f'{lang.short_label(edit)} (masked)')
        b.end_selection(index)


@procedure('blur', 'Blur', 'effect', 'effect', 'soften/blur the target', area_safe=True)
def blur(b, index, edit):
    w, h = b.canvas.width, b.canvas.height
    filtered(b, index, edit, 'filter.blur.gaussianBlur',
             {'radius': lang.amount({**edit, 'direction': 'increase'}, max(2, min(w, h) * 0.006), 0.1, 250)})


@procedure('motion_blur', 'Motion blur', 'effect', 'effect', 'motion blur (value = distance)', area_safe=True)
def motion_blur(b, index, edit):
    filtered(b, index, edit, 'filter.blur.motionBlur', {
        'distance': round(lang.amount({**edit, 'direction': 'increase'}, 20, 1, 2000)),
        'angle': 90 if re.search(r'vertical|falling|up|down', edit['quote'], re.IGNORECASE) else 0})


@procedure('radial_blur', 'Zoom or spin blur', 'effect', 'effect',
           'zoom blur or spin blur from a point (choice = zoom or spin, position = center)', options=('zoom', 'spin'),
           area_safe=True)
def radial_blur(b, index, edit):
    cx, cy = lang.position_xy(edit['position'] or 'center')
    spin = re.search(r'spin|twirl|rotat|circular', edit['choice'] + ' ' + edit['quote'], re.IGNORECASE)
    filtered(b, index, edit, 'filter.blur.radialBlur', {
        'amount': round(lang.amount({**edit, 'direction': 'increase'}, 8 if spin else 12, 1, 100)),
        'method': 'spin' if spin else 'zoom', 'quality': 'best', 'centerX': cx, 'centerY': cy})


@procedure('tilt_shift', 'Tilt-shift miniature', 'effect', 'effect', 'miniature tilt-shift blur, sharp band at position',
           area_safe=True)
def tilt_shift(b, index, edit):
    _, cy = lang.position_xy(edit['position'] or 'center')
    filtered(b, index, edit, 'filter.blurGallery.tiltShift', {
        'centerY': cy, 'blur': round(lang.amount({**edit, 'direction': 'increase'}, 15, 0, 500))})


@procedure('lens_flare', 'Lens flare', 'effect', 'effect', 'lens flare at position', area_safe=True)
def lens_flare(b, index, edit):
    cx, cy = lang.position_xy(edit['position'] or 'center')
    filtered(b, index, edit, 'filter.render.lensFlare', {
        'centerX': cx if edit['position'] else 0.2, 'centerY': cy if edit['position'] else 0.2,
        'brightness': round(lang.amount({**edit, 'direction': 'increase'}, 100, 10, 300))})


@procedure('relight', 'Relight', 'light', 'effect', 'add directional light coming from position (color = light color)',
           area_safe=True)
def relight(b, index, edit):
    angles = {'right': 0, 'top right': 45, 'top': 90, 'top left': 135, 'left': 180, 'bottom left': -135,
              'bottom': -90, 'bottom right': -45, 'center': 90, '': 135}
    color = lang.hex_color(edit['color'])
    warmth = 0
    if color:
        hue = lang.hls(color)[0] * 360
        warmth = 40 if hue < 70 or hue > 330 else -40 if 160 < hue < 280 else 0
    filtered(b, index, edit, 'filter.render.relight', {
        'angle': angles[edit['position']], 'warmth': warmth,
        'intensity': round(lang.amount({**edit, 'direction': 'increase'}, 40, 0, 100))})


@procedure('artistic', 'Artistic filter', 'effect', 'effect',
           'artistic filter, choice = oil paint, watercolor, pencil, cutout, dry brush, poster edges, ink outlines, '
           'sponge, emboss, find edges, solarize, pixelate, halftone, glitch…', options=tuple(lang.ARTISTIC) + ('glitch',),
           area_safe=True)
def artistic(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    if re.search(r'glitch|rgb split|channel (split|shift)', words):
        glitch(b, index, edit)
        return
    found = next((lang.ARTISTIC[key] for key in sorted(lang.ARTISTIC, key=len, reverse=True) if key in words), None)
    if found is None:
        b.expert_requests.append(index)
        return
    filtered(b, index, edit, *found)


def glitch(b, index, edit):
    """RGB split: copies that show only the red or only the blue channel, nudged apart."""
    shift = max(2, round(b.canvas.width * 0.006 * lang.LEVEL[edit['strength']]))
    b.add(index, 'studio.select_insert', {}, 'Choose where the layers go')
    for channels, dx, name in (([True, False, False], shift, 'Glitch red'), ([False, False, True], -shift, 'Glitch blue')):
        b.add(index, 'layer.stampVisible', {}, f'Copy the picture for {name.lower()}')
        b.add(index, 'layer.setProps', {'channels': channels, 'name': name}, f'{name}: one channel only')
        b.add(index, 'layer.translate', {'dx': dx, 'dy': 0}, f'Shift it {dx:+d}px')


@procedure('glow', 'Glow (Orton)', 'effect', 'effect',
           'soft glow or bloom (Orton effect, glowing lights or neon); target = what glows', area_safe=True)
def glow(b, index, edit):
    """Orton glow: a blurred copy of the picture screened over it, limited to what glows when named."""
    radius = round(min(b.canvas.width, b.canvas.height) * 0.02 * lang.LEVEL[edit['strength']], 1)
    opacity = {'subtle': 0.35, 'moderate': 0.55, 'strong': 0.8}[edit['strength']]
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'layer.stampVisible', {}, 'Copy the picture for the glow')
    b.add(index, 'filter.blur.gaussianBlur', {'radius': max(2, radius)}, f'Blur it ({radius:g} px)')
    b.add(index, 'layer.setProps', {'blend': 'Screen', 'opacity': opacity, 'name': 'Glow'},
          f'Screen it at {opacity:.0%} as a glow')
    if edit['target'] in ('object', 'main subject'):
        if not b.selection(index, edit):
            return
        b.add(index, 'select.modify.expand', {'radius': max(4, round(radius * 2))}, 'Let the glow spill out')
        b.add(index, 'select.modify.feather', {'radius': max(2, round(radius))}, 'Soften it')
        b.add(index, 'layer.layerMask.revealSelection', {}, 'Glow only there')
        b.end_selection(index)


@procedure('high_pass_sharpen', 'High-pass sharpening', 'correct', 'effect',
           'crisp local-contrast sharpening the retoucher’s way (a high-pass copy in Overlay), on the whole picture or '
           'the target only (“sharpen the subject”, “make the details crisp”)', area_safe=False,
           examples=('make the details on the product crisp',))
def high_pass_sharpen(b, index, edit):
    """A merged copy is high-passed at a radius set by the picture size, made colourless (so
    sharpening never shifts colours) and blended in Overlay; targeted, it is masked to the target."""
    side = min(b.canvas.width, b.canvas.height)
    radius = round(max(1.0, side / 900) * {'subtle': 0.8, 'moderate': 1.2, 'strong': 2.0}[edit['strength']], 1)
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'layer.stampVisible', {}, 'Copy the picture for sharpening')
    b.add(index, 'filter.other.highPass', {'radius': radius}, f'High pass ({radius:g} px)')
    b.add(index, 'image.adjustments.desaturate', {}, 'Make it colourless')
    opacity = {'subtle': 0.6, 'moderate': 0.85, 'strong': 1.0}[edit['strength']]
    b.add(index, 'layer.setProps', {'blend': 'Overlay', 'opacity': opacity, 'name': 'High-pass sharpen'},
          f'Overlay at {opacity:.0%}')
    if edit['target'] not in ('whole image', 'layer'):
        if not b.selection(index, edit):
            return
        b.add(index, 'layer.layerMask.revealSelection', {}, 'Sharpen only there')
        b.end_selection(index)


@procedure('light_leak', 'Light leak', 'effect', 'effect',
           'a film light leak: a warm glow bleeding in from one edge or corner (position; color, orange by default)',
           examples=('add a light leak in the top right',),
           requires=r'leak|flare|film|glow')
def light_leak(b, index, edit):
    """A pool of warm light centred just outside the frame at the corner or edge, faded to nothing
    well before the middle. A linear gradient across the whole frame tinted everything orange
    (measured 2026-10-12), so the light is a feathered ellipse screened over the picture."""
    color = lang.hex_color(edit['color']) or '#ff7a1a'
    edge = edit['position'] or 'top right'
    w, h = b.canvas.width, b.canvas.height
    cx, cy = lang.position_xy(edge)
    cx = 0 if cx < 0.5 else w if cx > 0.5 else w / 2
    cy = 0 if cy < 0.5 else h if cy > 0.5 else h / 2
    radius = max(w, h) * {'subtle': 0.35, 'moderate': 0.45, 'strong': 0.6}[edit['strength']]
    opacity = {'subtle': 0.55, 'moderate': 0.75, 'strong': 0.9}[edit['strength']]
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'select.rect', {'x': round(cx - radius), 'y': round(cy - radius), 'width': round(radius * 2),
                                 'height': round(radius * 2), 'ellipse': True, 'feather': round(radius * 0.6)},
          f'A soft pool of light at the {edge}')
    b.add(index, 'layer.newFillLayer.solidColor', {'color': color}, 'Warm light')
    b.add(index, 'layer.setProps', {'blend': 'Screen', 'opacity': opacity, 'name': 'Light leak'},
          f'Screen it at {opacity:.0%}')
    b.end_selection(index)


@procedure('weather', 'Rain or snow', 'effect', 'effect', 'add falling rain or snow (choice = rain or snow)',
           options=('rain', 'snow'))
def weather(b, index, edit):
    """Rain or snow the way it is made by hand: sparse noise on a black layer, shaped, then screened."""
    snow = bool(re.search(r'snow', edit['choice'] + ' ' + edit['quote'], re.IGNORECASE))
    side = min(b.canvas.width, b.canvas.height)
    name = 'Snow' if snow else 'Rain'
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'layer.new.layer', {'name': name}, f'New {name.lower()} layer')
    b.add(index, 'edit.fill', {'contents': 'color', 'color': '#000000'}, 'Fill it black')
    # Measured in PhotoCraft: Add Noise on black is half-normal with sigma ≈ 0.64 × amount, so the
    # Levels cut-off decides how many specks survive (amount 100: 0.085% reach level 200).
    level = edit['strength']
    if snow:
        b.add(index, 'filter.noise.addNoise', {'amount': 100, 'distribution': 'gaussian', 'monochromatic': True},
              'Scatter specks')
        b.add(index, 'image.adjustments.levels', {'inBlack': {'subtle': 210, 'moderate': 200, 'strong': 185}[level],
                                                  'inWhite': 255}, 'Keep only a few as flakes')
        b.add(index, 'filter.other.maximum', {'radius': max(1, round(side / 1100))}, 'Grow them into flakes')
        b.add(index, 'filter.blur.gaussianBlur', {'radius': max(0.8, round(side / 1200, 1))}, 'Soften the flakes')
        b.add(index, 'image.adjustments.levels', {'inBlack': 0, 'inWhite': 50}, 'Make the flakes white')
    else:
        b.add(index, 'filter.noise.addNoise', {'amount': 150, 'distribution': 'gaussian', 'monochromatic': True},
              'Scatter specks')
        b.add(index, 'image.adjustments.levels', {'inBlack': {'subtle': 140, 'moderate': 120, 'strong': 100}[level],
                                                  'inWhite': 255}, 'Keep only some drops')
        b.add(index, 'filter.blur.motionBlur', {'distance': max(10, round(side * 0.04)), 'angle': 75},
              'Streak them as falling rain')
        b.add(index, 'image.adjustments.levels', {'inBlack': 5, 'inWhite': 60}, 'Brighten the streaks')
    opacity = 0.9 if snow else 0.6
    b.add(index, 'layer.setProps', {'blend': 'Screen', 'opacity': opacity}, f'Screen at {opacity:.0%}')


@procedure('mirror', 'Mirror a half', 'effect', 'effect',
           'mirror one half of the picture onto the other (choice = left, right, top or bottom = the half that is kept)',
           options=('left', 'right', 'top', 'bottom'))
def mirror(b, index, edit):
    words = (edit['choice'] + ' ' + edit['quote']).lower()
    keep = next((side for side in ('left', 'right', 'top', 'bottom') if side in words), 'left')
    b.add(index, 'studio.mirror', {'keep': keep}, f'Mirror the {keep} half onto the other side')


@procedure('drop_shadow', 'Contact shadow', 'background', 'effect',
           'soft contact shadow under the main subject or objects, as if standing on a surface', whole_picture=True)
def drop_shadow(b, index, edit):
    """A soft shadow where each object meets the surface, under the objects, not over them."""
    key, boxes = b.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the subject"} to put a shadow under.')
        return
    strength = lang.LEVEL[edit['strength']]
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'layer.new.layer', {'name': 'Shadow'}, 'New shadow layer')
    heights = []
    for number, (x, y, w, h) in enumerate(boxes):
        sh = max(6, round(h * 0.07))
        heights.append(sh)
        b.add(index, 'select.rect', {'x': round(x + w * 0.06), 'y': round(y + h - sh * 0.6),
                                     'width': max(2, round(w * 0.88)), 'height': sh, 'ellipse': True,
                                     'mode': 'replace' if number == 0 else 'add'}, 'Where it touches down')
    b.add(index, 'edit.fill', {'contents': 'color', 'color': '#000000'}, 'Fill the shadow')
    b.end_selection(index)
    b.add(index, 'filter.blur.gaussianBlur', {'radius': max(3, round(max(heights) * 0.45))}, 'Soften it')
    b.add(index, 'layer.setProps', {'blend': 'Multiply', 'opacity': min(0.85, round(0.45 * strength, 2))},
          'Multiply the shadow onto the surface')
    b.add(index, 'studio.select_outline', {'boxes': boxes, 'what': key}, f'Select {key}')
    b.add(index, 'layer.layerMask.hideSelection', {}, f'Keep the shadow behind {key}')
    b.end_selection(index)
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})


@procedure('reflection', 'Mirror reflection', 'background', 'effect',
           'a mirror reflection of the subject or objects on the surface below them', whole_picture=True)
def reflection(b, index, edit):
    key, boxes = b.target_boxes({**edit, 'target': 'object' if edit['object'] else 'main subject'})
    if not boxes:
        b.blocking.append(f'Could not find {key or "the subject"} to reflect.')
        return
    opacity = {'subtle': 0.2, 'moderate': 0.3, 'strong': 0.45}[edit['strength']]
    b.add(index, 'studio.reflection', {'boxes': boxes, 'what': key, 'opacity': opacity},
          f'Reflect {key} on the surface below ({opacity:.0%})')
    b.regions.append({'requirement': index, 'label': key, 'boxes': b.normalized(boxes)})

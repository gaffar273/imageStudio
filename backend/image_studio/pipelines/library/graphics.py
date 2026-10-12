"""Text and graphics, placed on the final canvas after every crop and color change.

Text is created, measured in the live document, shrunk if it does not fit inside 5% margins and
moved so its measured box sits exactly at the asked position (studio.text).
"""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


@procedure('add_text', 'Add text', 'graphics', 'graphics',
           'add text: text = EXACT words, position, color, size or value in pt, choice = font or style (bold, italic, '
           'serif, script, shadow, outline, glow)',
           examples=('add the title SUMMER at the top in white', 'add a watermark'))
def add_text(b, index, edit):
    if not edit['text']:
        b.blocking.append('Which words should the text say? Put them in quotes.')
        return
    family, weight, italic, effects = lang.font_choice(edit['choice'], b.fonts)
    params = {'text': edit['text'], 'position': edit['position'] or 'center',
              'size': lang.text_size_pt(edit, b.canvas), 'color': lang.hex_color(edit['color']) or 'auto',
              'effects': effects, 'name': edit['text'][:60]}
    if family:
        params['font'] = family
    if weight:
        params['weight'] = weight
    if italic:
        params['italic'] = True
    if edit['choice'] and not family and not (weight or italic or effects):
        b.notes.append(f'Font “{edit["choice"]}” is not installed; using the default font.')
    detail = [f'{params["size"]:g} pt', edit['position'] or 'center', edit['color'] or 'readable color', family or '']
    b.add(index, 'studio.text', params, f'Add “{edit["text"][:40]}” · ' + ', '.join(d for d in detail if d))
    if re.search(r'watermark|semi[\s-]?transparent|transparent|faint|see[\s-]?through|ghost', edit['quote'],
                 re.IGNORECASE):
        opacity = edit['value'] / 100 if edit['value'] and 1 <= edit['value'] <= 100 and \
            re.search(r'\d\s*%', edit['quote']) else 0.5
        b.add(index, 'layer.setProps', {'opacity': opacity}, f'Text at {opacity:.0%} opacity')


@procedure('edit_text', 'Change existing text', 'graphics', 'graphics',
           'change the words of an existing text layer (object = current text, text = new)')
def edit_text(b, index, edit):
    layer = b.layer_named(edit['object'])
    if layer is None or layer['kind'] != 'Type':
        b.blocking.append(f'Which text layer does “{edit["quote"]}” mean?')
        return
    if not edit['text']:
        b.blocking.append('What should the text say instead?')
        return
    b.add(index, 'type.edit', {'layer': layer['id'], 'text': edit['text']},
          f'Change “{layer["name"][:30]}” to “{edit["text"][:30]}”')


@procedure('frame', 'Frame line', 'graphics', 'graphics', 'draw a frame line inside the edges (value = px, color)')
def frame(b, index, edit):
    width = round(edit['value']) if edit['value'] else max(2, round(min(b.canvas.width, b.canvas.height) * 0.015))
    color = lang.hex_color(edit['color']) or '#ffffff'
    inset = round(min(b.canvas.width, b.canvas.height) * 0.03)
    b.add(index, 'studio.select_top', {}, 'Work above everything')
    b.add(index, 'layer.new.layer', {'name': 'Frame'}, 'New frame layer')
    b.add(index, 'select.rect', {'x': inset, 'y': inset, 'width': b.canvas.width - inset * 2,
                                 'height': b.canvas.height - inset * 2}, 'Frame area')
    b.add(index, 'edit.stroke', {'width': min(250, width), 'color': color, 'location': 'inside'},
          f'Draw a {width}px frame line')
    b.end_selection(index)


@procedure('gradient_overlay', 'Gradient overlay', 'graphics', 'graphics',
           'a gradient that darkens (or tints with color) from one edge, e.g. behind text (position = the darkest edge)')
def gradient_overlay(b, index, edit):
    """A gradient multiplied over the picture: the named color at one edge fading to nothing."""
    color = lang.hex_color(edit['color']) or '#000000'
    edge = edit['position'] or next((side for side in ('top', 'left', 'right', 'bottom') if side in edit['quote'].lower()),
                                    'bottom')
    angle = {'bottom': 90, 'top': -90, 'left': 0, 'right': 180}.get(edge.split()[-1], 90)
    opacity = {'subtle': 0.45, 'moderate': 0.7, 'strong': 0.9}[edit['strength']]
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    b.add(index, 'layer.newFillLayer.gradient', {'from': color, 'to': '#ffffff', 'angle': angle, 'style': 'linear'},
          f'Gradient from the {edge}')
    b.add(index, 'layer.setProps', {'blend': 'Multiply', 'opacity': opacity,
                                    'name': f'{edit["color"] or "Dark"} gradient'.capitalize()},
          f'Multiply it at {opacity:.0%} (white leaves the rest unchanged)')


@procedure('round_corners', 'Round the corners', 'graphics', 'graphics',
           'round the corners of the picture (color = what shows in the corners)')
def round_corners(b, index, edit):
    w, h = b.canvas.width, b.canvas.height
    radius = round(edit['value']) if edit['value'] else round(min(w, h) * {'subtle': 0.03, 'moderate': 0.06,
                                                                         'strong': 0.12}[edit['strength']])
    color = lang.hex_color(edit['color']) or '#ffffff'
    b.add(index, 'studio.select_top', {}, 'Work above everything')
    b.add(index, 'layer.new.layer', {'name': 'Rounded corners'}, 'New corners layer')
    b.add(index, 'select.rect', {'x': 0, 'y': 0, 'width': w, 'height': h}, 'Select the picture')
    b.add(index, 'select.modify.smooth', {'radius': max(1, min(500, radius)), 'applyAtCanvasBounds': True},
          f'Round the corners ({radius}px)')
    b.add(index, 'select.inverse', {}, 'Select the corners')
    b.add(index, 'edit.fill', {'contents': 'color', 'color': color}, f'Fill them {edit["color"] or "white"}')
    b.end_selection(index)


PICTURE_FRAMES = ['vineWithFlowers', 'vineWithLeaves', 'ivy', 'roses', 'daisies', 'berries', 'bamboo', 'waves',
                  'zigzag', 'dots', 'rope', 'scallops', 'doubleLine', 'snowflakes', 'stars', 'hearts']


@procedure('picture_frame', 'Decorative frame', 'graphics', 'graphics',
           'decorative frame, choice = roses, ivy, bamboo, waves, dots, stars, hearts…', options=tuple(PICTURE_FRAMES))
def picture_frame(b, index, edit):
    choice = (edit['choice'] or 'doubleLine').lower()
    chosen = next((name for name in PICTURE_FRAMES if name.lower() in choice.replace(' ', '')), 'doubleLine')
    b.add(index, 'studio.select_top', {}, 'Work above everything')
    b.add(index, 'filter.render.pictureFrame', {'frame': chosen, 'newLayer': True}, f'{chosen} frame')


@procedure('color_overlay', 'Color overlay', 'graphics', 'graphics',
           'semi-transparent color layer over the image (color, value = opacity %)', area_safe=True)
def color_overlay(b, index, edit):
    color = lang.hex_color(edit['color'])
    if not color:
        b.blocking.append('Which color should the overlay be?')
        return
    opacity = max(1, min(100, edit['value'] if edit['value'] is not None else
                         {'subtle': 15, 'moderate': 30, 'strong': 50}[edit['strength']]))
    b.add(index, 'studio.select_insert', {}, 'Choose where the layer goes')
    if edit['target'] != 'whole image' and not b.selection(index, edit):
        return
    b.add(index, 'layer.newFillLayer.solidColor', {'color': color}, f'{edit["color"]} overlay')
    blend = (edit['choice'] or '').title() if edit['choice'].lower() in (
        'multiply', 'screen', 'overlay', 'soft light', 'color', 'hard light') else 'Normal'
    b.add(index, 'layer.setProps', {'opacity': opacity / 100, 'blend': blend, 'name': f'{edit["color"]} overlay'},
          f'{opacity:g}% opacity, {blend}')
    if edit['target'] != 'whole image':
        b.end_selection(index)


@procedure('letterbox', 'Cinema letterbox bars', 'graphics', 'graphics',
           'black cinema bars at the top and bottom for a widescreen film frame (aspect, 2.39:1 by default)',
           examples=('add cinematic black bars',),
           requires=r'bars?\b|letterbox|widescreen|cinema|anamorphic|2\.39|2\.35')
def letterbox(b, index, edit):
    """Bars drawn on their own layer so the picture underneath stays whole and editable."""
    ratio = lang.aspect_from(edit['aspect']) or (2.39, 1)
    w, h = b.canvas.width, b.canvas.height
    band = round(w / (ratio[0] / ratio[1]))
    if band >= h:
        b.notes.append('The picture is already wider than that frame, so no bars were needed.')
        return
    bar = (h - band) // 2
    color = lang.hex_color(edit['color']) or '#000000'
    b.add(index, 'studio.select_top', {}, 'Work above everything')
    b.add(index, 'layer.new.layer', {'name': 'Letterbox'}, 'New bars layer')
    b.add(index, 'select.rect', {'x': 0, 'y': 0, 'width': w, 'height': bar}, 'Top bar')
    b.add(index, 'select.rect', {'x': 0, 'y': h - bar, 'width': w, 'height': bar, 'mode': 'add'}, 'Bottom bar')
    b.add(index, 'edit.fill', {'contents': 'color', 'color': color}, f'Fill the bars ({ratio[0]:g}:{ratio[1]:g} frame)')
    b.end_selection(index)

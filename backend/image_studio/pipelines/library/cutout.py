"""Cut-outs and backgrounds. The subject is traced along its real outline (SAM 2.1, handed to
PhotoCraft as lasso rings); the background is everything else."""

import re

from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines.core import procedure


@procedure('blur_background', 'Blur the background', 'background', 'cutout',
           'blur behind the main subject (portrait/bokeh look)', whole_picture=True, area_safe=True,
           examples=('blur the background',))
def blur_background(b, index, edit):
    edit = {**edit, 'target': 'main subject'}
    if not b.selection(index, edit, invert=True):
        return
    b.add(index, 'select.modify.feather', {'radius': max(1, round(min(b.canvas.width, b.canvas.height) * 0.003))},
          'Soften the mask edge')
    radius = round(lang.amount({**edit, 'direction': 'increase'}, 15, 1, 100))
    b.add(index, 'studio.local_filter', {'command': 'filter.blur.lensBlur', 'params': {'radius': radius},
                                         'label': 'Background blur'}, f'Lens blur the background ({radius})')
    b.end_selection(index)


@procedure('remove_background', 'Cut out the subject', 'background', 'cutout',
           'cut out the main subject; color = new backdrop color or transparent', whole_picture=True,
           examples=('remove the background', 'put the puppy on a pastel pink background'))
def remove_background(b, index, edit):
    if not b.selection(index, {**edit, 'target': 'main subject'}):
        return
    b.add(index, 'studio.select_photo', {'smart': True, 'keep_selection': True}, 'Select the photo')
    b.add(index, 'layer.layerMask.revealSelection', {}, 'Hide everything but the subject (layer mask)')
    b.end_selection(index)
    color = lang.hex_color(edit['color'])
    if color and re.search(r'gradient|studio', edit['quote'], re.IGNORECASE):
        # A studio backdrop: lighter behind the subject, falling off toward the edges.
        b.add(index, 'layer.newFillLayer.gradient', {'from': lang.mix(color, '#ffffff', 0.25),
                                                     'to': lang.mix(color, '#000000', 0.35), 'style': 'radial'},
              f'New {edit["color"]} gradient backdrop')
    elif color:
        b.add(index, 'layer.newFillLayer.solidColor', {'color': color}, f'New {edit["color"]} backdrop')
    if color:
        b.add(index, 'layer.renameLayer', {'name': 'Backdrop'}, 'Name the layer “Backdrop”')
        b.add(index, 'layer.arrange.sendToBack', {}, 'Put the backdrop behind the subject')

"""User-drawn edit boundaries, independent of the vision model's object guesses."""

from typing import Annotated, Literal
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw
from pydantic import BaseModel, Field, model_validator

from . import photocraft_intents as intents

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Mark(BaseModel):
    tool: Literal['brush', 'lasso', 'erase']
    points: list[tuple[Unit, Unit]] = Field(min_length=1, max_length=2000)
    size: float = Field(default=0.03, ge=0.001, le=0.5, allow_inf_nan=False)

    @model_validator(mode='after')
    def polygon(self):
        if self.tool == 'lasso' and len(self.points) < 3:
            raise ValueError('Circle an area with at least three points.')
        return self


class MarkedArea(BaseModel):
    marks: list[Mark] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def limit_points(self):
        if sum(len(mark.points) for mark in self.marks) > 10000:
            raise ValueError('The selection is too complex. Clear it and draw fewer strokes.')
        return self


def mask_for(area, width, height):
    area = MarkedArea.model_validate(area)
    mask = Image.new('L', (width, height))
    draw = ImageDraw.Draw(mask)
    for mark in area.marks:
        points = [(round(x * (width - 1)), round(y * (height - 1))) for x, y in mark.points]
        if mark.tool == 'lasso':
            draw.polygon(points, fill=255)
        else:
            diameter = max(1, round(mark.size * width))
            radius = diameter / 2
            fill = 0 if mark.tool == 'erase' else 255
            draw.line(points, fill=fill, width=diameter)
            for x, y in points:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    if not mask.getbbox():
        raise ValueError('The marked area is empty. Paint or circle an area before planning.')
    return mask


def select_marked(engine, folder, params, context):
    import cv2
    import numpy as np

    state = engine.call('doc.inspect')
    mask = mask_for(params['area'], state['width'], state['height'])
    # PhotoCraft and OpenCV round polygon edges differently. Stay one pixel inside the
    # painted boundary (also around eraser holes), never grow an edit outside it.
    inside = cv2.erode(np.asarray(mask), np.ones((3, 3), dtype=np.uint8), borderValue=255)
    contours, hierarchy = cv2.findContours(inside, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    levels = []
    for index in range(len(contours)):
        level, parent = 0, hierarchy[0][index][3]
        while parent >= 0:
            level, parent = level + 1, hierarchy[0][parent][3]
        levels.append(level)
    count = 0
    for index in sorted(range(len(contours)), key=lambda i: levels[i]):
        points = contours[index].reshape(-1, 2).tolist()
        if len(points) < 3:
            continue
        engine.call('engine.execute', {'command': 'select.lasso', 'params': {
            'points': points, 'antiAlias': False,
            'mode': 'subtract' if levels[index] % 2 else 'replace' if count == 0 else 'add',
        }})
        count += 1
    if not count or not engine.call('doc.inspect').get('hasSelection'):
        raise ValueError('The marked area is too small. Enlarge it and try again.')
    # Fade inward, not across the user boundary. Contracting before feathering puts
    # almost all of the transition inside the marks; intersecting protects the rest.
    distance = cv2.distanceTransform(inside, cv2.DIST_L2, 5)
    _, components = cv2.connectedComponents(inside)
    depths = [float(distance[components == label].max()) for label in range(1, int(components.max()) + 1)]
    radius = min(max(1, min(state['width'], state['height']) * .012), min(depths) / 3)
    if radius >= 1:
        channel = f'Marked boundary {uuid4().hex}'
        def execute(command, values):
            return engine.call('engine.execute', {'command': command, 'params': values})
        execute('select.saveSelection', {'name': channel})
        try:
            execute('select.modify.contract', {'radius': max(1, round(radius))})
            execute('select.modify.feather', {'radius': max(.5, radius / 2)})
            execute('select.loadSelection', {'channel': channel, 'operation': 'intersect'})
        finally:
            execute('channel.delete', {'channel': channel})
    return {'coverage': float((np.asarray(mask) > 0).mean())}


def check_boundary(engine, folder, area, before_path, width, height):
    """Reject a leaking edit before committing history, even if an engine tool ignored its mask."""
    after_path = folder / '_area-after.png'
    try:
        engine.call('doc.render', {'path': str(after_path), 'maxSide': max(width, height)})
        with Image.open(before_path) as before, Image.open(after_path) as after:
            if before.size != after.size or after.size != (width, height):
                raise ValueError('The edit changed the canvas size. The previous revision is unchanged.')
            difference = ImageChops.difference(before.convert('RGBA'), after.convert('RGBA'))
            difference.paste((0, 0, 0, 0), mask=mask_for(area, width, height))
            if any(channel.getbbox() for channel in difference.split()):
                raise ValueError('That tool changed pixels outside your marked area, so the edit was not saved. '
                                 'The previous revision is unchanged. Try a different edit.')
    finally:
        after_path.unlink(missing_ok=True)
        before_path.unlink(missing_ok=True)


class AreaCompiler(intents.Compiler):
    def __init__(self, state, area, fonts=(), ai=False):
        super().__init__(state, fonts, ai=ai)
        self.area = MarkedArea.model_validate(area).model_dump()
        mask = mask_for(self.area, state['width'], state['height'])
        x0, y0, x1, y1 = mask.getbbox()
        self.bounds = [x0 / state['width'], y0 / state['height'],
                       (x1 - x0) / state['width'], (y1 - y0) / state['height']]
        self.expert_requests = []

    def add(self, index, command, params=None, label=''):
        for position in intents.POSITIONS:
            label = label.replace(f'{position} area', 'marked area')
        params = dict(params or {})
        for key in ('label', 'name'):
            if isinstance(params.get(key), str):
                for position in intents.POSITIONS:
                    params[key] = params[key].replace(f'{position} area', 'marked area')
        if command == 'studio.local_filter':
            # A previous request can have the same words but a different drawn outline.
            params = {**params, 'region': ''}
        if command == 'studio.ai_layer':
            params['area'] = self.area
        super().add(index, command, params, label)
        tone_only = command == 'studio.local_filter' and params.get('command') == 'filter.cameraRaw' and \
            set(params.get('params', {})) <= {'exposure', 'shadows', 'highlights', 'whites', 'blacks'}
        if tone_only or command == 'layer.newAdjustmentLayer.brightnessContrast':
            super().add(index, 'layer.setProps', {'blend': 'Luminosity'}, 'Preserve the original color')

    def selection(self, index, edit, invert=False):
        self.add(index, 'studio.select_marked', {'area': self.area}, 'Select only your marked area')
        self.regions.append({'requirement': index, 'label': 'Marked area', 'boxes': [self.bounds]})
        return True

    def adjustment(self, index, edit, command, params, name):
        # Some recipes deliberately choose whole-image adjustment layers. The explicit
        # user boundary takes precedence even inside those recipes.
        return super().adjustment(index, {**edit, 'target': 'area'}, command, params, name)

    def do_remove_object(self, index, edit):
        self.selection(index, edit)
        self.add(index, 'studio.retouch_fill', {'label': 'Removed marked area'}, 'Fill only the marked area')
        self.end_selection(index)

    def do_blur_background(self, index, edit):
        self.group_effect(index, {**edit, 'action': 'blur'})


def compile_area(edits, state, area, fonts=(), ai=False):
    compiler = AreaCompiler(state, area, fonts, ai)
    safe = []
    for edit in edits:
        allowed = intents.group(edit) in ('develop', 'adjust', 'effect', 'retouch', 'ai') or \
            edit['action'] in ('blur_background', 'color_overlay')
        if not allowed:
            raise ValueError(f'“{edit["quote"]}” cannot be limited to a marked area. '
                             'Use Whole image for layout, text, layer or crop changes.')
        safe.append({**edit, 'target': 'area'})
    compiler.compile(safe)
    if compiler.expert_requests:
        raise ValueError('That tool cannot be safely limited to your marked area. Try a light, color or blur edit.')
    return (compiler.steps, compiler.notes, compiler.blocking, compiler.regions, [], compiler.canvas)

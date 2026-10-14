"""The pipeline engine's plans, run in Krita.

Pipelines build PhotoCraft commands (pipelines/, photocraft_intents.Compiler). This module turns a
built plan into the steps the Krita plugin runs (integrations/krita-plugin/ai_prompt: ops.py for
Krita's own tools, runner.py for the steps that need Image Studio), command by command. The Krita
assistant therefore plans with the same planner, finds things with the same grounder, measures with
the same analyses and builds with the same pipelines as PhotoCraft; only this last translation
differs.

How each kind of command is carried over:

- Selections, canvas changes, layers, fills, text, blurs, posterize, threshold, invert and
  black-and-white map to the Krita tool of the same kind, with the pipeline's own settings
  (pixel sizes converted to the plugin's 1500-pixel reference, see ops.scale_px).
- Hue/saturation, colour balance and colorize become Krita filter layers with the same values.
- Camera Raw settings, curves, levels, vibrance and exposure layers become a *grade*: Krita 6's
  Python API cannot set curves or per-channel levels (they are stored, never applied), so the
  grading engine (services/grading.py) renders the same settings and Krita adds the result as a
  layer group, limited to the selection when the pipeline made one.
- A command with no faithful Krita equivalent (adaptive wide angle, lens correction, tilt-shift,
  gradient maps, canvas extension, CMYK…) is not approximated. Every edit that needs one is
  reported back as PhotoCraft-only, and its steps are left out as a whole.
"""

# Steps that make a layer, so a following rename becomes that layer's name.
MAKES_LAYER = {'brightness', 'contrast', 'black_and_white', 'invert_colors', 'posterize', 'threshold', 'blur',
               'motion_blur', 'lens_blur', 'sharpen', 'denoise', 'oil_paint', 'fill', 'add_text', 'grade',
               'filter_layer', 'new_layer', 'ai_edit', 'sepia', 'paint_fill'}
# Commands that only change the selection: a new layer the plan asked for can wait past them for
# the fill that paints it.
SELECTING = ('select.', 'studio.select_outline', 'studio.require_selection')
NO_OP = {
    'studio.select_insert',  # Krita adds a new layer above the active one by itself
    'studio.select_photo',  # Krita's filters are filter layers over the picture, not edits of one layer
    'studio.select_top',
}
LEAVES_OWN_LAYER = NO_OP
# Camera Raw settings the grading engine has under the same name and scale (-100..100, EV).
GRADE_KNOBS = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks', 'temperature', 'tint',
               'vibrance', 'saturation', 'clarity', 'texture', 'dehaze')
BANDS = {'reds': 'red', 'yellows': 'yellow', 'greens': 'green', 'cyans': 'aqua', 'blues': 'blue',
         'magentas': 'magenta'}
# Photoshop's default black-and-white mix; a pipeline's mix is read as offsets from it.
GREY_MIX = {'reds': 40, 'yellows': 60, 'greens': 40, 'cyans': 60, 'blues': 20, 'magentas': 80}
BLENDS = {'normal': 'normal', 'multiply': 'multiply', 'screen': 'screen', 'overlay': 'overlay',
          'softlight': 'soft light', 'hardlight': 'hard light', 'color': 'color', 'hue': 'hue',
          'saturation': 'saturation', 'luminosity': 'luminosity', 'darken': 'darken', 'lighten': 'lighten',
          'colordodge': 'color dodge', 'colorburn': 'color burn', 'difference': 'difference',
          'exclusion': 'exclusion', 'lineardodge': 'add', 'add': 'add', 'subtract': 'subtract', 'divide': 'divide'}


class Unsupported(Exception):
    """A command Krita has no faithful equivalent for."""


class Translation:
    """Tracks what Krita's document looks like while the steps are translated: its size after
    each crop, resize or rotation, the layer names, and whether a selection is active."""

    def __init__(self, state):
        self.width, self.height = state['width'], state['height']
        self.layers = {layer['id']: layer['name'] for layer in state.get('layers', []) if 'id' in layer}
        self.selection = False
        self.pending_layer = None  # a new empty layer waiting to see whether a fill paints it
        # Whether the active layer is one this plan painted (a shadow, a frame): PhotoCraft's
        # filters then change that layer's pixels, where Krita's filter layers would change all below.
        self.own_layer = False

    def ref(self, pixels):
        """A size in document pixels as the plugin's sizes, given for a picture 1500 pixels across."""
        return max(1, round(pixels * 1500 / max(self.width, self.height)))

    def percent_box(self, box):
        x, y, w, h = box
        return [round(100 * x / self.width, 3), round(100 * y / self.height, 3),
                round(100 * w / self.width, 3), round(100 * h / self.height, 3)]


def _grade(recipe, label, selection):
    step = dict(op='grade', layers=[dict(name=label or 'Adjustments', **recipe)], label=label or 'Adjustments')
    if selection:
        step['within_selection'] = True
    return step


def develop_steps(settings, label, selection):
    """Camera Raw settings as a grade, then Krita's own sharpening and noise reduction."""
    recipe = {key: float(settings[key]) for key in GRADE_KNOBS if settings.get(key)}
    if settings.get('vignetteAmount'):
        recipe['vignette'] = -float(settings['vignetteAmount'])  # Camera Raw darkens with negative values
    if settings.get('grainAmount'):
        recipe['grain'] = float(settings['grainAmount'])
    known = set(GRADE_KNOBS) | {'vignetteAmount', 'grainAmount', 'grainSize', 'sharpenAmount', 'noiseLuminance',
                                'noiseColor'}
    unknown = sorted(key for key, value in settings.items() if value and key not in known)
    if unknown:
        raise Unsupported('Camera Raw ' + ', '.join(unknown))
    steps = [_grade(recipe, label, selection)] if recipe else []
    if settings.get('sharpenAmount'):
        steps.append(dict(op='sharpen', amount=max(1, min(100, round(float(settings['sharpenAmount'])))),
                          label=(label + ' · sharpen') if label else 'Sharpen'))
    if settings.get('noiseLuminance') or settings.get('noiseColor'):
        strength = max(float(settings.get('noiseLuminance') or 0), float(settings.get('noiseColor') or 0))
        steps.append(dict(op='denoise', strength=max(1, min(100, round(strength))),
                          label=(label + ' · noise') if label else 'Noise reduction'))
    return steps


def levels_curve(channel):
    """A levels setting ({inBlack, inWhite, gamma}, 0..255) as curve points."""
    black, white = float(channel.get('inBlack', 0)), float(channel.get('inWhite', 255))
    gamma = float(channel.get('gamma', 1.0) or 1.0)
    white = max(black + 1, white)
    points = [[0, 0], [black, 0]]
    for share in (0.25, 0.5, 0.75):
        points.append([round(black + (white - black) * share, 2), round(255 * share ** (1 / gamma), 2)])
    return points + [[white, 255], [255, 255]]


def hue_saturation(params, label, selection):
    steps = []
    bands = {BANDS[key]: value for key, value in params.items() if key in BANDS and isinstance(value, dict)}
    if params.get('colorize'):
        return [dict(op='filter_layer', filter='hsvadjustment',
                     props=dict(type=1, colorize=True, h=max(0, round(float(params.get('hue', 0)))) % 360,
                                s=round(float(params.get('saturation', 25))), v=round(float(params.get('lightness', 0)))),
                     label=label or 'Colorize')]
    if bands:
        # One colour band at a time: Krita's filter has no bands, the grading engine's HSL mixer does.
        # Its band hue is a share of ±30°, Photoshop's is in degrees.
        hsl = {name: {key: float(band[out]) * (100 / 30 if out == 'hue' else 1)
                      for key, out in (('hue', 'hue'), ('saturation', 'saturation'), ('luminance', 'lightness'))
                      if band.get(out)} for name, band in bands.items()}
        steps.append(_grade({'hsl': hsl}, label, selection))
    master = {key: round(float(params.get(key, 0) or 0)) for key in ('hue', 'saturation', 'lightness')}
    if any(master.values()):
        steps.append(dict(op='filter_layer', filter='hsvadjustment',
                          props=dict(type=1, colorize=False, h=master['hue'], s=master['saturation'],
                                     v=master['lightness']), label=label or 'Hue/Saturation'))
    return steps


def black_white(params, label, selection):
    mix = {key: float(params[key]) - GREY_MIX[key] for key in GREY_MIX if key in params}
    if any(mix.values()):
        # A channel mix: each colour's lightness moved before the colour is taken out.
        steps = [_grade({'hsl': {BANDS[key]: {'luminance': value * 0.5} for key, value in mix.items() if value},
                         'saturation': -100}, label or 'Black and white', selection)]
    else:
        steps = [dict(op='black_and_white', label=label or 'Black and white')]
    if params.get('tint'):
        steps.append(dict(op='filter_layer', filter='hsvadjustment',
                          props=dict(type=1, colorize=True, h=hue_of(params.get('tintColor', '#a3845c')), s=28, v=0),
                          label=(label or 'Black and white') + ' · tint'))
    return steps


def hue_of(color):
    import colorsys

    value = str(color).lstrip('#')
    red, green, blue = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return round(colorsys.rgb_to_hls(red, green, blue)[0] * 360)


def color_balance(params, label):
    props = {}
    for tone in ('shadows', 'midtones', 'highlights'):
        values = params.get(tone) or [0, 0, 0]
        for name, value in zip(('cyan_red', 'magenta_green', 'yellow_blue'), values):
            if value:
                props[f'{name}_{tone}'] = round(float(value))
    props['preserve_luminosity'] = bool(params.get('preserveLuminosity', True))
    return [dict(op='filter_layer', filter='colorbalance', props=props, label=label or 'Color balance')]


def text_step(params, t):
    if params.get('effects') and set(params['effects']) - {'outline'}:
        raise Unsupported('text effects ' + ', '.join(params['effects']))
    size = max(1, min(50, round(100 * float(params.get('size', 24)) / t.height)))
    color = params.get('color') or 'white'
    position = str(params.get('position') or 'center').replace('-', ' ')
    return [dict(op='add_text', text=str(params['text']), position=position, size=size,
                 color='white' if color == 'auto' else color, font=params.get('font') or 'Arial',
                 label=params.get('name') or str(params['text'])[:40])]


def translate_step(step, t):
    """The Krita steps for one PhotoCraft command; raises Unsupported."""
    command, params, label = step['command'], step.get('params') or {}, step.get('label') or ''
    if command in NO_OP:
        t.own_layer = False
        return []
    if command == 'studio.require_selection':
        return [dict(op='require_selection', what=params.get('what') or 'what this edit changes')]
    if command == 'select.deselect':
        t.selection = False
        return [dict(op='deselect')]
    if command == 'studio.select_outline':
        t.selection = True
        return [dict(op='select', target=params.get('what') or 'the subject',
                     boxes=[t.percent_box(box) for box in params.get('boxes') or []])]
    if command == 'select.rect':
        t.selection = True
        x, y, w, h = t.percent_box([params['x'], params['y'], params['width'], params['height']])
        return [dict(op='select_box', x=x, y=y, w=w, h=h, ellipse=bool(params.get('ellipse')),
                     mode=params.get('mode', 'replace'), feather=t.ref(float(params.get('feather') or 0))
                     if params.get('feather') else 0)]
    if command == 'select.colorRange':
        t.selection = True
        spec = {key: params[key] for key in ('select', 'colors', 'fuzziness') if key in params}
        return [dict(op='select_color', spec=spec, mode=params.get('mode', 'replace'),
                     label=f'Select {params.get("select") or "colours"}')]
    if command == 'select.inverse':
        return [dict(op='invert_selection')]
    if command == 'select.modify.feather':
        return [dict(op='feather_selection', pixels=t.ref(float(params.get('radius', 1))))]
    if command == 'layer.renameLayer':
        return [dict(op='rename_layer', name=params['name'])]
    if command == 'studio.develop':
        return develop_steps(params.get('params') or {}, label, False)
    if command == 'studio.local_filter':
        inner = params.get('params') or {}
        kind = params.get('command')
        if kind == 'filter.cameraRaw':
            return develop_steps(inner, params.get('label') or label, t.selection)
        if kind == 'filter.blur.lensBlur':
            return [dict(op='lens_blur', radius=min(100, t.ref(float(inner.get('radius', 12)))),
                         label=params.get('label') or 'Lens blur')]
        if kind == 'filter.blur.gaussianBlur':
            return [dict(op='blur', radius=min(200, t.ref(float(inner.get('radius', 10)))),
                         label=params.get('label') or 'Blur')]
        raise Unsupported(kind or command)
    if command == 'layer.newAdjustmentLayer.brightnessContrast':
        steps = []
        if params.get('brightness'):
            steps.append(dict(op='brightness', amount=max(-100, min(100, round(float(params['brightness']))))))
        if params.get('contrast'):
            steps.append(dict(op='contrast', amount=max(-100, min(100, round(float(params['contrast']))))))
        return steps
    if command == 'layer.newAdjustmentLayer.hueSaturation':
        return hue_saturation(params, label, t.selection)
    if command == 'layer.newAdjustmentLayer.blackWhite':
        return black_white(params, label, t.selection)
    if command == 'layer.newAdjustmentLayer.colorBalance':
        return color_balance(params, label)
    if command == 'layer.newAdjustmentLayer.curves':
        return [_grade({'curve': params['points']}, label or 'Curves', t.selection)]
    if command == 'layer.newAdjustmentLayer.levels':
        curves = {f'curve_{name}': levels_curve(params[name]) for name in ('red', 'green', 'blue')
                  if isinstance(params.get(name), dict)}
        if 'inBlack' in params or 'inWhite' in params:
            curves['curve'] = levels_curve(params)
        return [_grade(curves, label or 'Levels', t.selection)]
    if command == 'layer.newAdjustmentLayer.vibrance':
        recipe = {key: float(params[key]) for key in ('vibrance', 'saturation') if params.get(key)}
        return [_grade(recipe, label or 'Vibrance', t.selection)] if recipe else []
    if command == 'layer.newAdjustmentLayer.exposure':
        recipe = {'exposure': float(params.get('exposure', 0))}
        gamma = float(params.get('gamma', 1.0) or 1.0)
        if abs(gamma - 1) > 1e-3:
            recipe['curve'] = [[round(255 * x, 2), round(255 * x ** (1 / gamma), 2)] for x in (0, .25, .5, .75, 1)]
        return [_grade(recipe, label or 'Exposure', t.selection)]
    if command == 'layer.newAdjustmentLayer.invert':
        return [dict(op='invert_colors')]
    if command == 'layer.newAdjustmentLayer.posterize':
        return [dict(op='posterize', levels=max(2, min(64, int(params.get('levels', 6)))))]
    if command == 'layer.newAdjustmentLayer.threshold':
        return [dict(op='threshold', level=max(1, min(254, int(params.get('level', 128)))))]
    if command == 'filter.blur.gaussianBlur':
        if t.own_layer:
            radius = max(1, round(float(params.get('radius', 10))))
            return [dict(op='apply_filter', filter='gaussian blur', label=label or 'Blur',
                         props=dict(horizRadius=radius, vertRadius=radius, lockAspect=True))]
        return [dict(op='blur', radius=min(200, t.ref(float(params.get('radius', 10)))))]
    if command == 'filter.blur.motionBlur':
        if t.own_layer:
            return [dict(op='apply_filter', filter='motion blur', label=label or 'Motion blur',
                         props=dict(blurAngle=round(float(params.get('angle', 0))),
                                    blurLength=max(1, round(float(params.get('distance', 30))))))]
        return [dict(op='motion_blur', angle=round(float(params.get('angle', 0))),
                     length=min(400, t.ref(float(params.get('distance', 30)))))]
    if command == 'filter.stylize.oilPaint':
        return [dict(op='oil_paint', size=max(1, min(10, round(float(params.get('scale', params.get('size', 3)))))))]
    if command == 'image.crop':
        t.width, t.height = int(params['width']), int(params['height'])
        t.selection = False
        return [dict(op='crop_rect', x=int(params['x']), y=int(params['y']), w=t.width, h=t.height)]
    if command == 'image.imageSize':
        t.width, t.height = int(params['width']), int(params['height'])
        return [dict(op='resize', width=t.width, height=t.height)]
    if command == 'image.canvasSize':
        width = int(params['width']) + (t.width if params.get('relative') else 0)
        height = int(params['height']) + (t.height if params.get('relative') else 0)
        anchor = str(params.get('anchor') or 'center')
        share_x = 0 if 'left' in anchor else 1 if 'right' in anchor else 0.5
        share_y = 0 if 'top' in anchor else 1 if 'bottom' in anchor else 0.5
        # The new margins are transparent in Krita; the pipelines that extend the canvas put a
        # fill layer behind the photo for their colour.
        x, y = -round((width - t.width) * share_x), -round((height - t.height) * share_y)
        t.width, t.height = width, height
        return [dict(op='canvas_size', x=x, y=y, w=width, h=height)]
    if command == 'layer.arrange.sendToBack':
        return [dict(op='send_to_back')]
    if command == 'image.imageRotation.90cw':
        t.width, t.height = t.height, t.width
        return [dict(op='rotate', degrees=90)]
    if command == 'image.imageRotation.90ccw':
        t.width, t.height = t.height, t.width
        return [dict(op='rotate', degrees=-90)]
    if command == 'image.imageRotation.180':
        return [dict(op='rotate', degrees=180)]
    if command == 'image.imageRotation.flipCanvasHorizontal':
        return [dict(op='flip', direction='horizontal')]
    if command == 'image.imageRotation.flipCanvasVertical':
        return [dict(op='flip', direction='vertical')]
    if command == 'layer.newFillLayer.solidColor':
        return [dict(op='fill', color=params.get('color', '#ffffff'), opacity=100, label=label or 'Color fill')]
    if command == 'layer.new.layer':
        t.pending_layer = params.get('name') or 'Layer'
        return []
    if command == 'edit.fill':
        if params.get('contents', 'color') != 'color':
            raise Unsupported(f'fill with {params.get("contents")}')
        name, t.pending_layer = t.pending_layer, None
        t.own_layer = True
        return [dict(op='paint_fill', color=params.get('color', '#000000'), label=name or label or 'Fill')]
    if command == 'layer.setProps':
        steps = []
        if 'layer' in params:
            if params['layer'] not in t.layers:
                raise Unsupported('a layer Krita does not have')
            steps.append(dict(op='select_layer', layer=t.layers[params['layer']]))
        if 'opacity' in params:
            steps.append(dict(op='layer_opacity', opacity=round(100 * float(params['opacity']))))
        if 'blend' in params:
            mode = BLENDS.get(str(params['blend']).lower().replace(' ', '').replace('_', ''))
            if mode is None:
                raise Unsupported(f'blend mode {params["blend"]}')
            steps.append(dict(op='blend_mode', mode=mode))
        if params.get('visible') is False:
            steps.append(dict(op='hide_layer', layer='active'))
        elif params.get('visible') is True:
            steps.append(dict(op='show_layer', layer='active'))
        if params.get('name'):
            steps.append(dict(op='rename_layer', name=params['name']))
        return steps
    if command == 'layer.delete':
        if params.get('layer') not in t.layers:
            raise Unsupported('a layer Krita does not have')
        return [dict(op='delete_layer', layer=t.layers[params['layer']])]
    if command == 'layer.layerMask.revealSelection':
        return [dict(op='mask_from_selection', invert=False, label=label or 'Cut out')]
    if command == 'layer.layerMask.hideSelection':
        return [dict(op='mask_from_selection', invert=True, label=label or 'Mask')]
    if command == 'studio.text':
        return text_step(params, t)
    if command == 'studio.ai_layer':
        steps = []
        if params.get('boxes'):
            steps += [dict(op='select', target=params.get('label') or 'the area',
                           boxes=[t.percent_box(box) for box in params['boxes']]),
                      dict(op='grow_selection', pixels=t.ref(12))]
        steps.append(dict(op='ai_edit', instruction=params['instruction'], label=params.get('label') or 'AI edit'))
        if params.get('boxes'):
            steps.append(dict(op='deselect'))
        return steps
    raise Unsupported(command)


def translate(steps, state):
    """(Krita steps, {edit index: [what Krita cannot do]}) for a compiled PhotoCraft plan.
    `state` is the PhotoCraft-shaped document state the plan was compiled against. The steps of
    an edit that needs anything Krita cannot do are all left out, so no edit runs half-built."""
    t = Translation(state)
    out, missing = [], {}
    for step in steps:
        try:
            translated = translate_step(step, t)
        except Unsupported as exc:
            t.pending_layer = None
            for index in step.get('requirements') or [None]:
                missing.setdefault(index, []).append(str(exc))
            continue
        except (KeyError, TypeError, ValueError) as exc:
            for index in step.get('requirements') or [None]:
                missing.setdefault(index, []).append(f'{step["command"]} ({exc})')
            continue
        if t.pending_layer and step['command'] != 'layer.new.layer' and not step['command'].startswith(SELECTING):
            out.insert(len(out) - 0, dict(op='new_layer', name=t.pending_layer,
                                          requirements=step.get('requirements', [])))
            t.pending_layer = None
            t.own_layer = True
        for item in translated:
            if item['op'] in MAKES_LAYER and item['op'] not in ('paint_fill', 'new_layer'):
                t.own_layer = False
            item['requirements'] = list(step.get('requirements') or [])
            if item['op'] == 'rename_layer' and out and out[-1]['op'] in MAKES_LAYER \
                    and out[-1]['requirements'] == item['requirements']:
                out[-1]['label'] = item['name']  # the layer is made with its name
                continue
            out.append(item)
    if t.pending_layer:
        out.append(dict(op='new_layer', name=t.pending_layer, requirements=[]))
    kept = [step for step in out if not step['requirements']
            or any(index not in missing for index in step['requirements'])]
    return kept, missing


def plan(prompt, preview, state, status=print):
    """The pipeline engine's plan for a request typed in Krita: (Krita steps, notes, the request's
    words no pipeline could run in Krita, questions). Planned, found, measured and built exactly
    as for PhotoCraft (photocraft_workspace.compile_plan), then translated."""
    from image_studio.pipelines import models
    from image_studio.pipelines.measure import analyse

    from . import photocraft_intents as intents, photocraft_macros, photocraft_planner as planner

    document = krita_state(state)
    status('Choosing pipelines for your request...')
    edits, preserve, questions, notes = planner.understand(prompt, preview, document)
    edits = intents.expand(edits, preserve, prompt)
    boxes = {}
    wanted = sorted({query for edit in edits for query in planner.queries_for(edit)})
    if wanted:
        if not models.available('grounder'):
            raise ValueError('Finding things in the photo needs a model that can see it. Connect one in Settings.')
        status('Finding ' + ', '.join(wanted[:3]) + '...')
        hints = {query: edit['quote'] for edit in edits for query in planner.queries_for(edit)}
        boxes = planner.locate(preview, wanted, document, hints)
    steps, compile_notes, blocking, _, expert, _ = intents.compile_edits(
        edits, document, (), boxes, photocraft_macros.ai_available(), analyse(edits, preview, document, boxes))
    krita, missing = translate(steps, document)
    # Edits Krita cannot run as pipelines, and the last-resort “other”, go to the Krita assistant.
    left = sorted({index for index in missing if index is not None} | set(expert))
    leftover = [edits[index]['quote'] for index in left if index < len(edits)]
    leftover += intents.uncovered_clauses(prompt, edits, preserve)
    for step in krita:
        step.pop('requirements', None)
    return krita, notes + compile_notes + blocking + summary(missing, edits), leftover, questions


def krita_state(state):
    """The Krita plugin's document state (ops.state) in the shape the pipelines compile against."""
    kinds = {'paintlayer': 'Pixel', 'vectorlayer': 'Shape', 'grouplayer': 'Group', 'filterlayer': 'Adjustment',
             'filllayer': 'Fill', 'clonelayer': 'Pixel', 'filelayer': 'Smart Object'}
    layers = []
    for number, layer in enumerate(state.get('layers') or [], 1):
        if layer.get('type') in ('transparencymask', 'filtermask', 'transformmask', 'colorizemask'):
            continue
        layers.append({'id': number, 'name': layer.get('name', ''), 'kind': kinds.get(layer.get('type'), 'Pixel'),
                       'visible': layer.get('visible', True), 'opacity': (layer.get('opacity', 100) or 0) / 100})
    return {'width': int(state['width']), 'height': int(state['height']), 'resolution': 72.0, 'layers': layers}


def color_range_mask(image, spec):
    """A selection mask (L) like PhotoCraft's Color Range: a named range (reds … magentas,
    highlights, midtones, shadows, skin tones) or sampled colours within a fuzziness."""
    import numpy as np
    from PIL import Image

    from image_studio.services import grading

    rgb = grading.to_array(image)
    if spec.get('colors'):
        fuzziness = float(spec.get('fuzziness', 40))
        samples = np.array([[int(str(c).lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)] for c in spec['colors']],
                           np.float32)
        pixels = rgb.reshape(-1, 1, 3) * 255
        distance = np.sqrt(((pixels - samples[None]) ** 2).sum(-1)).min(-1).reshape(rgb.shape[:2])
        # Fuzziness is how far from a sampled colour still counts, fading out beyond it.
        mask = 1 - grading.smoothstep(fuzziness * 0.6, fuzziness * 1.4, distance)
    else:
        name = str(spec.get('select') or '').lower()
        lum = np.clip(grading.luma(rgb), 0, 1)
        hue, sat, _ = grading.rgb_to_hsl(np.clip(rgb, 0, 1))
        centers = {'reds': 0, 'yellows': 60, 'greens': 120, 'cyans': 180, 'blues': 240, 'magentas': 300,
                   'skintones': 25}
        if name == 'highlights':
            mask = grading.smoothstep(0.55, 0.8, lum)
        elif name == 'shadows':
            mask = 1 - grading.smoothstep(0.2, 0.45, lum)
        elif name == 'midtones':
            mask = grading.smoothstep(0.15, 0.35, lum) * (1 - grading.smoothstep(0.65, 0.85, lum))
        elif name.replace(' ', '') in centers:
            center = centers[name.replace(' ', '')]
            span = 22 if name.startswith('skin') else 30
            distance = np.abs((hue - center + 180) % 360 - 180)
            mask = (1 - grading.smoothstep(span * 0.6, span, distance)) * grading.smoothstep(0.08, 0.25, sat)
        else:
            raise ValueError(f'Unknown colour range “{name}”.')
    return Image.fromarray((np.clip(mask, 0, 1) * 255 + 0.5).astype(np.uint8))


def coverage(built):
    """{pipeline id: [what Krita cannot do]} for a dry build of every procedure; `built(pipeline
    id)` returns its compiled steps and state. Empty lists are pipelines Krita runs in full."""
    from image_studio import pipelines

    result = {}
    for pipeline in pipelines.REGISTRY.values():
        if pipeline.id == 'other':
            continue
        steps, state = built(pipeline.id)
        _, missing = translate(steps, state)
        result[pipeline.id] = sorted({item for items in missing.values() for item in items})
    return result


def summary(missing, edits):
    """Plain notes about the edits Krita cannot run as pipelines."""
    notes = []
    for index, items in sorted(missing.items(), key=lambda item: (item[0] is None, item[0] or 0)):
        quote = edits[index]['quote'] if index is not None and index < len(edits) else 'part of the plan'
        notes.append(f'“{quote}” needs {", ".join(dict.fromkeys(items))}, which Krita does not have.')
    return notes

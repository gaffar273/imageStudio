"""The pipeline engine: registry integrity, every pipeline building, workflows, the model contract.

These run without PhotoCraft and without any model.
"""

import io
import json
import unittest
from unittest.mock import patch

from image_studio import pipelines
from image_studio.integrations import photocraft_intents as lang
from image_studio.pipelines import measure, models
from image_studio.pipelines.models import adapters, contract
from PIL import Image, ImageDraw

STATE = {'width': 1200, 'height': 900, 'resolution': 72.0, 'layers': [
    {'id': 2, 'name': 'Background', 'kind': 'Pixel', 'visible': True, 'opacity': 1.0},
    {'id': 5, 'name': 'Title', 'kind': 'Type', 'visible': True, 'opacity': 1.0, 'text': {'text': 'Title'}}]}
SUBJECT = [420, 200, 360, 600]
BOXES = {
    'the main subject': [SUBJECT], 'the product': [SUBJECT], 'the dog': [SUBJECT], lang.PASSPORT_HEAD: [[520, 180, 160, 210]],
    lang.FACES: [[530, 220, 140, 170]], lang.EYES: [[555, 270, 40, 20], [615, 270, 40, 20]],
    lang.TEETH: [[575, 345, 50, 15]], lang.FOREGROUND: [SUBJECT, [100, 500, 150, 300]],
}
ANALYSIS = {
    'levels': {'all': (10, 240), 'red': (12, 238), 'green': (9, 241), 'blue': (15, 230),
               'gamma': {'red': 1.0, 'green': 1.0, 'blue': 1.05}},
    'exposure': {'median': 0.2, 'p02': 0.01, 'p98': 0.7, 'clipped_high': 0.0, 'clipped_low': 0.05},
    'noise': 3.0, 'tilt': 2.5,
    'verticals': [[[100, 100], [110, 800]], [[1100, 100], [1092, 800]]],
    'skin_colors': ['#c08a70', '#d8a088'], 'teeth': True, 'teeth_colors': ['#e8e0d0'],
}
# What a planner would fill in for each pipeline, so every one is built with sensible slots.
SLOTS = {
    'layer_opacity': dict(object='Title', value=50), 'layer_visibility': dict(object='Title'),
    'layer_delete': dict(object='Title'), 'layer_rename': dict(object='Title', text='Heading'),
    'layer_blend': dict(object='Title', choice='multiply'), 'edit_text': dict(object='Title', text='New'),
    'crop_aspect': dict(aspect='4:5'), 'resize': dict(quote='make it an instagram post'),
    'rotate': dict(value=90), 'remove_object': dict(object='the dog'),
    'transform_object': dict(object='the dog', choice='bigger', quote='make the dog bigger'),
    'recolor': dict(target='object', object='the dog', color='red'), 'add_text': dict(text='SUMMER', position='top'),
    'color_overlay': dict(color='blue'), 'keep_one_color': dict(color='red'), 'season': dict(choice='autumn'),
    'retouch_portrait': dict(choice='smooth skin, teeth, eyes', target='main subject'),
    'convert_mode': dict(choice='cmyk'), 'youtube_thumbnail': dict(text='I QUIT'),
    'print_prep': dict(quote='prepare it for printing as an 8x10'), 'artistic': dict(choice='oil paint'), 'split_tone': dict(color='teal and orange'),
}


def built(pipeline_id, ai=True, analysis=ANALYSIS, **extra):
    fields = {**SLOTS.get(pipeline_id, {}), **extra}
    edits = lang.expand([lang.blank(pipeline_id, **fields)], prompt=fields.get('quote', ''))
    return lang.compile_edits(edits, STATE, fonts=('Inter', 'Georgia'), boxes=BOXES, ai=ai, analysis=analysis), edits


class RegistryTests(unittest.TestCase):
    def test_every_pipeline_is_described_for_the_planner(self):
        self.assertGreaterEqual(len(pipelines.REGISTRY), 100)
        for pipeline in pipelines.REGISTRY.values():
            self.assertTrue(pipeline.summary and pipeline.title, pipeline.id)
            for name in pipeline.measures:
                self.assertIn(name, measure.ANALYSES, pipeline.id)

    def test_the_planner_menu_lists_every_offered_pipeline_once(self):
        listed = [p.id for _, _, group in pipelines.menu() for p in group]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), {p.id for p in pipelines.REGISTRY.values() if p.menu})
        self.assertEqual(set(lang.ACTIONS), set(pipelines.REGISTRY))

    def test_every_procedure_builds_engine_steps(self):
        for pipeline in pipelines.REGISTRY.values():
            if pipeline.workflow or pipeline.id == 'other':
                continue
            with self.subTest(pipeline=pipeline.id):
                (steps, notes, blocking, *_), _ = built(pipeline.id)
                self.assertEqual(blocking, [], pipeline.id)
                self.assertTrue(steps or any('already' in note for note in notes), pipeline.id)
                for step in steps:
                    self.assertIn('command', step)
                    json.dumps(step['params'])  # every setting can be sent to the engine

    def test_every_workflow_expands_into_registered_procedures(self):
        for pipeline in pipelines.REGISTRY.values():
            if not pipeline.workflow:
                continue
            with self.subTest(workflow=pipeline.id):
                (steps, notes, blocking, *_), edits = built(pipeline.id)
                parts = [edit for edit in edits if edit.get('workflow') == pipeline.id]
                self.assertTrue(parts)
                for edit in edits:  # its parts, and what a part implies (a headshot's polish)
                    self.assertFalse(pipelines.get(edit['action']).workflow)
                self.assertLessEqual({edit['action'] for edit in parts}, set(pipeline.steps))
                self.assertEqual(blocking, [], pipeline.id)
                self.assertTrue(steps, pipeline.id)

    def test_pipelines_that_frame_or_cut_around_the_subject_ask_for_it_to_be_found(self):
        # compose once found nothing to compose around in a real run: it never asked for the subject.
        from image_studio.integrations import photocraft_planner as planner

        for pipeline in pipelines.REGISTRY.values():
            if pipeline.whole_picture and pipeline.id != 'crop_aspect':  # a plain crop keeps a position
                with self.subTest(pipeline=pipeline.id):
                    self.assertTrue(planner.queries_for(lang.blank(pipeline.id, **SLOTS.get(pipeline.id, {}))))

    def test_steps_name_the_pipeline_that_made_them(self):
        (steps, *_), _ = built('graduated_filter')
        self.assertTrue(all(step['pipeline'] == 'graduated_filter' for step in steps))


class WorkflowTests(unittest.TestCase):
    def test_marketplace_photo_is_cut_out_shadowed_framed_and_exported(self):
        (steps, notes, blocking, regions, _, canvas), edits = built('product_marketplace', object='the product',
                                                                     quote='ready for amazon')
        self.assertEqual([e['action'] for e in edits], ['remove_background', 'drop_shadow', 'product_frame', 'resize'])
        commands = [s['command'] for s in steps]
        # The retoucher's order: cut-out and shadow while the product is whole, then framing, then size.
        self.assertLess(commands.index('layer.layerMask.revealSelection'), commands.index('image.crop'))
        self.assertLess(commands.index('image.crop'), commands.index('image.imageSize'))
        self.assertEqual((canvas.width, canvas.height), (2000, 2000))
        frame = next(s for s in steps if s['command'] == 'image.crop')['params']
        self.assertEqual(frame['width'], frame['height'])
        self.assertAlmostEqual(SUBJECT[3] / frame['height'], 0.85, places=2)

    def test_product_frame_extends_the_canvas_when_the_product_is_near_the_edge(self):
        boxes = {**BOXES, 'the main subject': [[900, 100, 280, 700]]}
        steps, notes, blocking, regions, _, canvas = lang.compile_edits(
            [lang.blank('product_frame', aspect='1:1', value=85, color='white')], STATE, boxes=boxes)
        self.assertEqual(blocking, [])
        self.assertEqual(steps[0]['command'], 'image.canvasSize')
        self.assertEqual(canvas.width, canvas.height)

    def test_optional_parts_that_do_not_apply_become_notes(self):
        analysis = {**ANALYSIS, 'verticals': []}
        (steps, notes, blocking, *_), _ = built('real_estate_interior', analysis=analysis)
        self.assertEqual(blocking, [])
        self.assertTrue(any(note.startswith('Skipped “Real estate interior: vertical walls”') for note in notes))
        self.assertNotIn('filter.adaptiveWideAngle', [s['command'] for s in steps])

    def test_what_the_person_asks_for_outright_replaces_the_workflows_own_part(self):
        explicit = lang.blank('vibrance', direction='increase', strength='strong', quote='much more color')
        edits = lang.expand([lang.blank('real_estate_interior'), explicit])
        vibrance = [e for e in edits if e['action'] == 'vibrance']
        self.assertEqual(vibrance, [explicit])

    def test_a_workflows_parts_account_for_the_words_that_asked_for_it(self):
        prompt = 'edit this room for a real estate listing'
        edits = lang.expand([lang.blank('real_estate_interior', quote=prompt)], prompt=prompt)
        self.assertTrue(all(edit['source'] == prompt for edit in edits))
        self.assertEqual(lang.uncovered_clauses(prompt, edits, []), [])

    def test_well_exposed_photos_are_left_alone(self):
        fine = {**ANALYSIS, 'exposure': {'median': 0.46, 'p02': 0.03, 'p98': 0.95, 'clipped_high': 0.002,
                                         'clipped_low': 0.001}}
        (steps, notes, blocking, *_), _ = built('exposure_fix', analysis=fine)
        self.assertEqual(steps, [])
        self.assertTrue(any('already balanced' in note for note in notes))

    def test_dark_photos_get_a_measured_exposure_lift(self):
        from image_studio.pipelines.library.develop import exposure_correction

        params = exposure_correction(ANALYSIS['exposure'])
        self.assertGreater(params['exposure'], 0.8)
        self.assertGreater(params['shadows'], 0)


class FitTests(unittest.TestCase):
    def test_a_choice_that_does_not_fit_the_words_is_asked_again_without_it(self):
        from image_studio.integrations import photocraft_planner as planner

        first = {'edits': [{'quote': 'make the water more turquoise', 'action': 'color_splash', 'target': 'background',
                            'object': 'the water'}], 'preserve': [], 'questions': []}
        second = {'edit': {'quote': 'make the water more turquoise', 'action': 'hue_shift', 'target': 'color',
                           'color': 'blue', 'direction': 'decrease'}}
        calls = []

        def chat(role, system, content, schema=None, **kwargs):
            calls.append(schema)
            return first if len(calls) == 1 else second

        with patch.object(models, 'chat', side_effect=chat), patch.object(planner.models, 'image_part',
                                                                          return_value={'type': 'text', 'text': ''}):
            edits, *_ = planner.understand('make the water more turquoise', Image.new('RGB', (8, 8)), STATE)
        self.assertEqual([edit['action'] for edit in edits], ['hue_shift'])
        self.assertNotIn('color_splash', calls[1]['properties']['edit']['properties']['action']['enum'])

    def test_fit_rules(self):
        get = pipelines.get
        self.assertFalse(get('color_splash').fits(lang.blank('color_splash', quote='make the water more turquoise')))
        self.assertTrue(get('color_splash').fits(lang.blank('color_splash', quote='keep only her in color')))
        self.assertFalse(get('color_grade').fits(lang.blank('color_grade', quote='make his beard darker')))
        self.assertTrue(get('color_grade').fits(lang.blank('color_grade', quote='blue tint in the shadows')))
        self.assertTrue(get('blur').fits(lang.blank('blur', quote='anything at all')))  # no rule: always fits


class MeasureTests(unittest.TestCase):
    def test_noise_reads_higher_on_a_grainy_picture(self):
        import random

        clean = Image.new('RGB', (400, 300), (120, 120, 120))
        grainy = clean.copy()
        pixels = grainy.load()
        random.seed(1)
        for x in range(400):
            for y in range(300):
                v = max(0, min(255, round(120 + random.gauss(0, 8))))
                pixels[x, y] = (v, v, v)
        self.assertLess(measure.noise(clean, STATE, {}, []), 0.5)
        self.assertGreater(measure.noise(grainy, STATE, {}, []), 4)

    def test_exposure_statistics(self):
        image = Image.new('RGB', (100, 100), (30, 30, 30))
        ImageDraw.Draw(image).rectangle((0, 0, 99, 9), fill=(255, 255, 255))
        stats = measure.exposure(image, STATE, {}, [])
        self.assertLess(stats['median'], 0.15)
        self.assertAlmostEqual(stats['clipped_high'], 0.1, places=2)

    def test_only_the_analyses_the_plan_reads_are_run(self):
        image = Image.new('RGB', (64, 48), (100, 110, 120))
        result = measure.analyse([lang.blank('exposure_fix'), lang.blank('brightness')], image, STATE)
        self.assertEqual(set(result), {'exposure'})


def _photo(size=(160, 120)):
    """A picture with colour, detail and flat areas, the same every run."""
    import numpy as np

    rng = np.random.default_rng(7)
    y, x = np.mgrid[:size[1], :size[0]]
    rgb = np.stack([(x * 255 / size[0]), (y * 255 / size[1]), np.full(x.shape, 140.0)], axis=-1)
    rgb[20:60, 20:70] = (40, 90, 200)  # a blue patch
    rgb[70:110, 90:150] = (200, 60, 40)  # a red patch
    rgb += rng.normal(0, 6, rgb.shape) * ((x // 8 + y // 8) % 2)[..., None]  # textured squares
    return Image.fromarray(np.clip(rgb, 0, 255).astype('uint8'))


class CheckTests(unittest.TestCase):
    """Every effect check passes on a picture that has the effect and fails on the untouched one."""

    def assertCheck(self, action, after, before=None, **fields):
        from image_studio.pipelines import checks

        before = before or _photo()
        edit = lang.blank(action, **fields)
        done = checks.run(0, edit, before, after, [], [], False)
        self.assertTrue(done and all(record['passed'] for record in done), (action, done))
        undone = checks.run(0, edit, before, before.copy(), [], [], False)
        self.assertTrue(undone and not any(record['passed'] for record in undone), (action, undone))

    def test_effect_checks(self):
        import numpy as np
        from PIL import ImageEnhance, ImageFilter, ImageOps

        photo = _photo()
        self.assertCheck('sharpen', photo.filter(ImageFilter.UnsharpMask(2, 200, 0)))
        self.assertCheck('blur', photo.filter(ImageFilter.GaussianBlur(2)))
        self.assertCheck('motion_blur', photo.filter(ImageFilter.BoxBlur(2)))
        self.assertCheck('tilt_shift', photo.filter(ImageFilter.GaussianBlur(3)))
        self.assertCheck('noise_reduction', photo.filter(ImageFilter.MedianFilter(5)))
        self.assertCheck('texture', photo.filter(ImageFilter.GaussianBlur(1.5)), quote='smooth the skin',
                         direction='decrease')
        self.assertCheck('invert', ImageOps.invert(photo))
        self.assertCheck('flip', ImageOps.mirror(photo), quote='flip it horizontally')
        self.assertCheck('posterize', ImageOps.posterize(photo, 2))
        self.assertCheck('threshold', photo.convert('L').point(lambda v: 255 if v > 128 else 0).convert('RGB'))
        rgb = np.asarray(photo, dtype=np.float32)
        noisy = np.clip(rgb + np.random.default_rng(3).normal(0, 12, rgb.shape), 0, 255).astype('uint8')
        self.assertCheck('grain', Image.fromarray(noisy))
        h, w = rgb.shape[:2]
        yy, xx = np.ogrid[:h, :w]
        fall = np.clip(1.2 - 0.6 * np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)), 0, 1)[..., None]
        self.assertCheck('vignette', Image.fromarray((rgb * np.minimum(fall, 1)).astype('uint8')),
                         direction='decrease')
        magenta = np.clip(rgb + np.array([12, -12, 12]), 0, 255).astype('uint8')
        self.assertCheck('tint', Image.fromarray(magenta), direction='increase')
        orange = Image.blend(photo, Image.new('RGB', photo.size, '#f77f00'), 0.25)
        self.assertCheck('color_filter', orange, color='orange')
        hsv = np.asarray(photo.convert('HSV')).copy()
        hsv[..., 0] = (hsv[..., 0].astype(int) + 20) % 256
        turned = Image.merge('HSV', [Image.fromarray(hsv[..., channel]) for channel in range(3)])
        self.assertCheck('hue_shift', turned.convert('RGB'), color='blue')
        self.assertCheck('tone_curve', ImageEnhance.Contrast(photo).enhance(1.4))

    def test_a_faint_change_the_right_way_is_marked_weak(self):
        from image_studio.pipelines import checks
        from PIL import ImageFilter

        import numpy as np

        board = (np.indices((120, 160)).sum(axis=0) % 2).astype(np.uint8)
        photo = Image.fromarray((100 + 50 * board).astype(np.uint8)).convert('RGB')
        slightly = Image.fromarray((99 + 52 * board).astype(np.uint8)).convert('RGB')  # +4% detail
        record = checks.run(0, lang.blank('sharpen'), photo, slightly, [], [], False)[0]
        self.assertFalse(record['passed'])
        self.assertTrue(record.get('weak'))
        wrong_way = checks.run(0, lang.blank('sharpen'), photo, photo.filter(ImageFilter.GaussianBlur(2)), [], [],
                               False)[0]
        self.assertFalse(wrong_way.get('weak'))

    def test_only_faint_amounts_without_a_written_number_are_run_again(self):
        from image_studio.integrations import photocraft_workspace as ws

        plan = {'planner': 'brain', 'steps': [], 'edits': [
            lang.blank('brightness', direction='increase', strength='subtle'),
            lang.blank('vibrance', direction='increase', value=12.0),
            lang.blank('temperature', direction='increase', strength='strong'),
            lang.blank('contrast', direction='increase')]}
        checks = [{'requirement': i, 'measured': True, 'passed': False, 'weak': True} for i in range(4)]
        checks.append({'requirement': 3, 'measured': True, 'passed': False})  # also failed another way
        self.assertEqual(ws.too_faint(plan, checks), [0])
        self.assertEqual(ws.too_faint({**plan, 'planner': 'manual'}, checks), [])
        self.assertEqual(ws.too_faint({**plan, 'steps': [{'command': 'studio.ai_layer'}]}, checks), [])


class ContractTests(unittest.TestCase):
    SCHEMA = {'type': 'object', 'properties': {
        'edits': {'type': 'array', 'maxItems': 2, 'items': {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['blur_background', 'crop_aspect']},
            'value': {'anyOf': [{'type': 'number'}, {'type': 'null'}]},
            'position': {'type': 'string', 'enum': ['top', 'bottom', '']}},
            'required': ['action', 'value', 'position'], 'additionalProperties': False}}},
        'required': ['edits'], 'additionalProperties': False}

    def test_json_is_found_inside_prose_and_fences(self):
        self.assertEqual(contract.extract('Sure!\n```json\n{"a": [1, 2,],}\n```'), {'a': [1, 2]})
        self.assertIsNone(contract.extract('no json here'))

    def test_answers_are_repaired_without_guessing(self):
        value = {'edits': [{'action': 'Blur Background', 'value': '12', 'extra': 1},
                           {'action': 'crop-aspect', 'value': None, 'position': 'TOP'}, {'action': 'crop_aspect'}]}
        fixed, problems = contract.conform(value, self.SCHEMA)
        self.assertEqual(problems, [])
        self.assertEqual(fixed['edits'], [{'action': 'blur_background', 'value': 12.0, 'position': ''},
                                          {'action': 'crop_aspect', 'value': None, 'position': 'top'}])

    def test_choices_off_the_menu_are_reported(self):
        _, problems = contract.conform({'edits': [{'action': 'make it nice', 'value': None, 'position': ''}]},
                                       self.SCHEMA)
        self.assertEqual(len(problems), 1)
        self.assertIn('answer.edits[0].action', problems[0])

    def test_portable_schema_drops_constraints_some_providers_reject(self):
        self.assertNotIn('maxItems', json.dumps(contract.portable(self.SCHEMA)))

    def test_a_missing_menu_choice_is_asked_again_never_filled_with_the_first(self):
        # A missing review verdict once read as “done”, the first value of its menu.
        from image_studio.integrations import photocraft_planner as planner

        for verdict in ({'note': 'x'}, {'verdict': '', 'note': 'x'}, {'verdict': None, 'note': 'x'}):
            with self.subTest(verdict=verdict):
                fixed, problems = contract.conform({'verdicts': [verdict]}, planner.REVIEW_SCHEMA)
                self.assertIsNone(fixed['verdicts'][0]['verdict'])
                self.assertEqual(len(problems), 1)
        fixed, problems = contract.conform({'edits': [{'quote': 'x'}], 'preserve': [], 'questions': []},
                                           planner.UNDERSTAND_SCHEMA)
        self.assertIsNone(fixed['edits'][0]['action'])  # not “brightness”, the menu's first pipeline
        self.assertTrue(any('action' in problem for problem in problems))

    def test_a_near_spelling_is_not_a_menu_match(self):
        menu = ['saturation', 'sharpen', 'vignette', 'blur_background']
        self.assertIsNone(contract._menu_choice('desaturation', menu))  # the opposite edit
        self.assertIsNone(contract._menu_choice('unsharpen', menu))
        self.assertEqual(contract._menu_choice('vignettes', menu), 'vignette')
        self.assertEqual(contract._menu_choice('Blur-Background', menu), 'blur_background')

    def test_constraints_dropped_for_providers_are_checked_here(self):
        schema = {'type': 'object', 'properties': {'boxes': {'type': 'array', 'items': {
            'type': 'array', 'minItems': 4, 'maxItems': 4, 'items': {'type': 'number', 'minimum': 0, 'maximum': 1000}}},
            'name': {'type': 'string', 'minLength': 2, 'maxLength': 5}}}
        _, problems = contract.conform({'boxes': [[10, 20], [-50, 0, 4000, 900]], 'name': 'a'}, schema)
        self.assertEqual(len(problems), 4)  # two numbers, one short box, one short name
        fixed, problems = contract.conform({'boxes': [[0, 0, 500, 1000]], 'name': 'abcdefgh'}, schema)
        self.assertEqual((problems, fixed['name']), ([], 'abcde'))

    def test_the_review_reads_missing_or_skipped_verdicts_as_unclear(self):
        from image_studio.integrations import photocraft_planner as planner

        image = Image.new('RGB', (8, 8))
        with patch.object(models, 'chat', return_value={'verdicts': [{'verdict': None, 'note': ''}]}):
            verdicts = planner.review(['brighter', 'crop to 4:5'], ['keep the cat'], image, image)
        self.assertEqual([v['verdict'] for v in verdicts], ['unclear', 'unclear', 'unclear'])
        self.assertEqual([v['requirement'] for v in verdicts], [0, 1, None])

    def test_grounder_boxes_past_the_grid_are_clipped(self):
        from image_studio.services import segment

        boxes = segment.parse_boxes(json.dumps([{'bbox_2d': [-50, 0, 4000, 900]}, {'bbox_2d': [1100, 0, 1200, 50]}]),
                                    100, 100)
        self.assertEqual(boxes, [(0, 0, 100, 90)])


class ModelTests(unittest.TestCase):
    def tearDown(self):
        models.disconnect()

    def test_roles_default_to_the_bundled_model(self):
        with patch('image_studio.core.paths.load_settings', return_value={}):
            self.assertEqual({spec['kind'] for spec in models.settings().values()}, {'local'})

    def test_a_model_without_schema_support_is_asked_again_with_its_mistakes(self):
        replies = iter(['I think you want {"edits": [{"action": "sharpen it", "value": null, "position": ""}]}',
                        '{"edits": [{"action": "blur_background", "value": null, "position": "bottom"}]}'])
        seen = []

        def complete(self, system, content, schema=None, max_tokens=0, temperature=0.0):
            seen.append((system, content))
            return next(replies)

        models.connect('planner', preset='ollama', structured='none')
        with patch.object(adapters.OpenAICompatible, 'complete', complete):
            answer = models.chat('planner', 'Plan.', 'blur the background', schema=ContractTests.SCHEMA)
        self.assertEqual(answer['edits'][0]['action'], 'blur_background')
        self.assertIn('JSON schema', seen[0][0])  # the schema is spelled out for models that cannot enforce it
        self.assertIn('did not fit', seen[1][1][-1]['text'])

    def test_openai_compatible_request_carries_images_and_the_schema(self):
        sent = {}

        def post(url, body, headers, timeout=600):
            sent.update(url=url, body=body, headers=headers)
            return {'choices': [{'message': {'content': '{"edits": []}'}}]}

        models.connect('planner', preset='openai', model='some-model', api_key='key')
        with patch.object(adapters, '_post', post):
            answer = models.chat('planner', 'Plan.', [models.image_part(Image.new('RGB', (8, 8))),
                                                      {'type': 'text', 'text': 'go'}], schema=ContractTests.SCHEMA)
        self.assertEqual(answer, {'edits': []})
        self.assertTrue(sent['url'].endswith('/chat/completions'))
        self.assertEqual(sent['body']['response_format']['type'], 'json_schema')
        self.assertEqual(sent['body']['messages'][1]['content'][0]['type'], 'image_url')
        self.assertEqual(sent['headers']['Authorization'], 'Bearer key')

    def test_gemini_boxes_are_read_in_its_own_order(self):
        from image_studio.services import segment

        models.connect('grounder', preset='gemini', model='m', api_key='k')
        with patch.object(models, 'chat', return_value={'boxes': [[100, 200, 300, 600]]}):
            boxes = segment.find_boxes_brain(Image.new('RGB', (1000, 1000)), 'the cat')
        self.assertEqual(boxes, [(200, 100, 600, 300)])

    def test_rate_limits_and_server_errors_are_asked_again(self):
        import urllib.error

        calls, waits = [], []

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true}'

        def urlopen(request, timeout=0):
            calls.append(request.full_url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(request.full_url, 429 if len(calls) == 1 else 503, 'busy',
                                             {'retry-after': '1'}, io.BytesIO(b'{}'))
            return Reply()

        with patch('urllib.request.urlopen', urlopen):
            self.assertEqual(adapters._post('http://x/v1/chat', {}, {}, sleep=waits.append), {'ok': True})
        self.assertEqual((len(calls), waits), (3, [1.0, 1.0]))

        def refused(request, timeout=0):
            raise urllib.error.HTTPError(request.full_url, 401, 'no', {}, io.BytesIO(b'bad key'))

        with patch('urllib.request.urlopen', refused), self.assertRaises(RuntimeError):
            adapters._post('http://x/v1/chat', {}, {}, sleep=waits.append)
        self.assertEqual(len(waits), 2)  # a refused key is not asked again

    def test_a_text_only_model_cannot_ground_or_check(self):
        models.connect('grounder', preset='ollama', model='llama3', vision=False)
        self.assertFalse(models.available('grounder'))
        self.assertTrue(models.warnings('grounder'))

    def test_anthropic_messages_use_base64_images(self):
        adapter = adapters.Anthropic({'kind': 'anthropic'})
        blocks = adapter._blocks([models.image_part(Image.new('RGB', (8, 8))), {'type': 'text', 'text': 'hi'}])
        self.assertEqual(blocks[0]['source']['media_type'], 'image/jpeg')
        self.assertEqual(blocks[1], {'type': 'text', 'text': 'hi'})


if __name__ == '__main__':
    unittest.main()

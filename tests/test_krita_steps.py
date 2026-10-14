"""The pipeline engine's plans translated into Krita steps (integrations/krita_steps.py).

These run without Krita and without any model: the translated steps are checked against the
steps the Krita plugin can run, read from its source.
"""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from image_studio import pipelines
from image_studio.integrations import krita_steps
from image_studio.integrations import photocraft_intents as lang
from PIL import Image
from test_pipelines import BOXES, STATE, built

PLUGIN = Path(__file__).resolve().parents[1] / 'integrations' / 'krita-plugin' / 'ai_prompt'


def plugin_steps():
    """The step names Krita's plugin runs: its own tools (ops.LOCAL) and Image Studio jobs (AI_STEPS)."""
    names = set()
    for file, variable in (('ops.py', 'LOCAL'), ('runner.py', 'AI_STEPS')):
        tree = ast.parse((PLUGIN / file).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == variable for t in node.targets):
                names |= {const.value for const in ast.walk(node.value)
                          if isinstance(const, ast.Constant) and isinstance(const.value, str)}
    return names


def translated(pipeline_id, **extra):
    (steps, *_), edits = built(pipeline_id, **extra)
    return krita_steps.translate(steps, STATE), edits


class TranslationTests(unittest.TestCase):
    def test_every_translated_step_is_one_the_krita_plugin_runs(self):
        known = plugin_steps()
        self.assertIn('crop_rect', known)
        self.assertIn('select_color', known)
        for pipeline in pipelines.REGISTRY.values():
            if pipeline.id == 'other':
                continue
            with self.subTest(pipeline=pipeline.id):
                (steps, _), _ = translated(pipeline.id)
                for step in steps:
                    self.assertIn(step['op'], known)

    def test_most_pipelines_run_in_krita_in_full(self):
        coverage = krita_steps.coverage(lambda pid: (built(pid)[0][0], STATE))
        full = {pid for pid, missing in coverage.items() if not missing}
        self.assertGreaterEqual(len(full), 80)
        for pid in ('crop_aspect', 'recolor', 'blur_background', 'retouch_portrait', 'exposure_fix',
                    'keep_one_color', 'passport_photo', 'product_marketplace', 'add_text', 'remove_object'):
            self.assertIn(pid, full)
        # Not approximated: these need tools Krita does not have.
        for pid in ('perspective', 'lens_correction', 'tilt_shift', 'duotone', 'convert_mode'):
            self.assertTrue(coverage[pid], pid)

    def test_a_crop_keeps_the_pipelines_exact_frame(self):
        (steps, missing), _ = translated('crop_aspect')
        self.assertEqual(missing, {})
        self.assertEqual(steps, [{'op': 'crop_rect', 'x': 240, 'y': 0, 'w': 720, 'h': 900, 'requirements': [0]}])

    def test_camera_raw_settings_become_a_grade_with_the_same_values(self):
        step = {'command': 'studio.develop', 'requirements': [0], 'label': 'Develop',
                'params': {'params': {'exposure': 0.5, 'shadows': 25.0, 'vignetteAmount': -20.0,
                                      'sharpenAmount': 40.0, 'noiseLuminance': 25}}}
        steps, missing = krita_steps.translate([step], STATE)
        self.assertEqual(missing, {})
        grade, sharpen, denoise = steps
        self.assertEqual(grade['op'], 'grade')
        self.assertEqual(grade['layers'][0]['exposure'], 0.5)
        self.assertEqual(grade['layers'][0]['shadows'], 25.0)
        self.assertEqual(grade['layers'][0]['vignette'], 20.0)  # Camera Raw darkens corners with negatives
        self.assertNotIn('within_selection', grade)
        self.assertEqual((sharpen['op'], sharpen['amount']), ('sharpen', 40))
        self.assertEqual((denoise['op'], denoise['strength']), ('denoise', 25))

    def test_a_local_adjustment_keeps_to_the_selection_it_was_built_for(self):
        (steps, missing), _ = translated('retouch_portrait')
        self.assertEqual(missing, {})
        ops = [step['op'] for step in steps]
        self.assertEqual(ops[:3], ['select', 'require_selection', 'select_color'])
        self.assertEqual(steps[0]['boxes'], [[47.917, 38.333, 4.167, 1.667]])  # the teeth, in percent
        self.assertEqual(steps[2]['mode'], 'intersect')
        eyes = next(step for step in steps if step['op'] == 'select_box')
        self.assertTrue(eyes['ellipse'])
        local = [step for step in steps if step['op'] == 'grade']
        self.assertTrue(local and all(step.get('within_selection') for step in local))

    def test_colour_band_changes_use_the_grading_mixer_and_a_rename_names_the_layer(self):
        (steps, missing), _ = translated('season', choice='autumn')
        self.assertEqual(missing, {})
        bands = [step for step in steps if step['op'] == 'grade' and 'hsl' in step['layers'][0]]
        self.assertTrue(bands)
        self.assertNotIn('rename_layer', [step['op'] for step in steps])
        self.assertTrue(all(step.get('label') for step in steps if step['op'] in ('grade', 'filter_layer')))

    def test_an_edit_krita_cannot_run_is_left_out_whole_and_reported(self):
        edits = lang.expand([lang.blank('crop_aspect', aspect='4:5'), lang.blank('tilt_shift', quote='miniature')])
        steps, *_ = lang.compile_edits(edits, STATE, boxes=BOXES, ai=True)
        krita, missing = krita_steps.translate(steps, STATE)
        self.assertEqual(set(missing), {1})
        self.assertTrue(all(step['requirements'] == [0] for step in krita))
        self.assertIn('Krita does not have', krita_steps.summary(missing, edits)[0])

    def test_canvas_size_tracks_the_frame_for_later_boxes(self):
        steps = [{'command': 'image.canvasSize', 'params': {'width': 1200, 'height': 1200, 'anchor': 'center'},
                  'requirements': [0]},
                 {'command': 'select.rect', 'params': {'x': 0, 'y': 0, 'width': 600, 'height': 600},
                  'requirements': [0]}]
        krita, _ = krita_steps.translate(steps, STATE)
        self.assertEqual(krita[0], {'op': 'canvas_size', 'x': 0, 'y': -150, 'w': 1200, 'h': 1200,
                                    'requirements': [0]})
        self.assertEqual((krita[1]['w'], krita[1]['h']), (50.0, 50.0))

    def test_krita_state_becomes_the_document_the_pipelines_compile_against(self):
        state = {'width': 800, 'height': 600, 'layers': [
            {'name': 'Title', 'type': 'vectorlayer', 'visible': True, 'opacity': 100},
            {'name': 'Mask', 'type': 'transparencymask', 'visible': True, 'opacity': 100},
            {'name': 'Background', 'type': 'paintlayer', 'visible': True, 'opacity': 50}]}
        document = krita_steps.krita_state(state)
        self.assertEqual(document['width'], 800)
        self.assertEqual([(layer['name'], layer['kind'], layer['opacity']) for layer in document['layers']],
                         [('Title', 'Shape', 1.0), ('Background', 'Pixel', 0.5)])

    def test_colour_range_selects_the_named_colours(self):
        image = Image.new('RGB', (40, 20), '#2050d0')
        image.paste((220, 30, 30), (0, 0, 20, 20))
        mask = krita_steps.color_range_mask(image, {'select': 'reds'})
        self.assertGreater(mask.getpixel((5, 5)), 200)
        self.assertLess(mask.getpixel((30, 5)), 30)
        sampled = krita_steps.color_range_mask(image, {'colors': ['#2050d0'], 'fuzziness': 30})
        self.assertGreater(sampled.getpixel((30, 5)), 200)
        self.assertLess(sampled.getpixel((5, 5)), 30)


class PlanTests(unittest.TestCase):
    def test_krita_plans_with_the_pipeline_planner_and_hands_on_what_it_cannot_run(self):
        edits = [lang.blank('crop_aspect', aspect='4:5', quote='crop to 4:5'),
                 lang.blank('recolor', target='object', object='the dog', color='red', quote='make the dog red'),
                 lang.blank('tilt_shift', quote='make it look like a miniature')]
        state = {'width': 1200, 'height': 900, 'layers': [{'name': 'Background', 'type': 'paintlayer'}]}
        with patch('image_studio.integrations.photocraft_planner.understand', return_value=(edits, [], [], [])),                 patch('image_studio.integrations.photocraft_planner.locate',
                      return_value={'the dog': [[420, 200, 360, 600]]}) as locate,                 patch('image_studio.pipelines.models.available', return_value=True):
            steps, notes, leftover, questions = krita_steps.plan(
                'crop to 4:5, make the dog red and make it look like a miniature', Image.new('RGB', (600, 450)),
                state, status=str)
        self.assertEqual(locate.call_args[0][1], ['the dog'])  # found once, by the grounder, as in PhotoCraft
        # The retoucher's order, as in PhotoCraft: the colour change first, on the whole frame, then the crop.
        self.assertEqual(steps[0], {'op': 'select', 'target': 'the dog', 'boxes': [[35.0, 22.222, 30.0, 66.667]]})
        self.assertEqual(steps[-1], {'op': 'crop_rect', 'x': 240, 'y': 0, 'w': 720, 'h': 900})
        self.assertEqual(leftover, ['make it look like a miniature'])
        self.assertTrue(any('Krita does not have' in note for note in notes))


class SegmentJobTests(unittest.TestCase):
    def test_boxes_from_the_plan_are_outlined_without_asking_a_model_again(self):
        from image_studio.integrations import bridge
        from image_studio.services import workflows

        image = Image.new('RGB', (200, 100), 'white')
        request = {'image': bridge.encode_png(image), 'target': 'the dog', 'boxes': [[10, 20, 50, 40]]}
        with patch('image_studio.services.segment.available', return_value=True), \
                patch('image_studio.services.segment.outline', return_value=Image.new('L', (200, 100), 255)) as outline, \
                patch('image_studio.services.segment.select') as select:
            result = workflows.editor_segment(request, lambda *a, **k: None)
        outline.assert_called_once()
        self.assertEqual(outline.call_args[0][1], [[20.0, 20.0, 120.0, 60.0]])
        select.assert_not_called()
        self.assertEqual(result['mask'].size, (200, 100))


if __name__ == '__main__':
    unittest.main()

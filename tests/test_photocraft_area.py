import colorsys
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from image_studio.integrations import photocraft
from image_studio.integrations import photocraft_intents as intents
from image_studio.integrations import photocraft_workspace as ws
from image_studio.integrations.photocraft_area import MarkedArea, compile_area, mask_for
from PIL import Image
from pydantic import ValidationError

AREA = {'marks': [
    {'tool': 'lasso', 'points': [[.15, .15], [.45, .15], [.45, .6], [.15, .6]], 'size': .03},
    {'tool': 'brush', 'points': [[.8, .7], [.8, .8]], 'size': .06},
    {'tool': 'erase', 'points': [[.3, .35]], 'size': .1},
]}


class AreaTests(unittest.TestCase):
    def test_planner_sees_the_original_and_explicit_area(self):
        from image_studio.integrations import photocraft_planner as planner

        photo = Image.new('RGB', (200, 200), 'gray')
        with patch.object(planner.brain, 'image_part', side_effect=lambda image: image.copy()), \
                patch.object(planner.brain, 'chat', return_value={'edits': [], 'preserve': [], 'questions': []}) as chat:
            planner.understand('brighten these spots', photo, {'width': 200, 'height': 200}, area=AREA)
        content = chat.call_args.args[1]
        self.assertEqual(content[0].getpixel((40, 40)), (128, 128, 128))
        self.assertNotEqual(content[1].getpixel((40, 40)), (128, 128, 128))
        self.assertEqual(content[1].getpixel((60, 70)), (128, 128, 128))
        self.assertIn('exact user-marked area', content[2]['text'])

    def test_validate_empty_nonfinite_and_complex_marks(self):
        for area in ({'marks': []}, {'marks': [{'tool': 'brush', 'points': [[float('nan'), 0]]}]},
                     {'marks': [{'tool': 'lasso', 'points': [[.1, .2]]}]}):
            with self.assertRaises(ValidationError):
                MarkedArea.model_validate(area)
        with self.assertRaisesRegex(ValueError, 'empty'):
            mask_for({'marks': [{'tool': 'erase', 'points': [[.5, .5]]}]}, 100, 100)

    def test_marked_regions_and_erased_hole(self):
        mask = mask_for(AREA, 200, 200)
        self.assertEqual(mask.getpixel((40, 40)), 255)
        self.assertEqual(mask.getpixel((60, 70)), 0)
        self.assertEqual(mask.getpixel((160, 150)), 255)
        self.assertEqual(mask.getpixel((100, 100)), 0)

    def test_named_targets_do_not_trigger_object_guessing_or_inverse_selection(self):
        for action in ('brightness', 'shadows', 'blur_background', 'remove_object', 'generate'):
            result = compile_area([intents.blank(action, target='object', object='ear')],
                                  {'width': 320, 'height': 240, 'layers': []}, AREA, ai=True)
            commands = [step['command'] for step in result[0]]
            self.assertIn('studio.select_marked', commands)
            self.assertNotIn('select.inverse', commands)
            self.assertNotIn('studio.select_outline', commands)
        with self.assertRaisesRegex(ValueError, 'cannot be limited'):
            compile_area([intents.blank('crop_aspect', aspect='4:5')],
                         {'width': 320, 'height': 240}, AREA)


@unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
class AreaEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(ws, 'ROOT', Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)
        self.cancel = threading.Event()
        self.picture = np.random.default_rng(7).integers(40, 180, (240, 320, 3), dtype=np.uint8)
        contents = io.BytesIO()
        Image.fromarray(self.picture).save(contents, format='PNG')
        self.doc = ws.create(contents.getvalue(), 'test.png')

    def apply_plan(self, plan):
        return ws.apply(self.doc['id'], self.doc['revision'], plan['steps'], 'Marked edit',
                        lambda *a, **k: None, self.cancel, plan)

    def test_real_engine_changes_only_marked_pixels_and_keeps_eraser_hole(self):
        with patch.object(ws.photocraft_planner, 'locate') as locate:
            plan = ws.smart_plan(self.doc['id'], self.doc['revision'], 'make it brighter and warmer',
                                 lambda *a, **k: None, self.cancel, area=AREA)
            locate.assert_not_called()
        result = self.apply_plan(plan)
        with Image.open(ws.export(result['id'], result['revision'], 'png')) as image:
            edited = np.asarray(image.convert('RGB'))
        mask = np.asarray(mask_for(AREA, 320, 240)) > 0
        self.assertTrue(np.array_equal(self.picture[~mask], edited[~mask]))
        self.assertGreater(np.abs(edited[mask].astype(float) - self.picture[mask]).mean(), 1)
        self.assertTrue(any('outside your marked area' in c['check'] for c in result['history'][-1]['checks']))
        # A later same-word request for a different area must not reuse the earlier mask.
        self.doc = result
        second = {'marks': [{'tool': 'brush', 'points': [[.6, .3]], 'size': .1}]}
        plan = ws.smart_plan(self.doc['id'], self.doc['revision'], 'make it warmer',
                             lambda *a, **k: None, self.cancel, area=second)
        next_doc = self.apply_plan(plan)
        with Image.open(ws.export(next_doc['id'], next_doc['revision'], 'png')) as image:
            after = np.asarray(image.convert('RGB'))
        mask2 = np.asarray(mask_for(second, 320, 240)) > 0
        self.assertTrue(np.array_equal(edited[~mask2], after[~mask2]))
        self.assertTrue(np.any(edited[mask2] != after[mask2]))

    def test_leaking_tool_does_not_commit_a_revision(self):
        plan = {'area': AREA, 'steps': [{'command': 'layer.newAdjustmentLayer.brightnessContrast',
                                       'params': {'brightness': 70}}]}
        with self.assertRaisesRegex(ValueError, 'outside your marked area'):
            self.apply_plan(plan)
        self.assertEqual(ws.public(ws.load(self.doc['id']))['revision'], self.doc['revision'])

    def test_blur_and_color_grade_respect_the_boundary(self):
        for action in ('blur_background', 'color_grade'):
            with self.subTest(action=action):
                data = ws.load(self.doc['id'])
                with Image.open(ws.folder_for(self.doc['id']) / f'{self.doc["revision"]}.png') as image:
                    preview = image.copy()
                plan = ws.compile_plan(data, action, [intents.blank(action, color='blue')],
                                       [], [], [], preview, 'manual', area=AREA)
                result = self.apply_plan(plan)
                with Image.open(ws.export(result['id'], result['revision'], 'png')) as image:
                    edited = np.asarray(image.convert('RGB'))
                mask = np.asarray(mask_for(AREA, 320, 240)) > 0
                self.assertTrue(np.array_equal(self.picture[~mask], edited[~mask]))
                self.assertTrue(np.any(self.picture[mask] != edited[mask]))
                self.doc = ws.move_history(result['id'], result['revision'], -1)

    def test_shadow_lift_fades_inward_and_preserves_blue_hue(self):
        photo = Image.new('RGB', (320, 240), (20, 45, 125))
        contents = io.BytesIO()
        photo.save(contents, format='PNG')
        self.doc = ws.create(contents.getvalue(), 'blue-fabric.png')
        area = {'marks': [{'tool': 'lasso', 'points': [[.2, .2], [.8, .2], [.8, .8], [.2, .8]]}]}
        plan = ws.compile_plan(ws.load(self.doc['id']), 'Lift shadows',
                               [intents.blank('shadows', direction='increase', value=40)],
                               [], [], [], photo, 'manual', area=area)
        result = self.apply_plan(plan)
        with Image.open(ws.export(result['id'], result['revision'], 'png')) as rendered:
            edited = np.asarray(rendered.convert('RGB')).astype(float)
        original = np.asarray(photo).astype(float)
        mask = np.asarray(mask_for(area, 320, 240)) > 0
        self.assertTrue(np.array_equal(original[~mask], edited[~mask]))
        delta = (edited - original).mean(axis=2)
        self.assertGreater(delta[120, 160], 3)
        self.assertLess(delta[120, 65], delta[120, 160] / 4)
        self.assertGreater(len(np.unique(delta[120, 64:85])), 3)
        before_hue = colorsys.rgb_to_hls(*(original[120, 160] / 255))[0]
        after_hue = colorsys.rgb_to_hls(*(edited[120, 160] / 255))[0]
        self.assertAlmostEqual(before_hue, after_hue, delta=.01)
        self.assertTrue(any(layer.get('blend') == 'Luminosity' for layer in result['state']['layers']))

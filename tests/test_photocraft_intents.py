"""The PhotoCraft edit language: understanding guards, exact geometry, ordering, measurements.

These run without PhotoCraft or the brain; the end-to-end workspace tests at the bottom need
the PhotoCraft CLI and are skipped without it.
"""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from image_studio.integrations import photocraft
from image_studio.integrations import photocraft_intents as intents
from image_studio.integrations import photocraft_specs as specs
from PIL import Image, ImageDraw

STATE = {'width': 1000, 'height': 800, 'resolution': 72.0, 'layers': [
    {'id': 2, 'name': 'Background', 'kind': 'Pixel', 'visible': True, 'opacity': 1.0}]}


def edit(action, **fields):
    return intents.blank(action, **fields)


class UnderstandingTests(unittest.TestCase):
    def test_numbers_not_in_the_request_are_ignored(self):
        prompt = 'make it a bit warmer'
        result, notes = intents.normalize({'action': 'temperature', 'quote': prompt, 'value': 37}, prompt)
        self.assertIsNone(result['value'])
        self.assertEqual(result['strength'], 'subtle')
        self.assertTrue(notes)

    def test_typed_numbers_are_kept_with_their_sign(self):
        prompt = 'reduce saturation by 20'
        result, _ = intents.normalize({'action': 'saturation', 'quote': prompt, 'value': 20}, prompt)
        self.assertEqual(result['value'], 20)
        self.assertEqual(result['direction'], 'decrease')
        self.assertEqual(intents.amount(result, 20, -100, 100), -20)

    def test_title_keeps_the_exact_words_and_case(self):
        prompt = 'Add the title "Home Sweet Home" at the bottom'
        result, _ = intents.normalize({'action': 'add_text', 'quote': prompt, 'text': 'home sweet home'}, prompt)
        self.assertEqual(result['text'], 'Home Sweet Home')

    def test_aspect_ratios_and_named_formats(self):
        self.assertEqual(intents.aspect_from('crop to 4:5'), (4, 5))
        self.assertEqual(intents.aspect_from('make it square'), (1, 1))
        self.assertEqual(intents.aspect_from('for an instagram story'), (9, 16))

    def test_layer_changes_need_the_word_layer(self):
        prompt = 'while the mugs keep their color'
        result, _ = intents.normalize({'action': 'layer_blend', 'quote': prompt, 'object': 'Background'}, prompt)
        self.assertEqual(result['action'], 'keep')

    def test_crop_keeps_what_the_request_names(self):
        self.assertEqual(intents.kept_in_frame('crop to 4:5 keeping the cat in frame'), 'the cat')
        self.assertEqual(intents.subject_query(edit('crop_aspect', quote='square centered on her face',
                                                    target='main subject', object='the woman')), 'her face')

    def test_background_is_found_as_everything_in_front(self):
        self.assertEqual(intents.subject_query(edit('black_and_white', target='background', object='Background')),
                         intents.FOREGROUND)
        self.assertEqual(intents.subject_query(edit('black_and_white', target='background', object='the mugs')),
                         'the mugs')

    def test_color_names(self):
        self.assertEqual(intents.hex_color('red'), '#d62828')
        pastel = intents.hex_color('pastel pink')
        self.assertNotEqual(pastel, '#ffffff')
        hue, light, sat = intents.hls(pastel)
        self.assertTrue(0.8 < hue or hue < 0.05 or 0.85 < hue, pastel)
        self.assertLess(light, 0.95)
        self.assertEqual(intents.color_family('#1f4fd1'), 'blues')

    def test_uncovered_clauses_are_reported(self):
        edits = [edit('brightness', quote='make it brighter')]
        missing = intents.uncovered_clauses('Make it brighter. Also turn the lamp into a candle.', edits, [])
        self.assertEqual(missing, ['Also turn the lamp into a candle.'])

    def test_fonts_match_whole_words(self):
        fonts = ['Microsoft Sans Serif', 'Georgia', 'Inter', 'Segoe Script']
        self.assertEqual(intents.font_choice('serif', fonts)[0], 'Georgia')
        self.assertEqual(intents.font_choice('script bold shadow', fonts)[:4], ('Segoe Script', 700, False, ['shadow']))


class GeometryTests(unittest.TestCase):
    def test_largest_centered_crop(self):
        self.assertEqual(intents.largest_crop(1012, 813, (1, 1)), (100, 0, 813, 813))
        self.assertEqual(intents.largest_crop(1000, 800, (4, 5)), (180, 0, 640, 800))

    def test_crop_follows_a_focus_box_without_leaving_the_picture(self):
        x, y, w, h = intents.largest_crop(1000, 800, (1, 1), focus=[0, 100, 100, 100])
        self.assertEqual((x, y, w, h), (0, 0, 800, 800))

    def test_rotation_crop_has_no_empty_corners(self):
        x, y, w, h = intents.rotation_crop(1000, 800, 5)
        self.assertAlmostEqual(w / h, 1000 / 800, places=2)
        self.assertLess(w, 1000)
        self.assertEqual((x, y), ((1000 - w) // 2, (800 - h) // 2))

    def test_objects_are_selected_whole_and_measured_after_the_crop(self):
        steps, _, blocking, regions, _, canvas = intents.compile_edits(
            [edit('crop_aspect', aspect='1:1'), edit('recolor', target='object', object='the car', color='red')],
            STATE, boxes={'the car': [[300, 300, 100, 100]]})
        self.assertFalse(blocking)
        commands = [step['command'] for step in steps]
        self.assertLess(commands.index('select.object'), commands.index('image.crop'))
        select = next(step for step in steps if step['command'] == 'select.object')
        self.assertEqual(select['params']['rect'], [300, 300, 100, 100])
        self.assertEqual((canvas.width, canvas.height), (800, 800))
        self.assertEqual(regions[0]['final'], [[200 / 800, 300 / 800, 100 / 800, 100 / 800]])

    def test_text_is_placed_on_the_cropped_canvas(self):
        steps, *_ = intents.compile_edits([edit('crop_aspect', aspect='1:1'), edit('add_text', text='HI')], STATE)
        self.assertEqual([step['command'] for step in steps][-2:], ['image.crop', 'studio.text'])


class CompileTests(unittest.TestCase):
    def test_ordering_puts_text_last_after_geometry(self):
        edits = [edit('add_text', text='SUMMER', position='top'), edit('vibrance', value=12.0, direction='increase'),
                 edit('crop_aspect', aspect='1:1')]
        steps, *_ = intents.compile_edits(edits, STATE)
        commands = [step['command'] for step in steps]
        self.assertEqual(commands[-2:], ['image.crop', 'studio.text'])
        self.assertIn('layer.newAdjustmentLayer.vibrance', commands)
        vibrance = next(step for step in steps if step['command'].endswith('vibrance'))
        self.assertEqual(vibrance['params'], {'vibrance': 12.0})

    def test_global_raw_edits_share_one_camera_raw_filter(self):
        steps, *_ = intents.compile_edits([edit('clarity', direction='increase'),
                                           edit('vignette', direction='decrease', strength='subtle')], STATE)
        develop = [step for step in steps if step['command'] == 'studio.develop']
        self.assertEqual(len(develop), 1)
        self.assertEqual(develop[0]['params']['params'], {'clarity': 20.0, 'vignetteAmount': -12.5})

    def test_local_edits_are_masked_and_deselected(self):
        steps, *_ = intents.compile_edits([edit('saturation', target='sky', direction='increase')], STATE)
        commands = [step['command'] for step in steps]
        self.assertEqual(commands, ['studio.select_insert', 'select.sky', 'studio.require_selection',
                                    'layer.newAdjustmentLayer.hueSaturation', 'layer.renameLayer', 'select.deselect'])

    def test_missing_objects_block_instead_of_guessing(self):
        _, _, blocking, *_ = intents.compile_edits([edit('recolor', target='object', object='the boat',
                                                         color='red')], STATE)
        self.assertTrue(blocking)

    def test_large_removals_use_ai_and_small_ones_content_aware(self):
        big = intents.compile_edits([edit('remove_object', target='object', object='the mug')], STATE,
                                    boxes={'the mug': [[300, 300, 200, 200]]}, ai=True)[0]
        small = intents.compile_edits([edit('remove_object', target='object', object='the speck')], STATE,
                                      boxes={'the speck': [[300, 300, 20, 20]]}, ai=True)[0]
        self.assertEqual(big[0]['command'], 'studio.ai_layer')
        self.assertIn('studio.retouch_fill', [step['command'] for step in small])

    def test_removed_objects_are_not_foreground_any_more(self):
        boxes = {'the mug': [[600, 300, 200, 200]], intents.FOREGROUND: [[100, 300, 200, 200], [600, 300, 200, 200]]}
        steps, *_ = intents.compile_edits([edit('remove_object', target='object', object='the mug'),
                                           edit('black_and_white', target='background')], STATE, boxes=boxes, ai=True)
        kept = [step['params']['rect'] for step in steps if step['command'] == 'select.object']
        self.assertEqual(kept, [[100, 300, 200, 200]])

    def test_empty_object_selections_stop_the_edit(self):
        steps, *_ = intents.compile_edits([edit('recolor', target='object', object='the car', color='red')], STATE,
                                          boxes={'the car': [[300, 300, 100, 100]]})
        commands = [step['command'] for step in steps]
        self.assertLess(commands.index('studio.require_selection'),
                        commands.index('layer.newAdjustmentLayer.hueSaturation'))

    def test_objects_cropped_out_are_reported(self):
        _, notes, *_ = intents.compile_edits(
            [edit('crop_aspect', aspect='1:1', position='left'), edit('recolor', target='object', object='the boat',
                                                                      color='red')],
            STATE, boxes={'the boat': [[900, 300, 90, 90]]})
        self.assertTrue(any('outside the cropped picture' in item for item in notes), notes)

    def test_sky_edits_cut_out_what_stands_in_front(self):
        steps, *_ = intents.compile_edits([edit('saturation', target='sky', direction='increase')], STATE,
                                          boxes={intents.FOREGROUND: [[100, 100, 200, 600]]})
        commands = [step['command'] for step in steps]
        self.assertEqual(commands[1:5], ['select.sky', 'studio.require_selection', 'select.modify.expand',
                                         'select.object'])
        self.assertEqual(steps[4]['params']['mode'], 'subtract')

    def test_a_look_on_the_sky_stays_on_the_sky(self):
        steps, *_ = intents.compile_edits([edit('look', choice='dramatic', target='sky', strength='strong')], STATE)
        commands = [step['command'] for step in steps]
        self.assertNotIn('studio.develop', commands)
        self.assertEqual(commands[:3], ['select.sky', 'studio.require_selection', 'studio.local_filter'])

    def test_generative_requests_need_ai(self):
        _, _, blocking, *_ = intents.compile_edits([edit('generate', quote='add a dog')], STATE, ai=False)
        self.assertTrue(blocking)

    def test_cutout_backdrop_goes_to_the_back(self):
        steps, *_ = intents.compile_edits([edit('remove_background', color='pastel pink')], STATE,
                                          boxes={'the main subject': [[200, 100, 400, 600]]})
        commands = [step['command'] for step in steps]
        self.assertIn('layer.layerMask.revealSelection', commands)
        self.assertEqual(commands[-1], 'layer.arrange.sendToBack')


class MeasureTests(unittest.TestCase):
    def picture(self, mug):
        image = Image.new('RGB', (200, 100), (200, 200, 200))
        ImageDraw.Draw(image).rectangle((60, 30, 120, 90), fill=mug)
        return image

    def test_recolor_is_measured_by_hue(self):
        edits = [edit('recolor', target='object', object='the mug', color='green')]
        regions = [{'requirement': 0, 'label': 'the mug', 'boxes': [[0.3, 0.3, 0.3, 0.6]]}]
        good = intents.measure(edits, regions, self.picture((200, 40, 40)), self.picture((40, 160, 60)), False)
        bad = intents.measure(edits, regions, self.picture((200, 40, 40)), self.picture((120, 120, 120)), False)
        self.assertIs(good[0]['passed'], True)
        self.assertFalse(bad[0]['passed'])

    def test_brightness_direction_is_measured(self):
        edits = [edit('brightness', direction='increase')]
        dark, light = Image.new('RGB', (10, 10), (90, 90, 90)), Image.new('RGB', (10, 10), (120, 120, 120))
        self.assertTrue(intents.measure(edits, [], dark, light, False)[0]['passed'])
        self.assertFalse(intents.measure(edits, [], light, dark, False)[0]['passed'])


class SpecTests(unittest.TestCase):
    def test_specs_become_typed_fields(self):
        fields = specs.parse('{"radius":0.1..1000=1,"distribution":"uniform|gaussian","monochromatic":bool,'
                             '"color":"#rrggbb"}')
        self.assertEqual([f['type'] for f in fields], ['number', 'choice', 'bool', 'color'])
        self.assertEqual((fields[0]['min'], fields[0]['max'], fields[0]['default']), (0.1, 1000, 1))

    def test_generated_settings_are_clamped_and_filtered(self):
        fields = specs.parse('{"amount":1..500=100,"mode":"a|b"}')
        clean, notes = specs.sanitize({'amount': 9000, 'mode': 'z', 'evil': 1}, fields)
        self.assertEqual(clean, {'amount': 500})
        self.assertEqual(len(notes), 3)


@unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
class EngineTests(unittest.TestCase):
    """Compiled plans running in the real headless engine."""

    def setUp(self):
        from image_studio.integrations import photocraft_workspace as ws

        self.ws = ws
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(ws, 'ROOT', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        picture = Image.new('RGB', (1000, 800), (40, 70, 110))
        ImageDraw.Draw(picture).rectangle((0, 500, 1000, 800), fill=(150, 120, 80))
        path = Path(self.temp.name) / 'scene.png'
        picture.save(path)
        self.document = ws.create(path.read_bytes(), 'scene.png')

    def test_crop_text_and_adjustments_land_as_planned(self):
        edits = [{'action': 'crop_aspect', 'aspect': '4:5'},
                 {'action': 'vibrance', 'value': 12, 'direction': 'increase'},
                 {'action': 'clarity', 'direction': 'increase'},
                 {'action': 'add_text', 'text': 'SUMMER', 'position': 'top', 'size': 'large'}]
        plan = self.ws.manual_plan(self.document['id'], self.document['revision'], edits, 'test')
        self.assertFalse(plan['unresolved'])
        result = self.ws.apply(self.document['id'], self.document['revision'], plan['steps'], 'test',
                               lambda *a, **k: None, threading.Event(), plan)
        self.assertEqual((result['state']['width'], result['state']['height']), (640, 800))
        names = [layer['name'] for layer in result['state']['layers']]
        self.assertEqual(names[0], 'SUMMER')
        self.assertIn('Photo', names)
        checks = result['history'][-1]['checks']
        self.assertTrue(checks and all(check['passed'] for check in checks), checks)


if __name__ == '__main__':
    unittest.main()

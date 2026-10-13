import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from image_studio.services import memory


def doc(*layers):
    """A Krita document state with these (name, depth) layers, top first."""
    return dict(
        name='photo.png',
        width=800,
        height=600,
        layers=[dict(name=name, type='paintlayer', depth=depth) for name, depth in layers],
    )


def plan(text, state, planner):
    """What workflows.editor_plan does around its planners."""
    intent = memory.understand(text, state)
    if intent.result is None:
        steps, how = planner(intent.text), 'rules'
    else:
        steps, how = [], 'memory'
    steps, how, notes = memory.finish(intent, steps, how)
    return steps, how, notes, intent


def rules(text):
    known = {
        'make it warmer': [dict(op='warmth', amount=30)],
        'make it brighter': [dict(op='brightness', amount=30)],
        'more contrast and saturation': [dict(op='contrast', amount=30), dict(op='saturation', amount=30)],
        'crop to square': [dict(op='crop', aspect='1:1')],
    }
    return [dict(step) for step in known.get(text.lower(), [dict(op='ai_edit', instruction=text)])]


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        self.patches = [
            patch.object(memory, 'FOLDER', folder),
            patch.object(memory, 'FILE', folder / 'memory.json'),
            patch.object(memory, '_last', None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.folder.cleanup()

    def test_taught_phrase_is_rewritten_in_later_requests(self):
        steps, how, notes, _ = plan('remember: make it pop means more contrast and saturation', doc(), rules)
        self.assertEqual([step['op'] for step in steps], ['say'])
        self.assertIn('Learned', steps[0]['text'])
        steps, _, notes, intent = plan('Make it pop', doc(), rules)
        self.assertEqual(intent.text, 'more contrast and saturation')
        self.assertEqual([step['op'] for step in steps], ['contrast', 'saturation'])
        self.assertTrue(any('taught me' in note for note in notes))
        self.assertEqual(memory.load()['words'][0]['used'], 1)

    def test_when_i_say_form_and_forget(self):
        plan('when I say "moody", I mean make it darker', doc(), rules)
        self.assertEqual(memory.load()['words'][0]['phrase'], 'moody')
        steps, *_ = plan('forget moody', doc(), rules)
        self.assertIn('Forgotten', steps[0]['text'])
        self.assertEqual(memory.load()['words'], [])

    def test_correction_removes_the_last_layers_and_learns(self):
        before = doc(('Background', 0))
        plan('make it brighter', before, rules)
        after = doc(('Brightness', 0), ('Background', 0))
        steps, _, notes, _ = plan('no, I meant make it warmer', after, rules)
        self.assertEqual(steps, [dict(op='delete_layer', layer='Brightness'), dict(op='warmth', amount=30)])
        self.assertEqual(
            memory.load()['words'][0],
            {
                **memory.load()['words'][0],
                'phrase': 'make it brighter',
                'means': 'make it warmer',
                'source': 'correction',
            },
        )
        # Next time, "make it brighter" is understood as taught.
        _, _, _, intent = plan('make it brighter', doc(('Warmth', 0), ('Background', 0)), rules)
        self.assertEqual(intent.text, 'make it warmer')

    def test_correction_after_crop_only_learns(self):
        plan('crop to square', doc(('Background', 0)), rules)
        steps, how, notes, _ = plan('no I meant make it warmer', doc(('Background', 0)), rules)
        self.assertEqual([step['op'] for step in steps], ['say'])
        self.assertIn('Undo', steps[0]['text'])
        self.assertEqual(memory.load()['words'][0]['phrase'], 'crop to square')

    def test_less_redoes_weaker_and_is_remembered(self):
        plan('make it warmer', doc(('Background', 0)), rules)
        steps, how, notes, _ = plan('too much', doc(('Warmth', 0), ('Background', 0)), rules)
        self.assertEqual(steps, [dict(op='delete_layer', layer='Warmth'), dict(op='warmth', amount=18)])
        self.assertEqual(how, 'memory')
        self.assertLess(memory.load()['strength']['warmth'], 1)
        # A second "less" starts from the same picture as the first request.
        steps, *_ = plan('even less', doc(('Warmth', 0), ('Background', 0)), rules)
        self.assertEqual(steps[0], dict(op='delete_layer', layer='Warmth'))
        self.assertLess(steps[1]['amount'], 18)
        # New warmth requests are made a little weaker from now on, unless a number is given.
        steps, *_ = plan('make it warmer', doc(('Background', 0)), rules)
        self.assertLess(steps[0]['amount'], 30)

    def test_layers_inside_a_new_group_are_not_deleted_separately(self):
        before = doc(('Background', 0))
        now = doc(('Sunset light', 0), ('Warm', 1), ('Glow', 1), ('Background', 0))
        self.assertEqual(memory.added_layers(before, now), ['Sunset light'])

    def test_unsafe_layer_lists_are_not_guessed(self):
        before = doc(('Brightness', 0), ('Background', 0))
        now = doc(('Brightness', 0), ('Brightness', 0), ('Background', 0))
        self.assertIsNone(memory.added_layers(before, now))
        self.assertIsNone(memory.added_layers(before, {**now, 'width': 400}))

    def test_ordinary_requests_are_not_mistaken_for_commands(self):
        for text in [
            'No people in the background',
            'more contrast',
            'less saturation please',
            'remember the cat',
        ]:
            intent = memory.understand(text, doc())
            self.assertIsNone(intent.result, text)
            self.assertEqual(intent.text, text)
            self.assertIsNone(intent.teach_phrase, text)

    def test_favorites(self):
        memory.set_favorite('a.png')
        memory.set_favorite('b.png')
        memory.set_favorite('a.png', False)
        self.assertEqual(memory.favorites(), ['b.png'])


class MemoryApiTests(MemoryTests.__base__):
    """The endpoints and the Krita planning job, with memory in a temporary folder."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from image_studio.api.app import app

        self.folder = tempfile.TemporaryDirectory()
        folder = Path(self.folder.name)
        self.patches = [
            patch.object(memory, 'FOLDER', folder),
            patch.object(memory, 'FILE', folder / 'memory.json'),
            patch.object(memory, '_last', None),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.folder.cleanup()

    def test_teach_and_forget_through_the_api(self):
        result = self.client.post(
            '/api/memory', json=dict(action='teach', phrase='Make it pop', means='more contrast')
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['words'][0]['phrase'], 'make it pop')
        self.assertIn('personal', result.json())
        bad = self.client.post('/api/memory', json=dict(action='teach', phrase='x', means='y'))
        self.assertEqual(bad.status_code, 422)
        result = self.client.post('/api/memory', json=dict(action='forget', phrase='make it pop'))
        self.assertEqual(result.json()['words'], [])

    def test_favorites_must_be_library_images(self):
        result = self.client.post('/api/favorites', json=dict(name='../secret.png'))
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.client.get('/api/favorites').json(), dict(names=[]))

    def test_personal_lora_needs_enough_favorites(self):
        result = self.client.post('/api/personal-lora', json=dict(action='train'))
        self.assertEqual(result.status_code, 409)
        self.assertIn('favorites', result.json()['detail'])

    def test_krita_planning_uses_what_was_taught(self):
        from image_studio.services import workflows

        memory.teach('make it pop', 'more contrast')
        with patch.object(workflows.models, 'available', return_value=False):
            result = workflows.editor_plan(
                dict(prompt='Make it pop', state=doc(('Background', 0))), lambda *a, **k: None
            )
        self.assertEqual([step['op'] for step in result['steps']], ['contrast'])
        self.assertTrue(any('taught me' in note for note in result['notes']))
        # "too much" right after it takes the new layer back and redoes it weaker.
        with patch.object(workflows.models, 'available', return_value=False):
            result = workflows.editor_plan(
                dict(prompt='too much', state=doc(('Contrast', 0), ('Background', 0))), lambda *a, **k: None
            )
        self.assertEqual([step['op'] for step in result['steps']], ['delete_layer', 'contrast'])
        self.assertEqual(result['how'], 'memory')


if __name__ == '__main__':
    unittest.main()

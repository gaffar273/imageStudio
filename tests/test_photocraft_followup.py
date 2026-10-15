"""Follow-up requests revise the last edit instead of stacking a new one (photocraft_followup)."""

import json
import tempfile
import unittest
from pathlib import Path

from image_studio.integrations import photocraft_followup as followup
from image_studio.integrations import photocraft_intents as lang


def last_plan(*edits):
    return {'prompt': 'make it warmer and add a vignette', 'revision': 'a' * 32, 'planner': 'rules',
            'edits': list(edits), 'boxes': {}, 'preserve': []}


WARMER = lang.blank('temperature', quote='make it warmer', direction='increase')
VIGNETTE = lang.blank('vignette', quote='add a vignette', direction='decrease')


class ReviseTests(unittest.TestCase):
    def test_too_much_turns_the_last_edit_down_a_step(self):
        edits, notes, changed = followup.revise('too much', last_plan(WARMER, VIGNETTE))
        self.assertTrue(changed)
        self.assertEqual([edit['strength'] for edit in edits], ['subtle', 'subtle'])
        self.assertIn('Turned down', notes[0])

    def test_more_turns_it_up(self):
        edits, _, changed = followup.revise('a bit more', last_plan(WARMER))
        self.assertTrue(changed)
        self.assertEqual(edits[0]['strength'], 'strong')

    def test_already_at_the_end_says_so_and_changes_nothing(self):
        subtle = {**WARMER, 'strength': 'subtle'}
        edits, notes, changed = followup.revise('tone it down', last_plan(subtle))
        self.assertFalse(changed)
        self.assertIn('subtlest', notes[0])

    def test_without_a_part_rebuilds_the_last_edit_without_it(self):
        edits, notes, changed = followup.revise('without the vignette', last_plan(WARMER, VIGNETTE))
        self.assertTrue(changed)
        self.assertEqual([edit['action'] for edit in edits], ['temperature'])
        edits, _, _ = followup.revise('remove the darker corners', last_plan(WARMER, VIGNETTE))
        self.assertEqual([edit['action'] for edit in edits], ['temperature'])

    def test_taking_out_all_of_the_last_edit_is_an_undo(self):
        # Found in a real session: “without the vignette” right after “add a vignette” left an empty plan.
        _, notes, changed = followup.revise('without the vignette', last_plan(VIGNETTE))
        self.assertFalse(changed)
        self.assertIn('Undo', notes[0])

    def test_a_new_request_is_not_a_follow_up_phrase(self):
        self.assertIsNone(followup.revise('add a title SUMMER at the top', last_plan(WARMER)))
        self.assertIsNone(followup.revise('without the dog', last_plan(WARMER)))  # nothing of the last edit

    def test_fixed_edits_are_not_turned_up_or_down(self):
        level = lang.blank('develop_level', quote='Professional photo develop: level horizon')
        crop = lang.blank('crop_aspect', quote='crop to 4:5', aspect='4:5')
        edits, notes, changed = followup.revise('too much', last_plan(level, crop))
        self.assertFalse(changed)

    def test_too_much_on_a_develop_dials_the_whole_develop_back(self):
        # Found in a real run: “too much” after a develop only “turned down” the horizon step.
        tone = lang.blank('develop_tone', quote='Professional photo develop: tones')
        level = lang.blank('develop_level', quote='Professional photo develop: level horizon')
        edits, _, changed = followup.revise('too much', last_plan(tone, level))
        self.assertTrue(changed)
        self.assertEqual([edit['strength'] for edit in edits], ['subtle', 'moderate'])


class MergeTests(unittest.TestCase):
    def test_the_other_way_turns_the_same_edit_down_instead_of_stacking(self):
        cooler = lang.blank('temperature', quote='less warm', direction='decrease')
        edits, notes = followup.merge([cooler], last_plan(WARMER, VIGNETTE))
        self.assertEqual([(edit['action'], edit['strength']) for edit in edits],
                         [('temperature', 'subtle'), ('vignette', 'moderate')])
        self.assertEqual(sum(edit['action'] == 'temperature' for edit in edits), 1)
        self.assertIn('instead of adding another layer', notes[0])

    def test_the_same_way_turns_it_up(self):
        warmer = lang.blank('temperature', quote='warmer still', direction='increase')
        edits, _ = followup.merge([warmer], last_plan(WARMER))
        self.assertEqual(edits[0]['strength'], 'strong')

    def test_the_other_way_on_a_subtle_edit_takes_it_out(self):
        cooler = lang.blank('temperature', quote='not warm', direction='decrease')
        edits, notes = followup.merge([cooler], last_plan({**WARMER, 'strength': 'subtle'}, VIGNETTE))
        self.assertEqual([edit['action'] for edit in edits], ['vignette'])

    def test_new_edits_are_added_and_unrelated_requests_are_not_follow_ups(self):
        cooler = lang.blank('temperature', quote='less warm', direction='decrease')
        title = lang.blank('add_text', quote='add SUMMER', text='SUMMER')
        edits, _ = followup.merge([cooler, title], last_plan(WARMER))
        self.assertEqual([edit['action'] for edit in edits], ['temperature', 'add_text'])
        self.assertIsNone(followup.merge([title], last_plan(WARMER)))
        # A written number is the person's exact amount, never a step of the old one.
        exact = lang.blank('temperature', quote='temperature -10', direction='decrease', value=10)
        self.assertIsNone(followup.merge([exact], last_plan(WARMER)))
        # Another target is another edit.
        shirt = lang.blank('temperature', quote='make his shirt cooler', direction='decrease', target='object',
                           object='his shirt')
        self.assertIsNone(followup.merge([shirt], last_plan(WARMER)))


class LastRequestTests(unittest.TestCase):
    def test_only_the_plan_that_made_the_photo_on_screen_is_revised(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            plan = {**last_plan(WARMER), 'id': 'b' * 32}
            (folder / f'plan-{"b" * 32}.json').write_text(json.dumps(plan), encoding='utf-8')
            data = {'cursor': 1, 'history': [{'id': 'a' * 32}, {'id': 'c' * 32, 'plan': 'b' * 32}]}
            found, base = followup.last_request(data, folder)
            self.assertEqual((found['id'], base), ('b' * 32, 'a' * 32))
            self.assertIsNone(followup.last_request({**data, 'cursor': 0}, folder))  # the original
            synced = {'cursor': 1, 'history': [{'id': 'a' * 32}, {'id': 'c' * 32}]}
            self.assertIsNone(followup.last_request(synced, folder))  # not made by a plan


if __name__ == '__main__':
    unittest.main()

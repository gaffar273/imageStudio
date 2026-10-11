import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from image_studio.api.app import app
from image_studio.integrations import photocraft
from image_studio.integrations import photocraft_workspace as ws


@unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(ws, 'ROOT', Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.cancel = threading.Event()
        self.document = ws.create(width=320, height=240)

    def apply(self, commands, label='Test edit'):
        return ws.apply(
            self.document['id'], self.document['revision'], commands, label, lambda *a, **k: None, self.cancel
        )

    def test_native_crop_text_adjustments_export_and_history(self):
        result = self.apply(
            [
                {'command': 'image.crop', 'params': {'x': 40, 'y': 0, 'width': 240, 'height': 240}},
                {
                    'command': 'type.create',
                    'params': {
                        'text': 'SUMMER',
                        'x': 120,
                        'y': 45,
                        'size': 24,
                        'align': 'center',
                        'color': '#224466',
                    },
                },
                {'command': 'layer.newAdjustmentLayer.vibrance', 'params': {'vibrance': 12}},
            ]
        )
        self.assertEqual((result['state']['width'], result['state']['height']), (240, 240))
        text = next(layer for layer in result['state']['layers'] if layer['kind'] == 'Type')
        self.assertEqual(text['text']['text'], 'SUMMER')
        self.assertEqual(text['text']['sizePt'], 24)
        self.assertEqual(len(result['state']['layers']), 3)
        path = ws.export(result['id'], result['revision'], 'psd')
        self.assertEqual(path.read_bytes()[:4], b'8BPS')
        undo = ws.move_history(result['id'], result['revision'], -1)
        self.assertEqual(undo['revision'], self.document['revision'])
        redo = ws.move_history(undo['id'], undo['revision'], 1)
        self.assertEqual(redo['revision'], result['revision'])
        self.assertEqual(ws.public(ws.load(redo['id']))['revision'], result['revision'])

    def test_failed_batch_and_cancel_preserve_revision(self):
        with self.assertRaises(ValueError):
            self.apply(
                [
                    {'command': 'layer.new.layer', 'params': {'name': 'Should not commit'}},
                    {'command': 'layer.select', 'params': {'layer': 999999}},
                ]
            )
        self.assertEqual(ws.public(ws.load(self.document['id']))['revision'], self.document['revision'])
        self.cancel.set()
        with self.assertRaises(ws.Cancelled):
            self.apply([{'command': 'layer.new.layer', 'params': {}}])
        self.assertEqual(len(ws.load(self.document['id'])['history']), 1)

    def test_unknown_external_and_stale_commands_rejected(self):
        for steps in [
            [],
            [{'command': 'fake.command'}],
            [{'command': 'file.open', 'params': {}}],
            [{'command': 'layer.newAdjustmentLayer.colorLookup', 'params': {'file': 'C:/secret.cube'}}],
            [{'command': 'image.imageSize', 'params': {'width': 90000}}],
        ]:
            with self.assertRaises(ValueError):
                self.apply(steps)
        result = self.apply([{'command': 'layer.new.layer', 'params': {'name': 'Committed'}}])
        with self.assertRaisesRegex(ValueError, 'document changed'):
            self.apply([{'command': 'layer.new.layer', 'params': {}}])
        self.assertEqual(len(result['history']), 2)

    def test_simple_plan_no_model_and_unresolved_plan_cannot_apply(self):
        with patch.object(ws.brain, 'chat') as model:
            plan = ws.smart_plan(
                self.document['id'],
                self.document['revision'],
                'make it brighter and warmer',
                lambda *a, **k: None,
                self.cancel,
            )
            model.assert_not_called()
        self.assertEqual([edit['action'] for edit in plan['edits']], ['brightness', 'temperature'])
        self.assertEqual(plan['planner'], 'rules')
        self.assertEqual(ws.load_plan(self.document['id'], plan['id'])['revision'], self.document['revision'])
        plan['unresolved'] = ['Need a target object']
        (ws.folder_for(self.document['id']) / f'plan-{plan["id"]}.json').write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'unanswered'):
            ws.load_plan(self.document['id'], plan['id'])
        self.assertTrue(ws.load_plan(self.document['id'], plan['id'], partial=True)['steps'])

    def test_planner_preserves_details_and_flags_missing_requirements(self):
        understood = {
            'edits': [
                {
                    'quote': 'Add a SUMMER title at the top', 'action': 'add_text', 'target': 'whole image',
                    'object': '', 'direction': 'none', 'strength': 'moderate', 'value': 99, 'text': 'summer',
                    'color': 'white', 'position': 'top', 'size': '', 'aspect': '', 'choice': '',
                }
            ],
            'preserve': ['Keep colors'],
            'questions': [],
        }
        with (
            patch.object(ws.brain, 'available', return_value=True),
            patch.object(ws.brain, 'chat', return_value=understood),
        ):
            plan = ws.smart_plan(
                self.document['id'],
                self.document['revision'],
                'Add a SUMMER title at the top. Turn the lamp into a glowing candle.',
                lambda *a, **k: None,
                self.cancel,
            )
        # The words keep the case the person typed; an invented number is dropped.
        self.assertEqual(plan['edits'][0]['text'], 'SUMMER')
        self.assertIsNone(plan['edits'][0]['value'])
        self.assertEqual(plan['preserve'], ['Keep colors'])
        self.assertIn('Not understood: “Turn the lamp into a glowing candle.”', plan['unresolved'])
        self.assertEqual(plan['steps'][-1]['command'], 'studio.text')
        self.assertEqual(plan['steps'][-1]['params']['text'], 'SUMMER')

    def test_import_layered_native_keeps_layer_types(self):
        result = self.apply([{'command': 'type.create', 'params': {'text': 'Live text', 'x': 12, 'y': 40}}])
        source = ws.export(result['id'], result['revision'], 'pcraft')
        imported = ws.create(source.read_bytes(), 'layered.pcraft')
        self.assertTrue(any(layer['kind'] == 'Type' for layer in imported['state']['layers']))

    def test_desktop_handoff_never_overwrites_revision_and_syncs_saved_copy(self):
        with patch.object(photocraft, 'open_document') as opened:
            handoff = ws.desktop(self.document['id'], self.document['revision'])
        copy = opened.call_args.args[0]
        self.assertNotEqual(copy.stem, self.document['revision'])
        with ws.Engine(copy.parent) as engine:
            engine.call('doc.open', {'path': str(copy)})
            engine.call(
                'engine.execute', {'command': 'layer.new.layer', 'params': {'name': 'Desktop change'}}
            )
            engine.call('doc.save', {'path': str(copy)})
        result = ws.sync_desktop(handoff['id'], handoff['revision'], self.cancel)
        self.assertTrue(any(layer['name'] == 'Desktop change' for layer in result['state']['layers']))
        self.assertEqual(len(result['history']), 2)

    def test_api_preview_and_foreign_origin_guard(self):
        client = TestClient(app)
        route = f'/api/photocraft/workspaces/{self.document["id"]}'
        self.assertEqual(client.get(route).json()['revision'], self.document['revision'])
        self.assertEqual(client.get(self.document['preview']).status_code, 200)
        self.assertEqual(client.get(route + '/preview/not-a-revision').status_code, 404)
        self.assertEqual(
            client.post(
                '/api/photocraft/workspaces', json={}, headers={'Origin': 'https://foreign.example'}
            ).status_code,
            403,
        )

"""Project lifecycle regressions: originals, explicit placement, recovery and portable files."""

import io
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from image_studio.api import photocraft as api
from image_studio.api.app import app
from image_studio.integrations import bridge, photocraft, photocraft_projects as projects
from image_studio.integrations import photocraft_workspace as ws
from image_studio.services import krita_projects as krita


def png(size, color):
    output = io.BytesIO()
    Image.new('RGBA', size, color).save(output, 'PNG')
    return output.getvalue()


@unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
class PhotoCraftProjects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for key, path in [('ROOT', 'projects'), ('LEGACY_ROOT', 'old-cache')]:
            change = patch.object(ws, key, Path(self.temp.name) / path)
            change.start()
            self.addCleanup(change.stop)

    def test_originals_stay_separate_until_placed_and_survive_clear_backup_and_reopen(self):
        doc = ws.create(width=600, height=400, filename='Card layout')
        ident, original = doc['id'], doc['revision']
        barcode = png((200, 30), '#101010')
        card = png((400, 250), '#2288cc')
        doc = projects.import_assets(ident, original, [('barcode.png', barcode), ('card.png', card)])
        self.assertEqual(doc['revision'], original)
        self.assertEqual(len(doc['state']['layers']), 1)
        self.assertEqual(len(doc['assets']), 2)
        sources = {a['name']: a for a in doc['assets']}
        doc = projects.clear_canvas(ident, original, asset_id=sources['card.png']['id'])
        self.assertEqual((doc['state']['width'], doc['state']['height']), (400, 250))
        doc = projects.place_asset(ident, doc['revision'], sources['barcode.png']['id'], x=200, y=190)
        self.assertEqual(doc['state']['layers'][0]['bounds'], [100, 175, 200, 30])
        self.assertEqual(len(doc['assets']), 2)  # placement does not duplicate the source
        before_clear = doc['revision']
        doc = projects.clear_canvas(ident, before_clear)
        self.assertEqual(len(doc['state']['layers']), 1)
        self.assertEqual(len(doc['assets']), 2)
        doc = ws.move_history(ident, doc['revision'], -1)
        self.assertEqual(doc['revision'], before_clear)
        path = projects.archive(ident, doc['revision'])
        backup = path.read_bytes()
        self.assertEqual(ws.public(ws.load(ident))['revision'], before_clear)
        with patch.object(ws, 'ROOT', Path(self.temp.name) / 'another-computer'):
            restored = projects.import_archive(backup)
            self.assertNotEqual(restored['id'], ident)
            self.assertEqual(restored['name'], 'Card layout')
            self.assertEqual(restored['state'], doc['state'])
            self.assertEqual(len(restored['history']), len(doc['history']))
            for asset in restored['assets']:
                self.assertEqual(
                    (ws.folder_for(restored['id']) / 'assets' / asset['file']).read_bytes(),
                    barcode if asset['name'] == 'barcode.png' else card,
                )

    def test_import_failure_stale_revision_and_old_cache_migration(self):
        doc = ws.create(width=50, height=40)
        ident, revision = doc['id'], doc['revision']
        with self.assertRaises(ValueError):
            projects.import_assets(ident, revision, [('ok.png', png((10, 10), 'red')), ('bad.png', b'bad')])
        self.assertEqual(list((ws.folder_for(ident) / 'assets').glob('*')), [])
        self.assertEqual(ws.load(ident)['assets'], [])
        changed = projects.clear_canvas(ident, revision)
        with self.assertRaises(ValueError):
            projects.import_assets(ident, revision, [('x.png', png((10, 10), 'red'))])
        old = ws.LEGACY_ROOT / ident
        old.parent.mkdir(parents=True)
        shutil.move(str(ws.folder_for(ident)), old)
        reopened = ws.public(ws.load(ident))
        self.assertEqual(reopened['revision'], changed['revision'])
        self.assertTrue(old.is_dir())
        self.assertTrue(ws.folder_for(ident).is_dir())

    def test_portable_api_cleans_temporary_export_and_rejects_unexpected_files(self):
        doc = ws.create(width=50, height=40)
        response = TestClient(app).get(
            f'/api/photocraft/workspaces/{doc["id"]}/project', params={'revision': doc['revision']}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(list(ws.folder_for(doc['id']).glob('*.istudio')), [])
        output = io.BytesIO(response.content)
        with zipfile.ZipFile(output, 'a') as archive:
            archive.writestr('../escape.txt', 'unexpected')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            projects.import_archive(output.getvalue())
        self.assertFalse((ws.ROOT / 'escape.txt').exists())

    def test_assistant_applies_in_one_action_but_questions_leave_document_unchanged(self):
        doc = ws.create(width=50, height=40)
        client = TestClient(app)

        def submit(run):
            result = {}
            run(lambda *a, **k: None, lambda **values: result.update(values))
            return result

        plan = dict(unresolved=['Which layer?'], steps=[], prompt='Hide background')
        path = f'/api/photocraft/workspaces/{doc["id"]}/assistant'
        body = dict(revision=doc['revision'], prompt=plan['prompt'])
        with (
            patch.object(api, 'submit', side_effect=submit),
            patch.object(ws, 'smart_plan', return_value=plan),
        ):
            result = client.post(path, json=body)
        self.assertIn('plan', result.json())
        self.assertEqual(ws.public(ws.load(doc['id']))['revision'], doc['revision'])
        plan = dict(
            unresolved=[],
            steps=[dict(command='layer.setVisible', params=dict(visible=False))],
            prompt='Hide background',
        )
        # Exercise routing with a controlled planner; actual engine execution is covered above and in workspace tests.
        with (
            patch.object(api, 'submit', side_effect=submit),
            patch.object(ws, 'smart_plan', return_value=plan),
            patch.object(ws, 'apply', return_value=doc) as apply,
        ):
            result = client.post(path, json=body)
        self.assertIn('workspace', result.json())
        self.assertEqual(apply.call_args.args[2], plan['steps'])


class AcknowledgingKrita(bridge.Link):
    """Transport stand-in; native Krita behavior is tested separately in tests/krita."""

    def __init__(self):
        super().__init__()
        self.krita_seen = time.monotonic()
        self.capabilities = {'projects': True}
        self.failure = None

    def send(self, kind, **payload):
        ident = super().send(kind, **payload)
        path = Path(payload['path'])
        if not self.failure:
            if kind in {'project_new', 'project_clear'}:
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('mimetype', 'application/x-krita')
                    archive.writestr('maindoc.xml', '<DOC/>')
                    archive.writestr('layers', 'original' if kind == 'project_new' else 'clear')
            elif kind in {'project_restore', 'project_canvas'}:
                shutil.copy2(payload['source'], path)
        self.event(
            dict(
                run=ident, kind='failed' if self.failure else 'done', text=self.failure, width=300, height=200
            )
        )
        return ident


class KritaProjects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.link = AcknowledgingKrita()
        for target, key, value in [(krita, 'ROOT', Path(self.temp.name)), (bridge, 'link', self.link)]:
            change = patch.object(target, key, value)
            change.start()
            self.addCleanup(change.stop)

    def test_sources_do_not_queue_placement_clear_restore_keeps_both_canvases_and_backup_reopens(self):
        project = krita.create('Krita composition', 300, 200)
        ident = project['id']
        self.link.commands.clear()
        project = krita.import_assets(ident, [('logo.png', png((30, 20), '#ff000080'))])
        self.assertEqual(self.link.commands, [])
        project = krita.place_asset(ident, project['assets'][0]['id'])
        self.assertEqual(self.link.commands[-1]['kind'], 'project_place')
        self.assertFalse(self.link.commands[-1]['fit'])
        original = (krita.folder_for(ident) / 'project.kra').read_bytes()
        project = krita.action(ident, 'clear')
        clear = (krita.folder_for(ident) / 'project.kra').read_bytes()
        self.assertNotEqual(original, clear)
        project = krita.action(ident, 'restore')
        self.assertEqual((krita.folder_for(ident) / 'project.kra').read_bytes(), original)
        self.assertEqual(len(project['checkpoints']), 2)
        project = krita.action(ident, 'restore')
        self.assertEqual((krita.folder_for(ident) / 'project.kra').read_bytes(), clear)
        backup = krita.archive(ident).read_bytes()
        restored = krita.import_archive(backup)
        self.assertNotEqual(restored['id'], ident)
        self.assertEqual(restored['assets'][0]['name'], 'logo.png')
        self.assertEqual(len(restored['checkpoints']), 3)
        self.assertEqual(self.link.commands[-1]['kind'], 'project_open')

    def test_no_success_without_save_acknowledgement_and_stale_editor_is_identified(self):
        project = krita.create('Krita test')
        ident = project['id']
        metadata = (krita.folder_for(ident) / 'project.json').read_bytes()
        self.link.failure = 'Disk full: project remains open.'
        with self.assertRaisesRegex(ValueError, 'Disk full'):
            krita.action(ident, 'close')
        self.assertEqual((krita.folder_for(ident) / 'project.json').read_bytes(), metadata)
        with patch.object(bridge, 'link', bridge.Link()):
            bridge.link.krita_seen = time.monotonic()
            bridge.link.capabilities = {'projects': True}
            with self.assertRaisesRegex(ValueError, 'not confirmed'):
                krita.send('project_save', timeout=0.01, path='unused')
        state = dict(path=str(krita.folder_for(ident) / 'project.kra'), modified=True, save_error='Disk full')
        self.assertFalse(krita.current(state)['saved'])
        self.assertEqual(krita.current(state)['save_error'], 'Disk full')
        self.assertIsNone(krita.current(dict(path=str(Path(self.temp.name) / 'elsewhere.kra'))))

    def test_project_dimensions_rejected_before_engine_or_krita_allocation(self):
        for path in ['/api/krita/projects', '/api/photocraft/workspaces']:
            result = TestClient(app).post(path, json=dict(name='Too big', width=8192, height=8192))
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.link.commands, [])

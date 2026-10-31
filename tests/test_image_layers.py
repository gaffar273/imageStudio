"""Regression coverage for adding overlays without replacing an editor's background."""

import asyncio
import io
import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from starlette.datastructures import UploadFile

from image_studio.api import photocraft as craft_routes, routes
from image_studio.api.app import app
from image_studio.integrations import photocraft, photocraft_workspace as ws
from image_studio.integrations.bridge import Link
from image_studio.services import image_imports


def png(size=(40, 20), color=(255, 0, 0, 128)):
    buffer = io.BytesIO()
    Image.new('RGBA', size, color).save(buffer, 'PNG')
    return buffer.getvalue()


class UploadTests(unittest.TestCase):
    def test_limits_close_all_files_and_reject_empty_batches(self):
        for count in (0, 17):
            files = [UploadFile(io.BytesIO(b'a'), filename='a.png') for _ in range(count)]
            with self.assertRaises(ValueError):
                asyncio.run(image_imports.read_files(files))
            self.assertTrue(all(file.file.closed for file in files))
        files = [UploadFile(io.BytesIO(b'1234')), UploadFile(io.BytesIO(b'56'))]
        with patch.object(image_imports, 'MAX_BYTES', 5), self.assertRaises(ValueError):
            asyncio.run(image_imports.read_files(files))
        self.assertTrue(all(file.file.closed for file in files))

    def test_layer_orientation_and_alpha(self):
        with Image.open(io.BytesIO(png())) as source:
            exif = source.getexif()
            exif[274] = 6
            output = io.BytesIO()
            source.save(output, 'PNG', exif=exif)
        image = image_imports.decode_layer(output.getvalue())
        self.assertEqual(image.size, (20, 40))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 128))


@unittest.skipUnless(photocraft.available(), 'PhotoCraft CLI not installed')
class PhotoCraftLayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(ws, 'ROOT', Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)
        self.document = ws.create(width=100, height=80)

    def test_batch_keeps_background_transparency_order_undo_and_layered_export(self):
        original = self.document
        files = [('Red overlay.png', png()), ('Blue corner.png', png((10, 10), (0, 0, 255, 255)))]
        result = ws.add_layers(original['id'], original['revision'], files)
        self.assertEqual(result['id'], original['id'])
        self.assertEqual((result['state']['width'], result['state']['height']), (100, 80))
        self.assertEqual(
            [layer['name'] for layer in result['state']['layers']],
            ['Blue corner', 'Red overlay', 'Background'],
        )
        self.assertEqual(result['state']['layers'][-1]['id'], original['state']['layers'][0]['id'])
        self.assertEqual(len(result['history']), 2)
        with Image.open(ws.folder_for(result['id']) / f'{result["revision"]}.png') as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 255))
            self.assertEqual(image.getpixel((35, 35)), (255, 127, 127, 255))
            self.assertEqual(image.getpixel((50, 40)), (0, 0, 255, 255))
        undo = ws.move_history(result['id'], result['revision'], -1)
        self.assertEqual(undo['revision'], original['revision'])
        redo = ws.move_history(undo['id'], undo['revision'], 1)
        self.assertEqual(redo['revision'], result['revision'])
        exported = ws.export(result['id'], result['revision'], 'psd')
        reopened = ws.create(exported.read_bytes(), 'layers.psd')
        self.assertEqual(len(reopened['state']['layers']), 3)

    def test_fits_large_overlay_and_move_resize_does_not_touch_background(self):
        result = ws.add_layers(self.document['id'], self.document['revision'], [('wide.png', png((400, 80)))])
        layer = result['state']['layers'][0]
        self.assertEqual(layer['bounds'], [0, 30, 100, 20])
        moved = ws.apply(
            result['id'],
            result['revision'],
            [
                dict(
                    command='edit.transform',
                    params=dict(layer=layer['id'], dx=10, dy=-5, scaleX=50, scaleY=50),
                )
            ],
            'Placement',
            lambda *a, **k: None,
            None,
        )
        self.assertEqual(moved['state']['layers'][0]['bounds'], [35, 30, 50, 10])
        self.assertEqual(moved['state']['layers'][-1]['bounds'], [0, 0, 100, 80])

    def test_bad_batch_stale_revision_and_cancel_preserve_history(self):
        original = self.document
        for files in ([], [('good.png', png()), ('bad.png', b'bad')]):
            with self.assertRaises(ValueError):
                ws.add_layers(original['id'], original['revision'], files)
            self.assertEqual(ws.public(ws.load(original['id']))['revision'], original['revision'])
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(ws.Cancelled):
            ws.add_layers(original['id'], original['revision'], [('a.png', png())], cancelled)
        result = ws.add_layers(original['id'], original['revision'], [('a.png', png())])
        with self.assertRaisesRegex(ValueError, 'document changed'):
            ws.add_layers(original['id'], original['revision'], [('b.png', png())])
        self.assertEqual(ws.public(ws.load(original['id']))['revision'], result['revision'])

    def test_open_multiple_and_api_add_use_one_workspace(self):
        client = TestClient(app)

        def submit(run):
            result = {}
            run(lambda *a, **k: None, lambda **values: result.update(values))
            return result

        with patch.object(craft_routes, 'submit', side_effect=submit):
            opened = client.post(
                '/api/photocraft/workspaces/import',
                files=[
                    ('file', ('background.png', png((100, 80), (255, 255, 255, 255)))),
                    ('files', ('overlay.png', png())),
                ],
            )
            self.assertEqual(opened.status_code, 202, opened.text)
            document = opened.json()['workspace']
            self.assertEqual(len(document['state']['layers']), 2)
            result = client.post(
                f'/api/photocraft/workspaces/{document["id"]}/layers',
                params={'revision': document['revision']},
                files=[('files', ('another.png', png()))],
            )
            self.assertEqual(result.status_code, 202, result.text)
            self.assertEqual(result.json()['workspace']['id'], document['id'])
            self.assertEqual(len(result.json()['workspace']['state']['layers']), 3)
            stale = client.post(
                f'/api/photocraft/workspaces/{document["id"]}/layers',
                params={'revision': document['revision']},
                files=[('files', ('another.png', png()))],
            )
            self.assertEqual(stale.status_code, 422)


class KritaLayerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.link = Link()
        self.link.krita_seen = time.monotonic()
        self.link.state = dict(name='background.png', path='background.png', image_layers=True)
        link = patch.object(routes.bridge, 'link', self.link)
        link.start()
        self.addCleanup(link.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        cache = patch.object(routes, 'CACHE', Path(self.temp.name))
        cache.start()
        self.addCleanup(cache.stop)

    def test_batch_queues_placement_with_original_names_and_alpha(self):
        response = self.client.post(
            '/api/krita/layers',
            files=[
                ('files', ('foreground.png', png())),
                ('files', ('logo.png', png((10, 10)))),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.link.commands), 1)
        command = self.link.commands[0]
        self.assertEqual(command['kind'], 'place')
        self.assertEqual([image['name'] for image in command['images']], ['foreground', 'logo'])
        self.assertEqual(command['document'], dict(name='background.png', path='background.png'))
        with Image.open(command['images'][0]['path']) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 128))

    def test_invalid_batch_cleans_up_and_never_queues_partial_import(self):
        response = self.client.post(
            '/api/krita/layers',
            files=[
                ('files', ('valid.png', png())),
                ('files', ('broken.png', b'bad')),
            ],
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.link.commands, [])
        self.assertEqual(list(Path(self.temp.name).rglob('*.png')), [])

    def test_requires_current_document_and_updated_panel(self):
        for state in (None, dict(name='old-plugin.png')):
            self.link.state = state
            response = self.client.post('/api/krita/layers', files={'files': ('a.png', png())})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.link.commands, [])


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'PySide6 is not installed')
class DesktopLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_desktop import desktop

        cls.app, cls.window = desktop()

    def test_photocraft_drop_uploads_every_file_into_existing_revision(self):
        from PySide6.QtCore import QMimeData, QUrl
        from types import SimpleNamespace
        from test_desktop import PHOTOCRAFT_CAPABILITIES, craft_document

        page = self.window.photocraft
        page.active, page.pending, page.job, page.ready = None, False, None, True
        page.got_capabilities(PHOTOCRAFT_CAPABILITIES)
        document = craft_document()
        with patch.object(page.client, 'bytes'), patch.object(page.client, 'post'):
            page.show_document(document)
        self.assertTrue(page.add_images.isEnabled())
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ['foreground.png', 'logo.png']]
            for path in paths:
                path.write_bytes(png())
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
            accepted = []
            event = SimpleNamespace(mimeData=lambda: mime, acceptProposedAction=lambda: accepted.append(True))
            with patch.object(page.client, 'upload_files') as upload:
                page.dropEvent(event)
                self.assertEqual(
                    upload.call_args.args[0],
                    f'/api/photocraft/workspaces/{document["id"]}/layers?revision={document["revision"]}',
                )
                self.assertEqual(
                    [file[0] for file in upload.call_args.args[1]], ['foreground.png', 'logo.png']
                )
                self.assertEqual(accepted, [True])
                self.assertTrue(page.busy)
                self.assertFalse(page.add_images.isEnabled())
                upload.call_args.args[3]('Upload failed')
            self.assertFalse(page.busy)
            self.assertEqual(page.document, document)

    def test_krita_drop_adds_layers_and_keeps_current_canvas(self):
        from PySide6.QtCore import QMimeData, QUrl
        from test_desktop import CONFIG, KRITA_DOCUMENT

        page = self.window.krita
        page.poller.stop()
        page.ready, page.lost, page.sending = True, False, False
        page.configured(dict(CONFIG, krita=True))
        with patch.object(page.client, 'bytes'):
            page.got_state(
                dict(connected=True, state=KRITA_DOCUMENT, events=[], preview=False, preview_version=0)
            )
        self.assertTrue(page.add_images.isEnabled())
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ['foreground.png', 'logo.png']]
            for path in paths:
                path.write_bytes(png())
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
            with (
                patch.object(page.client, 'upload_files') as upload,
                patch.object(page.client, 'post') as replace,
            ):
                self.assertTrue(page.take(mime))
                replace.assert_not_called()
                self.assertEqual(upload.call_args.args[0], '/api/krita/layers')
                self.assertEqual(
                    [file[0] for file in upload.call_args.args[1]], ['foreground.png', 'logo.png']
                )
                self.assertTrue(page.sending)
                upload.call_args.args[3]('Upload failed')
            self.assertFalse(page.sending)
            self.assertEqual(page.document, KRITA_DOCUMENT)

    def test_photocraft_selected_layer_placement_controls(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QDialog, QDoubleSpinBox
        from test_desktop import craft_document

        page = self.window.photocraft
        page.active, page.pending, page.job, page.ready = None, False, None, True
        with patch.object(page.client, 'bytes'), patch.object(page.client, 'post'):
            page.show_document(craft_document())

        def fill():
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            for field, value in zip(dialog.findChildren(QDoubleSpinBox), (20, -10, 50)):
                field.setValue(value)
            dialog.accept()

        QTimer.singleShot(0, fill)
        with patch.object(page, 'commands') as commands:
            page.inspector.transform_layer()
        step = commands.call_args.args[0][0]
        self.assertEqual(step['command'], 'edit.transform')
        self.assertEqual(step['params'], dict(layer=2, dx=20, dy=-10, scaleX=50, scaleY=50))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt is not installed')
class KritaPlacementTests(unittest.TestCase):
    def test_plugin_fits_centers_and_preserves_transparency_and_existing_layers(self):
        from types import ModuleType, SimpleNamespace
        from PySide6 import QtCore, QtGui

        # Run the plugin's placement code with real Qt images and a small stand-in for Krita's document.
        package = ModuleType('studio_test_krita')
        qt = ModuleType('studio_test_krita.qt')
        for name in ['QByteArray', 'QPointF', 'Qt']:
            setattr(qt, name, getattr(QtCore, name))
        for name in ['QColor', 'QImage', 'QPainter', 'QRadialGradient']:
            setattr(qt, name, getattr(QtGui, name))
        qt.ARGB32 = QtGui.QImage.Format.Format_ARGB32
        qt.GRAY8 = QtGui.QImage.Format.Format_Grayscale8
        qt.raw_bytes = lambda image: bytes(image.constBits())
        qt.scaled_exact = lambda image, w, h: image.scaled(w, h)
        qt.scoped = lambda cls, enum, name: getattr(getattr(cls, enum), name)
        krita = ModuleType('krita')
        krita.Krita, krita.Selection = object, object
        path = Path(__file__).resolve().parents[1] / 'integrations/krita-plugin/ai_prompt/ops.py'
        spec = importlib.util.spec_from_file_location('studio_test_krita.ops', path)
        ops = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules, {'studio_test_krita': package, 'studio_test_krita.qt': qt, 'krita': krita}
        ):
            spec.loader.exec_module(ops)
        background = object()
        children = [background]
        root = SimpleNamespace(
            childNodes=lambda: list(children), addChildNode=lambda node, above: children.append(node)
        )
        doc = SimpleNamespace(width=lambda: 100, height=lambda: 80, rootNode=lambda: root)
        def make(doc, name, image, x, y):
            return SimpleNamespace(name=name, image=image, x=x, y=y)
        with tempfile.TemporaryDirectory() as folder:
            wide, logo = Path(folder) / 'wide.png', Path(folder) / 'logo.png'
            wide.write_bytes(png((400, 80)))
            logo.write_bytes(png((10, 10)))
            with (
                patch.object(ops, 'pixel_node', side_effect=make),
                patch.object(ops, 'active_node', return_value=background),
                patch.object(ops, 'activate'),
                patch.object(ops, 'settle'),
            ):
                added = ops.place_images(
                    doc, [dict(path=str(wide), name='Wide'), dict(path=str(logo), name='Logo')]
                )
                self.assertIs(children[0], background)
                self.assertEqual([node.name for node in children[1:]], ['Wide', 'Logo'])
                self.assertEqual(
                    (added[0].x, added[0].y, added[0].image.width(), added[0].image.height()),
                    (0, 30, 100, 20),
                )
                self.assertEqual((added[1].x, added[1].y), (45, 35))
                self.assertEqual(added[0].image.pixelColor(0, 0).alpha(), 128)
                invalid = Path(folder) / 'bad.png'
                invalid.write_bytes(b'bad')
                with self.assertRaises(ops.StepError):
                    ops.place_images(
                        doc, [dict(path=str(logo), name='Valid'), dict(path=str(invalid), name='Bad')]
                    )
                self.assertEqual(len(children), 3)

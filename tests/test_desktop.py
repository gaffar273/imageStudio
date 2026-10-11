"""Desktop app foundations: folders, hardware verdicts, engine endpoints and the Library screen."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from image_studio.api.app import app
from image_studio.core import hardware, paths
from image_studio.services import assistant, workflows
from image_studio.services.jobs import store
from image_studio.services.runtime import render_session


def card(name, vendor, memory, integrated=False):
    return dict(name=name, vendor=vendor, vram_gb=memory, used_gb=None, load=None, driver=None,
                integrated=integrated)


class FolderTests(unittest.TestCase):
    def test_environment_beats_settings_beats_default(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            default = Path(folder) / 'default'
            with patch.object(paths, 'SETTINGS_FILE', settings), patch.dict(os.environ, {}, clear=False):
                os.environ.pop('IMAGE_STUDIO_WORK', None)
                self.assertEqual(paths.chosen('IMAGE_STUDIO_WORK', 'models_dir', default), default)
                paths.save_settings(models_dir=str(Path(folder) / 'chosen'), port=7861)
                self.assertEqual(
                    paths.chosen('IMAGE_STUDIO_WORK', 'models_dir', default), (Path(folder) / 'chosen').resolve()
                )
                os.environ['IMAGE_STUDIO_WORK'] = str(Path(folder) / 'from-env')
                self.assertEqual(
                    paths.chosen('IMAGE_STUDIO_WORK', 'models_dir', default), (Path(folder) / 'from-env').resolve()
                )
                os.environ.pop('IMAGE_STUDIO_WORK')
                self.assertEqual(paths.save_settings(models_dir=None), {'port': 7861})

    def test_broken_settings_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.json'
            settings.write_text('{not json', encoding='utf-8')
            with patch.object(paths, 'SETTINGS_FILE', settings):
                self.assertEqual(paths.load_settings(), {})

    def test_per_user_folders_are_outside_the_install(self):
        for folder in (paths.config_dir(), paths.data_dir()):
            self.assertFalse(folder.is_relative_to(paths.ROOT))


class HardwareTests(unittest.TestCase):
    def test_tiers_follow_nvidia_video_memory(self):
        cases = [
            ([card('RTX 4090', 'NVIDIA', 24.0)], 'great'),
            ([card('RTX 4060 Laptop GPU', 'NVIDIA', 8.0), card('Radeon 780M', 'AMD', 0.5, True)], 'good'),
            ([card('RTX 3050', 'NVIDIA', 6.0)], 'limited'),
            ([card('GTX 1650', 'NVIDIA', 4.0)], 'cloud'),
            ([card('Radeon RX 7900 XTX', 'AMD', 24.0)], 'cloud'),
            ([card('Intel UHD Graphics', 'Intel', None, True)], 'cloud'),
            ([], 'cloud'),
        ]
        for cards, tier in cases:
            with self.subTest(cards=[item['name'] for item in cards]):
                self.assertEqual(hardware.verdict(cards)[0], tier)

    def test_the_biggest_nvidia_card_decides(self):
        tier, text = hardware.verdict([card('RTX 3050', 'NVIDIA', 6.0), card('RTX 3090', 'NVIDIA', 24.0)])
        self.assertEqual(tier, 'great')
        self.assertIn('RTX 3090', text)

    def test_other_cards_are_listed_and_integrated_ones_marked(self):
        system = [
            ('NVIDIA GeForce RTX 4060 Laptop GPU', 'NVIDIA', 8.0),
            ('AMD Radeon 780M Graphics', 'AMD', 0.5),
            ('Intel(R) Arc(TM) A770', 'Intel', 16.0),
            ('Intel(R) UHD Graphics 770', 'Intel', 0.1),
        ]
        live = [card('NVIDIA GeForce RTX 4060 Laptop GPU', 'NVIDIA', 8.0)]
        with patch.object(hardware, 'nvidia', return_value=live), patch.object(
            hardware, 'system_adapters', return_value=system
        ):
            cards = hardware.graphics()
        self.assertEqual(cards[0]['name'], 'NVIDIA GeForce RTX 4060 Laptop GPU')
        self.assertEqual(len(cards), 4)  # NVIDIA listed once, from the live tool
        integrated = {item['name']: item['integrated'] for item in cards}
        self.assertTrue(integrated['AMD Radeon 780M Graphics'])
        self.assertFalse(integrated['Intel(R) Arc(TM) A770'])
        self.assertTrue(integrated['Intel(R) UHD Graphics 770'])

    def test_summary_reads_this_machine(self):
        summary = hardware.summary()
        self.assertIn(summary['tier'], {'great', 'good', 'limited', 'cloud'})
        self.assertGreater(summary['ram_gb'], 0)
        self.assertTrue(summary['cpu'])


class EngineEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_system_reports_the_folders_in_use(self):
        answer = self.client.get('/api/system').json()
        self.assertEqual(Path(answer['library_dir']), paths.IMAGES)
        self.assertEqual(Path(answer['models_dir']), paths.WORK)

    def test_pages_from_the_engine_itself_may_post_on_any_port(self):
        with patch.object(workflows.engine, 'unload'), patch.object(assistant, 'release'):
            own = {'host': '127.0.0.1:54321', 'origin': 'http://127.0.0.1:54321'}
            self.assertEqual(self.client.post('/api/system/release', headers=own).status_code, 200)
            for origin in ('http://evil.example', 'http://127.0.0.1:54322', 'http://evil.example:54321'):
                with self.subTest(origin=origin):
                    headers = {'host': '127.0.0.1:54321', 'origin': origin}
                    self.assertEqual(self.client.post('/api/system/release', headers=headers).status_code, 403)

    def test_release_unloads_models_but_never_during_a_job(self):
        with patch.object(workflows.engine, 'unload') as unload, patch.object(assistant, 'release') as release:
            self.assertEqual(self.client.post('/api/system/release').status_code, 200)
            unload.assert_called_once()
            release.assert_called_once()
            self.assertTrue(render_session.acquire(blocking=False))  # handed back afterwards
            try:
                self.assertEqual(self.client.post('/api/system/release').status_code, 409)
            finally:
                render_session.release()
            with patch.object(store, 'active', 'job'):
                self.assertEqual(self.client.post('/api/system/release').status_code, 409)
            self.assertEqual(unload.call_count, 1)


HAS_QT = __import__('importlib').util.find_spec('PySide6') is not None
_desktop = []


def desktop():
    """The app and its window, built once: Qt allows one application per process."""
    if not _desktop:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from image_studio.desktop.app import build
        from PySide6.QtCore import QSettings

        app, window = build()
        window.settings = QSettings('Image Studio Tests', 'desktop')  # keep the real app's choices
        _desktop.extend([app, window])
    return _desktop


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class LibraryScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.window = desktop()

    @staticmethod
    def item(name, created, prompt='', request=''):
        return dict(name=name, created=created, url=f'/images/{name}', thumbnail='/none',
                    metadata=dict(prompt=prompt, request=request))

    def test_search_favorites_and_sorting(self):
        page = self.window.library
        page.all = [
            self.item('a.png', 1, prompt='A red fox in snow'),
            self.item('b.png', 3, prompt='city at night', request='Neon street in the rain'),
            self.item('c.png', 2, prompt='a red barn'),
        ]
        page.model.favorites = {'c.png'}
        page.apply()
        self.assertEqual([item['name'] for item in page.model.items], ['b.png', 'c.png', 'a.png'])
        page.search.setText('RED')
        self.assertEqual({item['name'] for item in page.model.items}, {'a.png', 'c.png'})
        page.search.setText('neon rain')  # every word, from the request too
        self.assertEqual([item['name'] for item in page.model.items], ['b.png'])
        page.search.setText('')
        page.favorites_only.setChecked(True)
        page.apply()
        self.assertEqual([item['name'] for item in page.model.items], ['c.png'])
        page.everything.setChecked(True)
        page.flip_sort()
        self.assertEqual([item['name'] for item in page.model.items], ['a.png', 'c.png', 'b.png'])
        page.flip_sort()

    def test_every_screen_has_a_page(self):
        from image_studio.desktop.app import FOOTER, SCREENS

        self.assertEqual(set(self.window.screens), {route for route, *_ in SCREENS + FOOTER})
        for route in self.window.screens:
            self.window.navigate(route)
            self.assertIs(self.window.pages.currentWidget(), self.window.screens[route])

    def test_a_failed_thumbnail_is_not_fetched_again(self):
        model = self.window.library.model
        entry = self.item('broken.png', 5)
        with patch.object(model.client, 'bytes') as fetch:
            self.assertIsNone(model.thumbnail(entry))
            model.loaded(model.key(entry), b'not an image')
            self.assertTrue(model.thumbnail(entry).isNull())
        fetch.assert_called_once()


CONFIG = dict(
    models=[dict(id='realistic', label='', ready=True), dict(id='accurate', label='', ready=True),
            dict(id='turbo', label='', ready=False)],
    sizes=[dict(id='Square', width=1024, height=1024), dict(id='Portrait', width=832, height=1216),
           dict(id='Landscape', width=1216, height=832), dict(id='Wide', width=1344, height=768),
           dict(id='Small', width=768, height=768)],
    negative_prompt='blurry', assistant=False, search=False, repair=True, references=True, lora=True,
    personal_lora=False, editing=False, active_job=None,
)


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class CreateSettingsTests(unittest.TestCase):
    def test_saved_settings_are_cleaned_and_limited_to_installed_parts(self):
        from image_studio.desktop.create import starting

        saved = dict(negative_prompt='', model='nope', size='Gone', steps=500, guidance='x', smart=True,
                     check=True, repair=True, seed='12a3', sketch='data:old', count=9, prompt='p' * 7000)
        settings = starting(CONFIG, saved)
        self.assertEqual(settings['negative_prompt'], '')  # a cleared list stays cleared
        self.assertEqual((settings['model'], settings['size']), ('realistic', 'Square'))
        self.assertEqual((settings['steps'], settings['guidance'], settings['count']), (50, 5.0, 4))
        self.assertEqual((settings['smart'], settings['check'], settings['repair']), (False, False, True))
        self.assertEqual(settings['seed'], '123')
        self.assertIsNone(settings['sketch'])
        self.assertEqual(len(settings['prompt']), 6000)
        self.assertEqual(starting(CONFIG, {})['negative_prompt'], 'blurry')

    def test_reusing_a_picture_restores_how_it_was_made(self):
        from image_studio.desktop.create import clean, reused

        meta = dict(request='A fox', prompt='A fox, detailed', seed=7, model='Tongyi/Z-Image-Turbo', width=1600,
                    height=1600, base_width=832, base_height=1216, steps=9, guidance=None, style='Natural photo',
                    finish='Film', detail_pass=dict(option='2× size', strength=0.5))
        settings = clean(reused(meta, CONFIG), CONFIG)
        self.assertEqual(settings['prompt'], 'A fox')
        self.assertEqual((settings['seed'], settings['model'], settings['size']), ('7', 'accurate', 'Portrait'))
        self.assertEqual((settings['steps'], settings['guidance']), (9, 5.0))
        self.assertEqual((settings['detail'], settings['detail_strength'], settings['photo_finish']),
                         ('2× size', 0.5, 'Film'))
        self.assertEqual(settings['negative_prompt'], 'blurry')

    def test_the_engine_accepts_what_the_form_sends(self):
        from image_studio.api.schemas import GenerateRequest
        from image_studio.desktop.create import request_body, starting

        settings = dict(starting(CONFIG, {}), prompt='A fox')
        self.assertIsNone(request_body(settings)['seed'])
        body = request_body(dict(settings, seed='42'))
        self.assertEqual(body['seed'], 42)
        GenerateRequest(**body)
        with self.assertRaises(ValueError):
            request_body(dict(settings, seed='4294967296'))


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class CreateScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.window = desktop()

    def setUp(self):
        from image_studio.desktop.create import DEFAULTS

        self.window.settings.clear()
        self.page = self.window.create
        self.page.config, self.page.job, self.page.active = None, None, None
        self.page.settings = dict(DEFAULTS)
        self.page.ready = True
        self.page.configured(dict(CONFIG))

    def reopen(self):
        """As when the app opens again: a fresh form filled from what was remembered."""
        from image_studio.desktop.create import DEFAULTS

        self.page.config, self.page.settings = None, dict(DEFAULTS)
        self.page.configured(dict(CONFIG))

    def test_form_follows_the_model(self):
        page = self.page
        self.assertEqual(page.negative.toPlainText(), 'blurry')
        page.model.setCurrentIndex(page.model.findData('accurate'))
        self.assertEqual((page.settings['model'], page.settings['steps']), ('accurate', 9))
        self.assertEqual((page.steps.minimum, page.steps.maximum), (6, 16))
        self.assertTrue(page.guidance.isHidden())
        self.assertFalse(page.combine.isHidden())
        page.model.setCurrentIndex(page.model.findData('turbo'))
        self.assertTrue(page.sketching.isHidden())
        page.prompt.setPlainText('A fox')
        self.assertFalse(page.go.isEnabled())  # turbo is not installed in this config
        self.assertEqual(page.hint.text(), 'This model is not installed yet.')
        page.model.setCurrentIndex(page.model.findData('realistic'))
        self.assertTrue(page.go.isEnabled())
        self.assertFalse(page.smart.isEnabled())  # no prompt assistant installed

    def test_the_form_is_remembered(self):
        page = self.page
        page.prompt.setPlainText('A lighthouse')
        page.aspects.button(1).click()
        page.negative.setPlainText('')
        self.assertEqual(page.settings['size'], 'Portrait')
        self.reopen()
        self.assertEqual(page.prompt.toPlainText(), 'A lighthouse')
        self.assertEqual(page.size.currentData(), 'Portrait')
        self.assertTrue(page.aspects.button(1).isChecked())
        self.assertEqual(page.negative.toPlainText(), '')  # once crashed the form when it was saved

    def test_a_render_from_start_to_finish(self):
        page = self.page
        page.prompt.setPlainText('A fox in snow')
        posted = []
        with patch.object(page.client, 'post', side_effect=lambda *args, **kwargs: posted.append(args)), \
                patch.object(page.client, 'get'), patch.object(page.client, 'bytes'):
            page.generate()
            path, body, started, _ = posted[0]
            self.assertEqual((path, body['prompt'], body['seed']), ('/api/generate', 'A fox in snow', None))
            self.assertTrue(page.busy)
            self.assertFalse(page.go.isEnabled())
            started(dict(id='j1', state='running', progress=0, message='Preparing', images=[]))
            self.assertEqual(page.active, 'j1')
            self.assertFalse(page.stop.isHidden())
            picture = dict(name='fox.png', url='/images/fox.png', thumbnail='/t', created=1, metadata={})
            with patch.object(page.library, 'refresh') as refresh:
                page.polled('j1', dict(id='j1', state='done', progress=1, message='Done', images=[picture],
                                       understood='A fox, in snow'))
            refresh.assert_called_once()
        self.assertIsNone(page.active)
        self.assertIs(page.canvas.currentWidget(), page.result)
        self.assertTrue(page.stop.isHidden())
        self.assertFalse(page.save.isHidden())
        self.assertFalse(page.notes.isHidden())
        self.assertTrue(page.go.isEnabled())

    def test_a_refused_render_frees_the_form(self):
        page = self.page
        page.prompt.setPlainText('A fox')
        with patch.object(page.client, 'post', side_effect=lambda path, body, done, failed, **_: failed('Busy')), \
                patch.object(page, 'notify') as notify:
            page.generate()
        notify.assert_called_once_with('Busy', error=True)
        self.assertFalse(page.busy)
        self.assertTrue(page.go.isEnabled())

    def test_losing_the_engine_mid_render_gives_up_after_retries(self):
        page = self.page
        with patch.object(page.client, 'get'), patch.object(page, 'notify'):
            page.follow('j2', 'generate')
            for _ in range(4):
                page.lost('j2', 'Connection refused')
            self.assertEqual(page.active, 'j2')
            page.lost('j2', 'Connection refused')
        self.assertIsNone(page.active)
        self.assertEqual(page.job['state'], 'error')

    def test_a_finished_sketch_becomes_the_guide_but_is_not_remembered(self):
        from image_studio.desktop.create import data_url
        from PySide6.QtGui import QColor, QImage

        page = self.page
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill(QColor('red'))
        with patch.object(page.client, 'get'), patch.object(page.library, 'refresh'), patch.object(page, 'notify'):
            page.follow('s1', 'sketch')
            self.assertIsNone(page.job)  # a sketch never replaces the picture on the canvas
            page.polled('s1', dict(id='s1', state='done', progress=1, message='ok', images=[],
                                   sketch=data_url(image)))
        self.assertTrue(page.settings['sketch'].startswith('data:image/png;base64,'))
        self.assertFalse(page.sketch_view.isHidden())
        self.assertIsNone(json.loads(self.window.settings.value('create/settings'))['sketch'])

    def test_long_prompts_are_cut_at_the_limit(self):
        self.page.prompt.setPlainText('x' * 6100)
        self.assertEqual(len(self.page.settings['prompt']), 6000)
        self.assertEqual(self.page.counter.text(), '6000/6000')

    def test_use_these_settings_from_the_library(self):
        item = dict(name='a.png', url='/images/a.png', thumbnail='/t', created=1,
                    metadata=dict(prompt='A barn', seed=5, model='RealVisXL', width=768, height=768, steps=25))
        with patch.object(self.window, 'notify'):
            self.window.reuse(item)
        self.assertIs(self.window.pages.currentWidget(), self.page)
        self.assertEqual(self.page.prompt.toPlainText(), 'A barn')
        self.assertEqual((self.page.seed.text(), self.page.size.currentData()), ('5', 'Small'))
        self.assertEqual(self.page.steps.value(), 25)


EDIT_CONFIG = dict(CONFIG, editing=True, photocraft=True)


def png(width, height, color='red'):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return image, bytes(buffer.data().data())


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class EditRulesTests(unittest.TestCase):
    def test_the_tool_follows_what_is_installed(self):
        from image_studio.desktop.edit import choose_engine

        self.assertEqual(choose_engine(EDIT_CONFIG, None), 'photocraft')
        self.assertEqual(choose_engine(EDIT_CONFIG, 'kontext'), 'kontext')
        self.assertEqual(choose_engine(dict(EDIT_CONFIG, photocraft=False), 'photocraft'), 'kontext')

    def test_the_mask_is_the_painted_area_at_the_photos_size(self):
        from PySide6.QtCore import QPointF, QSize
        from image_studio.desktop.edit import render_mask

        mask = render_mask(QSize(300, 200), [(20, [QPointF(50, 50), QPointF(150, 50)]), (10, [QPointF(250, 150)])])
        self.assertEqual((mask.width(), mask.height()), (300, 200))
        self.assertEqual(mask.pixelColor(100, 50).value(), 255)  # along the stroke
        self.assertEqual(mask.pixelColor(250, 150).value(), 255)  # a single click leaves a dot
        self.assertEqual(mask.pixelColor(100, 120).value(), 0)

    def test_the_engine_accepts_what_the_form_sends(self):
        from image_studio.api.schemas import EditRequest
        from image_studio.desktop.edit import edit_body

        body = edit_body('/images/a.png', 'kontext', 'Make it golden hour', True, 'data:image/png;base64,AA==')
        self.assertEqual((body['smart'], body['mask']), (True, 'data:image/png;base64,AA=='))
        EditRequest(**body)
        body = edit_body('/images/a.png', 'photocraft', 'Warm portrait', True, 'data:image/png;base64,AA==')
        self.assertEqual((body['smart'], body['mask']), (False, None))  # PhotoCraft changes the whole photo
        EditRequest(**body)


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class EditScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.window = desktop()

    def setUp(self):
        self.window.settings.clear()
        self.page = self.window.edit
        self.page.config, self.page.job, self.page.active, self.page.submitting = None, None, None, False
        self.page.set_source(None)
        self.page.prompt.clear()
        self.page.ready = True
        self.page.configured(dict(EDIT_CONFIG))

    def with_photo(self, width=400, height=200):
        from PySide6.QtGui import QPixmap

        image, _ = png(width, height)
        self.page.set_source(dict(ref=None, name='photo.png', image=image))
        self.assertIs(self.page.stage.currentWidget(), self.page.canvas)
        return QPixmap.fromImage(image)

    def paint(self, *points):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        canvas = self.page.canvas
        canvas.resize(440, 240)  # the photo fills 400 × 200 of it: one screen pixel per photo pixel
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(*points[0]))
        for point in points[1:]:
            QTest.mouseMove(canvas, QPoint(*point))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(*points[-1]))

    def test_starts_with_photocraft_and_a_drop_target(self):
        page = self.page
        self.assertEqual(page.tool.currentData(), 'photocraft')
        self.assertEqual(page.stage.currentIndex(), 0)
        self.assertTrue(page.brush.isHidden())  # PhotoCraft has no painted area
        self.assertFalse(page.go.isEnabled())
        self.assertEqual(page.hint.text(), 'Add a photo to begin.')

    def test_painting_an_area_and_switching_tools(self):
        page = self.page
        page.tool.setCurrentIndex(page.tool.findData('kontext'))
        self.assertFalse(page.brush.isHidden())
        self.with_photo()
        page.brush.setChecked(True)
        page.brush_size.slider.setValue(30 - 5)  # as when the slider is dragged
        self.assertFalse(page.brush_tools.isHidden())
        self.paint((70, 70), (120, 70), (170, 70))
        self.assertEqual(len(page.canvas.strokes), 1)
        width, points = page.canvas.strokes[0]
        self.assertAlmostEqual(width, 30, places=3)
        self.assertAlmostEqual(points[0].x(), 50, places=3)
        self.assertTrue(page.undo.isEnabled())
        page.canvas.undo()
        self.assertEqual(page.canvas.strokes, [])
        self.paint((70, 70))
        page.tool.setCurrentIndex(page.tool.findData('photocraft'))
        self.assertEqual(page.canvas.strokes, [])  # PhotoCraft lets the painted area go
        self.assertFalse(page.brush.isChecked())
        self.reopen()
        self.assertEqual(page.tool.currentData(), 'photocraft')
        self.assertEqual(page.brush_size.value(), 30)

    def reopen(self):
        self.page.config = None
        self.page.configured(dict(EDIT_CONFIG))

    def test_an_edit_from_start_to_finish(self):
        from image_studio.desktop.create import from_data_url

        page = self.page
        page.tool.setCurrentIndex(page.tool.findData('kontext'))
        self.with_photo()
        page.brush.setChecked(True)
        page.brush_size.slider.setValue(20 - 5)
        self.paint((70, 70), (170, 70))
        page.set_prompt('Make it golden hour')
        posted = []
        run_now = lambda work, done: done(work(), None)  # noqa: E731
        with patch('image_studio.desktop.edit.in_background', side_effect=run_now), \
                patch.object(page.client, 'post', side_effect=lambda *args, **kwargs: posted.append(args)), \
                patch.object(page.client, 'get'), patch.object(page.client, 'bytes'):
            page.apply()
            path, body, started, _ = posted[0]
            self.assertEqual((path, body['engine'], body['prompt']), ('/api/edit', 'kontext', 'Make it golden hour'))
            self.assertTrue(body['image'].startswith('data:image/png;base64,'))
            mask = from_data_url(body['mask'])
            self.assertEqual((mask.width(), mask.height()), (400, 200))
            self.assertEqual(mask.pixelColor(100, 50).value(), 255)
            self.assertFalse(page.go.isEnabled())
            started(dict(id='e1', state='running', progress=0, message='Editing 1 of 28', images=[]))
            self.assertEqual(page.active, 'e1')
            self.assertFalse(page.stop.isHidden())
            self.assertTrue(page.remove.isHidden() or not page.remove.isEnabled())
            picture = dict(name='edit.png', url='/images/edit.png', thumbnail='/t', created=1, metadata={})
            with patch.object(page.library, 'refresh') as refresh:
                page.polled('e1', dict(id='e1', state='done', progress=1, message='Saved', images=[picture],
                                       understood='Golden hour light'))
            refresh.assert_called_once()
        self.assertIs(page.stage.currentWidget(), page.result)
        self.assertFalse(page.actions.isHidden())
        self.assertTrue(page.psd.isHidden())  # only PhotoCraft edits have layers
        self.assertEqual(page.understood.text(), 'Golden hour light')
        page.compare.button(0).click()
        self.assertIs(page.stage.currentWidget(), page.canvas)
        page.compare.button(1).click()
        self.assertIs(page.stage.currentWidget(), page.result)
        self.assertTrue(page.go.isEnabled())

    def test_keep_editing_continues_from_the_result(self):
        page = self.page
        self.with_photo()
        layered = dict(name='photocraft_1.png', url='/images/photocraft_1.png', thumbnail='/t', created=1,
                       metadata=dict(layered_document='photocraft_1.psd'))
        page.follow('p1', dict(id='p1', state='running', progress=0, message='', images=[]))
        with patch.object(page.client, 'get'), patch.object(page.client, 'bytes'), \
                patch.object(page.library, 'refresh'):
            page.polled('p1', dict(id='p1', state='done', progress=1, message='ok', images=[layered]))
        self.assertFalse(page.psd.isHidden())
        self.assertFalse(page.open_psd.isHidden())
        fetched = []
        with patch.object(page.client, 'bytes', side_effect=lambda *args, **kwargs: fetched.append(args)):
            page.keep_editing()
        self.assertIsNone(page.job)
        self.assertEqual(page.source['ref'], '/images/photocraft_1.png')
        self.assertFalse(page.go.isEnabled())  # not until the full picture has arrived
        url, loaded, _ = fetched[0]
        self.assertEqual(url, '/images/photocraft_1.png')
        loaded(png(64, 32)[1])
        self.assertEqual(page.canvas.picture.width(), 64)
        page.set_prompt('Warm portrait')
        self.assertTrue(page.go.isEnabled())

    def test_a_late_picture_never_replaces_a_newer_choice(self):
        page = self.page
        fetched = []
        with patch.object(page.client, 'bytes', side_effect=lambda *args, **kwargs: fetched.append(args)):
            page.load_item(dict(name='old.png', url='/images/old.png', thumbnail='/t', created=1, metadata={}))
        self.with_photo(30, 30)
        fetched[0][1](png(500, 500)[1])
        self.assertEqual(page.canvas.picture.width(), 30)

    def test_a_refused_edit_frees_the_form(self):
        page = self.page
        self.with_photo()
        page.set_prompt('Warm portrait')
        run_now = lambda work, done: done(work(), None)  # noqa: E731
        with patch('image_studio.desktop.edit.in_background', side_effect=run_now), \
                patch.object(page.client, 'post', side_effect=lambda path, body, done, failed, **_: failed('Busy')), \
                patch.object(page, 'notify') as notify:
            page.apply()
        notify.assert_called_once_with('Busy', error=True)
        self.assertFalse(page.busy)
        self.assertTrue(page.go.isEnabled())

    def test_edit_image_from_the_library(self):
        item = dict(name='a.png', url='/images/a.png', thumbnail='/t', created=1, metadata={})
        with patch.object(self.page.client, 'bytes'):
            self.window.edit_picture(item)
        self.assertIs(self.window.pages.currentWidget(), self.page)
        self.assertEqual(self.page.source['ref'], '/images/a.png')


PHOTOCRAFT_CAPABILITIES = dict(
    installed=True, brain=True, marked_area=True, discovered=3, runnable=2,
    commands=[
        dict(id='filter.blur.gaussianBlur', label='Gaussian Blurâ€¦', menu=['Filter', 'Blur'],
             category='filter.blur', runnable=True, reason='',
             fields=[dict(name='radius', type='number', min=0.1, max=1000, integer=False, default=1)]),
        dict(id='layer.setProps', label='Layer Properties', menu=['Layer'], category='layer.setProps', runnable=True,
             reason='', fields=[dict(name='layer', type='layer', optional=True),
                                dict(name='extra', type='json', optional=True)]),
        dict(id='file.new', label='New…', menu=['File'], category='file.new', runnable=False,
             reason='Use the document controls.', fields=[]),
    ],
)


def craft_document(revision='a' * 32, cursor=1, history=2, **extra):
    layers = [
        dict(id=3, name='Warm Â· the shirt', kind='Adjustment', visible=True, opacity=1.0, blend='Normal',
             hasMask=True, adjustment={'Vibrance': {'vibrance': 12.5}}),
        dict(id=2, name='Title', kind='Type', visible=True, opacity=0.5, blend='Normal',
             text=dict(text='SUMMER', font='Inter', sizePt=48)),
        dict(id=1, name='Background', kind='Pixel', visible=False, opacity=1.0, blend='Normal',
             smartFilters=[dict(command='filter.blur.gaussianBlur', params={}, visible=True)]),
    ]
    entries = [dict(id=f'{index:032x}', label=f'Step {index}', created=1_790_000_000 + index,
                    checks=[dict(requirement=0, check='Warmer by 3', passed=True)] if index else [])
               for index in range(history)]
    entries[cursor]['id'] = revision
    return dict(id='w' * 32, name='portrait.jpg', revision=revision, cursor=cursor, history=entries,
                can_undo=cursor > 0, can_redo=cursor < history - 1,
                preview=f'/api/photocraft/workspaces/{"w" * 32}/preview/{revision}',
                original=f'/api/photocraft/workspaces/{"w" * 32}/preview/{entries[0]["id"]}',
                state=dict(width=400, height=200, mode='Rgb', depth=8, layers=layers, activeLayer=2,
                           hasSelection=False), **extra)


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class PhotoCraftRulesTests(unittest.TestCase):
    def test_panels_write_the_edit_language(self):
        from image_studio.desktop.photocraft_tools import adjust_edits, crop_edit, text_edit

        edits, title = adjust_edits({'exposure': 0.5, 'vignette': 20, 'contrast': -10, 'tint': 0}, 'sky')
        self.assertEqual([edit['action'] for edit in edits], ['exposure', 'vignette', 'contrast'])
        self.assertEqual(edits[2], dict(action='contrast', value=10, direction='decrease', target='sky',
                                        quote='contrast -10'))
        self.assertEqual(edits[1]['quote'], 'lighten the edges')
        self.assertEqual(title, 'Adjust: exposure +0.5, vignette +20, contrast -10')
        self.assertEqual(crop_edit('4:5', 'object', ' the car ')['target'], 'object')
        self.assertEqual(crop_edit('4:5', 'object', '  ')['target'], 'whole image')
        self.assertEqual(crop_edit('1:1', 'center')['position'], 'center')
        exact = text_edit(' Hi ', 'top', 'points', 72, '', 'serif', ['bold'])
        self.assertEqual((exact['text'], exact['size'], exact['value'], exact['choice']), ('Hi', '', 72, 'serif bold'))
        named = text_edit('Hi', 'top', 'large', 72, '#ffffff', '', [])
        self.assertEqual((named['size'], named['value'], named['color'], named['choice']), ('large', None, '#ffffff', ''))

    def test_photocrafts_misread_text_is_shown_as_meant(self):
        from image_studio.desktop.photocraft_tools import field_title, filter_name, plain, readable

        self.assertEqual(readable('Warm Â· the shirt'), 'Warm · the shirt')
        self.assertEqual(plain('Gaussian Blurâ€¦'), 'Gaussian Blur')
        self.assertEqual(readable('Ãx'), 'Ãx')  # not a misreading: left alone
        self.assertEqual(field_title('blendMode'), 'Blend Mode')
        self.assertEqual(filter_name('filter.blur.gaussianBlur'), 'Gaussian blur')

    def test_the_engine_accepts_what_the_panels_send(self):
        from image_studio.desktop.photocraft_tools import adjust_edits, crop_edit, text_edit
        from image_studio.integrations import photocraft_workspace as workspace

        edits = [*adjust_edits({'exposure': 0.5, 'saturation': -20}, 'whole image')[0], crop_edit('4:5', 'center'),
                 text_edit('SUMMER', 'top', 'large', 48, '', '', ['shadow'])]
        with tempfile.TemporaryDirectory() as folder, patch.object(workspace, 'ROOT', Path(folder)), \
                patch.object(workspace, 'validate_steps'):
            from PIL import Image

            data = dict(id='c' * 32, name='photo.png', cursor=0, updated=0,
                        history=[dict(id='d' * 32, label='Original', created=0, steps=[],
                                      state=dict(width=400, height=200, layers=[], activeLayer=None))])
            workspace.folder_for(data['id']).mkdir(parents=True)
            workspace.save(data)
            Image.new('RGB', (400, 200), 'gray').save(workspace.folder_for(data['id']) / f'{"d" * 32}.png')
            plan = workspace.manual_plan(data['id'], 'd' * 32, edits, 'Panels')
        self.assertEqual(plan['unresolved'], [])
        commands = ' '.join(step['command'] for step in plan['steps'])
        self.assertIn('image.crop', commands)
        self.assertIn('studio.text', commands)


class PhotoCraftEndpointTests(unittest.TestCase):
    def test_a_library_picture_opens_without_an_upload(self):
        from image_studio.api import photocraft as routes

        client = TestClient(app)
        with tempfile.TemporaryDirectory() as folder:
            plain_png = Path(folder) / 'a.png'
            plain_png.write_bytes(b'png')
            edited = Path(folder) / 'photocraft_b.png'
            edited.write_bytes(b'flat')
            edited.with_suffix('.psd').write_bytes(b'layers')
            opened = []
            ran = lambda run: run(lambda *a, **k: None, lambda **k: opened.append(k)) or {'id': 'j'}
            with patch.object(routes.library, 'image_path', side_effect=lambda name: Path(folder) / name), \
                    patch.object(routes.workspace, 'create', side_effect=lambda data, name, **_: (data, name)), \
                    patch.object(routes, 'submit', side_effect=ran):
                self.assertEqual(client.post('/api/photocraft/workspaces/from-library', json={'name': 'a.png'})
                                 .status_code, 202)
                client.post('/api/photocraft/workspaces/from-library', json={'name': 'photocraft_b.png'})
            self.assertEqual(opened[0]['workspace'], (b'png', 'a.png'))
            self.assertEqual(opened[1]['workspace'], (b'layers', 'photocraft_b.psd'))  # the layers come along
            missing = client.post('/api/photocraft/workspaces/from-library', json={'name': '../secret.png'})
            self.assertEqual(missing.status_code, 422)


@unittest.skipUnless(HAS_QT, 'PySide6 is not installed')
class PhotoCraftScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.window = desktop()

    def setUp(self):
        self.window.settings.clear()
        self.page = page = self.window.photocraft
        page.poller.stop()
        page.active, page.pending, page.job, page.plan_data, page.renders = None, False, None, None, {}
        page.ready = True
        page.compare.setChecked(False)
        page.set_area(False)
        with patch.object(page.client, 'bytes'):
            page.show_document(None)
        page.got_capabilities(dict(PHOTOCRAFT_CAPABILITIES))

    def open(self, document=None):
        fetched = []
        with patch.object(self.page.client, 'bytes', side_effect=lambda *args, **kwargs: fetched.append(args)):
            self.page.show_document(document or craft_document())
        for address, loaded, _ in fetched:
            loaded(png(400, 200, 'red' if 'preview/' + 'a' * 32 in address else 'blue')[1])
        return fetched

    def post(self, action):
        posted = []
        with patch.object(self.page.client, 'post', side_effect=lambda *args, **kwargs: posted.append(args)):
            action()
        return posted

    def test_starts_empty_and_opens_a_document(self):
        page = self.page
        self.assertEqual(page.stack.currentIndex(), 0)
        self.assertTrue(page.empty_open.isEnabled())
        self.assertTrue(page.export_button.isHidden())
        fetched = self.open()
        self.assertEqual(len(fetched), 2)  # the current version and the original
        self.assertEqual(page.stack.currentIndex(), 1)
        self.assertEqual(page.title.text(), 'portrait.jpg')
        self.assertIn('400 × 200 px', page.subtitle.text())
        self.assertIn('revision 2 of 2', page.subtitle.text())
        self.assertTrue(page.undo_button.isEnabled())
        self.assertFalse(page.redo_button.isEnabled())
        self.assertFalse(page.canvas.current.isNull())
        self.assertEqual(json.loads(self.window.settings.value('photocraft/settings'))['workspace'], 'w' * 32)

    def test_the_layers_and_history(self):
        from image_studio.desktop.photocraft import LayerRow

        page = self.page
        self.open()
        inspector = page.inspector
        rows = [inspector.layer_rows.itemAt(index).widget() for index in range(inspector.layer_rows.count())
                if isinstance(inspector.layer_rows.itemAt(index).widget(), LayerRow)]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].toolTip(), 'Warm · the shirt')
        self.assertEqual(inspector.name.text(), 'Title')  # the active layer
        self.assertEqual(inspector.opacity.value(), 50)
        posted = self.post(lambda: rows[2].eye.click())
        path, body = posted[0][:2]
        self.assertEqual(path, f'/api/photocraft/workspaces/{"w" * 32}/operation')
        self.assertEqual(body['commands'][0], dict(command='layer.setProps', params=dict(layer=1, visible=True),
                                                   label='Show Background'))
        self.assertEqual(body['revision'], 'a' * 32)
        page.pending = False
        inspector.opacity.setValue(80)
        posted = self.post(inspector.set_opacity)
        self.assertEqual(posted[0][1]['commands'][0]['params'], dict(layer=2, opacity=0.8))
        page.pending = False
        inspector.name.setText('Headline')
        posted = self.post(inspector.rename)
        self.assertEqual(posted[0][1]['commands'][0]['command'], 'layer.renameLayer')
        page.pending = False
        posted = self.post(lambda: page.operation(dict(action='goto', index=0)))
        self.assertEqual((posted[0][1]['action'], posted[0][1]['index']), ('goto', 0))

    def test_a_panel_edit_from_start_to_finish(self):
        page = self.page
        self.open()
        page.choose_tool('adjust')
        panel = page.panels['adjust']
        self.assertFalse(panel.apply.isEnabled())  # nothing moved yet
        panel.sliders['exposure'].slider.setValue(panel.sliders['exposure'].slider.value() + 10)
        self.assertTrue(panel.apply.isEnabled())
        posted = self.post(panel.apply.click)
        path, body, started, _ = posted[0]
        self.assertEqual(path, f'/api/photocraft/workspaces/{"w" * 32}/edits')
        self.assertEqual(body['edits'][0]['action'], 'exposure')
        self.assertEqual(body['edits'][0]['value'], 0.5)
        self.assertTrue(page.busy)
        self.assertFalse(panel.apply.isEnabled())
        with patch.object(page.client, 'get'):
            started(dict(id='j1', state='running', progress=0.2, message='Applying 1 of 3'))
        self.assertEqual(page.active, 'j1')
        self.assertFalse(page.stop.isHidden())
        self.assertEqual(page.message.text(), 'Applying 1 of 3')
        newer = craft_document('b' * 32, cursor=2, history=3)
        fetched = []
        with patch.object(page.client, 'bytes', side_effect=lambda *args, **kwargs: fetched.append(args)), \
                patch.object(page.client, 'get'):
            page.polled('j1', dict(id='j1', state='done', progress=1, message='Adjust applied.', workspace=newer))
        self.assertFalse(page.busy)
        self.assertEqual(page.document['revision'], 'b' * 32)
        self.assertIn('revision 3 of 3', page.subtitle.text())
        self.assertEqual(fetched[0][0], newer['preview'])
        self.assertEqual(len(fetched), 1)  # the original was fetched already

    def test_marking_an_area_and_planning_it(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        page = self.page
        self.open()
        page.choose_tool('assistant')
        panel = page.assistant
        panel.set_prompt('Brighten this')
        self.assertTrue(panel.plan_button.isEnabled())
        panel.scope.button('area').click()
        self.assertTrue(page.area)
        self.assertFalse(panel.plan_button.isEnabled())  # not before something is marked
        canvas = page.canvas
        canvas.resize(440, 240)  # the 400 × 200 document fills it: one screen pixel per document pixel
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(canvas, QPoint(220, 120))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(220, 120))
        self.assertEqual(len(canvas.marks), 1)
        self.assertEqual(canvas.marks[0]['points'][0], (0, 0))
        self.assertEqual(canvas.marks[0]['points'][-1], (0.5, 0.5))
        self.assertTrue(panel.undo_mark.isEnabled())
        self.assertTrue(panel.plan_button.isEnabled())
        posted = self.post(panel.plan)
        path, body = posted[0][:2]
        self.assertEqual(path, f'/api/photocraft/workspaces/{"w" * 32}/plan')
        self.assertEqual(body['prompt'], 'Brighten this')
        self.assertEqual(body['area']['marks'][0]['tool'], 'brush')
        self.assertAlmostEqual(body['area']['marks'][0]['size'], 0.03)
        from image_studio.api.photocraft import PromptRequest

        PromptRequest(**body)  # the engine accepts it

    def test_a_plan_is_shown_and_applied(self):
        page = self.page
        self.open()
        page.choose_tool('assistant')
        plan = dict(id='p' * 32, revision='a' * 32, prompt='Warm it', summary='', requirements=['Warm it'],
                    edits=[dict(action='temperature', quote='Warm it', explain='Warmer light', target='sky',
                                value=None, strength='subtle')],
                    preserve=['the person'], questions=[], notes=[], unresolved=['Could not find the dog.'],
                    regions=[dict(requirement=0, label='Sky', boxes=[[0, 0, 1, 0.4]])], planner='brain',
                    steps=[dict(command='filter.cameraRaw', label='Warmer', params={}, requirements=[0])])
        page.active = 'j2'
        page.polled('j2', dict(id='j2', state='done', progress=1, message='Review', plan=plan))
        self.assertEqual(page.canvas.regions[0]['label'], 'Sky')
        panel = page.assistant
        self.assertTrue(panel.examples.isHidden())
        texts = [widget.text() for widget in panel.plan_box.findChildren(type(panel.planner))]
        self.assertIn('I UNDERSTOOD 1 CHANGE', texts)
        apply = [button for button in panel.plan_box.findChildren(type(panel.plan_button))
                 if 'understood parts' in button.text()]
        self.assertEqual(len(apply), 1)
        posted = self.post(apply[0].click)
        self.assertEqual((posted[0][1]['plan_id'], posted[0][1]['partial']), ('p' * 32, True))
        page.pending = False
        self.open(craft_document('c' * 32, cursor=1))
        self.assertEqual(page.canvas.regions, [])  # the plan belongs to the old revision
        texts = [widget.text() for widget in panel.plan_box.findChildren(type(panel.planner))]
        self.assertTrue(any('changed since this plan' in text for text in texts))

    def test_undo_redo_and_the_tool_are_remembered(self):
        page = self.page
        self.open(craft_document(cursor=1, history=3))
        posted = self.post(page.undo)
        self.assertEqual(posted[0][1]['action'], 'undo')
        page.pending = False
        posted = self.post(page.redo)
        self.assertEqual(posted[0][1]['action'], 'redo')
        page.pending = False
        page.choose_tool('crop')
        self.assertIs(page.tool_stack.currentWidget(), page.panels['crop'])
        self.assertEqual(json.loads(self.window.settings.value('photocraft/settings'))['tool'], 'crop')

    def test_engine_commands_with_their_settings(self):
        page = self.page
        self.open()
        page.choose_tool('filters')
        runner = page.panels['filters'].runner
        self.assertEqual(runner.title.text(), 'Gaussian Blur')
        posted = self.post(runner.apply.click)
        steps = posted[0][1]['commands']
        self.assertEqual([step['command'] for step in steps], ['studio.select_photo', 'filter.blur.gaussianBlur'])
        self.assertEqual(steps[1]['params'], {})  # untouched settings keep PhotoCraft's defaults
        page.pending = False
        panel = page.panels['all']
        panel.search.setText('layer prop')
        panel.fill()
        self.assertEqual(panel.list.count(), 1)
        panel.list.setCurrentRow(0)
        form = panel.runner.form
        json_box = form.findChildren(__import__('PySide6.QtWidgets', fromlist=['QPlainTextEdit']).QPlainTextEdit)[0]
        json_box.setPlainText('{not json')
        self.assertFalse(panel.runner.apply.isEnabled())
        json_box.setPlainText('{"a": 1}')
        self.assertTrue(panel.runner.apply.isEnabled())
        self.assertEqual(form.values(), {'extra': {'a': 1}})
        panel.search.setText('new')
        panel.fill()
        panel.list.setCurrentRow(0)
        self.assertTrue(panel.runner.apply.isHidden())  # needs PhotoCraft desktop
        self.assertEqual(panel.runner.reason.text(), 'Use the document controls.')

    def test_opening_a_file_uploads_it(self):
        page = self.page
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'photo.png'
            path.write_bytes(png(10, 10)[1])
            sent = []
            with patch.object(page.client, 'upload', side_effect=lambda *args, **kwargs: sent.append(args)):
                page.open_file(path)
                page.open_file(Path(folder) / 'notes.txt')
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][:2], ('/api/photocraft/workspaces/import', 'photo.png'))
        self.assertTrue(page.busy)
        sent[0][4]('Busy')  # refused
        self.assertFalse(page.busy)

    def test_the_photo_from_edit_comes_along(self):
        posted = []
        with patch.object(self.page.client, 'post', side_effect=lambda *args, **kwargs: posted.append(args)):
            self.window.open_photocraft(dict(ref='/images/a.png', name='a.png', image=None))
        self.assertIs(self.window.pages.currentWidget(), self.page)
        self.assertEqual(posted[0][:2], ('/api/photocraft/workspaces/from-library', {'name': 'a.png'}))
        edit = self.window.edit
        edit.set_source(dict(ref=None, name='photo.png', image=png(40, 20)[0]))
        result = dict(name='photocraft_1.png', url='/images/photocraft_1.png', thumbnail='/t', created=1, metadata={})
        edit.job = dict(id='e', state='done', progress=1, message='', images=[result])
        with patch.object(edit.client, 'bytes'):
            edit.render()
        self.assertEqual(edit.shown_picture()['ref'], '/images/photocraft_1.png')  # the result, while it is shown
        edit.show_after(False)
        self.assertEqual(edit.shown_picture()['name'], 'photo.png')
        edit.job = None
        edit.set_source(None)

    def test_narrow_windows_take_turns(self):
        page = self.page
        page.resize(1500, 800)
        page.arrange()
        self.assertFalse(page.tool_area.isHidden())
        self.assertFalse(page.inspector.isHidden())
        page.resize(900, 800)
        page.arrange()
        self.assertFalse(page.tool_area.isHidden())
        self.assertTrue(page.inspector.isHidden())
        page.flip_layers()
        self.assertTrue(page.tool_area.isHidden())
        self.assertFalse(page.inspector.isHidden())
        page.choose_tool('looks')
        self.assertFalse(page.tool_area.isHidden())
        self.assertTrue(page.inspector.isHidden())


if __name__ == '__main__':
    unittest.main()

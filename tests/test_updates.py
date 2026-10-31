"""Stable release detection, persistent reminder choices and app-wide update UI."""

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from image_studio.core import paths
from image_studio.core.version import current
from image_studio.services import updates


def release(version='2.0.4', **extra):
    tag = 'v' + version
    name = f'ImageStudio-{version}-Setup.exe'
    return dict(
        tag_name=tag,
        draft=False,
        prerelease=False,
        assets=[
            dict(
                name=name,
                size=42_000_000,
                state='uploaded',
                browser_download_url=f'{updates.RELEASES}/download/{tag}/{name}',
            )
        ],
        **extra,
    )


class ReleaseTests(unittest.TestCase):
    def test_numeric_versions_never_offer_a_downgrade_or_prerelease(self):
        self.assertEqual(updates.number('v2.0.10'), (2, 0, 10))
        self.assertIsNone(updates.number('2.1.0-beta.1'))
        self.assertIsNone(updates.number('2.01.0'))
        for version in ['2.0.2', '2.0.3']:
            self.assertEqual(
                updates.select_release([release(version)], '2.0.3', 'win32')['status'], 'current'
            )
        preview, draft = release('8.0.0'), release('9.0.0')
        preview['prerelease'], draft['draft'] = True, True
        result = updates.select_release([release(), preview, draft, release('2.0.10')], '2.0.3', 'win32')
        self.assertEqual(result['latest'], '2.0.10')
        self.assertEqual(result['status'], 'available')

    def test_only_an_uploaded_official_platform_installer_is_offered(self):
        candidate = release()
        for url in [
            'https://elsewhere.test/setup.exe',
            candidate['assets'][0]['browser_download_url'] + '?wrong=1',
        ]:
            candidate['assets'][0]['browser_download_url'] = url
            self.assertEqual(updates.select_release([candidate], '2.0.3', 'win32')['status'], 'unavailable')
        candidate = release()
        candidate['assets'][0]['state'] = 'new'
        self.assertEqual(updates.select_release([candidate], '2.0.3', 'win32')['status'], 'unavailable')
        self.assertEqual(updates.select_release([release()], '2.0.3', 'linux')['status'], 'unavailable')
        name = 'image-studio-2.0.4-linux-x86_64.tar.gz'
        candidate['assets'] = [
            dict(name=name, size=10, browser_download_url=f'{updates.RELEASES}/download/v2.0.4/{name}')
        ]
        self.assertEqual(updates.select_release([candidate], '2.0.3', 'linux')['status'], 'available')

    def test_empty_malformed_and_unknown_versions_are_not_reported_as_updates(self):
        self.assertEqual(updates.select_release([], '2.0.3', 'win32')['status'], 'unavailable')
        with self.assertRaises(updates.UpdateError):
            updates.select_release({}, '2.0.3', 'win32')
        with self.assertRaises(updates.UpdateError):
            updates.select_release([release()], 'unknown', 'win32')

    def test_network_request_is_bounded_and_store_builds_never_fetch_external_updates(self):
        response = io.BytesIO(json.dumps([release()]).encode())
        with (
            patch.object(paths, 'PACKAGE', None),
            patch.object(updates, 'current', return_value='2.0.3'),
            patch.object(updates.urllib.request, 'urlopen', return_value=response) as request,
        ):
            result = updates.check()
        self.assertEqual(result['status'], 'available')
        self.assertEqual(request.call_args.args[0].full_url, updates.API)
        self.assertEqual(request.call_args.kwargs['timeout'], 10)
        self.assertNotIn('Authorization', request.call_args.args[0].headers)
        with (
            patch.object(paths, 'PACKAGE', 'StorePackage'),
            patch.object(updates.urllib.request, 'urlopen') as request,
        ):
            self.assertEqual(updates.check()['status'], 'store')
            request.assert_not_called()
        for error in [OSError('offline'), urllib.error.HTTPError(updates.API, 429, 'limited', {}, None)]:
            with (
                patch.object(paths, 'PACKAGE', None),
                patch.object(updates.urllib.request, 'urlopen', side_effect=error),
            ):
                with self.assertRaises(updates.UpdateError):
                    updates.check()
        with (
            patch.object(paths, 'PACKAGE', None),
            patch.object(updates.urllib.request, 'urlopen', return_value=io.BytesIO(b'x' * 11)),
            patch.object(updates, 'MAX_RESPONSE', 10),
        ):
            with self.assertRaisesRegex(updates.UpdateError, 'too large'):
                updates.check()

    def test_installed_version_does_not_depend_on_the_engine_or_qt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'pyproject.toml').write_text('version = "2.0.3"')
            metadata = root / 'build.json'
            with patch.object(paths, 'ROOT', root), patch.object(paths, 'BUILD_FILE', metadata):
                self.assertEqual(current(), '2.0.3')
                self.assertEqual(current(source_label=True), '2.0.3 (source)')
                metadata.write_text('{"version":"2.0.1"}')
                self.assertEqual(current(), '2.0.1')


try:
    import PySide6  # noqa: F401

    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, 'PySide6 not installed')
class UpdateWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_desktop import desktop

        cls.app, cls.window = desktop()

    def setUp(self):
        from PySide6.QtCore import QSettings
        from image_studio.desktop.updates import UpdateController, UpdatePanel

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(str(Path(self.temp.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.busy = False
        self.controller = UpdateController(self.window, lambda: self.settings, lambda: self.busy)
        self.addCleanup(self.dispose)
        self.panel = UpdatePanel(self.controller)
        self.result = updates.select_release([release()], '2.0.3', 'win32')

    def dispose(self):
        if self.controller.dialog:
            self.controller.dialog.reject()
        self.controller.reminder.stop()
        self.panel.deleteLater()
        self.controller.deleteLater()

    def test_manual_check_opens_popup_and_later_remembers_the_version(self):
        from image_studio.desktop import updates as ui

        def work(fetch, done):
            done(self.result, None)

        with patch.object(ui, 'in_background', side_effect=work):
            self.panel.check.click()
        self.assertIsNotNone(self.controller.dialog)
        self.assertEqual(self.controller.dialog.download.text(), 'Download update')
        self.controller.dialog.later.click()
        self.assertIsNone(self.controller.dialog)
        self.assertGreater(float(self.settings.value('updates/reminded/2.0.4')), 0)
        with patch.object(self.window, 'isActiveWindow', return_value=True):
            self.controller.maybe_show()
        self.assertIsNone(self.controller.dialog)
        self.controller.maybe_show(manual=True)  # Settings always lets the person ask again.
        self.assertIsNotNone(self.controller.dialog)

    def test_download_opens_only_the_installer_and_keeps_the_app_and_project_open(self):
        from image_studio.desktop import updates as ui

        self.controller.checked(self.result, None)
        self.controller.maybe_show(manual=True)
        with (
            patch.object(ui.QDesktopServices, 'openUrl', return_value=True) as opened,
            patch.object(self.window, 'close') as close,
        ):
            self.controller.dialog.download.click()
        self.assertEqual(opened.call_args.args[0].toString(), self.result['download'])
        close.assert_not_called()
        self.assertIsNone(self.controller.dialog)

    def test_failed_browser_launch_stays_open_to_retry(self):
        from image_studio.desktop import updates as ui

        self.controller.result = self.result
        self.controller.maybe_show(manual=True)
        with patch.object(ui.QDesktopServices, 'openUrl', return_value=False):
            self.controller.dialog.download.click()
        self.assertIsNotNone(self.controller.dialog)
        self.assertFalse(self.controller.dialog.error.isHidden())
        self.assertIsNone(self.settings.value('updates/reminded/2.0.4'))

    def test_automatic_checks_and_reminders_respect_disabled_busy_and_background_states(self):
        from image_studio.desktop import updates as ui

        self.controller.set_automatic(False)
        with patch.object(ui, 'in_background') as work:
            self.controller.automatic_check()
            work.assert_not_called()
        self.assertFalse(self.settings.value('updates/automatic', type=bool))
        self.controller.set_automatic(True)
        self.controller.result = self.result
        with patch.object(self.window, 'isActiveWindow', return_value=False):
            self.controller.maybe_show()
        self.assertIsNone(self.controller.dialog)
        self.assertTrue(self.controller.reminder.isActive())
        self.busy = True
        with patch.object(self.window, 'isActiveWindow', return_value=True):
            self.controller.maybe_show()
        self.assertIsNone(self.controller.dialog)
        self.busy = False
        with (
            patch.object(self.window, 'isActiveWindow', return_value=True),
            patch.object(self.window, 'isMinimized', return_value=False),
        ):
            self.controller.maybe_show()
        self.assertIsNotNone(self.controller.dialog)

    def test_current_offline_and_overlapping_checks_have_honest_status_without_a_popup(self):
        from image_studio.desktop import updates as ui

        self.controller.checked(dict(status='current', message='You’re up to date.'), None)
        self.assertIn('up to date', self.panel.status.text())
        self.assertIsNone(self.controller.dialog)
        self.controller.checked(None, updates.UpdateError('Connection unavailable'))
        self.assertEqual(self.panel.status.text(), 'Connection unavailable')
        self.assertIsNone(self.controller.dialog)
        with patch.object(ui, 'in_background') as work:
            self.controller.check()
            self.controller.check(manual=True)
            self.assertEqual(work.call_count, 1)
            self.assertTrue(self.controller.manual_pending)
        self.controller.checked(self.result, None)
        self.assertIsNotNone(self.controller.dialog)

    def test_main_window_settings_contains_the_checker_and_store_has_no_external_download(self):
        self.assertEqual(self.window.system.updates.check.text(), 'Check for updates')
        with patch.object(paths, 'PACKAGE', 'StorePackage'):
            self.panel.refresh()
            self.assertTrue(self.panel.check.isHidden())
            self.assertTrue(self.panel.auto.isHidden())
            self.assertTrue(self.panel.releases.isHidden())
            self.assertIn('Microsoft Store', self.panel.status.text())

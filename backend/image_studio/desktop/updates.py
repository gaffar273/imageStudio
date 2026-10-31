"""App-wide update reminders and the Updates card in Settings → This PC."""

import time

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from image_studio.core import paths
from image_studio.core.version import current
from image_studio.desktop import theme
from image_studio.desktop.controls import Toggle
from image_studio.desktop.engine import in_background
from image_studio.desktop.theme import label
from image_studio.services import updates


def setting_time(settings, key):
    try:
        return float(settings.value(key, 0))
    except (ValueError, TypeError):
        return 0


class UpdateDialog(QDialog):
    def __init__(self, window, release):
        super().__init__(window)
        self.setWindowTitle('Update available')
        self.setMinimumWidth(460)
        self.setMaximumWidth(600)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.release = release
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 22, 24, 20)
        column.setSpacing(14)
        column.addWidget(label('A new version is available', 'title'))
        column.addWidget(label(f'Image Studio {release["latest"]} · You have {release["current"]}', 'value'))
        size = round(release['size'] / 1024 / 1024)
        column.addWidget(
            label(
                f'Download the {size} MB installer, then close Image Studio and run it to update. '
                'Your saved projects, pictures, models and settings stay on this computer.',
                'muted',
                wrap=True,
            )
        )
        self.error = label('', 'small', wrap=True)
        self.error.hide()
        column.addWidget(self.error)
        row = QHBoxLayout()
        self.notes = QPushButton('Release notes')
        self.notes.clicked.connect(lambda: self.open_link(release['page']))
        row.addWidget(self.notes)
        row.addStretch()
        self.later = QPushButton('Later')
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        self.download = QPushButton(theme.icon('download', theme.ON_ACCENT), 'Download update')
        self.download.setProperty('kind', 'primary')
        self.download.clicked.connect(self.download_update)
        row.addWidget(self.download)
        column.addLayout(row)

    def open_link(self, url):
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            self.error.setText('Could not open your browser. Try again, or download from agslabs.tech.')
            self.error.show()
        return opened

    def download_update(self):
        if self.open_link(self.release['download']):
            self.accept()


class UpdateController(QObject):
    changed = Signal()

    def __init__(self, window, settings, busy):
        super().__init__(window)
        self.window, self.settings, self.busy = window, settings, busy
        self.checking, self.result, self.error, self.dialog = False, None, '', None
        self.manual_pending = False
        self.timer = QTimer(self)
        self.timer.setInterval(updates.CHECK_SECONDS * 1000)
        self.timer.timeout.connect(self.automatic_check)
        self.reminder = QTimer(self)
        self.reminder.setSingleShot(True)
        self.reminder.setInterval(30_000)
        self.reminder.timeout.connect(self.maybe_show)

    @property
    def automatic(self):
        return not paths.PACKAGE and self.settings().value('updates/automatic', True, type=bool)

    def set_automatic(self, enabled):
        self.settings().setValue('updates/automatic', enabled)
        if not enabled:
            self.reminder.stop()
        self.changed.emit()

    def start(self):
        if not paths.PACKAGE:
            QTimer.singleShot(8_000, self.automatic_check)
            self.timer.start()

    def automatic_check(self):
        if not self.automatic:
            return
        self.check()

    def check(self, manual=False):
        self.manual_pending = self.manual_pending or manual
        if self.checking:
            return
        self.checking, self.error = True, ''
        self.changed.emit()
        in_background(updates.check, self.checked)

    def checked(self, result, error):
        if not isValid(self):
            return
        manual, self.manual_pending = self.manual_pending, False
        self.checking = False
        if error:
            self.error = str(error)
        else:
            self.result, self.error = result, ''
            self.settings().setValue('updates/checked_at', time.time())
        self.changed.emit()
        if not error and result.get('status') == 'available':
            self.maybe_show(manual)

    def maybe_show(self, manual=False):
        if not self.result or self.result.get('status') != 'available' or self.dialog is not None:
            return
        if not manual:
            if not self.automatic:
                return
            elapsed = time.time() - setting_time(self.settings(), f'updates/reminded/{self.result["latest"]}')
            if 0 <= elapsed < updates.REMIND_SECONDS:
                return
            if (
                self.busy()
                or not self.window.isActiveWindow()
                or self.window.isMinimized()
                or QApplication.activeModalWidget() is not None
            ):
                self.reminder.start()
                return
        self.reminder.stop()
        self.dialog = UpdateDialog(self.window, self.result)
        self.dialog.finished.connect(self.dismissed)
        self.dialog.open()

    def dismissed(self, _):
        if self.dialog:
            self.settings().setValue(f'updates/reminded/{self.dialog.release["latest"]}', time.time())
            self.dialog.deleteLater()
            self.dialog = None


class UpdatePanel(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(label('App updates', 'heading'))
        column.addWidget(label(f'Installed version: {current()}', 'small'))
        self.status = label('', 'muted', wrap=True)
        column.addWidget(self.status)
        self.last = label('', 'small')
        column.addWidget(self.last)
        self.auto = Toggle(
            'Check automatically',
            'Check at startup and every six hours. Later defers a reminder for one day.',
        )
        self.auto.toggled.connect(controller.set_automatic)
        column.addWidget(self.auto)
        row = QHBoxLayout()
        self.check = QPushButton(theme.icon('refresh-cw'), 'Check for updates')
        self.check.clicked.connect(lambda: controller.check(manual=True))
        row.addWidget(self.check)
        self.download = QPushButton(theme.icon('download'), 'Download update')
        self.download.clicked.connect(lambda: controller.maybe_show(manual=True))
        row.addWidget(self.download)
        releases = QPushButton('Releases')
        releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updates.RELEASES)))
        row.addWidget(releases)
        self.releases = releases
        row.addStretch()
        column.addLayout(row)
        controller.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        controller = self.controller
        store = bool(paths.PACKAGE)
        self.auto.switch.blockSignals(True)
        self.auto.setChecked(controller.automatic)
        self.auto.switch.blockSignals(False)
        self.auto.setVisible(not store)
        self.check.setVisible(not store)
        self.releases.setVisible(not store)
        self.check.setEnabled(not controller.checking)
        self.check.setText('Checking…' if controller.checking else 'Check for updates')
        text = (
            'Updates are managed by Microsoft Store.'
            if store
            else (
                'Checking GitHub for a new version…'
                if controller.checking
                else controller.error
                or (controller.result or {}).get('message')
                or 'Check for new versions of Image Studio.'
            )
        )
        self.status.setText(text)
        self.download.setVisible(
            not store and bool(controller.result and controller.result.get('status') == 'available')
        )
        self.download.setEnabled(not controller.checking)
        checked = setting_time(controller.settings(), 'updates/checked_at')
        self.last.setText(
            'Last checked: ' + time.strftime('%d %b %Y, %H:%M', time.localtime(checked)) if checked else ''
        )
        self.last.setVisible(not store and bool(checked))

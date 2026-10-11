"""Image Studio as a desktop application (Qt), for Windows and Linux.

Run with `python -m image_studio.desktop`. The window starts the engine, shows the
screens, and stops the engine again when it closes so the GPU is freed.
"""

import sys

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from image_studio.core import hardware
from image_studio.desktop import theme
from image_studio.desktop.create import CreatePage
from image_studio.desktop.edit import EditPage
from image_studio.desktop.engine import Client, Engine, in_background
from image_studio.desktop.library import LibraryPage
from image_studio.desktop.photocraft import PhotoCraftPage
from image_studio.desktop.system_page import SystemPage
from image_studio.desktop.theme import label

# (id, label, icon, phase that brings it to the desktop app; None = already here)
SCREENS = [
    ('create', 'Create image', 'sparkles', None),
    ('edit', 'Edit image', 'square-pen', None),
    ('photocraft', 'PhotoCraft studio', 'layers', None),
    ('library', 'My library', 'folder-heart', None),
    ('krita', 'Krita canvas', 'image-plus', 5),
]
FOOTER = [
    ('system', 'This PC', 'cpu', None),
    ('settings', 'Studio settings', 'sliders-horizontal', 5),
]
USAGE_SECONDS = 3


class PendingPage(QWidget):
    """A screen not yet rebuilt for the desktop; it opens in the web version meanwhile."""

    def __init__(self, client, route, title, icon, phase):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        box = QWidget()
        box.setFixedWidth(540)  # wrapped labels need a definite width to measure their height
        outer.addWidget(box, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        symbol = QPushButton(theme.icon(icon, theme.LIME), '')
        symbol.setProperty('kind', 'flat')
        symbol.setIconSize(QSize(44, 44))
        symbol.setEnabled(False)
        layout.addWidget(symbol, 0, Qt.AlignmentFlag.AlignHCenter)
        for widget in (
            label(f'ARRIVING IN PHASE {phase}', 'eyebrow'),
            label(title, 'title'),
            label(
                'This screen is being rebuilt for the desktop app. Until then it works in the web '
                'version, with the same engine and the same library.',
                'muted',
                wrap=True,
            ),
        ):
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(widget)
        layout.addSpacing(10)
        self.button = QPushButton(theme.icon('external-link', theme.INK), 'Open in the web version')
        self.button.setProperty('kind', 'primary')
        self.button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f'{client.base}/#{route}')))
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Image Studio')
        self.setWindowIcon(theme.icon('aperture', theme.LIME))
        self.setMinimumSize(1080, 640)
        self.settings = QSettings()
        self.client = Client(self)
        self.engine = Engine(self.client, self)
        self.engine.changed.connect(self.engine_changed)
        self.job_running = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar())
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)

        self.library = LibraryPage(self.client, self.notify)
        self.system = SystemPage(self.client, self.engine, self.notify)
        self.create = CreatePage(
            self.client, self.library, self.notify, lambda: self.settings, lambda: self.navigate('library')
        )
        self.edit = EditPage(
            self.client, self.library, self.notify, lambda: self.settings, lambda: self.navigate('library'),
            self.open_photocraft,
        )
        self.photocraft = PhotoCraftPage(self.client, self.library, self.notify, lambda: self.settings)
        self.library.reuse = self.reuse
        self.library.edit = self.edit_picture
        self.screens = {}
        for route, title, icon, phase in SCREENS + FOOTER:
            built = {'create': self.create, 'edit': self.edit, 'photocraft': self.photocraft, 'library': self.library,
                     'system': self.system}
            page = built.get(route) or PendingPage(
                self.client, route, title, icon, phase
            )
            self.screens[route] = page
            self.pages.addWidget(page)
        self.status_bar()

        self.usage = QTimer(self)
        self.usage.setInterval(USAGE_SECONDS * 1000)
        self.usage.timeout.connect(self.measure)
        self.usage.start()
        self.measure()

        geometry = self.settings.value('geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1360, 860)
        self.navigate(self.settings.value('page', 'create'))

    # Layout ------------------------------------------------------------------------------

    def sidebar(self):
        bar = QWidget()
        bar.setObjectName('Sidebar')
        bar.setFixedWidth(232)
        column = QVBoxLayout(bar)
        column.setContentsMargins(14, 18, 14, 14)
        column.setSpacing(4)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(theme.icon('aperture', theme.LIME).pixmap(26, 26))
        brand.addWidget(mark)
        name = QLabel('image<span style="color:#898f89">studio</span>')
        name.setTextFormat(Qt.TextFormat.RichText)
        font = name.font()
        font.setPointSizeF(14)
        font.setWeight(QFont.Weight.DemiBold)
        name.setFont(font)
        brand.addWidget(name)
        brand.addStretch()
        column.addLayout(brand)
        column.addSpacing(18)
        column.addWidget(label('WORKSPACE', 'eyebrow'))
        column.addSpacing(4)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}

        def add(route, title, icon):
            button = QPushButton(theme.icon(icon, theme.MUTED), f'  {title}')
            button.setProperty('nav', True)
            button.setCheckable(True)
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _=False, route=route: self.navigate(route))
            self.nav.addButton(button)
            self.nav_buttons[route] = (button, icon)
            column.addWidget(button)

        for route, title, icon, _ in SCREENS:
            add(route, title, icon)
        column.addStretch()
        for route, title, icon, _ in FOOTER:
            add(route, title, icon)
        return bar

    def status_bar(self):
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self.engine_label = QLabel()
        bar.addWidget(self.engine_label)
        self.message = QLabel()
        bar.addWidget(self.message, 1)
        self.message_timer = QTimer(self)
        self.message_timer.setSingleShot(True)
        self.message_timer.timeout.connect(lambda: self.message.setText(''))
        self.gpu_label = QLabel()
        bar.addPermanentWidget(self.gpu_label)
        self.ram_label = QLabel()
        bar.addPermanentWidget(self.ram_label)
        self.free = QPushButton(theme.icon('memory-stick', theme.MUTED), 'Free GPU')
        self.free.setProperty('kind', 'flat')
        self.free.setToolTip('Unload every model so games and other programs get the video memory back.')
        self.free.clicked.connect(self.system.free_gpu)
        bar.addPermanentWidget(self.free)
        self.engine_changed(self.engine.state, self.engine.message)

    # Behaviour ---------------------------------------------------------------------------

    def navigate(self, route):
        if route not in self.screens:
            route = 'create'
        for name, (button, icon) in self.nav_buttons.items():
            button.setChecked(name == route)
            button.setIcon(theme.icon(icon, theme.LIME if name == route else theme.MUTED))
        page = self.screens[route]
        self.pages.setCurrentWidget(page)
        self.settings.setValue('page', route)
        if page is self.system or (hasattr(page, 'refresh') and self.engine.state == 'ready'):
            page.refresh()

    def reuse(self, item):
        self.navigate('create')
        self.create.reuse(item)

    def edit_picture(self, item):
        self.navigate('edit')
        self.edit.load_item(item)

    def open_photocraft(self, source=None):
        """The PhotoCraft studio, with the photo from Edit when there is one."""
        self.navigate('photocraft')
        if source is None:
            return
        if source.get('ref'):
            self.photocraft.open_library(dict(name=source['ref'].removeprefix('/images/')))
        elif source.get('image') is not None:
            self.photocraft.open_image(source['image'], source.get('name') or 'photo.png')

    def notify(self, text, error=False):
        self.message.setText(text)
        self.message.setStyleSheet(f'color: {theme.DANGER if error else theme.TEXT};')
        self.message_timer.start(9000 if error else 5000)

    def engine_changed(self, state, message):
        colors = {'ready': theme.LIME, 'starting': theme.WARN}
        dot = colors.get(state, theme.DANGER)
        self.engine_label.setText(f'<span style="color:{dot}">●</span>&nbsp; {message}')
        self.free.setEnabled(state == 'ready')
        for page in self.screens.values():
            if isinstance(page, PendingPage):
                page.button.setEnabled(state == 'ready')
        if state == 'ready':
            self.library.engine_ready()
            self.create.engine_ready()
            self.edit.engine_ready()
            self.photocraft.engine_ready()
        else:
            self.library.engine_gone()
            self.create.engine_gone()
            self.edit.engine_gone()
            self.photocraft.engine_gone()
            if state == 'failed':
                self.library.waiting('The engine is not running.', message + ' Use This PC to restart it.')

    def measure(self):
        if self.isMinimized():
            return  # no polling while the window is out of the way
        in_background(hardware.usage, self.show_usage)
        if self.engine.state == 'ready':
            self.client.get('/api/system', lambda info: setattr(self, 'job_running', bool(info.get('active_job'))))

    def show_usage(self, usage, error):
        if error or usage is None:
            return
        gpus = usage['gpus']
        if gpus:
            gpu = max(gpus, key=lambda card: card['vram_gb'])
            load = f' · {gpu["load"]:.0f}%' if gpu['load'] is not None else ''
            self.gpu_label.setText(f'GPU {gpu["used_gb"]:.1f} / {gpu["vram_gb"]:.0f} GB{load}')
            self.gpu_label.setToolTip(f'{gpu["name"]}: video memory in use and current load')
        else:
            self.gpu_label.setText('No NVIDIA GPU')
        self.ram_label.setText(f'RAM {usage["ram_used_gb"]:.0f} / {usage["ram_gb"]:.0f} GB')

    def closeEvent(self, event):
        if self.engine.owned and self.job_running:
            answer = QMessageBox.question(
                self, 'A job is running', 'Closing the app stops the engine and the current job. Close anyway?'
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.settings.setValue('geometry', self.saveGeometry())
        if self.engine.owned:
            self.engine_label.setText('Stopping the engine…')
            QApplication.processEvents()
            self.engine.stop()
        event.accept()


def palette():
    colors = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.BG,
        QPalette.ColorRole.WindowText: theme.TEXT,
        QPalette.ColorRole.Base: theme.PANEL,
        QPalette.ColorRole.AlternateBase: theme.RAISED,
        QPalette.ColorRole.Text: theme.TEXT,
        QPalette.ColorRole.Button: theme.RAISED,
        QPalette.ColorRole.ButtonText: theme.TEXT,
        QPalette.ColorRole.Highlight: '#4d5d36',
        QPalette.ColorRole.HighlightedText: theme.TEXT,
        QPalette.ColorRole.ToolTipBase: theme.RAISED,
        QPalette.ColorRole.ToolTipText: theme.TEXT,
        QPalette.ColorRole.PlaceholderText: theme.MUTED,
        QPalette.ColorRole.Link: theme.LIME,
    }
    for role, color in roles.items():
        colors.setColor(role, QColor(color))
    return colors


def build():
    """The application and its window, styled; the engine is not started yet."""
    if sys.platform == 'win32':
        import ctypes

        # Its own taskbar entry and icon, rather than Python's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ImageStudio.Desktop')
    QApplication.setOrganizationName('Image Studio')
    QApplication.setApplicationName('Image Studio')
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setPalette(palette())
    if theme.font_family():
        font = app.font()
        font.setFamily(theme.font_family())
        app.setFont(font)
    app.setStyleSheet(theme.STYLE + theme.arrow())
    return app, MainWindow()


def main():
    app, window = build()
    window.show()
    window.engine.start()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

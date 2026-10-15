"""Image Studio as a desktop application (Qt), for Windows and Linux.

Run with `python -m image_studio.desktop`. The window starts the engine, shows the
screens, and stops the engine again when it closes so the GPU is freed.
"""

import sys

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from image_studio.core import engine_env, hardware, paths
from image_studio.desktop import theme
from image_studio.desktop.controls import Toast
from image_studio.desktop.create import CreatePage
from image_studio.desktop.edit import EditPage
from image_studio.desktop.engine import Client, Engine, in_background
from image_studio.desktop.krita import KritaPage
from image_studio.desktop.library import LibraryPage
from image_studio.desktop.photocraft import PhotoCraftPage
from image_studio.desktop.providers_page import ProvidersPage
from image_studio.desktop.settings_page import SettingsPage
from image_studio.desktop.system_page import SystemPage
from image_studio.desktop.theme import label

# (id, label, icon), in the sidebar's three groups
SCREENS = [
    ('create', 'Create', 'sparkles'),
    ('edit', 'Edit', 'square-pen'),
    ('library', 'Library', 'images'),
]
APPS = [
    ('photocraft', 'PhotoCraft', 'layers'),
    ('krita', 'Krita', 'brush'),
]
FOOTER = [
    ('settings', 'Settings', 'settings-2'),
]
# Routes that open a tab of Settings: (screen, tab)
TABS = {'system': ('settings', 'system'), 'providers': ('settings', 'providers'),
        'models': ('settings', 'models')}
USAGE_SECONDS = 3


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Image Studio')
        self.setWindowIcon(theme.icon('aperture', theme.ACCENT))
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
        self.toast = Toast(central)

        self.library = LibraryPage(self.client, self.notify)
        self.system = SystemPage(self.client, self.engine, self.notify)
        self.providers = ProvidersPage(self.notify, self.providers_changed)
        self.create = CreatePage(
            self.client, self.library, self.notify, lambda: self.settings, lambda: self.navigate('library'),
            lambda: self.navigate('providers'),
        )
        self.edit = EditPage(
            self.client, self.library, self.notify, lambda: self.settings, lambda: self.navigate('library'),
            self.open_photocraft, lambda: self.navigate('providers'),
        )
        self.photocraft = PhotoCraftPage(self.client, self.library, self.notify, lambda: self.settings)
        self.krita = KritaPage(self.client, self.library, self.notify)
        self.studio_settings = SettingsPage(self.client, self.notify, self.use_profile, self.parts_installed,
                                            self.engine.start, self.engine.pause)
        self.studio_settings.add_tab('providers', 'Providers', 'key-round', self.providers, first=True)
        self.studio_settings.add_tab('system', 'This PC', 'cpu', self.system)
        self.studio_settings.tab_opened.connect(self.tab_opened)
        self.library.reuse = self.reuse
        self.library.edit = self.edit_picture
        self.screens = {
            'create': self.create, 'edit': self.edit, 'library': self.library, 'photocraft': self.photocraft,
            'krita': self.krita, 'settings': self.studio_settings,
        }
        for page in self.screens.values():
            self.pages.addWidget(page)
        self.engine_changed(self.engine.state, self.engine.message)

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
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        bar.setFixedWidth(220)
        column = QVBoxLayout(bar)
        column.setContentsMargins(12, 14, 12, 12)
        column.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(8, 0, 0, 0)
        brand.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(theme.icon('aperture', theme.ACCENT).pixmap(22, 22))
        brand.addWidget(mark)
        name = QLabel('Image Studio')
        font = name.font()
        font.setPointSizeF(11)
        font.setWeight(QFont.Weight.DemiBold)
        name.setFont(font)
        brand.addWidget(name)
        brand.addStretch()
        column.addLayout(brand)
        column.addSpacing(18)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}

        def add(route, title, icon):
            button = QPushButton(theme.icon(icon, theme.MUTED), f'  {title}')
            button.setProperty('nav', True)
            button.setCheckable(True)
            button.setIconSize(QSize(17, 17))
            button.clicked.connect(lambda _=False, route=route: self.navigate(route))
            self.nav.addButton(button)
            self.nav_buttons[route] = (button, icon)
            column.addWidget(button)

        for route, title, icon in SCREENS:
            add(route, title, icon)
        column.addSpacing(16)
        apps = label('Apps', 'group')
        apps.setContentsMargins(10, 0, 0, 4)
        column.addWidget(apps)
        for route, title, icon in APPS:
            add(route, title, icon)
        column.addStretch()
        for route, title, icon in FOOTER:
            add(route, title, icon)
        column.addSpacing(8)
        column.addWidget(self.engine_card())
        return bar

    def engine_card(self):
        """The engine's state and what it uses, kept in view at the foot of the sidebar."""
        card = QFrame()
        card.setObjectName('EngineCard')
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        column = QVBoxLayout(card)
        column.setContentsMargins(11, 8, 4, 9)
        column.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.engine_dot = QLabel()
        top.addWidget(self.engine_dot)
        self.engine_label = label('', 'value')
        top.addWidget(self.engine_label, 1)
        self.free = QPushButton(theme.icon('memory-stick', theme.MUTED), '')
        self.free.setProperty('kind', 'flat')
        self.free.setIconSize(QSize(15, 15))
        self.free.setToolTip('Free GPU memory: unload every model so games and other programs get it back.')
        self.free.clicked.connect(lambda: self.system.free_gpu())
        top.addWidget(self.free)
        column.addLayout(top)
        self.usage_label = label('', 'small')
        column.addWidget(self.usage_label)
        card.mousePressEvent = lambda event: self.navigate('system')
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setToolTip('This PC: hardware, engine and folders')
        return card

    # Behaviour ---------------------------------------------------------------------------

    def navigate(self, route):
        tab = None
        if route in TABS:
            route, tab = TABS[route]
        if route not in self.screens:
            route = 'create'
        for name, (button, icon) in self.nav_buttons.items():
            button.setChecked(name == route)
            button.setIcon(theme.icon(icon, theme.TEXT if name == route else theme.MUTED))
        page = self.screens[route]
        self.pages.setCurrentWidget(page)
        self.settings.setValue('page', route)
        if tab:
            page.open_tab(tab)
        elif hasattr(page, 'refresh') and (self.engine.state == 'ready' or page is self.studio_settings):
            page.refresh()

    def tab_opened(self, key):
        if key == 'system':
            self.system.refresh()
        elif key == 'providers':
            self.providers.refresh()

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

    def use_profile(self, profile):
        """Your usual settings, from Settings, loaded into Create."""
        config = self.create.config
        if not config:
            self.notify('The engine is not ready yet.', error=True)
            return
        values = {}
        if profile.get('model'):
            values['model'] = profile['model']
        size = profile.get('size') and next(
            (item['id'] for item in config['sizes'] if item['id'].endswith(profile['size'])), None)
        if size:
            values['size'] = size
        if profile.get('finish'):
            values['photo_finish'] = profile['finish']
        if profile.get('realism') is not None:
            values['realism'] = profile['realism']
        self.navigate('create')
        self.create.update_settings(**values)
        self.notify('Your usual settings are loaded.')

    def parts_installed(self):
        """A model or tool was installed from Settings: the other screens see it at once."""
        if self.engine.state == 'ready':
            for page in (self.library, self.create, self.edit, self.photocraft, self.krita):
                page.engine_ready()

    def providers_changed(self):
        """A provider or the assistant changed: Create, Edit and PhotoCraft see it at once."""
        if self.engine.state == 'ready':
            for page in (self.create, self.edit, self.photocraft):
                page.engine_ready()

    def notify(self, text, error=False):
        self.toast.show_message(text, error)

    def engine_changed(self, state, message):
        colors = {'ready': theme.SUCCESS, 'starting': theme.WARN, 'setup': theme.WARN}
        cloud = paths.INSTALLED and engine_env.kind() == 'cloud'  # no PyTorch: cloud providers only
        names = {'ready': 'Engine ready · cloud mode' if cloud else 'Engine ready', 'starting': 'Engine starting…',
                 'setup': 'Engine not set up', 'failed': 'Engine stopped', 'stopped': 'Engine stopped'}
        dot = colors.get(state, theme.DANGER)
        self.engine_dot.setText(f'<span style="color:{dot}; font-size:9pt">●</span>')
        self.engine_label.setText(names.get(state, message))
        self.engine_label.setToolTip(message)
        self.free.setEnabled(state == 'ready')
        if not hasattr(self, 'screens'):
            return  # the pages are not built yet
        pages = (self.library, self.create, self.edit, self.photocraft, self.krita, self.studio_settings)
        if state == 'ready':
            for page in pages:
                page.engine_ready()
        else:
            for page in pages:
                page.engine_gone()
            if state == 'failed':
                self.library.waiting('The engine is not running.', message + ' Restart it in Settings → This PC.')
            elif state == 'setup':
                self.library.waiting('The engine is not set up yet.', message)
                self.navigate('models')  # its first row installs it

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
        parts = []
        if gpus:
            gpu = max(gpus, key=lambda card: card['vram_gb'])
            parts.append(f'GPU {gpu["used_gb"]:.1f}/{gpu["vram_gb"]:.0f} GB')
            self.usage_label.setToolTip(f'{gpu["name"]}: video memory in use')
        parts.append(f'RAM {usage["ram_used_gb"]:.0f}/{usage["ram_gb"]:.0f} GB')
        self.usage_label.setText(' · '.join(parts))

    def closeEvent(self, event):
        installer = self.studio_settings.installer
        if installer.running:
            answer = QMessageBox.question(
                self, 'An install is running',
                'Closing the app stops the install. It resumes where it stopped when you install again. '
                'Close anyway?',
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            installer.cancel()
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
        QPalette.ColorRole.Base: theme.FIELD,
        QPalette.ColorRole.AlternateBase: theme.PANEL,
        QPalette.ColorRole.Text: theme.TEXT,
        QPalette.ColorRole.Button: theme.FIELD,
        QPalette.ColorRole.ButtonText: theme.TEXT,
        QPalette.ColorRole.Highlight: theme.SELECTION,
        QPalette.ColorRole.HighlightedText: theme.TEXT,
        QPalette.ColorRole.ToolTipBase: '#1f1f26',
        QPalette.ColorRole.ToolTipText: '#ffffff',
        QPalette.ColorRole.PlaceholderText: theme.FAINT,
        QPalette.ColorRole.Link: theme.ACCENT,
    }
    for role, color in roles.items():
        colors.setColor(role, QColor(color))
    return colors


def build():
    """The application and its window, styled; the engine is not started yet."""
    if sys.platform == 'win32' and not paths.PACKAGE:  # a Store package has its own, from the manifest
        import ctypes

        # Its own taskbar entry and icon, rather than Python's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ImageStudio.Desktop')
    QApplication.setOrganizationName('Image Studio')
    QApplication.setApplicationName('Image Studio')
    QGuiApplication.setDesktopFileName('image-studio')  # Linux: the menu entry packaging/linux/install.sh adds
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
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

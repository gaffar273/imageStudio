"""Krita canvas: open pictures in Krita, follow its live canvas and layers, and send it typed edits.

Krita does the painting; this screen talks to the AI panel inside it through the engine
(/api/krita). The canvas, layers and activity are read every two seconds while the screen
is on view, and the preview picture is fetched only when Krita reports a new one.
"""

import json
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QInputDialog,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import Box, Flow, PageHeader, Section, Thumb
from image_studio.desktop.edit import PICTURES, check_size
from image_studio.desktop.engine import in_background
from image_studio.desktop.library import searchable
from image_studio.desktop.photocraft import DocumentCanvas, ElidedLabel, png_bytes
from image_studio.desktop.library import save_to
from image_studio.desktop.projects import NewProjectDialog, ProjectAssets, ProjectHome
from image_studio.desktop.theme import label

POLL_MS = 2000
MAX_PROMPT = 6000
BLANK = '1024 × 1024'
KRITA_DOWNLOAD = 'https://krita.org/en/download/'
IMPORTED = re.compile(r'^import-[a-f0-9]{32}\.png$')
PICKER_LIMIT = 60


def document_name(name):
    return 'Imported image' if IMPORTED.match(name or '') else name or 'Untitled'


def event_text(event):
    return str(event.get('text') or event.get('message') or event.get('kind') or 'Canvas updated')


class LibraryPicker(QDialog):
    """Choose a library picture to open in Krita, with a search over the prompts."""

    def __init__(self, parent, library):
        super().__init__(parent)
        self.library, self.chosen = library, None
        self.setWindowTitle('Open from your library')
        self.resize(760, 560)
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 18)
        column.setSpacing(10)
        column.addWidget(label('Open from your library', 'heading'))
        column.addWidget(label('Choose a picture to open as a new document in Krita.', 'muted'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search your pictures…')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(theme.icon('search', theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.show_items)
        column.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_box = Box()
        self.grid = Flow(10)
        self.grid_box.setLayout(self.grid)
        scroll.setWidget(self.grid_box)
        column.addWidget(scroll, 1)
        self.empty = label('', 'muted')
        column.addWidget(self.empty)
        self.show_items()

    def show_items(self):
        while self.grid.count():
            self.grid.takeAt(0).widget().setParent(None)
        words = self.search.text().lower().split()
        items = sorted(self.library.all, key=lambda item: item['created'], reverse=True)
        matching = [item for item in items if all(word in searchable(item) for word in words)]
        for item in matching[:PICKER_LIMIT]:
            thumb = Thumb(self.library.model, 132)
            thumb.setFixedWidth(132)
            thumb.set_item(item)
            thumb.clicked.connect(lambda _=False, item=item: self.choose(item))
            self.grid.addWidget(thumb)
        self.grid_box.updateGeometry()
        if not items:
            self.empty.setText('Your library is empty. Open a picture from this PC, or create one first.')
        elif not matching:
            self.empty.setText('No pictures match your search.')
        elif len(matching) > PICKER_LIMIT:
            self.empty.setText(f'Showing the newest {PICKER_LIMIT} of {len(matching)}. Search to find others.')
        self.empty.setVisible(not matching or len(matching) > PICKER_LIMIT)

    def choose(self, item):
        self.chosen = item
        self.accept()


class KritaCanvas(DocumentCanvas):
    @property
    def pixmap(self):
        return self.current

    def set_pixmap(self, pixmap):
        self.current = pixmap
        if pixmap is None:
            self.set_document(None)
            self.set_layers([], None)
        self.update()


class KritaPage(QWidget):
    def __init__(self, client, library, notify):
        super().__init__()
        self.client, self.library, self.notify = client, library, notify
        self.ready = False
        self.config = None
        self.state = None  # the engine's /api/krita answer
        self.lost = False  # the engine stopped answering
        self.sending = False
        self.project, self.home_mode = None, True
        self.projection_key = None
        self.preview_version = None
        self.setAcceptDrops(True)
        self.poller = QTimer(self)
        self.poller.setInterval(POLL_MS)
        self.poller.timeout.connect(self.poll)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.views = QStackedWidget()
        outer.addWidget(self.views)
        self.home = ProjectHome(client, 'Krita', self.new_project, self.open_project_file,
                                self.choose_file, self.open_project)
        self.views.addWidget(self.home)
        self.editor = QWidget()
        self.views.addWidget(self.editor)
        self.home_launch = QPushButton(theme.icon('external-link'), 'Open Krita to connect')
        self.home_launch.clicked.connect(lambda: self.command('launch'))
        self.home.layout().insertWidget(2, self.home_launch, 0, Qt.AlignmentFlag.AlignLeft)
        self.capture = QPushButton('Save the open Krita canvas as a project…')
        self.capture.clicked.connect(self.capture_project)
        self.home.layout().insertWidget(3, self.capture, 0, Qt.AlignmentFlag.AlignLeft)
        outer = QVBoxLayout(self.editor)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = PageHeader('Krita')
        self.project_home_button = QPushButton(theme.icon('folder-open'), 'Projects')
        self.project_home_button.clicked.connect(self.close_project)
        self.header.add(self.project_home_button)
        self.title = ElidedLabel('', 'muted')
        self.header.actions.insertWidget(3, self.title, 1)
        self.dimensions = label('', 'small')
        self.header.add(self.dimensions)
        self.project_menu_button = QToolButton()
        self.project_menu_button.setText('Project')
        self.project_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_menu = QMenu(self)
        self.project_menu.aboutToShow.connect(self.fill_project_menu)
        self.project_menu_button.setMenu(self.project_menu)
        self.header.add(self.project_menu_button)
        outer.addWidget(self.header)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        outer.addLayout(layout, 1)
        layout.addWidget(self.canvas_area(), 1)
        layout.addWidget(self.panel())
        QShortcut(QKeySequence('Ctrl+Return'), self, self.send_prompt)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.send_prompt)
        QShortcut(QKeySequence.StandardKey.Paste, self, self.paste)
        QShortcut(QKeySequence('Ctrl+N'), self, self.new_project)
        QShortcut(QKeySequence('Ctrl+O'), self, self.open_project_file)
        QShortcut(QKeySequence('Ctrl+S'), self, lambda: self.project_action('save'))
        QShortcut(QKeySequence('Ctrl+W'), self, self.close_project)
        self.render()

    # Layout ----------------------------------------------------------------------------

    def canvas_area(self):
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(20, 18, 20, 14)
        column.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(label('Drag an image to move it; drag a corner to resize.', 'small'), 1)
        self.clear_canvas_button = QPushButton(theme.icon('eraser'), 'Clear canvas')
        self.clear_canvas_button.clicked.connect(lambda: self.project_action('clear'))
        row.addWidget(self.clear_canvas_button)
        column.addLayout(row)

        self.stage = QStackedLayout()
        self.preview = KritaCanvas()
        self.preview.placed.connect(lambda ident, values: self.layer_action(ident, 'transform', **values))
        self.preview.selected.connect(lambda ident: self.layer_action(ident, 'select'))
        self.preview.asset_dropped.connect(self.place_asset_at)
        self.stage.addWidget(self.preview)
        empty = QFrame()
        empty.setProperty('stage', True)
        inside = QVBoxLayout(empty)
        inside.addStretch(1)
        self.empty_icon = QPushButton(theme.icon('image-plus', theme.MUTED), '')
        self.empty_icon.setProperty('kind', 'flat')
        self.empty_icon.setIconSize(QSize(40, 40))
        self.empty_icon.setEnabled(False)
        inside.addWidget(self.empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = label('', 'heading')
        self.empty_text = label('', 'muted', wrap=True)
        for widget in (self.empty_title, self.empty_text):
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            inside.addWidget(widget)
        inside.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.empty_open = QPushButton(theme.icon('upload', theme.ON_ACCENT), 'Open a picture…')
        self.empty_open.setProperty('kind', 'primary')
        self.empty_open.clicked.connect(self.choose_file)
        buttons.addWidget(self.empty_open)
        self.empty_library = QPushButton(theme.icon('images'), 'From the library')
        self.empty_library.clicked.connect(self.choose_library)
        buttons.addWidget(self.empty_library)
        self.get_krita = QPushButton(theme.icon('external-link', theme.ON_ACCENT), 'Get Krita (free)')
        self.get_krita.setProperty('kind', 'primary')
        self.get_krita.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KRITA_DOWNLOAD)))
        buttons.addWidget(self.get_krita)
        buttons.addStretch()
        inside.addLayout(buttons)
        inside.addStretch(2)
        self.stage.addWidget(empty)
        column.addLayout(self.stage, 1)
        self.assets = ProjectAssets(self.client, self.place_asset, self.choose_layers)
        column.addWidget(self.assets)

        foot = QHBoxLayout()
        self.caption = label('', 'small')
        foot.addWidget(self.caption, 1)
        self.selection = label('Selection active', 'badge')
        self.selection.setToolTip('Your typed edit will only change the area selected in Krita.')
        foot.addWidget(self.selection)
        column.addLayout(foot)
        return area

    def panel(self):
        panel = QWidget()
        panel.setObjectName('Panel')
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        panel.setFixedWidth(340)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = Box()
        scroll.setWidget(content)
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 20, 18, 18)
        column.setSpacing(10)

        row = QHBoxLayout()
        self.connection = label('')
        self.connection.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.connection, 1)
        self.launch = QPushButton(theme.icon('external-link'), 'Open Krita')
        self.launch.setToolTip('Start Krita with the AI panel, or bring it to the front.')
        self.launch.clicked.connect(lambda: self.command('launch'))
        row.addWidget(self.launch)
        column.addLayout(row)
        self.connection_note = label('', 'small', wrap=True)
        column.addWidget(self.connection_note)

        column.addSpacing(6)
        column.addWidget(label('Open', 'eyebrow'))
        row = QHBoxLayout()
        self.open_file = QPushButton(theme.icon('upload'), 'Open picture…')
        self.open_file.setToolTip('A picture from this PC, as a new Krita document. You can also drop or paste one.')
        self.open_file.clicked.connect(self.choose_file)
        self.from_library = QPushButton(theme.icon('images'), 'From library')
        self.from_library.clicked.connect(self.choose_library)
        row.addWidget(self.open_file)
        row.addWidget(self.from_library)
        column.addLayout(row)
        self.add_images = QPushButton(theme.icon('plus'), 'Import project images…')
        self.add_images.setToolTip('Keep source images in the project. Choose Place when you want an image on the canvas.')
        self.add_images.clicked.connect(self.choose_layers)
        column.addWidget(self.add_images)
        self.blank = QPushButton(theme.icon('plus'), 'New project…')
        self.blank.setProperty('kind', 'flat')
        self.blank.clicked.connect(self.new_project)
        column.addWidget(self.blank, 0, Qt.AlignmentFlag.AlignLeft)

        column.addSpacing(6)
        column.addWidget(label('What to change', 'eyebrow'))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText('Make the background warmer and bring out the details…')
        self.prompt.setFixedHeight(110)
        self.prompt.textChanged.connect(self.prompt_changed)
        column.addWidget(self.prompt)
        self.hint = label('', 'small', wrap=True)
        column.addWidget(self.hint)
        self.send = QPushButton(theme.icon('send', theme.ON_ACCENT), 'Send to canvas')
        self.send.setProperty('kind', 'primary')
        self.send.setProperty('size', 'large')
        self.send.clicked.connect(self.send_prompt)
        column.addWidget(self.send)
        row = QHBoxLayout()
        self.undo = QPushButton(theme.icon('undo-2'), 'Undo')
        self.undo.clicked.connect(lambda: self.command('undo'))
        self.stop = QPushButton(theme.icon('square'), 'Stop')
        self.stop.setToolTip('Stop the edit Krita is working on.')
        self.stop.clicked.connect(lambda: self.command('stop'))
        self.save = QPushButton(theme.icon('save'), 'Save')
        self.save.setToolTip('Save the canvas to My library.')
        self.save.clicked.connect(lambda: self.command('save'))
        for widget in (self.undo, self.stop, self.save):
            row.addWidget(widget)
        column.addLayout(row)

        column.addSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label('Layers', 'value'))
        self.layer_count = label('', 'small')
        head.addWidget(self.layer_count)
        head.addStretch()
        column.addLayout(head)
        self.layers = QVBoxLayout()
        self.layers.setSpacing(2)
        column.addLayout(self.layers)
        self.layers_note = label('', 'small', wrap=True)
        column.addWidget(self.layers_note)

        self.activity = Section('Canvas activity', 'history')
        self.activity_list = QVBoxLayout()
        self.activity_list.setSpacing(4)
        self.activity.body.addLayout(self.activity_list)
        column.addWidget(self.activity)
        column.addStretch()
        return panel

    # Engine ----------------------------------------------------------------------------

    def engine_ready(self):
        self.ready = True
        self.load_projects()
        self.client.get('/api/config', self.configured, None)
        self.refresh()

    def engine_gone(self):
        self.ready = False
        self.poller.stop()
        self.sending = False
        self.render()

    def configured(self, config):
        self.config = config or {}
        self.render()

    def refresh(self):
        """Follow Krita while this screen is on view, and refresh the saved project list."""
        if self.ready:
            self.load_projects()
        if self.ready and self.isVisible():
            self.poll()
            self.poller.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.poller.stop()

    def poll(self):
        if not self.ready:
            return
        self.client.get('/api/krita', self.got_state, self.poll_failed, timeout=POLL_MS * 2)

    def got_state(self, state):
        self.state, self.lost = state or {}, False
        active_project = self.state.get('project')
        if active_project and self.project and not self.home_mode and not self.sending:
            self.project = active_project
        version = self.state.get('preview_version')
        if self.has_document and self.state.get('preview') and version != self.preview_version:
            self.preview_version = version
            self.client.bytes(f'/api/krita/preview?v={version}', self.got_preview, None, timeout=20000)
        self.render()

    def poll_failed(self, _):
        self.lost = True
        self.render()

    def got_preview(self, data):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            document = self.document
            if document and self.preview.transform is None:
                self.preview.set_document(QSize(document['width'], document['height']))
                self.preview.set_layers(document.get('layers', []), document.get('activeLayer'), self.preview_version)
            self.preview.set_pixmap(pixmap)
            self.fetch_layer_projection()
            self.render()

    # Showing ---------------------------------------------------------------------------

    @property
    def installed(self):
        return bool((self.config or {}).get('krita', True))

    @property
    def connected(self):
        return self.ready and not self.lost and bool((self.state or {}).get('connected'))

    @property
    def document(self):
        return (self.state or {}).get('state')

    @property
    def has_document(self):
        return self.connected and bool(self.document) and (self.project is None or
            (self.state.get('project') or {}).get('id') == self.project['id'])

    def render(self):
        connected, document = self.connected, self.document
        has_document = self.has_document
        self.views.setCurrentIndex(0 if self.home_mode else 1)
        self.home.set_ready(self.ready and self.installed and connected, self.sending)
        self.home_launch.setEnabled(self.ready and self.installed and not self.sending)
        self.home_launch.setVisible(not connected)
        self.capture.setVisible(connected and bool(document) and self.state.get('project') is None)
        self.capture.setEnabled(not self.sending)
        self.home.note.setText('Waiting for Krita to save and confirm the project…' if self.sending else
                              'Projects, layers and source images are saved together. Save a project file for a portable copy.'
                               if connected else 'Open Krita above to start or resume a project. Your saved projects stay on this computer.')
        self.project_home_button.setEnabled(not self.sending)
        self.project_menu_button.setEnabled(not self.sending)
        self.clear_canvas_button.setEnabled(bool(self.project) and has_document and not self.sending)
        self.assets.setVisible(bool(self.project))
        self.assets.show_assets((self.project or {}).get('assets', []), self.sending)
        self.preview.arranging = bool(self.project and not self.sending and connected)
        if not self.ready:
            dot, text, note = theme.DANGER, 'The engine is not running', ''
        elif not self.installed:
            dot, text, note = theme.DANGER, 'Krita is not installed', ''
        elif self.lost:
            dot, text, note = theme.WARN, 'Connection lost. Retrying…', ''
        elif connected:
            dot, text, note = theme.ACCENT, 'Krita connected', ''
        else:
            dot, text, note = theme.MUTED, 'Krita is not open', ''
        self.connection.setText(f'<span style="color:{dot}">●</span>&nbsp; {text}')
        self.connection_note.setText(note)
        self.connection_note.setVisible(bool(note))

        usable = self.ready and self.installed and not self.sending
        self.launch.setEnabled(usable)
        for widget in (self.open_file, self.from_library, self.empty_open, self.empty_library):
            widget.setEnabled(usable)
        self.blank.setEnabled(usable and connected)
        self.add_images.setEnabled(bool(usable and has_document and self.project))
        self.send.setEnabled(usable and connected and bool(self.prompt.toPlainText().strip()))
        self.undo.setEnabled(usable and has_document)
        self.save.setEnabled(usable and has_document)
        self.stop.setEnabled(self.ready and connected)
        self.send.setText('Sending…' if self.sending else 'Send to canvas')

        self.title.setText(self.project['name'] if self.project else document_name(document['name']) if has_document else 'No project open')
        saved = 'Save failed — retry Save' if document and document.get('save_error') else (
            'Saving…' if self.sending or document and document.get('modified') else 'Saved on this computer')
        self.dimensions.setToolTip((document or {}).get('save_error') or '')
        self.dimensions.setText(f'{document["width"]} × {document["height"]} · {saved}' if has_document and self.project else '')
        shown = has_document and (self.state or {}).get('preview') and self.preview.pixmap is not None
        self.stage.setCurrentIndex(0 if shown else 1)
        installing = self.ready and not self.installed
        self.get_krita.setVisible(installing)
        self.empty_open.setVisible(not installing and not has_document)
        self.empty_library.setVisible(not installing and not has_document)
        if installing:
            self.empty_title.setText('Krita is not on this PC yet')
            self.empty_text.setText('Krita is a free painting app.')
        elif has_document:
            self.empty_title.setText('Waiting for the preview')
            self.empty_text.setText('')
        else:
            self.empty_title.setText('Open a picture in Krita')
            self.empty_text.setText('')
        self.empty_text.setVisible(bool(self.empty_text.text()))
        self.caption.setText('Reconnect Krita to see the current canvas.' if document and not connected else '')
        self.caption.setVisible(bool(self.caption.text()))
        self.selection.setVisible(has_document and bool(document.get('selection')))
        self.hint.setText('Uses the selection made in Krita.' if connected and has_document
                          and document.get('selection') else '')
        self.hint.setVisible(bool(self.hint.text()))
        self.send.setToolTip('Ctrl + Enter')
        self.show_layers(document if has_document else None)
        self.show_activity()

    def show_layers(self, document):
        layers = (document or {}).get('layers') or []
        key = json.dumps([layers, self.sending, (self.project or {}).get('id')], sort_keys=True)
        if getattr(self, 'layers_key', None) == key:
            return
        self.layers_key = key
        while self.layers.count():
            self.layers.takeAt(0).widget().deleteLater()
        self.layer_count.setText(str(len(layers)) if layers else '')
        for layer in layers:
            row = QHBoxLayout()
            box = Box()
            box.setLayout(row)
            row.setContentsMargins(6 + min(layer.get('depth', 0), 5) * 12, 3, 6, 3)
            eye = QToolButton()
            eye.setIcon(theme.icon('eye' if layer.get('visible') else 'eye-off', theme.MUTED))
            eye.setToolTip('Visible' if layer.get('visible') else 'Hidden')
            eye.setEnabled(bool(self.project and layer.get('id') and not self.sending and not layer.get('locked')))
            eye.clicked.connect(lambda _=False, item=layer: self.layer_action(item['id'], 'visibility', visible=not item.get('visible')))
            row.addWidget(eye)
            name = QPushButton(layer.get('name') or 'Layer')
            name.setFlat(True)
            name.setEnabled(bool(self.project and layer.get('id') and not self.sending))
            name.clicked.connect(lambda _=False, item=layer: self.layer_action(item['id'], 'select'))
            row.addWidget(name, 1)
            if layer.get('active'):
                row.addWidget(label('Active', 'small'))
                box.setObjectName('ActiveLayer')
                box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
                box.setStyleSheet(f'#ActiveLayer {{ background: {theme.RAISED}; border-radius: 6px; }} '
                                  'QLabel { background: transparent; }')
            self.layers.addWidget(box)
        self.layers_note.setText('' if layers else 'No layers yet')
        self.layers_note.setVisible(not layers)

    def show_activity(self):
        events = (self.state or {}).get('events') or []
        self.activity.setVisible(bool(events))
        if not events:
            return
        latest = event_text(events[-1])
        self.activity.header.setText(f'  Canvas activity · {latest[:28]}{"…" if len(latest) > 28 else ""}')
        while self.activity_list.count():
            self.activity_list.takeAt(0).widget().setParent(None)
        for event in reversed(events[-10:]):
            line = label(event_text(event), 'error' if event.get('kind') == 'failed' else 'small', wrap=True)
            self.activity_list.addWidget(line)

    # Commands --------------------------------------------------------------------------

    def prompt_changed(self):
        text = self.prompt.toPlainText()
        if len(text) > MAX_PROMPT:
            self.prompt.setPlainText(text[:MAX_PROMPT])
            return
        self.render()

    def command(self, action, **values):
        if self.sending or not self.ready:
            return
        self.sending = True
        self.render()

        def done(answer):
            self.sending = False
            self.notify((answer or {}).get('message') or 'Sent to Krita.')
            if action == 'prompt':
                self.prompt.clear()
            self.render()
            self.poll()

        def failed(error):
            self.sending = False
            self.notify(error, error=True)
            self.render()

        body = dict(action=action, **values)
        if action == 'prompt':
            body['text'] = self.prompt.toPlainText().strip()
        self.client.post('/api/krita', body, done, failed, timeout=120000)

    def send_prompt(self):
        if self.send.isEnabled():
            self.command('prompt')

    def choose_file(self):
        if not self.open_file.isEnabled():
            return
        start = Path.home() / 'Pictures'
        path, _ = QFileDialog.getOpenFileName(self, 'Open a picture in Krita', str(start if start.is_dir() else ''),
                                              PICTURES)
        if path:
            self.open_project_path(path)

    def import_file(self, path):
        self.open_project_path(path)

    def choose_layers(self):
        if not self.add_images.isEnabled():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add images as layers', '', PICTURES)
        if paths:
            self.import_layers(paths)

    def import_layers(self, paths=None, image=None):
        if self.sending or not self.ready or not self.has_document:
            return
        try:
            files, total = [], 0
            if image is not None:
                files = [('Pasted image.png', png_bytes(check_size(image)))]
            else:
                if not 1 <= len(paths or []) <= 16:
                    raise ValueError('Choose between 1 and 16 images at a time.')
                for value in paths:
                    path = Path(value)
                    total += path.stat().st_size
                    if total > 100_000_000 or path.stat().st_size == 0:
                        raise ValueError('Choose nonempty files totaling at most 100 MB.')
                    files.append((path.name, path.read_bytes()))
        except (OSError, ValueError) as exc:
            self.notify(str(exc), error=True)
            return
        self.sending = True
        self.render()

        def done(answer):
            self.sending = False
            self.notify(answer['message'])
            self.render()
            self.poll()

        def failed(error):
            self.sending = False
            self.notify(error, error=True)
            self.render()

        if self.project:
            def project_done(answer):
                self.project = answer['project']
                done(answer)
            self.client.upload_files(f'/api/krita/projects/{self.project["id"]}/assets', files, project_done, failed)
        else:
            failed('Save this canvas as a project first, so its source images can be kept together.')

    def import_image(self, image):
        """A picture from this PC: sent to the engine, which saves a PNG copy and opens it in Krita."""
        if self.sending or not self.ready or not self.installed:
            return
        self.sending = True
        self.render()

        def prepared(value, error):
            if error is not None:
                self.sending = False
                self.notify(str(error), error=True)
                self.render()
                return
            def done(answer):
                self.sending = False
                self.project, self.home_mode = answer['project'], False
                self.preview.set_pixmap(None)
                self.preview_version = None
                self.render()
                self.poll()
                self.load_projects()
            def failed(error):
                self.sending = False
                self.notify(error, error=True)
                self.render()
            self.client.upload('/api/krita/projects/import', 'Pasted image.png', value, done, failed)

        in_background(lambda: png_bytes(image), prepared)

    def choose_library(self):
        if not self.from_library.isEnabled():
            return
        picker = LibraryPicker(self, self.library)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.chosen is not None:
            self.open_item(picker.chosen)

    def open_item(self, item):
        """A library picture: the engine opens its file directly, so nothing is uploaded."""
        self.project_post('/api/krita/projects/from-library', dict(name=item['name']))

    def load_projects(self):
        self.client.get('/api/krita/projects', lambda answer: self.home.set_projects(answer.get('projects', [])), None)

    def project_post(self, path, body, after=None):
        if self.sending or not self.ready:
            return
        self.sending = True
        self.render()
        def done(answer):
            self.sending = False
            if answer.get('closed'):
                self.home_mode, self.project = True, None
                self.preview.transform = None
            elif answer.get('project'):
                if not self.project or self.project['id'] != answer['project']['id']:
                    self.preview.set_pixmap(None)
                    self.preview_version = None
                self.project, self.home_mode = answer['project'], False
            self.preview.transform = None
            self.projection_key = None
            self.notify(answer.get('message') or 'Project saved.')
            if after:
                after(answer)
            self.load_projects()
            self.render()
            self.poll()
        def failed(error):
            self.sending = False
            self.preview.transform = None
            self.notify(error, error=True)
            self.render()
        self.client.post(path, body, done, failed, timeout=120000)

    def new_project(self):
        if not self.connected or self.sending:
            self.notify('Open Krita to connect first.', error=True)
            return
        dialog = NewProjectDialog(self, 'Krita')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.project_post('/api/krita/projects', dialog.values())

    def capture_project(self):
        name, okay = QInputDialog.getText(self, 'Save canvas as a project', 'Project name', text='Untitled project')
        if okay and name.strip():
            self.project_post('/api/krita/projects', dict(name=name.strip(), use_current=True))

    def open_project(self, ident):
        self.project_post(f'/api/krita/projects/{ident}/action', dict(action='open'))

    def project_action(self, action):
        if self.project:
            self.project_post(f'/api/krita/projects/{self.project["id"]}/action', dict(action=action))

    def close_project(self):
        if self.project and self.has_document:
            self.project_action('close')
        elif not self.sending:
            self.project = None
            self.home_mode = True
            self.render()

    def open_project_file(self):
        if self.sending or not self.ready:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Open a Krita project', '',
                                              'Image Studio or Krita project (*.istudio *.kra)')
        if path:
            self.open_project_path(path)

    def open_project_path(self, value):
        if self.sending or not self.ready:
            return
        path = Path(value)
        try:
            if not 0 < path.stat().st_size <= 500_000_000:
                raise ValueError('Choose a project under 500 MB.')
        except (OSError, ValueError) as exc:
            self.notify(str(exc), error=True)
            return
        self.sending = True
        self.render()
        def prepared(data, error):
            if error is not None:
                failed(str(error))
                return
            self.client.upload('/api/krita/projects/import', path.name, data, done, failed)
        def done(answer):
            self.sending = False
            self.project, self.home_mode = answer['project'], False
            self.preview.set_pixmap(None)
            self.preview_version = None
            self.projection_key = None
            self.notify(answer.get('message') or 'Project opened.')
            self.render()
            self.poll()
            self.load_projects()
        def failed(error):
            self.sending = False
            self.notify(error, error=True)
            self.render()
        in_background(path.read_bytes, prepared)

    def fill_project_menu(self):
        menu = self.project_menu
        menu.clear()
        menu.addAction('New project…', self.new_project)
        menu.addAction('Open project file…', self.open_project_file)
        menu.addSeparator()
        menu.addAction('Save now', lambda: self.project_action('save')).setEnabled(bool(self.project))
        menu.addAction('Save project file…', self.save_project_file).setEnabled(bool(self.project))
        menu.addAction('Rename project…', self.rename_project).setEnabled(bool(self.project))
        menu.addAction('Clear canvas', lambda: self.project_action('clear')).setEnabled(bool(self.project))
        menu.addAction('Restore previous canvas', lambda: self.project_action('restore')).setEnabled(bool((self.project or {}).get('can_restore')))
        menu.addSeparator()
        menu.addAction('Close project', self.close_project)

    def rename_project(self):
        if self.project:
            name, okay = QInputDialog.getText(self, 'Rename project', 'Project name', text=self.project['name'])
            if okay and name.strip():
                self.project_post(f'/api/krita/projects/{self.project["id"]}/rename', dict(name=name.strip()))

    def save_project_file(self):
        if self.project and not self.sending:
            save_to(self, self.client, self.notify, f'/api/krita/projects/{self.project["id"]}/file',
                    self.project['name'], '.istudio', 'Save portable Krita project')

    def place_asset(self, asset, fit=False, as_canvas=False, x=None, y=None):
        if self.project:
            self.project_post(f'/api/krita/projects/{self.project["id"]}/assets/{asset["id"]}/place',
                              dict(fit=fit, as_canvas=as_canvas, x=x, y=y))

    def place_asset_at(self, ident, x, y):
        asset = next((a for a in (self.project or {}).get('assets', []) if a['id'] == ident), None)
        if asset:
            self.place_asset(asset, x=x, y=y)

    def layer_action(self, ident, operation, **values):
        if self.project and ident:
            self.project_post(f'/api/krita/projects/{self.project["id"]}/layers/{ident}', dict(operation=operation, **values))

    def fetch_layer_projection(self):
        if not self.project or not self.document:
            return
        active = self.document.get('activeLayer')
        if not active:
            return
        key = (self.project['id'], self.preview_version, active)
        if key == self.projection_key:
            return
        self.projection_key = key
        for part in ('below', 'image', 'above'):
            def loaded(data, part=part):
                if self.projection_key != key:
                    return
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    self.preview.projections[part] = pixmap
                    self.preview.update()
            self.client.bytes(f'/api/krita/projects/{key[0]}/layers/{active}/preview/{key[1]}/{part}', loaded, None, timeout=120000)

    def paste(self):
        if not self.take(QGuiApplication.clipboard().mimeData()):
            self.notify('The clipboard has no picture in it.', error=True)

    def take(self, mime):
        if mime is None or self.sending or not self.ready:
            return False
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        if paths:
            if len(paths) == 1 and Path(paths[0]).suffix.lower() in {'.istudio', '.kra'}:
                self.open_project_path(paths[0])
                return True
            if self.has_document:
                self.import_layers(paths)
            elif len(paths) == 1:
                self.import_file(paths[0])
            else:
                self.notify('Open a background first, then add or drop the other images as layers.', error=True)
            return True
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                try:
                    if self.has_document:
                        self.import_layers(image=image)
                    else:
                        self.import_image(check_size(image))
                except ValueError as exc:
                    self.notify(str(exc), error=True)
                return True
        return False

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if self.ready and self.installed and not self.sending and (
                mime.hasImage() or any(url.isLocalFile() for url in mime.urls())):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.take(event.mimeData()):
            event.acceptProposedAction()

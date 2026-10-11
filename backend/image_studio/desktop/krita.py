"""Krita canvas: open pictures in Krita, follow its live canvas and layers, and send it typed edits.

Krita does the painting; this screen talks to the AI panel inside it through the engine
(/api/krita). The canvas, layers and activity are read every two seconds while the screen
is on view, and the preview picture is fetched only when Krita reports a new one.
"""

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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import Box, Flow, Section, Thumb
from image_studio.desktop.edit import PICTURES, check_size, encode, read_picture
from image_studio.desktop.engine import in_background
from image_studio.desktop.library import ImageView, prompt_of, searchable
from image_studio.desktop.photocraft import ElidedLabel
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


class KritaPage(QWidget):
    def __init__(self, client, library, notify):
        super().__init__()
        self.client, self.library, self.notify = client, library, notify
        self.ready = False
        self.config = None
        self.state = None  # the engine's /api/krita answer
        self.lost = False  # the engine stopped answering
        self.sending = False
        self.preview_version = None
        self.setAcceptDrops(True)
        self.poller = QTimer(self)
        self.poller.setInterval(POLL_MS)
        self.poller.timeout.connect(self.poll)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas_area(), 1)
        layout.addWidget(self.panel())
        QShortcut(QKeySequence('Ctrl+Return'), self, self.send_prompt)
        QShortcut(QKeySequence('Ctrl+Enter'), self, self.send_prompt)
        QShortcut(QKeySequence.StandardKey.Paste, self, self.paste)
        self.render()

    # Layout ----------------------------------------------------------------------------

    def canvas_area(self):
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(32, 26, 24, 18)
        column.setSpacing(6)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.eyebrow = label('YOUR CANVAS', 'eyebrow')
        titles.addWidget(self.eyebrow)
        self.title = ElidedLabel('Start with an image', 'title')
        titles.addWidget(self.title)
        head.addLayout(titles, 1)
        self.dimensions = label('', 'muted')
        head.addWidget(self.dimensions, 0, Qt.AlignmentFlag.AlignBottom)
        column.addLayout(head)
        column.addSpacing(8)

        self.stage = QStackedLayout()
        self.preview = ImageView()
        self.stage.addWidget(self.preview)
        empty = QFrame()
        empty.setProperty('card', True)
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
        self.empty_open = QPushButton(theme.icon('upload', theme.INK), 'Open a picture…')
        self.empty_open.setProperty('kind', 'primary')
        self.empty_open.clicked.connect(self.choose_file)
        buttons.addWidget(self.empty_open)
        self.empty_library = QPushButton(theme.icon('images'), 'From your library')
        self.empty_library.clicked.connect(self.choose_library)
        buttons.addWidget(self.empty_library)
        self.get_krita = QPushButton(theme.icon('external-link', theme.INK), 'Get Krita (free)')
        self.get_krita.setProperty('kind', 'primary')
        self.get_krita.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KRITA_DOWNLOAD)))
        buttons.addWidget(self.get_krita)
        buttons.addStretch()
        inside.addLayout(buttons)
        inside.addStretch(2)
        self.stage.addWidget(empty)
        column.addLayout(self.stage, 1)

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
        column.addWidget(label('Add to your workspace', 'value'))
        row = QHBoxLayout()
        self.open_file = QPushButton(theme.icon('upload'), 'Open picture…')
        self.open_file.setToolTip('A picture from this PC, as a new Krita document. You can also drop or paste one.')
        self.open_file.clicked.connect(self.choose_file)
        self.from_library = QPushButton(theme.icon('images'), 'From library')
        self.from_library.clicked.connect(self.choose_library)
        row.addWidget(self.open_file)
        row.addWidget(self.from_library)
        column.addLayout(row)
        self.blank = QPushButton(theme.icon('plus'), f'New blank canvas  ({BLANK})')
        self.blank.setProperty('kind', 'flat')
        self.blank.clicked.connect(lambda: self.command('new_canvas'))
        column.addWidget(self.blank, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(label('Opens a new document. Your current canvas stays open in Krita.', 'small', wrap=True))

        column.addSpacing(6)
        column.addWidget(label('What would you like to change?', 'value'))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText('Make the background warmer and bring out the details…')
        self.prompt.setFixedHeight(110)
        self.prompt.textChanged.connect(self.prompt_changed)
        column.addWidget(self.prompt)
        self.hint = label('', 'small', wrap=True)
        column.addWidget(self.hint)
        self.send = QPushButton(theme.icon('send', theme.INK), 'Send to canvas')
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
        """Called when the screen is shown: follow Krita while it is on view."""
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
            self.preview.set_pixmap(pixmap)
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
        return self.connected and bool(self.document)

    def render(self):
        connected, document = self.connected, self.document
        has_document = self.has_document
        if not self.ready:
            dot, text = theme.DANGER, 'The engine is not running'
            note = 'Krita connects through the engine. This PC can restart it.'
        elif not self.installed:
            dot, text = theme.DANGER, 'Krita is not installed'
            note = 'Krita is a free painting app. Install it, then come back here and click Open Krita.'
        elif self.lost:
            dot, text, note = theme.WARN, 'Connection lost. Retrying…', ''
        elif connected:
            dot, text, note = theme.LIME, 'Krita connected', ''
        else:
            dot, text = theme.MUTED, 'Krita is not open'
            note = 'Open Krita to connect. Its AI panel starts with it.'
        self.connection.setText(f'<span style="color:{dot}">●</span>&nbsp; {text}')
        self.connection_note.setText(note)
        self.connection_note.setVisible(bool(note))

        usable = self.ready and self.installed and not self.sending
        self.launch.setEnabled(usable)
        for widget in (self.open_file, self.from_library, self.empty_open, self.empty_library):
            widget.setEnabled(usable)
        self.blank.setEnabled(usable and connected)
        self.send.setEnabled(usable and connected and bool(self.prompt.toPlainText().strip()))
        self.undo.setEnabled(usable and has_document)
        self.save.setEnabled(usable and has_document)
        self.stop.setEnabled(self.ready and connected)
        self.send.setText('Sending…' if self.sending else 'Send to canvas')

        self.eyebrow.setText('ACTIVE DOCUMENT' if has_document else 'YOUR CANVAS')
        self.title.setText(document_name(document['name']) if has_document else 'Start with an image')
        self.dimensions.setText(f'{document["width"]} × {document["height"]}' if has_document else '')
        shown = has_document and (self.state or {}).get('preview') and self.preview.pixmap is not None
        self.stage.setCurrentIndex(0 if shown else 1)
        installing = self.ready and not self.installed
        self.get_krita.setVisible(installing)
        self.empty_open.setVisible(not installing and not has_document)
        self.empty_library.setVisible(not installing and not has_document)
        if installing:
            self.empty_title.setText('Krita is not on this PC yet')
            self.empty_text.setText('Krita is a free painting app. Once it is installed, pictures open here as '
                                    'Krita documents and you can edit them by typing.')
        elif has_document:
            self.empty_title.setText('Your preview is on its way')
            self.empty_text.setText('Your canvas appears here as Krita updates.')
        else:
            self.empty_title.setText('A place for your next idea')
            self.empty_text.setText('Drop or paste a picture here, or open one, to start a new document in Krita.')
        if has_document:
            self.caption.setText('Live preview · Paint and select areas in Krita.')
        elif document and not connected:
            self.caption.setText('Reconnect Krita to see the current canvas and use the editing tools.')
        else:
            self.caption.setText('Pictures open as a new document in Krita.')
        self.selection.setVisible(has_document and bool(document.get('selection')))
        if not connected:
            self.hint.setText('Open Krita to send edits.')
        elif has_document and document.get('selection'):
            self.hint.setText('Your edit will use the selection made in Krita. Ctrl + Enter sends.')
        else:
            self.hint.setText('Describe an edit, or ask for a new image. Ctrl + Enter sends.')
        self.show_layers(document if has_document else None)
        self.show_activity()

    def show_layers(self, document):
        while self.layers.count():
            self.layers.takeAt(0).widget().setParent(None)
        layers = (document or {}).get('layers') or []
        self.layer_count.setText(str(len(layers)) if layers else '')
        for layer in layers:
            row = QHBoxLayout()
            box = Box()
            box.setLayout(row)
            row.setContentsMargins(6 + min(layer.get('depth', 0), 5) * 12, 3, 6, 3)
            eye = label('')
            eye.setPixmap(theme.icon('eye' if layer.get('visible') else 'eye-off', theme.MUTED).pixmap(14, 14))
            eye.setToolTip('Visible' if layer.get('visible') else 'Hidden')
            row.addWidget(eye)
            name = label(layer.get('name') or 'Layer', 'value' if layer.get('active') else '')
            row.addWidget(name, 1)
            if layer.get('active'):
                row.addWidget(label('Active', 'small'))
                box.setObjectName('ActiveLayer')
                box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
                box.setStyleSheet(f'#ActiveLayer {{ background: {theme.RAISED}; border-radius: 6px; }} '
                                  'QLabel { background: transparent; }')
            self.layers.addWidget(box)
        self.layers_note.setText('Manage layers in Krita.' if layers else 'Layers appear when a document is open.')

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
            self.import_file(path)

    def import_file(self, path):
        try:
            image = read_picture(path)
        except ValueError as exc:
            self.notify(str(exc), error=True)
            return
        self.import_image(image)

    def import_image(self, image):
        """A picture from this PC: sent to the engine, which saves a PNG copy and opens it in Krita."""
        if self.sending or not self.ready or not self.installed:
            return
        self.sending = True
        self.render()

        def prepared(value, error):
            self.sending = False
            if error is not None:
                self.notify(str(error), error=True)
                self.render()
                return
            self.command('import', image=value)

        in_background(lambda: encode(image), prepared)

    def choose_library(self):
        if not self.from_library.isEnabled():
            return
        picker = LibraryPicker(self, self.library)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.chosen is not None:
            self.open_item(picker.chosen)

    def open_item(self, item):
        """A library picture: the engine opens its file directly, so nothing is uploaded."""
        self.command('open', image=item['name'])
        self.notify(f'Opening “{(prompt_of(item) or item["name"])[:60]}” in Krita…')

    def paste(self):
        if not self.take(QGuiApplication.clipboard().mimeData()):
            self.notify('The clipboard has no picture in it.', error=True)

    def take(self, mime):
        if mime is None or self.sending or not self.ready:
            return False
        for url in mime.urls():
            if url.isLocalFile():
                self.import_file(url.toLocalFile())
                return True
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                try:
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

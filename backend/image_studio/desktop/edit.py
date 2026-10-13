"""Edit image: change a photo by describing it, optionally only inside an area you paint.

The same form as the web studio's Edit page, sending the same request to the engine.
"""

import base64
import json
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import Box, Flow, PageHeader, Range, Thumb, Toggle
from image_studio.desktop.create import MAX_PROMPT, POLL_MS, rule
from image_studio.desktop.engine import in_background
from image_studio.desktop.library import ImageView, save_to
from image_studio.desktop.theme import label

# id: (name, menu entry, what it does, the config flag that says it is installed, placeholder, ideas)
ENGINES = {
    'photocraft': (
        'PhotoCraft', 'PhotoCraft · light and color', 'Adjusts the whole photo in editable PSD layers.', 'photocraft',
        'Make it brighter and warmer, or try professional polish…',
        ['Professional polish', 'Warm portrait', 'Cinematic teal and orange', 'Soft faded film', 'Make it grayscale'],
    ),
    'kontext': (
        'FLUX.1 Kontext', 'FLUX.1 Kontext · change content', 'Adds, removes or replaces things. Runs on this PC.',
        'editing', 'Change the background to a sunlit garden. Keep the person and their expression…',
        ['Make it golden hour', 'Turn it into a watercolor', 'Remove the background'],
    ),
}
CLOUD_IDEAS = ['Make it golden hour', 'Remove the people in the background', 'Turn it into a watercolor']


def cloud_editor(engine, config):
    return next((entry for entry in (config or {}).get('cloud_editors') or [] if entry['id'] == engine), None)


def details(engine, config=None):
    """(name, menu entry, note, config flag, placeholder, ideas) for a tool, cloud editors included."""
    if engine in ENGINES:
        return ENGINES[engine]
    entry = cloud_editor(engine, config) or dict(label='Cloud', model=engine.partition(':')[2])
    return (entry['label'], f'{entry["label"]} · {entry["model"]}', f'Runs on {entry["label"]} with your API key. '
            'Changes the whole photo.', None, ENGINES['kontext'][4], CLOUD_IDEAS)
MAX_PIXELS = 25_000_000
MAX_UPLOAD = 38_000_000  # characters of data URL; the engine takes up to 40 million
PICTURES = 'Images (*.png *.jpg *.jpeg *.webp *.bmp)'


def installed(engine, config):
    if engine not in ENGINES:
        return bool((cloud_editor(engine, config) or {}).get('ready'))
    return bool((config or {}).get(ENGINES[engine][3]))


def choose_engine(config, saved):
    """The tool to start with: the one used last if it is installed, else PhotoCraft, else AI editing."""
    if saved and installed(saved, config):
        return saved
    return 'photocraft' if installed('photocraft', config) else 'kontext'


def read_picture(path):
    """A picture file as an upright QImage; ValueError says why it cannot be used."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # phone photos come out the right way up
    size = reader.size()
    if size.isValid() and size.width() * size.height() > MAX_PIXELS:
        raise ValueError('Please use a picture below 25 megapixels.')
    image = reader.read()
    if image.isNull():
        raise ValueError('That file is not a picture this app can read.')
    return image


def check_size(image):
    if image.width() * image.height() > MAX_PIXELS:
        raise ValueError('Please use a picture below 25 megapixels.')
    return image


def encode(image):
    """A picture as a data URL: PNG, or a fine JPEG when a PNG would be too large to send."""
    for kind, quality in (('PNG', -1), ('JPEG', 95)):
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        picture = image if kind == 'PNG' else image.convertToFormat(QImage.Format.Format_RGB32)
        picture.save(buffer, kind, quality)
        value = f'data:image/{kind.lower()};base64,' + base64.b64encode(bytes(buffer.data().data())).decode('ascii')
        if len(value) <= MAX_UPLOAD:
            return value
    raise ValueError('This picture is too large to send. Please use a smaller one.')


def stroke_path(points):
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    if len(points) == 1:
        path.lineTo(points[0] + QPointF(0.01, 0))  # a single click still leaves a round dot
    return path


def render_mask(size, strokes):
    """The painted area as the engine wants it: white strokes on black, as large as the picture."""
    mask = QImage(size, QImage.Format.Format_RGB32)
    mask.fill(QColor('black'))
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for width, points in strokes:
        painter.setPen(QPen(QColor('white'), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(stroke_path(points))
    painter.end()
    return mask.convertToFormat(QImage.Format.Format_Grayscale8)


def edit_body(image, engine, prompt, smart, mask):
    """What /api/edit receives. Only AI editing takes a painted area or the prompt assistant."""
    kontext = engine == 'kontext'
    return dict(image=image, engine=engine, prompt=prompt, smart=bool(smart and kontext),
                mask=mask if kontext else None)


class PaintCanvas(QWidget):
    """The photo, fitted to the space, with the area you paint shown over it."""

    changed = Signal()  # a stroke was added or taken away

    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.picture = None  # the photo's real size; None while it loads (no painting until then)
        self.strokes = []  # (width, points), both in the photo's own pixels
        self.painting = False
        self.brush = 35  # on screen, in pixels
        self.drawing = False
        self.pointer = None
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)

    def set_picture(self, pixmap, picture=None):
        self.pixmap, self.picture = pixmap, picture
        self.update()

    def set_painting(self, on):
        self.painting = on
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.update()

    def clear(self):
        self.strokes, self.drawing = [], False
        self.update()
        self.changed.emit()

    def undo(self):
        if self.strokes and not self.drawing:
            self.strokes.pop()
            self.update()
            self.changed.emit()

    def target(self):
        if self.pixmap is None or self.pixmap.isNull():
            return QRectF()
        size = self.picture or self.pixmap.size()
        area = QRectF(self.rect()).adjusted(20, 20, -20, -20)
        scale = min(area.width() / size.width(), area.height() / size.height())
        box = QRectF(0, 0, size.width() * scale, size.height() * scale)
        box.moveCenter(area.center())
        return box

    def to_picture(self, point):
        box = self.target()
        scale = self.picture.width() / box.width()
        return QPointF((point.x() - box.left()) * scale, (point.y() - box.top()) * scale)

    def mousePressEvent(self, event):
        if self.painting and self.picture is not None and event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            width = self.brush * self.picture.width() / self.target().width()
            self.strokes.append((width, [self.to_picture(event.position())]))
            self.update()

    def mouseMoveEvent(self, event):
        self.pointer = event.position()
        if self.drawing:
            self.strokes[-1][1].append(self.to_picture(event.position()))
        if self.painting:
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            self.drawing = False
            self.changed.emit()

    def leaveEvent(self, event):
        self.pointer = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.CANVAS))
        box = self.target()
        if box.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(box, self.pixmap, QRectF(self.pixmap.rect()))
        if self.strokes and self.picture is not None:
            # Strokes go on a layer of their own, so overlapping ones keep one even tint.
            ratio = self.devicePixelRatioF()
            layer = QImage(self.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
            layer.setDevicePixelRatio(ratio)
            layer.fill(Qt.GlobalColor.transparent)
            brush = QPainter(layer)
            brush.setRenderHint(QPainter.RenderHint.Antialiasing)
            brush.setClipRect(box)
            brush.translate(box.topLeft())
            brush.scale(box.width() / self.picture.width(), box.width() / self.picture.width())
            for width, points in self.strokes:
                brush.setPen(QPen(QColor(theme.ACCENT), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
                brush.drawPath(stroke_path(points))
            brush.end()
            painter.setOpacity(0.5)
            painter.drawImage(0, 0, layer)
            painter.setOpacity(1)
        if self.painting and self.pointer is not None and self.picture is not None:
            radius = self.brush / 2
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
            painter.drawEllipse(self.pointer, radius, radius)
            painter.setPen(QPen(QColor('#f3f5f1'), 1.2))
            painter.drawEllipse(self.pointer, radius, radius)


class EditPage(QWidget):
    def __init__(self, client, library, notify, store, show_library, open_photocraft, show_providers=None):
        super().__init__()
        self.show_providers = show_providers or (lambda: None)
        self.client, self.library, self.notify = client, library, notify
        self.store = store  # returns the QSettings the form is remembered in
        self.config = None
        self.ready = False
        self.engine = 'kontext'
        self.source = None  # dict(ref, name, image): ref is '/images/<name>' for library pictures
        self.loading = 0  # counts picture loads, so a slow one never replaces a newer choice
        self.job = None  # the latest edit job and its result
        self.active = None  # the job being followed
        self.submitting = False
        self.failures = 0
        self.after = True  # show the result rather than the photo it was made from
        self.full = {}  # full-size results already fetched, by name
        self.recent_items = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = PageHeader('Edit')
        outer.addWidget(self.header)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        outer.addLayout(layout, 1)
        layout.addWidget(self.panel(open_photocraft))
        layout.addWidget(self.workspace(show_library), 1)
        self.setAcceptDrops(True)
        for keys, action in (('Ctrl+Return', self.apply), ('Ctrl+Enter', self.apply), ('Ctrl+Z', self.canvas.undo),
                             ('Ctrl+V', self.paste)):
            shortcut = QShortcut(QKeySequence(keys), self, action)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # text boxes keep their own
        library.changed.connect(self.show_recent)
        self.poller = QTimer(self)
        self.poller.setSingleShot(True)
        self.poller.timeout.connect(self.poll)
        self.form.setEnabled(False)  # until the engine says what is installed
        self.render()

    # The form ------------------------------------------------------------------------

    def panel(self, open_photocraft):
        panel = QWidget()
        panel.setObjectName('Panel')
        panel.setProperty('side', 'left')
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        panel.setFixedWidth(372)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)
        self.form = QWidget()
        scroll.setWidget(self.form)
        column = QVBoxLayout(self.form)
        column.setContentsMargins(20, 18, 18, 18)
        column.setSpacing(9)

        self.workspace_button = QPushButton(theme.icon('layers'), 'Open in PhotoCraft')
        self.workspace_button.setToolTip('Continue in the full PhotoCraft studio, with layers and every tool.')
        self.workspace_button.clicked.connect(lambda: open_photocraft(self.shown_picture()))  # it goes along
        self.header.add(self.workspace_button)

        column.addWidget(label('Tool', 'eyebrow'))
        self.tool = QComboBox()
        for engine, tool in ENGINES.items():
            self.tool.addItem(tool[1], engine)
        self.tool.currentIndexChanged.connect(self.tool_changed)
        column.addWidget(self.tool)
        notes = QHBoxLayout()
        self.engine_note = label('', 'small', wrap=True)
        notes.addWidget(self.engine_note, 1)
        self.connect_button = QPushButton('Connect…')
        self.connect_button.setProperty('kind', 'link')
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.clicked.connect(lambda: self.show_providers())
        notes.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(notes)
        column.addSpacing(4)

        top = QHBoxLayout()
        top.addWidget(label('What to change', 'eyebrow'))
        top.addStretch()
        self.counter = label(f'0/{MAX_PROMPT}', 'small')
        top.addWidget(self.counter)
        column.addLayout(top)
        self.prompt = QPlainTextEdit()
        self.prompt.setFixedHeight(132)
        self.prompt.setTabChangesFocus(True)
        self.prompt.textChanged.connect(self.prompt_changed)
        column.addWidget(self.prompt)
        chips = Flow()  # straight in the column: a wrapping row inside a widget would not get its height
        self.ideas = []
        ideas = {engine: tool[5] for engine, tool in ENGINES.items()}
        ideas['cloud'] = CLOUD_IDEAS
        for engine, texts in ideas.items():
            for text in texts:
                chip = QPushButton(text)
                chip.setProperty('kind', 'chip')
                chip.clicked.connect(lambda _=False, text=text: self.set_prompt(text))
                chips.addWidget(chip)
                self.ideas.append((engine, chip))
        column.addLayout(chips)
        self.smart = Toggle('Smart prompt', 'Rewords the request after a look at the photo')
        self.smart.toggled.connect(lambda _: self.remember())
        column.addWidget(self.smart)
        column.addSpacing(4)
        column.addWidget(rule())
        column.addSpacing(4)

        self.brush = Toggle('Paint an area to edit', 'Only the painted area will change')
        self.brush.toggled.connect(self.brush_toggled)
        column.addWidget(self.brush)
        self.brush_tools = Box()
        tools = QVBoxLayout(self.brush_tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(8)
        self.brush_size = Range('Brush size', 5, 120)
        self.brush_size.changed.connect(self.brush_resized)
        tools.addWidget(self.brush_size)
        buttons = QHBoxLayout()
        self.undo = QPushButton(theme.icon('undo-2'), 'Undo stroke')
        self.undo.setToolTip('Take back the last stroke (Ctrl + Z)')
        buttons.addWidget(self.undo)
        self.clear_mask = QPushButton(theme.icon('eraser'), 'Clear mask')
        buttons.addWidget(self.clear_mask)
        tools.addLayout(buttons)
        column.addWidget(self.brush_tools)

        column.addStretch()

        footer = QVBoxLayout()
        footer.setContentsMargins(20, 12, 18, 12)
        footer.setSpacing(6)
        self.go = QPushButton(theme.icon('sparkles', theme.ON_ACCENT), ' Apply edit')
        self.go.setProperty('kind', 'primary')
        self.go.setProperty('size', 'large')
        self.go.setIconSize(QSize(18, 18))
        self.go.clicked.connect(self.apply)
        footer.addWidget(self.go)
        self.hint = label('', 'small')
        self.hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        footer.addWidget(self.hint)
        outer.addWidget(rule())
        outer.addLayout(footer)
        return panel

    # The photo -----------------------------------------------------------------------

    def workspace(self, show_library):
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(20, 14, 20, 16)
        column.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.mode_icon = label('')
        top.addWidget(self.mode_icon)
        self.mode = label('', 'small')
        top.addWidget(self.mode)
        top.addStretch()
        self.compare = QButtonGroup(self)
        for index, text in enumerate(('Before', 'After')):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty('kind', 'tile')
            button.clicked.connect(lambda _=False, after=bool(index): self.show_after(after))
            self.compare.addButton(button, index)
            top.addWidget(button)
        self.another = QPushButton(theme.icon('upload', theme.MUTED), '')
        self.another.setProperty('kind', 'flat')
        self.another.setToolTip('Choose another photo')
        self.another.clicked.connect(self.choose)
        top.addWidget(self.another)
        self.remove = QPushButton(theme.icon('x', theme.MUTED), '')
        self.remove.setProperty('kind', 'flat')
        self.remove.setToolTip('Remove the photo')
        self.remove.clicked.connect(lambda: self.set_source(None))
        top.addWidget(self.remove)
        column.addLayout(top)

        self.stage = QStackedLayout()
        self.stage.addWidget(self.drop_target(show_library))
        self.canvas = PaintCanvas()
        self.canvas.changed.connect(self.sync)
        self.stage.addWidget(self.canvas)
        self.result = ImageView()
        self.result.setMinimumSize(200, 200)
        self.stage.addWidget(self.result)
        holder = Box()
        holder.setLayout(self.stage)
        holder.setMinimumHeight(240)
        column.addWidget(holder, 1)
        self.undo.clicked.connect(self.canvas.undo)
        self.clear_mask.clicked.connect(self.canvas.clear)

        self.status = QFrame()
        self.status.setProperty('card', True)
        status = QVBoxLayout(self.status)
        status.setContentsMargins(14, 8, 8, 10)
        status.setSpacing(6)
        line = QHBoxLayout()
        self.status_text = label('', wrap=True)
        self.status_text.setMinimumWidth(120)
        line.addWidget(self.status_text, 1)
        self.stop = QPushButton(theme.icon('square', theme.MUTED), 'Stop')
        self.stop.setProperty('kind', 'flat')
        self.stop.clicked.connect(self.cancel)
        line.addWidget(self.stop, 0, Qt.AlignmentFlag.AlignTop)
        status.addLayout(line)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        status.addWidget(self.progress)
        self.understood = label('', 'small', wrap=True, selectable=True)
        status.addWidget(self.understood)
        self.actions = Box()
        actions = Flow()
        self.actions.setLayout(actions)

        def action(text, icon, slot, kind=''):
            button = QPushButton(theme.icon(icon, theme.ON_ACCENT if kind == 'primary' else theme.TEXT), text)
            if kind:
                button.setProperty('kind', kind)
            button.clicked.connect(slot)
            actions.addWidget(button)
            return button

        action('Keep editing', 'square-pen', self.keep_editing, 'primary')
        action('Save a copy…', 'arrow-down-to-line', self.save_result)
        action('View details', 'expand', self.view_details)
        self.psd = action('Save layered PSD…', 'layers', self.save_psd)
        self.open_psd = action('Open in PhotoCraft', 'external-link', self.open_in_photocraft)
        status.addWidget(self.actions)
        column.addWidget(self.status)
        return area

    def drop_target(self, show_library):
        target = QFrame()
        target.setProperty('stage', True)
        column = QVBoxLayout(target)
        column.setContentsMargins(28, 24, 28, 24)
        column.setSpacing(8)
        column.addStretch(1)
        symbol = label('')
        symbol.setPixmap(theme.icon('image-plus', theme.FAINT).pixmap(38, 38))
        symbol.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(symbol)
        for text, role in (('Add a photo to edit', 'heading'),
                           ('Drop a photo here, paste one with Ctrl + V, or choose a file.', 'muted')):
            widget = label(text, role, wrap=True)
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(widget)
        column.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch()
        choose = QPushButton(theme.icon('upload', theme.ON_ACCENT), 'Choose a photo…')
        choose.setProperty('kind', 'primary')
        choose.clicked.connect(self.choose)
        buttons.addWidget(choose)
        paste = QPushButton(theme.icon('clipboard-paste'), 'Paste')
        paste.clicked.connect(self.paste)
        buttons.addWidget(paste)
        buttons.addStretch()
        column.addLayout(buttons)
        note = label('PNG, JPG, WEBP · Up to 25 megapixels', 'small')
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(note)
        column.addStretch(1)

        self.recent_box = Box()
        lower = QVBoxLayout(self.recent_box)
        lower.setContentsMargins(0, 0, 0, 0)
        lower.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label('Or pick a recent picture', 'eyebrow'))
        heading.addStretch()
        everything = QPushButton('View all')
        everything.setProperty('kind', 'flat')
        everything.clicked.connect(show_library)
        heading.addWidget(everything)
        lower.addLayout(heading)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.recent = []
        for index in range(5):
            thumb = Thumb(self.library.model, 84)
            thumb.setMinimumWidth(48)
            thumb.clicked.connect(lambda _=False, index=index: self.load_item(self.recent_items[index]))
            row.addWidget(thumb, 1)
            self.recent.append(thumb)
        lower.addLayout(row)
        column.addWidget(self.recent_box)
        return target

    # Settings ------------------------------------------------------------------------

    def remember(self):
        if self.config:
            self.store().setValue('edit/settings', json.dumps(dict(
                engine=self.engine, smart=self.smart.isChecked(), brush=self.brush_size.value(),
            )))

    def saved(self):
        try:
            value = json.loads(self.store().value('edit/settings', '{}') or '{}')
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def tool_changed(self, _):
        engine = self.tool.currentData()
        if engine and engine != self.engine:
            self.set_engine(engine)
            self.remember()

    def set_engine(self, engine):
        """Switch tools. PhotoCraft changes the whole photo, so a painted area is let go."""
        self.engine = engine
        self.tool.blockSignals(True)
        self.tool.setCurrentIndex(self.tool.findData(engine))
        self.tool.blockSignals(False)
        if engine != 'kontext':
            self.brush.setChecked(False)
            if self.canvas.strokes:
                self.canvas.clear()
        self.prompt.setPlaceholderText(details(engine, self.config)[4])
        self.sync()

    def brush_toggled(self, on):
        self.canvas.set_painting(on)
        if on and self.stage.currentWidget() is self.result:
            self.show_after(False)  # paint on the photo, not on the result
        self.sync()

    def brush_resized(self, value):
        self.canvas.brush = value
        self.remember()

    def prompt_changed(self):
        text = self.prompt.toPlainText()
        if len(text) > MAX_PROMPT:
            cursor = self.prompt.textCursor()
            self.prompt.setPlainText(text[:MAX_PROMPT])
            cursor.setPosition(min(cursor.position(), MAX_PROMPT))
            self.prompt.setTextCursor(cursor)
            return
        self.sync()

    def set_prompt(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        self.prompt.moveCursor(QTextCursor.MoveOperation.End)

    def sync(self):
        """Show and enable what applies to the current tool, photo and job."""
        config = self.config or {}
        kontext = self.engine == 'kontext'
        self.counter.setText(f'{len(self.prompt.toPlainText())}/{MAX_PROMPT}')
        for engine, chip in self.ideas:
            chip.setVisible(engine == self.engine or (engine == 'cloud' and self.engine not in ENGINES))
        self.workspace_button.setVisible(bool(config.get('photocraft')))
        self.smart.setVisible(kontext)
        self.smart.setEnabled(bool(config.get('assistant')))
        if not config.get('assistant'):
            self.smart.setChecked(False)
        self.smart.set_description(
            'Clearer wording, with a look at your photo' if config.get('assistant')
            else 'Needs the prompt assistant model'
        )
        self.brush.setVisible(kontext)
        self.brush_tools.setVisible(kontext and self.brush.isChecked())
        self.undo.setEnabled(bool(self.canvas.strokes))
        self.clear_mask.setEnabled(bool(self.canvas.strokes))
        name, _, note, _, _, _ = details(self.engine, config)
        ready_tool = installed(self.engine, config)
        if not ready_tool:
            note = ('PhotoCraft was not found on this PC.' if self.engine == 'photocraft' else
                    'Install the editing model in Settings → Models.' if self.engine == 'kontext' else
                    f'Connect {name} with an API key to use it.')
        self.engine_note.setText(note)
        self.connect_button.setVisible(self.engine not in ENGINES and not ready_tool)
        painting = self.brush.isChecked() and kontext
        self.mode_icon.setPixmap(theme.icon('brush' if painting else 'image-plus', theme.ACCENT).pixmap(15, 15))
        if self.source is None:
            mode = 'No photo yet'
        elif painting:
            mode = 'Paint over the area to change'
        elif self.stage.currentWidget() is self.result:
            mode = 'Result'
        else:
            mode = self.source.get('name') or 'Photo'
        self.mode.setText(mode)
        self.update_buttons()

    def update_buttons(self):
        busy = self.busy
        ready_tool = installed(self.engine, self.config)
        loaded = self.source is not None and self.source.get('image') is not None
        self.go.setEnabled(self.ready and ready_tool and loaded and not busy
                           and bool(self.prompt.toPlainText().strip()))
        self.go.setText(' Editing…' if busy else ' Apply edit')
        for button in (self.another, self.remove):
            button.setVisible(self.source is not None)
            button.setEnabled(not busy)
        if not self.ready:
            hint = 'Waiting for the engine…'
        elif self.config and not ready_tool:
            hint = 'This tool is not set up yet.'
        elif self.source is None:
            hint = 'Add a photo to begin.'
        else:
            hint = 'Ctrl + Enter to apply'
        self.hint.setText(hint)

    @property
    def busy(self):
        return self.submitting or self.active is not None

    # Choosing the photo ----------------------------------------------------------------

    def choose(self):
        if self.busy:
            return
        start = Path.home() / 'Pictures'
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a photo to edit', str(start if start.is_dir() else ''),
                                              PICTURES)
        if path:
            self.open_file(path)

    def open_file(self, path):
        try:
            image = read_picture(path)
        except ValueError as exc:
            self.notify(str(exc), error=True)
            return
        self.set_source(dict(ref=None, name=Path(path).name, image=image))

    def paste(self):
        if self.busy:
            self.notify('Wait for the current edit to finish first.', error=True)
        elif not self.take(QGuiApplication.clipboard().mimeData()):
            self.notify('The clipboard has no picture in it.', error=True)

    def take(self, mime):
        """Use a picture from a drop or the clipboard: a picture file, or the picture itself."""
        if mime is None or self.busy:
            return False
        for url in mime.urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())
                return True
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                try:
                    self.set_source(dict(ref=None, name='Pasted picture', image=check_size(image)))
                except ValueError as exc:
                    self.notify(str(exc), error=True)
                return True
        return False

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if not self.busy and (mime.hasImage() or any(url.isLocalFile() for url in mime.urls())):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.take(event.mimeData()):
            event.acceptProposedAction()

    def load_item(self, item):
        """Edit a library picture: the engine reads it from the library, so nothing is uploaded."""
        if self.busy:
            self.notify('Wait for the current edit to finish first.', error=True)
            return
        self.set_source(dict(ref=item['url'], name=item['name'], image=None))
        ticket = self.loading
        self.canvas.set_picture(self.library.model.thumbs.get(self.library.model.key(item)))

        def loaded(data):
            if ticket != self.loading:
                return
            image = QImage()
            if not image.loadFromData(data):
                self.notify('Could not read that picture.', error=True)
                self.set_source(None)
                return
            self.source['image'] = image
            self.canvas.set_picture(QPixmap.fromImage(image), image.size())
            self.sync()

        def failed(error):
            if ticket == self.loading:
                self.notify(f'Could not load the picture: {error}', error=True)
                self.set_source(None)

        self.client.bytes(item['url'], loaded, failed, timeout=120000)

    def set_source(self, source):
        """A new photo to edit (or none). The painted area and the last result belong to the old one."""
        self.loading += 1
        self.source = source
        self.canvas.strokes = []
        if source is not None and source.get('image') is not None:
            self.canvas.set_picture(QPixmap.fromImage(source['image']), source['image'].size())
        elif source is None:
            self.canvas.set_picture(None)
        if not self.busy:
            self.job = None
        self.render()

    # Talking to the engine ----------------------------------------------------------

    def engine_ready(self):
        self.ready = True
        self.client.get('/api/config', self.configured, lambda error: self.notify(error, error=True))

    def engine_gone(self):
        self.ready = False
        self.poller.stop()
        self.active, self.submitting = None, False
        self.update_buttons()

    def refresh(self):
        if self.ready:
            self.show_recent()

    def configured(self, config):
        first = self.config is None
        self.config = config
        self.tool.blockSignals(True)
        self.tool.clear()
        for engine, tool in ENGINES.items():
            self.tool.addItem(tool[1] + ('' if installed(engine, config) else '  ·  not installed'), engine)
            self.tool.model().item(self.tool.count() - 1).setEnabled(installed(engine, config))
        editors = config.get('cloud_editors') or []
        if editors:
            self.tool.insertSeparator(self.tool.count())
        for entry in editors:
            self.tool.addItem(f'{entry["label"]} · {entry["model"]}' + ('' if entry['ready'] else '  ·  not connected'),
                              entry['id'])
        self.tool.setCurrentIndex(max(0, self.tool.findData(self.engine)))
        self.tool.blockSignals(False)
        if first:
            saved = self.saved()
            self.smart.blockSignals(True)
            self.smart.setChecked(bool(saved.get('smart')))
            self.smart.blockSignals(False)
            try:
                self.brush_size.setValue(int(saved.get('brush', 35)))
            except (TypeError, ValueError):
                pass
            self.canvas.brush = self.brush_size.value()
            self.set_engine(choose_engine(config, saved.get('engine')))
        elif not installed(self.engine, config):
            self.set_engine(choose_engine(config, self.engine))
        self.form.setEnabled(True)
        self.sync()

    def apply(self):
        if not self.go.isEnabled():
            return
        source, engine = self.source, self.engine
        prompt, smart = self.prompt.toPlainText(), self.smart.isChecked()
        strokes = list(self.canvas.strokes) if engine == 'kontext' else []
        image = source['image']
        self.submitting = True
        self.update_buttons()

        def prepare():
            # Encoding a large photo takes a moment, so it happens off the UI thread.
            picture = source['ref'] or source.get('data') or encode(image)
            mask = encode(render_mask(image.size(), strokes)) if strokes else None
            return picture, mask

        def prepared(result, error):
            if error is not None:
                self.submitting = False
                self.update_buttons()
                self.notify(str(error), error=True)
                return
            picture, mask = result
            if source['ref'] is None:
                source['data'] = picture  # sent again as it is for another try
            self.submit(edit_body(picture, engine, prompt, smart, mask))

        in_background(prepare, prepared)

    def submit(self, body):
        def started(job):
            self.submitting = False
            self.follow(job['id'], job)

        def refused(error):
            self.submitting = False
            self.update_buttons()
            self.notify(error, error=True)

        self.client.post('/api/edit', body, started, refused, timeout=120000)

    def follow(self, job_id, job=None):
        self.active, self.failures = job_id, 0
        self.job = job or dict(id=job_id, state='running', progress=0, message='Editing…', images=[])
        self.render()
        self.poll()

    def poll(self):
        if self.active is None:
            return
        job_id = self.active
        self.client.get(
            f'/api/jobs/{job_id}', lambda job: self.polled(job_id, job), lambda error: self.lost(job_id, error),
            timeout=15000,
        )

    def polled(self, job_id, job):
        if job_id != self.active:
            return
        self.failures = 0
        self.job = job
        if job['state'] == 'running':
            self.render()
            self.poller.start(POLL_MS)
            return
        self.active = None
        if job['state'] == 'error':
            self.notify(job['message'], error=True)
        if job.get('images'):
            self.after = True
            self.brush.setChecked(False)
            self.library.refresh()
        self.render()

    def lost(self, job_id, error):
        if job_id != self.active:
            return
        self.failures += 1
        if self.failures >= 5 or 'not found' in error.lower():
            self.active = None
            if self.job and self.job.get('state') == 'running':
                self.job = dict(self.job, state='error', message=f'Lost track of the edit: {error}')
            self.notify(f'Lost track of the edit: {error}', error=True)
            self.render()
            return
        self.poller.start(POLL_MS)

    def cancel(self):
        if self.active:
            self.client.post(
                f'/api/jobs/{self.active}/cancel', {}, lambda _: self.notify('Stopping after the current step…'),
                lambda error: self.notify(error, error=True),
            )

    # Showing results ----------------------------------------------------------------

    @property
    def outcome(self):
        """The edited picture, once there is one."""
        images = (self.job or {}).get('images') or []
        return images[-1] if images else None

    def render(self):
        job, outcome = self.job, self.outcome
        if self.source is None:
            self.stage.setCurrentIndex(0)
        elif outcome is not None and self.after:
            self.stage.setCurrentWidget(self.result)
            self.load_full(outcome)
        else:
            self.stage.setCurrentWidget(self.canvas)
        for index, button in enumerate(self.compare.buttons()):
            button.setVisible(outcome is not None and self.source is not None)
            button.setChecked(bool(index) == (self.stage.currentWidget() is self.result))
        self.status.setVisible(job is not None)
        if job is not None:
            running = job['state'] == 'running'
            self.status_text.setText(job.get('message') or '')
            self.status_text.setProperty('role', 'error' if job['state'] == 'error' else '')
            self.status_text.style().polish(self.status_text)
            self.progress.setVisible(running)
            self.progress.setValue(max(30, int(job.get('progress', 0) * 1000)))
            self.stop.setVisible(running and self.active == job.get('id'))
            understood = job.get('understood') or ''
            self.understood.setText(understood)
            self.understood.setVisible(bool(understood) and not running)
            self.actions.setVisible(outcome is not None)
            if outcome is not None:
                layered = bool((outcome.get('metadata') or {}).get('layered_document'))
                self.psd.setVisible(layered)
                self.open_psd.setVisible(layered)
        self.sync()

    def show_after(self, after):
        self.after = after
        if after:
            self.brush.setChecked(False)
        self.render()

    def load_full(self, item):
        name = item['name']
        self.result.set_pixmap(self.full.get(name) or self.library.model.thumbs.get(self.library.model.key(item)))
        if name in self.full:
            return

        def loaded(data):
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.full[name] = pixmap
                if self.outcome and self.outcome['name'] == name:
                    self.result.set_pixmap(pixmap)

        self.client.bytes(item['url'], loaded, None, timeout=120000)

    def shown_picture(self):
        """The picture on screen: the result while it is shown, else the photo being edited."""
        if self.outcome is not None and self.stage.currentWidget() is self.result:
            return dict(ref=self.outcome['url'], name=self.outcome['name'], image=None)
        return self.source

    def keep_editing(self):
        """Carry on from the result: it becomes the photo you edit next."""
        if self.outcome is not None and not self.busy:
            item = self.outcome
            self.job = None
            self.load_item(item)

    def save_result(self):
        if self.outcome is not None:
            name = self.outcome['name']
            save_to(self, self.client, self.notify, f'/api/library/{name}/download', name, '.png', 'Save a copy')

    def save_psd(self):
        if self.outcome is not None:
            name = self.outcome['name']
            save_to(self, self.client, self.notify, f'/api/photocraft/{name}/download', name, '.psd',
                    'Save layered PSD')

    def open_in_photocraft(self):
        if self.outcome is not None:
            self.client.post(
                f'/api/photocraft/{self.outcome["name"]}/open', {},
                lambda answer: self.notify(answer.get('message') or 'Opened in PhotoCraft.'),
                lambda error: self.notify(error, error=True),
            )

    def view_details(self):
        if self.outcome is not None:
            self.library.show_details([self.outcome], 0)

    def show_recent(self):
        items = sorted(self.library.all, key=lambda item: item['created'], reverse=True)[:len(self.recent)]
        self.recent_items = items
        for index, thumb in enumerate(self.recent):
            thumb.setVisible(index < len(items))
            thumb.set_item(items[index] if index < len(items) else None)
        self.recent_box.setVisible(bool(items))

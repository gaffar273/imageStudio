"""Create image: describe a picture, choose how it is made, and watch it render.

The same form as the web studio's Create page, sending the same request to the engine.
"""

import base64
import json
import random
import re

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import Box, Flow, Range, Section, Thumb, Toggle, shape_icon
from image_studio.desktop.library import ImageView, cover, save_to
from image_studio.desktop.theme import label

IDEAS = [
    (
        'Coastal escape',
        (
            'A quiet Mediterranean seaside town on steep cliffs, terracotta rooftops, turquoise water and a '
            'winding coastal road, photographed in soft late afternoon light.'
        ),
    ),
    (
        'A little cinematic',
        (
            'A solitary traveler at a rainy Tokyo street corner at night, glowing neon reflected in puddles, '
            'candid 35mm street photograph.'
        ),
    ),
    (
        'Everyday beauty',
        (
            'Morning sunlight falling across a ceramic coffee cup and a half-read book on a wooden table, a '
            'small vase of wildflowers, natural intimate photograph.'
        ),
    ),
]
# id: (name, what it is good at, (fewest, most, usual) rendering steps)
MODELS = {
    'realistic': ('RealVisXL 5.0', 'Lifelike people, beautiful details', (20, 50, 30)),
    'accurate': ('Z-Image Turbo', 'Precise prompts, thoughtful compositions', (6, 16, 9)),
    'turbo': ('SDXL Turbo', 'Fast ideas, endless possibilities', (4, 4, 4)),
}
ASPECTS = ['1:1', '2:3', '3:2', '16:9']  # the first four engine sizes
DEFAULTS = dict(
    prompt='', model='realistic', size='', seed='', steps=30, guidance=5.0, negative_prompt='', detail='Off',
    detail_strength=0.35, count=1, smart=False, sketch=None, sketch_freedom=0.65, vary=True, check=False,
    attempts=2, repair=True, repair_strength=0.3, photo_style='Natural photo', photo_finish='Light',
    combine=True, references=True, realism=0.6, personal=0.5,
)
CHOICES = dict(
    model=tuple(MODELS),
    photo_style=('Natural photo', 'Polished'),
    photo_finish=('Off', 'Light', 'Film'),
    detail=('Off', '1.5× size', '2× size'),
)
LIMITS = dict(
    guidance=(1, 12), detail_strength=(0.1, 0.7), count=(1, 4), sketch_freedom=(0.1, 1), attempts=(1, 4),
    repair_strength=(0.1, 0.7), realism=(0, 1), personal=(0, 1),
)
# Switches that need an optional model, and the config flag that says it is installed.
NEEDS = dict(repair='repair', references='references', smart='assistant', check='assistant')
MAX_PROMPT = 6000
MAX_SEED = 4294967295
POLL_MS = 1000
ROOMY = 700  # below this height the canvas keeps the room and the recent pictures step aside
SCENIC = re.compile(
    r'^(a |an )?(wide |cinematic |photograph of |landscape )*'
    r'(seaside|coast|mountain|landscape|turquoise alpine|cabin|aurora)',
    re.IGNORECASE,
)


def clean(settings, config):
    """Settings the engine accepts: known choices, numbers in range, and switches only for installed parts."""
    result = dict(DEFAULTS)
    result.update({key: value for key, value in settings.items() if key in DEFAULTS})
    for key, options in CHOICES.items():
        if result[key] not in options:
            result[key] = DEFAULTS[key]
    sizes = [size['id'] for size in config['sizes']]
    if result['size'] not in sizes:
        result['size'] = sizes[0]
    for key, (low, high) in dict(LIMITS, steps=MODELS[result['model']][2][:2]).items():
        try:
            value = float(result[key])
        except (TypeError, ValueError):
            value = DEFAULTS[key]
        value = min(max(value, low), high)
        result[key] = round(value) if isinstance(DEFAULTS[key], int) else value
    for key in ('smart', 'vary', 'check', 'repair', 'combine', 'references'):
        result[key] = bool(result[key]) and (key not in NEEDS or bool(config.get(NEEDS[key])))
    result['seed'] = re.sub(r'\D', '', str(result['seed'] or ''))
    result['prompt'] = str(result['prompt'] or '')[:MAX_PROMPT]
    result['negative_prompt'] = str(result['negative_prompt'] or '')[:MAX_PROMPT]
    return result


def starting(config, saved):
    """The form when the app opens: defaults, then what was used last time (never an old sketch)."""
    return clean({'negative_prompt': config['negative_prompt'], **saved, 'sketch': None}, config)


def reused(meta, config):
    """The settings that made a saved picture, to make it again or a variation of it."""
    combined = bool(meta.get('texture_from'))
    name = meta.get('model') or ''
    model = 'accurate' if combined or 'Z-Image' in name else 'turbo' if 'sdxl-turbo' in name else 'realistic'
    width = meta.get('base_width') or meta.get('width')
    height = meta.get('base_height') or meta.get('height')
    size = next((size['id'] for size in config['sizes'] if (size['width'], size['height']) == (width, height)), '')

    def given(value, fallback):
        return fallback if value is None else value

    return dict(
        prompt=meta.get('request') or meta.get('prompt') or '',
        seed='' if meta.get('seed') is None else str(meta['seed']),
        model=model,
        size=size,
        steps=9 if combined else meta.get('steps') or 30,
        guidance=given(meta.get('guidance'), 5),
        negative_prompt=given(meta.get('negative_prompt'), config['negative_prompt']),
        photo_style=meta.get('style') or 'Polished',
        photo_finish=meta.get('finish') or 'Off',
        detail=(meta.get('detail_pass') or {}).get('option') or 'Off',
        detail_strength=given((meta.get('detail_pass') or {}).get('strength'), 0.35),
        realism=given((meta.get('realism_lora') or {}).get('strength'), 0),
        personal=given((meta.get('personal_lora') or {}).get('strength'), 0),
        combine=combined,
        sketch=None,
    )


def request_body(settings):
    """What /api/generate receives. A seed out of range is refused here, before anything is sent."""
    seed = settings['seed']
    if seed and int(seed) > MAX_SEED:
        raise ValueError(f'Seed must be between 0 and {MAX_SEED}.')
    return dict(settings, seed=int(seed) if seed else None)


def data_url(image):
    """A picture as a PNG data URL, the form the engine takes uploads in."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(bytes(buffer.data().data())).decode('ascii')


def from_data_url(value):
    image = QImage()
    image.loadFromData(QByteArray(base64.b64decode(value.split(',')[-1])))
    return image


def rule():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f'background: {theme.LINE};')
    return line


class Hero(QWidget):
    """The welcome canvas: one of your own landscapes behind an invitation to begin."""

    def __init__(self, spark):
        super().__init__()
        self.setObjectName('Hero')
        self.pixmap = None
        column = QVBoxLayout(self)
        column.setContentsMargins(44, 40, 44, 32)
        column.addStretch(1)
        column.addWidget(label('A SPACE FOR YOUR IMAGINATION', 'eyebrow'))
        column.addSpacing(6)
        title = label(f'What if you could<br>make <i style="color:{theme.LIME}">anything?</i>', 'hero')
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        column.addWidget(title)
        text = label(
            'A passing thought. A faraway place. Something that only exists in your head. '
            'Start with a few words.', 'muted', wrap=True,
        )
        text.setMaximumWidth(420)
        column.addWidget(text)
        column.addSpacing(14)
        button = QPushButton(theme.icon('sparkles', theme.INK), ' Find your first spark')
        button.setProperty('kind', 'primary')
        button.clicked.connect(spark)
        column.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        column.addStretch(1)
        column.addWidget(label('FROM A SPARK TO SOMETHING BEAUTIFUL', 'small'))

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(self.rect())
        shape = QPainterPath()
        shape.addRoundedRect(box, 14, 14)
        painter.setClipPath(shape)
        painter.fillRect(box, QColor('#0d0f0f'))
        if self.pixmap is not None and not self.pixmap.isNull():
            painter.drawPixmap(box, self.pixmap, cover(box, self.pixmap))
            shade = QLinearGradient(box.topLeft(), box.topRight())
            shade.setColorAt(0, QColor(10, 12, 12, 235))
            shade.setColorAt(0.55, QColor(10, 12, 12, 150))
            shade.setColorAt(1, QColor(10, 12, 12, 40))
            painter.fillRect(box, shade)


class CreatePage(QWidget):
    def __init__(self, client, library, notify, store, show_library):
        super().__init__()
        self.client, self.library, self.notify = client, library, notify
        self.store = store  # returns the QSettings the form is remembered in
        self.config = None
        self.settings = dict(DEFAULTS)
        self.job = None  # the latest image job, shown on the canvas
        self.active, self.kind = None, ''  # the job being followed, and what it is
        self.submitting = False
        self.failures = 0
        self.ready = False
        self.shown = -1  # which result is on the canvas (-1: the newest)
        self.full = {}  # full-size pictures already fetched, by name
        self.scenic = ''
        self.recent_items = []
        self.inputs = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.panel())
        layout.addWidget(self.workspace(show_library), 1)
        for keys in ('Ctrl+Return', 'Ctrl+Enter'):
            shortcut = QShortcut(QKeySequence(keys), self, self.generate)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        library.changed.connect(self.show_recent)
        self.poller = QTimer(self)
        self.poller.setSingleShot(True)
        self.poller.timeout.connect(self.poll)
        self.form.setEnabled(False)  # until the engine says what is installed
        self.render()

    # The form ------------------------------------------------------------------------

    def panel(self):
        panel = QWidget()
        panel.setObjectName('Panel')
        panel.setProperty('side', 'left')
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        panel.setFixedWidth(384)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(22, 18, 14, 10)
        mark = label('')
        mark.setPixmap(theme.icon('wand-sparkles', theme.LIME).pixmap(18, 18))
        heading.addWidget(mark)
        heading.addWidget(label('Your vision', 'heading'))
        heading.addStretch()
        fresh = QPushButton(theme.icon('plus', theme.MUTED), 'New')
        fresh.setProperty('kind', 'flat')
        fresh.setToolTip('Start a new creation: clears the prompt, seed and sketch.')
        fresh.clicked.connect(self.new_creation)
        heading.addWidget(fresh)
        outer.addLayout(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)
        self.form = QWidget()
        scroll.setWidget(self.form)
        column = QVBoxLayout(self.form)
        column.setContentsMargins(22, 4, 18, 18)
        column.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(label('PROMPT', 'eyebrow'))
        top.addStretch()
        surprise = QPushButton(theme.icon('dices', theme.MUTED), 'Surprise me')
        surprise.setProperty('kind', 'flat')
        surprise.clicked.connect(lambda: self.set_prompt(random.choice(IDEAS)[1]))
        top.addWidget(surprise)
        column.addLayout(top)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("A place you've never been. A moment you've imagined. Describe it here…")
        self.prompt.setFixedHeight(132)
        self.prompt.setTabChangesFocus(True)
        self.prompt.textChanged.connect(self.prompt_changed)
        column.addWidget(self.prompt)
        under = QHBoxLayout()
        under.addWidget(label('Let your imagination do the talking.', 'small'))
        under.addStretch()
        self.counter = label(f'0/{MAX_PROMPT}', 'small')
        under.addWidget(self.counter)
        column.addLayout(under)
        chips = Flow()
        for title, text in IDEAS:
            chip = QPushButton(f'{title} ↗')
            chip.setProperty('kind', 'chip')
            chip.setToolTip(text)
            chip.clicked.connect(lambda _=False, text=text: self.set_prompt(text))
            chips.addWidget(chip)
        column.addLayout(chips)
        self.smart = self.toggle(column, 'smart', 'Smart prompt', 'A little help shaping your idea')
        column.addSpacing(4)
        column.addWidget(rule())
        column.addSpacing(4)

        column.addWidget(label('MODEL', 'eyebrow'))
        self.model = QComboBox()
        self.model.currentIndexChanged.connect(self.model_changed)
        column.addWidget(self.model)
        self.model_note = label('', 'small')
        column.addWidget(self.model_note)

        top = QHBoxLayout()
        top.addWidget(label('IMAGE FORMAT', 'eyebrow'))
        top.addStretch()
        top.addWidget(label('Aspect ratio', 'small'))
        column.addLayout(top)
        aspects = QHBoxLayout()
        aspects.setSpacing(6)
        self.aspects = QButtonGroup(self)
        self.aspects.setExclusive(False)  # a size outside the four leaves none chosen
        for index, name in enumerate(ASPECTS):
            button = QPushButton(f' {name}')
            button.setCheckable(True)
            button.setProperty('kind', 'tile')
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _=False, index=index: self.pick_aspect(index))
            self.aspects.addButton(button, index)
            aspects.addWidget(button)
        column.addLayout(aspects)
        self.size = QComboBox()
        self.size.currentIndexChanged.connect(lambda _: self.set('size', self.size.currentData()))
        column.addWidget(self.size)

        column.addWidget(label('PHOTO STYLE', 'eyebrow'))
        styles = QHBoxLayout()
        styles.setSpacing(6)
        self.styles = self.choice(styles, 'photo_style', [('Natural photo', '◉  Natural'), ('Polished', '✧  Polished')])
        column.addLayout(styles)
        counts = QHBoxLayout()
        counts.setSpacing(6)
        counts.addWidget(label('Number of images'))
        counts.addStretch()
        self.counts = self.choice(counts, 'count', [(number, str(number)) for number in range(1, 5)], width=40)
        column.addLayout(counts)
        column.addSpacing(4)

        self.tune = Section('Fine-tune your image', 'settings-2')
        body = self.tune.body
        self.steps = self.slider(body, 'steps', 'Rendering steps', 20, 50)
        self.guidance = self.slider(body, 'guidance', 'Prompt strength', 1, 12, 0.5)
        body.addWidget(label('Seed'))
        seed = QHBoxLayout()
        self.seed = QLineEdit()
        self.seed.setPlaceholderText('Random')
        self.seed.textEdited.connect(self.seed_edited)
        seed.addWidget(self.seed, 1)
        dice = QPushButton(theme.icon('dices'), '')
        dice.setToolTip('Pick a random seed')
        dice.clicked.connect(lambda: self.update_settings(seed=str(random.randrange(2147483647))))
        seed.addWidget(dice)
        body.addLayout(seed)
        body.addWidget(label('Things to avoid'))
        self.negative = QPlainTextEdit()
        self.negative.setFixedHeight(80)
        self.negative.setTabChangesFocus(True)
        self.negative.textChanged.connect(lambda: self.set('negative_prompt', self.negative.toPlainText()))
        body.addWidget(self.negative)
        self.detail = self.dropdown(body, 'detail', 'High-detail pass', CHOICES['detail'])
        self.detail_strength = self.slider(body, 'detail_strength', 'Detail strength', 0.1, 0.7, 0.05)
        self.finish = self.dropdown(body, 'photo_finish', 'Photo finish', CHOICES['photo_finish'])
        self.toggle(body, 'vary', 'Vary faces')
        self.repair = self.toggle(body, 'repair', 'Face & hand repair')
        self.repair_strength = self.slider(body, 'repair_strength', 'Repair strength', 0.1, 0.7, 0.05)
        self.references = self.toggle(body, 'references', 'Reference faces')
        self.check = self.toggle(body, 'check', 'Check & retry')
        self.attempts = self.slider(body, 'attempts', 'Maximum attempts', 1, 4)
        self.combine = self.toggle(body, 'combine', 'Finish with RealVisXL')
        self.realism = self.slider(body, 'realism', 'Realism LoRA', 0, 1, 0.05)
        self.personal = self.slider(body, 'personal', 'My style (learned from favorites)', 0, 1, 0.05)
        column.addWidget(self.tune)

        self.sketching = Section('Guide with a sketch', 'scan-line')
        body = self.sketching.body
        body.addWidget(label('Use shapes and colors to guide the composition.', 'small', wrap=True))
        preview = QHBoxLayout()
        self.sketch_view = label('')
        self.sketch_view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        preview.addWidget(self.sketch_view)
        self.unsketch = QPushButton(theme.icon('x', theme.MUTED), '')
        self.unsketch.setProperty('kind', 'flat')
        self.unsketch.setToolTip('Remove the sketch')
        self.unsketch.clicked.connect(lambda: self.update_settings(sketch=None))
        preview.addWidget(self.unsketch, 0, Qt.AlignmentFlag.AlignTop)
        preview.addStretch()
        body.addLayout(preview)
        buttons = QHBoxLayout()
        upload = QPushButton(theme.icon('upload'), 'Upload sketch…')
        upload.clicked.connect(self.upload_sketch)
        buttons.addWidget(upload)
        self.draft = QPushButton(theme.icon('wand-sparkles'), 'Sketch from prompt')
        self.draft.clicked.connect(self.sketch_from_prompt)
        buttons.addWidget(self.draft)
        body.addLayout(buttons)
        self.slider(body, 'sketch_freedom', 'Freedom from sketch', 0.1, 1, 0.05)
        column.addWidget(self.sketching)
        column.addStretch()

        footer = QVBoxLayout()
        footer.setContentsMargins(22, 12, 18, 14)
        footer.setSpacing(6)
        self.go = QPushButton(theme.icon('sparkles', theme.INK), ' Generate image')
        self.go.setProperty('kind', 'primary')
        self.go.setProperty('size', 'large')
        self.go.setIconSize(QSize(18, 18))
        self.go.clicked.connect(self.generate)
        footer.addWidget(self.go)
        self.hint = label('', 'small')
        self.hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        footer.addWidget(self.hint)
        outer.addWidget(rule())
        outer.addLayout(footer)
        return panel

    def toggle(self, column, key, title, description=''):
        widget = Toggle(title, description)
        widget.toggled.connect(lambda on: self.set(key, on))
        column.addWidget(widget)
        self.inputs[key] = widget.setChecked
        return widget

    def slider(self, column, key, title, minimum, maximum, step=1):
        widget = Range(title, minimum, maximum, step)
        widget.changed.connect(lambda value: self.set(key, value))
        column.addWidget(widget)
        self.inputs[key] = widget.setValue
        return widget

    def dropdown(self, column, key, title, options):
        column.addWidget(label(title))
        widget = QComboBox()
        widget.addItems(options)
        widget.currentTextChanged.connect(lambda text: self.set(key, text))
        column.addWidget(widget)
        self.inputs[key] = widget.setCurrentText
        return widget

    def choice(self, row, key, options, width=0):
        group = QButtonGroup(self)
        for value, text in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty('kind', 'tile')
            if width:
                button.setFixedWidth(width)
            button.clicked.connect(lambda _=False, value=value: self.set(key, value))
            group.addButton(button)
            button.setProperty('value', value)
            row.addWidget(button, 0 if width else 1)

        def show(value):
            for button in group.buttons():
                button.setChecked(button.property('value') == value)

        self.inputs[key] = show
        return group

    # The canvas ----------------------------------------------------------------------

    def workspace(self, show_library):
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(28, 22, 28, 18)
        column.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label('YOUR CANVAS', 'eyebrow'))
        top.addStretch()
        top.addWidget(label(f'<span style="color:{theme.LIME}">●</span>&nbsp; Private: made on this PC', 'small'))
        column.addLayout(top)

        self.canvas = QStackedLayout()
        self.hero = Hero(lambda: self.set_prompt(IDEAS[0][1]))
        self.canvas.addWidget(self.hero)
        waiting = QFrame()
        waiting.setProperty('card', True)
        middle = QVBoxLayout(waiting)
        middle.addStretch()
        mark = label('')
        mark.setPixmap(theme.icon('sparkles', theme.LIME).pixmap(40, 40))
        mark.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        middle.addWidget(mark)
        self.waiting_title = label('', 'heading')
        self.waiting_text = label('', 'muted', wrap=True)
        for widget in (self.waiting_title, self.waiting_text):
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            middle.addWidget(widget)
        middle.addStretch()
        self.canvas.addWidget(waiting)
        self.result = ImageView()
        self.result.setMinimumSize(200, 200)
        self.canvas.addWidget(self.result)
        holder = Box()
        holder.setLayout(self.canvas)
        holder.setMinimumHeight(240)
        column.addWidget(holder, 1)

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
        line.addWidget(self.stop)
        self.details = QPushButton(theme.icon('expand'), 'View details')
        self.details.clicked.connect(self.view_details)
        line.addWidget(self.details)
        self.save = QPushButton(theme.icon('arrow-down-to-line'), 'Save a copy…')
        self.save.clicked.connect(self.save_result)
        line.addWidget(self.save)
        status.addLayout(line)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        status.addWidget(self.progress)
        column.addWidget(self.status)

        self.strip = QHBoxLayout()
        self.strip.setSpacing(8)
        self.strip_thumbs = []
        for index in range(4):
            thumb = Thumb(self.library.model, 64)
            thumb.setFixedWidth(64)
            thumb.clicked.connect(lambda _=False, index=index: self.show_result(index))
            self.strip.addWidget(thumb)
            self.strip_thumbs.append(thumb)
        self.strip.addStretch()
        column.addLayout(self.strip)
        self.notes = Section('Prompt interpretation', 'file-text')
        self.notes_text = label('', 'muted', wrap=True, selectable=True)
        self.notes.body.addWidget(self.notes_text)
        column.addWidget(self.notes)

        self.recent_box = Box()
        lower = QVBoxLayout(self.recent_box)
        lower.setContentsMargins(0, 6, 0, 0)
        lower.setSpacing(10)
        heading = QHBoxLayout()
        self.recent_title = label('Fresh from your imagination', 'heading')
        heading.addWidget(self.recent_title)
        heading.addStretch()
        everything = QPushButton(theme.icon('folder-heart', theme.MUTED), 'View library')
        everything.setProperty('kind', 'flat')
        everything.clicked.connect(show_library)
        heading.addWidget(everything)
        lower.addLayout(heading)
        recent = QGridLayout()
        recent.setSpacing(10)
        self.recent = []
        for index in range(4):
            thumb = Thumb(self.library.model, 132)
            thumb.setMinimumWidth(48)
            thumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            thumb.clicked.connect(lambda _=False, index=index: self.open_recent(index))
            recent.addWidget(thumb, 0, index)
            recent.setColumnStretch(index, 1)
            self.recent.append(thumb)
        self.recent_empty = label('Your first creation belongs here.', 'muted')
        self.recent_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_empty.setFixedHeight(132)
        recent.addWidget(self.recent_empty, 0, 0, 1, 4)
        lower.addLayout(recent)
        column.addWidget(self.recent_box)
        return area

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recent_box.setVisible(event.size().height() >= ROOMY)

    # Settings ------------------------------------------------------------------------

    def set(self, key, value):
        """One control changed: remember it and update what depends on it."""
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        self.remember()
        self.sync()

    def update_settings(self, **values):
        """Change several settings from code, and show them in the controls."""
        self.settings.update(values)
        if self.config:
            self.settings = clean(self.settings, self.config)
        self.show_settings()
        self.remember()

    def remember(self):
        if self.config:
            self.store().setValue('create/settings', json.dumps(dict(self.settings, sketch=None)))

    def saved(self):
        try:
            value = json.loads(self.store().value('create/settings', '{}') or '{}')
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def show_settings(self):
        """Every control shows self.settings, without echoing back as changes."""
        s = self.settings
        for widget in self.findChildren(QWidget):
            widget.blockSignals(True)
        try:
            if self.prompt.toPlainText() != s['prompt']:
                self.prompt.setPlainText(s['prompt'])
            if self.negative.toPlainText() != s['negative_prompt']:
                self.negative.setPlainText(s['negative_prompt'])
            self.seed.setText(s['seed'])
            self.model.setCurrentIndex(max(0, self.model.findData(s['model'])))
            self.size.setCurrentIndex(max(0, self.size.findData(s['size'])))
            low, high, _ = MODELS[s['model']][2]
            self.steps.set_range(low, high)
            for key, show in self.inputs.items():
                show(s[key])
        finally:
            for widget in self.findChildren(QWidget):
                widget.blockSignals(False)
        self.sync()

    def sync(self):
        """Show and enable what applies to the current choices."""
        s, config = self.settings, self.config or {}
        model = s['model']
        self.counter.setText(f'{len(s["prompt"])}/{MAX_PROMPT}')
        self.model_note.setText(MODELS[model][1])
        sizes = [size['id'] for size in config.get('sizes', [])]
        for index, button in enumerate(self.aspects.buttons()):
            chosen = index < len(sizes) and sizes[index] == s['size']
            button.setChecked(chosen)
            if index < len(sizes):
                size = config['sizes'][index]
                button.setIcon(shape_icon(size['width'], size['height'], theme.LIME if chosen else theme.MUTED))
        self.steps.setEnabled(model != 'turbo')
        self.guidance.setVisible(model == 'realistic')
        self.detail_strength.setVisible(s['detail'] != 'Off')
        self.repair_strength.setVisible(s['repair'])
        self.attempts.setVisible(s['check'])
        self.combine.setVisible(model == 'accurate')
        self.realism.setVisible(bool(config.get('lora')))
        self.personal.setVisible(bool(config.get('personal_lora')))
        self.sketching.setVisible(model != 'turbo')
        for widget, need in ((self.smart, 'assistant'), (self.repair, 'repair'), (self.references, 'references'),
                             (self.check, 'assistant')):
            widget.setEnabled(bool(config.get(need)))
        self.smart.set_description(
            'A little help shaping your idea' if config.get('assistant') else 'Needs the prompt assistant model'
        )
        if s['sketch']:
            image = from_data_url(s['sketch'])
            self.sketch_view.setPixmap(
                QPixmap.fromImage(image).scaled(
                    220, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self.sketch_view.clear()
        self.sketch_view.setVisible(bool(s['sketch']))
        self.unsketch.setVisible(bool(s['sketch']))
        self.update_buttons()

    def update_buttons(self):
        busy = self.busy
        installed = any(m['id'] == self.settings['model'] and m['ready'] for m in (self.config or {}).get('models', []))
        self.go.setEnabled(self.ready and bool(self.config) and not busy and installed
                           and bool(self.settings['prompt'].strip()))
        self.go.setText(' Creating your image…' if busy and self.kind == 'generate' else ' Generate image')
        self.draft.setEnabled(
            bool((self.config or {}).get('assistant')) and self.ready and not busy
            and bool(self.settings['prompt'].strip())
        )
        self.draft.setText('Sketching…' if busy and self.kind == 'sketch' else 'Sketch from prompt')
        if not self.ready:
            hint = 'Waiting for the engine…'
        elif self.config and not installed:
            hint = 'This model is not installed yet.'
        elif busy and self.kind not in ('generate', 'sketch'):
            hint = 'Another job is running in the studio.'
        else:
            hint = 'Ctrl + Enter to generate'
        self.hint.setText(hint)

    @property
    def busy(self):
        return self.submitting or self.active is not None

    def prompt_changed(self):
        text = self.prompt.toPlainText()
        if len(text) > MAX_PROMPT:
            cursor = self.prompt.textCursor()
            self.prompt.setPlainText(text[:MAX_PROMPT])
            cursor.setPosition(min(cursor.position(), MAX_PROMPT))
            self.prompt.setTextCursor(cursor)
            return
        self.set('prompt', text)

    def set_prompt(self, text):
        self.update_settings(prompt=text)
        self.prompt.setFocus()

    def seed_edited(self, text):
        digits = re.sub(r'\D', '', text)
        if digits != text:
            self.seed.setText(digits)
        self.set('seed', digits)

    def model_changed(self, _):
        model = self.model.currentData()
        if model and model != self.settings['model']:
            self.update_settings(model=model, steps=MODELS[model][2][2], detail='Off')

    def pick_aspect(self, index):
        self.update_settings(size=self.config['sizes'][index]['id'])

    def new_creation(self):
        self.update_settings(prompt='', seed='', sketch=None)
        if not self.busy:
            self.job = None
            self.render()
        self.prompt.setFocus()

    def reuse(self, item):
        """Load the settings that made a library picture."""
        if not self.config:
            self.notify('The engine is not ready yet.', error=True)
            return
        self.update_settings(**reused(item.get('metadata') or {}, self.config))
        self.notify('Settings loaded. Keep the seed, or clear it for a new variation.')

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
        for box in (self.model, self.size):
            box.blockSignals(True)
            box.clear()
        for model in config['models']:
            name = MODELS.get(model['id'], (model['label'],))[0]
            self.model.addItem(name + ('' if model['ready'] else '  ·  not installed'), model['id'])
        for size in config['sizes']:
            self.size.addItem(size['id'], size['id'])
        for index, button in enumerate(self.aspects.buttons()):
            button.setVisible(index < len(config['sizes']))
        for box in (self.model, self.size):
            box.blockSignals(False)
        self.settings = starting(config, self.saved()) if first else clean(self.settings, config)
        self.form.setEnabled(True)
        self.show_settings()
        if config.get('active_job') and self.active is None:
            self.follow(config['active_job'], 'generate')  # a job that was running before the app opened

    def generate(self):
        if not self.go.isEnabled():
            return
        try:
            body = request_body(self.settings)
        except ValueError as exc:
            self.notify(str(exc), error=True)
            return
        self.submit('/api/generate', body, 'generate')

    def sketch_from_prompt(self):
        self.submit('/api/sketch', dict(prompt=self.settings['prompt'], size=self.settings['size']), 'sketch')

    def submit(self, path, body, kind):
        self.submitting = True
        self.kind = kind
        self.update_buttons()

        def started(job):
            self.submitting = False
            self.follow(job['id'], kind, job)

        def refused(error):
            self.submitting = False
            self.update_buttons()
            self.notify(error, error=True)

        self.client.post(path, body, started, refused, timeout=60000)

    def follow(self, job_id, kind, job=None):
        self.active, self.kind, self.failures = job_id, kind, 0
        if kind == 'generate':
            self.job, self.shown = job or dict(id=job_id, state='running', progress=0, message='Rendering…', images=[]), -1
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
        if self.kind == 'generate':
            self.job = job
        if job['state'] == 'running':
            self.render()
            self.poller.start(POLL_MS)
            return
        self.active = None
        if job['state'] == 'error':
            self.notify(job['message'], error=True)
        if job.get('sketch'):
            self.update_settings(sketch=job['sketch'])
            self.sketching.set_open(True)
            self.notify('Composition sketch ready.')
        self.library.refresh()
        self.render()

    def lost(self, job_id, error):
        if job_id != self.active:
            return
        self.failures += 1
        if self.failures >= 5 or 'not found' in error.lower():
            self.active = None
            if self.job and self.job.get('state') == 'running':
                self.job = dict(self.job, state='error', message=f'Lost track of the render: {error}')
            self.notify(f'Lost track of the render: {error}', error=True)
            self.render()
            return
        self.poller.start(POLL_MS)

    def cancel(self):
        if self.active:
            self.client.post(
                f'/api/jobs/{self.active}/cancel', {}, lambda _: self.notify('Stopping after the current step…'),
                lambda error: self.notify(error, error=True),
            )

    def upload_sketch(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose a sketch', '', 'Images (*.png *.jpg *.jpeg *.webp *.bmp)'
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            self.notify('That file is not a picture this app can read.', error=True)
            return
        if image.width() * image.height() > 25_000_000:
            self.notify('Please use a picture below 25 megapixels.', error=True)
            return
        self.update_settings(sketch=data_url(image))

    # Showing results ----------------------------------------------------------------

    @property
    def results(self):
        return (self.job or {}).get('images') or []

    def render(self):
        job, results = self.job, self.results
        if job is None:
            self.canvas.setCurrentWidget(self.hero)
        elif results:
            self.canvas.setCurrentWidget(self.result)
            self.load_full(results[self.shown])
        else:
            state = job['state']
            self.waiting_title.setText({
                'running': 'A little imagination. A little magic.',
                'error': 'Let’s give that another try.',
            }.get(state, 'Paused at your request.'))
            self.waiting_text.setText('Your image is taking shape.' if state == 'running' else job.get('message', ''))
            self.canvas.setCurrentIndex(1)
        self.status.setVisible(job is not None)
        if job is not None:
            running = job['state'] == 'running'
            self.status_text.setText(job.get('message') or '')
            self.status_text.setProperty('role', 'error' if job['state'] == 'error' else '')
            self.status_text.style().polish(self.status_text)
            self.progress.setVisible(running)
            self.progress.setValue(max(30, int(job.get('progress', 0) * 1000)))
            self.stop.setVisible(running and self.active == job.get('id'))
            self.details.setVisible(bool(results))
            self.save.setVisible(bool(results))
        for index, thumb in enumerate(self.strip_thumbs):
            thumb.setVisible(len(results) > 1 and index < len(results))
            if index < len(results):
                thumb.set_item(results[index])
        understood = (job or {}).get('understood')
        self.notes.setVisible(bool(understood))
        self.notes_text.setText('\n\n'.join(part for part in (understood, (job or {}).get('report')) if part))
        self.update_buttons()

    def show_result(self, index):
        self.shown = index
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
                if self.results and self.results[self.shown]['name'] == name:
                    self.result.set_pixmap(pixmap)

        self.client.bytes(item['url'], loaded, None, timeout=120000)

    def view_details(self):
        if self.results:
            self.library.show_details(list(self.results), self.shown % len(self.results))

    def save_result(self):
        if self.results:
            item = self.results[self.shown]
            save_to(self, self.client, self.notify, f'/api/library/{item["name"]}/download', item['name'], '.png',
                    'Save a copy')

    def show_recent(self):
        items = sorted(self.library.all, key=lambda item: item['created'], reverse=True)
        self.recent_title.setText(
            f'Fresh from your imagination  <span style="color:{theme.MUTED}; font-weight:400">{len(items)}</span>'
        )
        for index, thumb in enumerate(self.recent):
            thumb.setVisible(index < len(items))
            thumb.set_item(items[index] if index < len(items) else None)
        self.recent_empty.setVisible(not items)
        self.recent_items = items[:4]
        scenic = next((item for item in items if SCENIC.match((item.get('metadata') or {}).get('prompt') or '')),
                      items[0] if items else None)
        if scenic and scenic['name'] != self.scenic:
            self.scenic = scenic['name']
            self.client.bytes(scenic['url'], self.hero_loaded, None, timeout=120000)

    def hero_loaded(self, data):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.hero.set_pixmap(pixmap)

    def open_recent(self, index):
        self.library.show_details(list(self.recent_items), index)

"""Studio settings: what the studio has learned from you, the models and tools it can install, and its apps."""

import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from image_studio.core import engine_env, hardware, paths
from image_studio.desktop import installs, theme
from image_studio.desktop.controls import Box, PageHeader, Toggle, rule, scroll_page
from image_studio.desktop.engine import in_background
from image_studio.desktop.system_page import card
from image_studio.desktop.theme import label

TRAINING_POLL_MS = 4000
MODEL_NAMES = {'realistic': 'Realistic', 'accurate': 'Accurate', 'turbo': 'Turbo'}
STEP_NAMES = {'grade': 'light and color looks'}
KRITA_DOWNLOAD = 'https://krita.org/en/download/'
TOKENS = 'https://huggingface.co/settings/tokens'
BUSY = 'Another install is running.'  # the Install button's tooltip only; rows stay quiet


def profile_text(profile):
    """Your usual settings in words: 'Realistic · 1024 × 1024 · Film finish · realism 0.6'."""
    parts = [
        MODEL_NAMES.get(profile.get('model')),
        profile.get('size'),
        f'{profile["finish"]} finish' if profile.get('finish') and profile['finish'] != 'Off' else None,
        f'realism {profile["realism"]}' if profile.get('realism') else None,
    ]
    return ' · '.join(part for part in parts if part)


def style_text(personal):
    """What the style training row says, from the engine's /api/memory personal status."""
    if personal['state'] == 'training':
        return personal.get('message') or 'Learning your style…'
    if personal['state'] == 'failed':
        return f'Last training failed: {personal.get("message")}'
    if personal.get('ready'):
        when = ''
        if personal.get('trained_at'):
            when = f' on {time.strftime("%d %B %Y", time.localtime(personal["trained_at"]))}'
        return (f'Learned from {personal["trained_on"]} favorites{when}. {personal["changed"]} changed since. '
                'Use the "My style" slider in Create.')
    if personal['favorites'] >= personal['minimum']:
        return (f'Learns the look of your {personal["favorites"]} favorite pictures, in about '
                f'{personal["minutes"]} minutes.')
    missing = personal['minimum'] - personal['favorites']
    return (f'Learns the look of your favorite pictures. Mark {missing} more as favorites to start '
            f'({personal["favorites"]} of {personal["minimum"]}).')


def restyle(widget, **properties):
    for name, value in properties.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def link_button(url, tip):
    button = QPushButton(theme.icon('external-link', theme.MUTED), '')
    button.setProperty('kind', 'flat')
    button.setToolTip(tip)
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return button


class PartRow(Box):
    """One installable model or tool: what it is for, whether it is installed, and Install."""

    def __init__(self, part):
        super().__init__()
        self.part = part
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 10, 0, 10)
        column.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(label(part.title, 'value'))
        self.badge = label('', 'badge')
        top.addWidget(self.badge)
        top.addStretch()
        self.cancel = QPushButton('Stop')
        self.cancel.setToolTip('Stop the download. It resumes where it stopped when you install again.')
        top.addWidget(self.cancel)
        self.install = QPushButton(theme.icon('download'), 'Install')
        top.addWidget(self.install)
        if part.page:
            top.addWidget(link_button(part.page, 'Model page and licence'))
        column.addLayout(top)
        details = f'{part.what} {part.size[0].upper()}{part.size[1:]}.'
        if part.note:
            details += ' ' + part.note
        self.details = label(details, 'small', wrap=True)
        column.addWidget(self.details)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        column.addWidget(self.bar)
        self.message = label('', 'small', wrap=True)
        column.addWidget(self.message)
        self.show_state(False, False, '')

    def show_state(self, ready, running, message, percent=None, blocked=''):
        installable = installs.supported(self.part)
        if running:
            name, tone = 'Installing', 'warn'
        elif ready:
            name, tone = 'Installed', ''
        else:
            name, tone = ('Not installed', 'off') if installable else ('Windows only for now', 'off')
        self.badge.setText(name)
        restyle(self.badge, tone=tone)
        self.install.setVisible(not ready and not running and installable)
        self.install.setEnabled(not blocked)
        self.install.setToolTip(blocked)
        self.cancel.setVisible(running)
        self.bar.setVisible(running)
        if percent is None:
            self.bar.setRange(0, 0)  # moving, while the size is unknown
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(percent)
        self.message.setText(message)
        self.message.setVisible(bool(message))


class TokenDialog(QDialog):
    """FLUX.1 Kontext is gated: accept its licence on Hugging Face, then give a read token."""

    def __init__(self, parent, part):
        super().__init__(parent)
        self.setWindowTitle('Accept the licence first')
        self.setMinimumWidth(520)
        column = QVBoxLayout(self)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(10)
        column.addWidget(label(part.title, 'heading'))
        steps = label(
            f'Its maker lets you download it once you accept the licence. This is free:<br><br>'
            f'1. Sign in at Hugging Face and accept the licence on '
            f'<a style="color:{theme.ACCENT}" href="{part.page}">the model page</a>.<br>'
            f'2. Create a token of the <b>Read</b> type on '
            f'<a style="color:{theme.ACCENT}" href="{TOKENS}">your tokens page</a>.<br>'
            f'3. Paste it here. It is used for this download only and is not saved.',
            wrap=True,
        )
        steps.setTextFormat(Qt.TextFormat.RichText)
        steps.setOpenExternalLinks(True)
        column.addWidget(steps)
        self.token = QLineEdit()
        self.token.setPlaceholderText('hf_…')
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        column.addWidget(self.token)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton(theme.icon('download', theme.ON_ACCENT), 'Install')
        self.ok.setProperty('kind', 'primary')
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(self.ok)
        column.addLayout(buttons)
        self.token.textChanged.connect(lambda text: self.ok.setEnabled(len(text.strip()) > 8))


class SettingsPage(QWidget):
    tab_opened = Signal(str)

    def __init__(self, client, notify, use_profile, installed, start_engine=None, stop_engine=None):
        super().__init__()
        self.client, self.notify = client, notify
        self.use_profile = use_profile  # loads your usual settings into Create
        self.installed = installed  # tells the other screens a model arrived
        self.start_engine = start_engine  # after the engine itself is installed
        self.stop_engine = stop_engine  # before PyTorch goes into the environment the engine runs from
        self.ready = False
        self.engine_status, self.engine_kind = 'ready', 'full'
        self.read_engine()
        self.nvidia = None  # NVIDIA cards found, once looked up (without one, the engine runs in cloud mode)
        self.engine_installing = 'full'  # which engine the running install sets up
        self.config, self.learned, self.models_dir = None, None, ''
        self.progress = {}  # part key -> (text, percent) while installing
        self.messages = {}  # part key -> how its last install ended
        self.installer = installs.Installer(self)
        self.installer.release = self.release_gpu
        self.installer.progress.connect(self.install_progress)
        self.installer.finished.connect(self.install_finished)
        self.poll = QTimer(self)
        self.poll.setInterval(TRAINING_POLL_MS)
        self.poll.timeout.connect(self.load_memory)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(PageHeader('Settings'))
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)
        tabs = QWidget()
        tabs.setObjectName('Panel')
        tabs.setProperty('side', 'left')
        tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        tabs.setFixedWidth(200)
        self.tab_column = QVBoxLayout(tabs)
        self.tab_column.setContentsMargins(10, 14, 10, 14)
        self.tab_column.setSpacing(2)
        self.tab_column.addStretch()
        body.addWidget(tabs)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.tab_group = QButtonGroup(self)
        self.tabs = {}  # key -> (button, icon, page)

        page, layout = scroll_page('Models and tools', 'Models that run on this PC. Each downloads once from its '
                                                         'maker into your models folder, and resumes if the '
                                                         'connection drops.')
        self.waiting_note = label('Waiting for the engine…', 'muted')
        layout.addWidget(self.waiting_note)
        layout.addWidget(self.engine_card())
        layout.addWidget(self.models_card())
        layout.addWidget(self.apps_card())
        layout.addStretch()
        self.add_tab('models', 'Models', 'hard-drive', page)
        page, layout = scroll_page('Personalization', 'What the studio has learned from your favorites and '
                                                       'your corrections. It stays on this PC.')
        layout.addWidget(self.learning_card())
        layout.addStretch()
        self.add_tab('learning', 'Personalization', 'heart', page)
        self.show_learned()
        self.show_parts()

    # Tabs ------------------------------------------------------------------------------

    def add_tab(self, key, title, icon, page, first=False):
        button = QPushButton(theme.icon(icon, theme.MUTED), f'  {title}')
        button.setProperty('kind', 'tab')
        button.setCheckable(True)
        button.setIconSize(QSize(16, 16))
        button.clicked.connect(lambda _=False, key=key: self.open_tab(key))
        self.tab_group.addButton(button)
        self.tab_column.insertWidget(0 if first else self.tab_column.count() - 1, button)
        self.stack.addWidget(page)
        self.tabs[key] = (button, icon, page)
        if len(self.tabs) == 1 or first:
            self.open_tab(key)

    def open_tab(self, key):
        if key not in self.tabs:
            return
        for name, (button, icon, _) in self.tabs.items():
            button.setChecked(name == key)
            button.setIcon(theme.icon(icon, theme.TEXT if name == key else theme.MUTED))
        self.stack.setCurrentWidget(self.tabs[key][2])
        self.tab_opened.emit(key)

    @property
    def tab_order(self):
        """The tabs as they are listed, top to bottom."""
        buttons = {button: key for key, (button, _, _) in self.tabs.items()}
        items = (self.tab_column.itemAt(index).widget() for index in range(self.tab_column.count()))
        return [buttons[widget] for widget in items if widget in buttons]

    @property
    def current_tab(self):
        return next((key for key, (_, _, page) in self.tabs.items() if page is self.stack.currentWidget()), None)

    # Layout ----------------------------------------------------------------------------

    def learning_card(self):
        frame, box = card()
        self.learning = frame
        box.addWidget(label('Learned from you', 'heading'))
        self.learning_off = label('', 'muted', wrap=True)
        box.addWidget(self.learning_off)

        self.learned_box = Box()
        column = QVBoxLayout(self.learned_box)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(12)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label('My style', 'value'))
        self.style_text = label('', 'small', wrap=True)
        text.addWidget(self.style_text)
        self.style_bar = QProgressBar()
        self.style_bar.setTextVisible(False)
        self.style_bar.setRange(0, 100)
        text.addWidget(self.style_bar)
        row.addLayout(text, 1)
        self.train = QPushButton(theme.icon('sparkles'), 'Train now')
        self.train.clicked.connect(self.start_training)
        row.addWidget(self.train, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(row)
        self.nightly = Toggle('Learn overnight', 'Between 1 and 5 AM, when the studio is open and idle and at '
                                                 'least 5 favorites changed.')
        self.nightly.toggled.connect(self.set_nightly)
        column.addWidget(self.nightly)

        self.usual = Box()
        row = QHBoxLayout(self.usual)
        row.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label('Your usual settings', 'value'))
        self.usual_text = label('', 'small', wrap=True)
        text.addWidget(self.usual_text)
        row.addLayout(text, 1)
        use = QPushButton('Use these')
        use.setToolTip('Load them into Create image.')
        use.clicked.connect(lambda: self.learned and self.use_profile(self.learned.get('profile') or {}))
        row.addWidget(use, 0, Qt.AlignmentFlag.AlignTop)
        column.addWidget(self.usual)

        head = QHBoxLayout()
        head.addWidget(label('Words you taught me', 'value'))
        head.addStretch()
        self.forget_all = QPushButton('Forget everything')
        self.forget_all.setProperty('kind', 'flat')
        self.forget_all.setToolTip('Forget every word you taught and how strong you like edits.')
        self.forget_all.clicked.connect(self.forget_everything)
        head.addWidget(self.forget_all)
        column.addLayout(head)
        self.words = QVBoxLayout()
        self.words.setSpacing(2)
        column.addLayout(self.words)
        teach = QHBoxLayout()
        self.phrase = QLineEdit()
        self.phrase.setPlaceholderText('When I say… (make it pop)')
        self.means = QLineEdit()
        self.means.setPlaceholderText('I mean… (more contrast and vibrance)')
        self.teach_button = QPushButton('Teach')
        self.teach_button.clicked.connect(self.teach)
        for widget in (self.phrase, self.means):
            widget.textChanged.connect(self.check_teach)
            widget.returnPressed.connect(self.teach)
        teach.addWidget(self.phrase, 1)
        teach.addWidget(self.means, 1)
        teach.addWidget(self.teach_button)
        column.addLayout(teach)
        self.check_teach()

        self.strength = Box()
        row = QHBoxLayout(self.strength)
        row.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label('How strong you like edits', 'value'))
        self.strength_text = label('', 'small', wrap=True)
        text.addWidget(self.strength_text)
        row.addLayout(text, 1)
        reset = QPushButton('Reset')
        reset.clicked.connect(lambda: self.change(dict(action='reset_strength'), 'Edit strengths are back to normal.'))
        row.addWidget(reset, 0, Qt.AlignmentFlag.AlignTop)
        column.addWidget(self.strength)
        column.addWidget(label(
            'In Krita, type "remember: make it pop means more contrast", correct a result with "no, I meant '
            'warmer", or say "too much" or "more" right after an edit. "forget make it pop" and "forget '
            'everything" undo what was learned.', 'small', wrap=True))
        box.addWidget(self.learned_box)
        return frame

    def engine_card(self):
        """An installed copy's first install: the engine every model runs on, or its cloud mode."""
        self.engine_frame, box = card()
        box.addWidget(label('Engine', 'heading'))
        self.engine_intro = label(
            'One-time setup: the app itself is small, and the engine downloads once from PyTorch and the '
            'Python package index. After that, install the models you want below. No NVIDIA graphics card? '
            'Cloud mode is a small download that creates and edits with the providers you connect.',
            'small', wrap=True)
        box.addWidget(self.engine_intro)
        self.engine_row = PartRow(installs.ENGINE)
        self.engine_row.install.clicked.connect(lambda: self.install_engine('full'))
        self.engine_row.cancel.clicked.connect(self.installer.cancel)
        box.addWidget(self.engine_row)
        self.cloud_rule = rule()
        box.addWidget(self.cloud_rule)
        self.cloud_row = PartRow(installs.ENGINE_CLOUD)
        self.cloud_row.install.clicked.connect(lambda: self.install_engine('cloud'))
        self.cloud_row.cancel.clicked.connect(self.installer.cancel)
        box.addWidget(self.cloud_row)
        if paths.INSTALLED:
            in_background(hardware.nvidia, self.found_cards)
        return self.engine_frame

    def found_cards(self, cards, error):
        self.nvidia = None if error else cards
        self.show_parts()

    def models_card(self):
        frame, box = card()
        top = QHBoxLayout()
        top.addWidget(label('On this PC', 'heading'))
        top.addStretch()
        self.space = label('', 'small')
        top.addWidget(self.space)
        box.addLayout(top)
        box.addWidget(label('No GPU for these? Connect a cloud provider in Providers instead.', 'small', wrap=True))
        self.rows = {}
        for index, part in enumerate(installs.PARTS):
            if index:
                box.addWidget(rule())
            row = PartRow(part)
            row.install.clicked.connect(lambda _=False, key=part.key: self.install(key))
            row.cancel.clicked.connect(self.installer.cancel)
            self.rows[part.key] = row
            box.addWidget(row)
        return frame

    def apps_card(self):
        frame, box = card()
        box.addWidget(label('Apps', 'heading'))
        self.apps = {}
        for key, title, what, url in (
            ('photocraft', 'PhotoCraft', 'The photo editor behind PhotoCraft studio and its layered edits.', ''),
            ('krita', 'Krita', 'The free painting app behind Krita canvas. The studio adds its AI panel to it.',
             KRITA_DOWNLOAD),
            ('lora', 'Realism LoRA', ('Makes RealVisXL pictures look more like everyday photos. It is trained on '
                                      'your PC rather than downloaded; see docs/model-guide.md.'), ''),
        ):
            row = QHBoxLayout()
            text = QVBoxLayout()
            text.setSpacing(2)
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(label(title, 'value'))
            badge = label('', 'badge')
            head.addWidget(badge)
            head.addStretch()
            text.addLayout(head)
            text.addWidget(label(what, 'small', wrap=True))
            row.addLayout(text, 1)
            if url:
                row.addWidget(link_button(url, f'Get {title}'), 0, Qt.AlignmentFlag.AlignTop)
            box.addLayout(row)
            self.apps[key] = badge
        return frame

    # Engine ----------------------------------------------------------------------------

    def engine_ready(self):
        self.ready = True
        self.engine_status = 'ready'
        self.refresh()

    def read_engine(self):
        """What the installed engine is: its status, and 'full' or 'cloud' (a source checkout: full, ready)."""
        if paths.INSTALLED:
            self.engine_status, self.engine_kind = engine_env.status(), engine_env.kind()

    def engine_gone(self):
        self.ready = False
        self.read_engine()
        self.poll.stop()
        self.show_learned()
        self.show_parts()

    def refresh(self):
        if not self.ready:
            return
        self.client.get('/api/config', self.configured, None)
        self.client.get('/api/system', self.got_system, None)
        self.load_memory()

    def configured(self, config):
        self.config = config or {}
        self.show_parts()

    def got_system(self, info):
        self.models_dir = (info or {}).get('models_dir', '')
        self.show_parts()

    # What was learned ------------------------------------------------------------------

    def load_memory(self):
        if self.ready:
            self.client.get('/api/memory', self.got_learned, lambda _: self.got_learned(None))

    def got_learned(self, learned):
        self.learned = learned
        self.show_learned()

    def show_learned(self):
        learned = self.learned if self.ready else None
        self.waiting_note.setVisible(not self.ready and self.engine_status == 'ready')
        self.learned_box.setVisible(learned is not None)
        self.learning_off.setVisible(learned is None)
        self.learning_off.setText('Your learning appears when the engine is running.' if not self.ready else
                                  'Restart the engine to turn on learning.')
        if learned is None:
            self.poll.stop()
            return
        personal = learned['personal']
        training = personal['state'] == 'training'
        self.style_text.setText(style_text(personal))
        self.style_bar.setVisible(training)
        self.style_bar.setValue(max(3, round(personal.get('progress', 0) * 100)))
        self.train.setEnabled(not training and personal['favorites'] >= personal['minimum'])
        self.train.setText('Learning…' if training else 'Retrain now' if personal.get('ready') else 'Train now')
        self.train.setToolTip(f'About {personal["minutes"]} minutes; rendering pauses while it learns.')
        if training:
            self.poll.start()
        else:
            self.poll.stop()
        self.nightly.blockSignals(True)
        self.nightly.setChecked(bool(personal.get('nightly')))
        self.nightly.blockSignals(False)
        usual = profile_text(learned.get('profile') or {})
        self.usual.setVisible(bool(usual))
        self.usual_text.setText(f'Most of your {learned.get("favorites", 0)} favorites: {usual}')
        while self.words.count():
            item = self.words.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for word in learned.get('words') or []:
            self.words.addWidget(self.word_row(word))
        if not learned.get('words'):
            self.words.addWidget(label('None yet. Teach one below, or in Krita.', 'small'))
        self.forget_all.setEnabled(bool(learned.get('words') or learned.get('strength')))
        strength = learned.get('strength') or {}
        self.strength.setVisible(bool(strength))
        self.strength_text.setText(' · '.join(
            f'{STEP_NAMES.get(step, step.replace("_", " "))}: {round(factor * 100)}% of normal'
            for step, factor in strength.items()))

    def word_row(self, word):
        row = Box()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        used = word.get('used', 0)
        source = 'from a correction' if word.get('source') == 'correction' else 'taught'
        text = label(f'“{word["phrase"]}” means “{word["means"]}”  ·  {source} · used {used} '
                     f'time{"" if used == 1 else "s"}', wrap=True)
        line.addWidget(text, 1)
        forget = QPushButton(theme.icon('trash-2', theme.MUTED), '')
        forget.setProperty('kind', 'flat')
        forget.setToolTip(f'Forget “{word["phrase"]}”')
        forget.clicked.connect(lambda: self.change(dict(action='forget', phrase=word['phrase']),
                                                   f'Forgotten: “{word["phrase"]}”.'))
        line.addWidget(forget)
        return row

    def change(self, body, message='', then=None):
        def saved(learned):
            self.got_learned(learned)
            if message:
                self.notify(message)
            if then:
                then()

        self.client.post('/api/memory', body, saved, lambda error: self.notify(error, error=True))

    def check_teach(self):
        self.teach_button.setEnabled(len(self.phrase.text().strip()) >= 3 and bool(self.means.text().strip()))

    def teach(self):
        if not self.teach_button.isEnabled():
            return
        phrase = self.phrase.text().strip()

        def taught():
            self.phrase.clear()
            self.means.clear()

        self.change(dict(action='teach', phrase=phrase, means=self.means.text().strip()), f'Learned: “{phrase}”.',
                    taught)

    def forget_everything(self):
        answer = QMessageBox.question(self, 'Forget everything?',
                                      'Forget every word you taught and how strong you like edits? '
                                      'Your favorites and your style training are kept.')
        if answer == QMessageBox.StandardButton.Yes:
            self.change(dict(action='forget_all'), 'Everything taught is forgotten.')

    def start_training(self):
        self.client.post('/api/personal-lora', dict(action='train'),
                         lambda _: (self.notify('Learning your style. Rendering is paused until it finishes.'),
                                    self.load_memory()),
                         lambda error: self.notify(error, error=True))

    def set_nightly(self, enabled):
        self.client.post('/api/personal-lora', dict(action='nightly', enabled=enabled), lambda _: self.load_memory(),
                         lambda error: (self.notify(error, error=True), self.load_memory()))

    # Installing ------------------------------------------------------------------------

    def show_parts(self):
        self.show_engine()
        config = self.config if self.ready else None
        free = installs.free_gb(self.models_dir) if self.models_dir else None
        self.space.setText(f'{free:.0f} GB free on the models drive' if free is not None else '')
        for key, row in self.rows.items():
            part = row.part
            running = self.installer.key == key
            ready = bool(config) and part.ready(config)
            blocked = ''
            if self.engine_status != 'ready':
                blocked = 'Set up the engine first.'
            elif config is not None and not config.get('local_models', True):
                blocked = 'Needs the full engine and an NVIDIA graphics card; this engine runs in cloud mode.'
            elif config is None or not self.models_dir:
                blocked = 'Installing needs the engine running.'
            elif self.installer.running and not running:
                blocked = BUSY
            elif part.needs and not installs.BY_KEY[part.needs].ready(config):
                blocked = f'Install {installs.BY_KEY[part.needs].title} first.'
            text, percent = self.progress.get(key, ('', None)) if running else (self.messages.get(key, ''), None)
            if blocked not in ('', BUSY) and not ready and not running and not text and config is not None:
                text = blocked
            row.show_state(ready, running, text, percent, blocked)
        for key, badge in self.apps.items():
            if config is None:
                badge.setText('')
                badge.setVisible(False)
                continue
            found = bool(config.get(key))
            badge.setVisible(True)
            badge.setText(('Trained' if key == 'lora' else 'Found') if found else
                          ('Not trained' if key == 'lora' else 'Not found'))
            restyle(badge, tone='' if found else 'off')

    def show_engine(self):
        """The Engine rows (installed copies only): the full engine and cloud mode, each set up,
        needing an update, or installing. Once the full engine is set up, cloud mode is part of it."""
        self.engine_frame.setVisible(paths.INSTALLED)
        status, kind = self.engine_status, self.engine_kind
        full_ready = status == 'ready' and kind == 'full'
        self.cloud_rule.setVisible(not full_ready)
        self.cloud_row.setVisible(not full_ready)
        self.engine_intro.setVisible(status != 'ready')
        for row, this in ((self.engine_row, 'full'), (self.cloud_row, 'cloud')):
            running = self.installer.key == 'engine' and self.engine_installing == this
            mine = status != 'missing' and kind == this  # the engine set up here is this one
            blocked = ''
            if self.installer.running and not running:
                blocked = BUSY
            elif this == 'full' and self.nvidia == []:
                blocked = ('The full engine needs an NVIDIA graphics card, and none was found (This PC shows what '
                           'this computer has). Cloud mode works without one.')
            elif this == 'cloud' and kind == 'full' and status != 'missing':
                blocked = 'The full engine is set up here; finish it above instead.'
            text, percent = (self.progress.get('engine', ('', None)) if running else
                             (self.messages.get('engine', '') if self.engine_installing == this else '', None))
            if not text and not running and mine and status == 'update':
                text = 'An update changed what the engine needs. Install to finish it; only what changed downloads.'
            if not text and not running and this == 'full' and kind == 'cloud' and status == 'ready' and self.nvidia:
                text = ('This PC has an NVIDIA graphics card: install the full engine to run models on it. '
                        'Cloud mode keeps working alongside.')
            if blocked not in ('', BUSY) and not running and not text and not (mine and status == 'ready'):
                text = blocked
            row.show_state(mine and status == 'ready', running, text, percent, blocked)

    def room_for(self, part, folder, drive):
        """Whether to go ahead: true, or the person says so when the drive is nearly full."""
        free = installs.free_gb(folder)
        if free is None or free >= part.size_gb + 1:
            return True
        answer = QMessageBox.question(
            self, 'Not much room', f'{part.title} needs {part.size}, and the {drive} has {free:.1f} GB free. '
                                   'Install anyway?')
        return answer == QMessageBox.StandardButton.Yes

    def install(self, key, token=''):
        part = installs.BY_KEY[key]
        if self.installer.running or not self.config or not self.models_dir:
            return
        if not self.room_for(part, self.models_dir, 'models drive'):
            return
        self.messages.pop(key, None)
        self.progress[key] = ('Starting…', None)
        self.installer.start(part, self.config, self.models_dir, token)
        self.show_parts()

    def install_engine(self, kind='full'):
        part = installs.ENGINE_CLOUD if kind == 'cloud' else installs.ENGINE
        if self.installer.running or not self.room_for(part, paths.ENGINE_ENV, 'drive it goes on'):
            return
        if self.engine_status == 'ready' and self.stop_engine is not None:
            # Libraries go into the environment the engine runs from: it starts again once the install ends.
            self.stop_engine('Stopped while the engine is installed.')
        self.engine_installing = kind
        self.messages.pop('engine', None)
        self.progress['engine'] = ('Starting…', None)
        self.installer.start(part, {}, paths.WORK)
        self.show_parts()

    def install_progress(self, key, text, percent):
        self.progress[key] = (text, percent)
        self.show_parts()

    def install_finished(self, key, ok, message):
        self.progress.pop(key, None)
        part = installs.ENGINE_CLOUD if key == 'engine' and self.engine_installing == 'cloud' else installs.BY_KEY[key]
        if key == 'engine':
            self.read_engine()
        if ok and key == 'engine':
            self.notify('The engine is installed (cloud mode). Starting it…' if self.engine_kind == 'cloud' else
                        'The engine is installed. Starting it…')
            if self.start_engine is not None:
                self.start_engine()
        elif ok:
            self.notify(f'{part.title} is installed.')
            self.installed()
            self.refresh()
        elif message == installs.GATED:
            self.messages[key] = 'Waiting for the licence: accept it on the model page, then install again.'
            self.show_parts()
            dialog = TokenDialog(self, part)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.install(key, dialog.token.text().strip())
            return
        else:
            self.messages[key] = message
            self.notify(f'{part.title}: {message}', error=True)
            if key == 'engine' and self.engine_status == 'ready' and self.start_engine is not None:
                self.start_engine()  # an upgrade that did not finish: the engine as it was still runs
        self.show_parts()

    def release_gpu(self, then):
        """Free the engine's GPU memory before a step that paints on the GPU."""
        self.client.post('/api/system/release', None, lambda _: then(),
                         lambda error: (self.installer.cancel(), self.notify(error, error=True)))

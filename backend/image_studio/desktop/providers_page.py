"""Settings → Providers: connect cloud services with an API key, and choose the assistant's model.

Everything here works without the engine: keys and choices are written straight to the
settings and the encrypted key store (core/providers.py, core/credentials.py), and the
engine reads them on its next request.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from image_studio.core import credentials, providers
from image_studio.desktop import theme
from image_studio.desktop.controls import Box, rule, scroll_page
from image_studio.desktop.engine import in_background
from image_studio.desktop.theme import label

GROUPS = [
    ('Create and edit pictures', ('openai', 'gemini', 'fal', 'replicate')),
    ('Editing assistant only', ('anthropic', 'openrouter')),
    ('Servers on this PC or your network', ('ollama', 'lmstudio', 'custom')),
]
# A quiet color per service for its initial, so the list is easy to scan.
MARKS = dict(openai='#10a37f', gemini='#4285f4', anthropic='#c96442', fal='#7c3aed', replicate='#e11d48',
             openrouter='#6366f1', ollama='#52525b', lmstudio='#0ea5e9', custom='#71717a')
LOCAL = 'Bundled Qwen model (this PC)'


def uses(spec):
    parts = [name for name, key in (('Create', 'images'), ('Edit', 'edits'), ('Assistant', 'assistant'))
             if spec.get(key)]
    return ' · '.join(parts)


def mark(provider, size=34):
    """The service's initial on its color, as a stand-in for a logo."""
    badge = QLabel(providers.PROVIDERS[provider]['label'][0].upper())
    badge.setFixedSize(size, size)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(f'background: {MARKS.get(provider, theme.MUTED)}; color: white; border-radius: 8px; '
                        f'font-weight: 600; font-size: 11pt;')
    return badge


def model_box(suggestions, current):
    """An editable drop-down: pick a suggested model, or type any name the provider offers."""
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    for name in dict.fromkeys([*(suggestions or []), current]):
        if name:
            box.addItem(name)
    box.setCurrentText(current or '')
    return box


class ProviderDialog(QDialog):
    """Connect one service: its key (or address), which models it uses, and a test."""

    def __init__(self, parent, provider, found=None):
        super().__init__(parent)
        self.provider = provider
        self.spec = spec = providers.PROVIDERS[provider]
        self.found = found or []
        self.options = providers.options(provider)
        connected = providers.connected(provider)
        self.setWindowTitle(f'Connect {spec["label"]}')
        self.setMinimumWidth(540)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 22, 24, 20)
        column.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(mark(provider, 40))
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(label(spec['label'], 'heading'))
        title.addWidget(label(uses(spec), 'small'))
        top.addLayout(title, 1)
        column.addLayout(top)
        column.addWidget(label(spec['about'], 'muted', wrap=True))

        self.key = None
        if providers.needs_key(provider):
            head = QHBoxLayout()
            head.addWidget(label('API key', 'eyebrow'))
            head.addStretch()
            if spec.get('keys'):
                get = QPushButton('Get a key ↗')
                get.setProperty('kind', 'link')
                get.setCursor(Qt.CursorShape.PointingHandCursor)
                get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(spec['keys'])))
                head.addWidget(get)
            column.addLayout(head)
            self.key = QLineEdit()
            self.key.setEchoMode(QLineEdit.EchoMode.Password)
            env = spec.get('env')
            if env and credentials.get('', env):
                self.key.setPlaceholderText(f'Using {env} from the environment')
            elif credentials.stored(providers.credential_name(provider)):
                self.key.setPlaceholderText('A key is saved. Paste a new one to replace it.')
            else:
                self.key.setPlaceholderText('Paste your key')
            reveal = QAction(theme.icon('eye', theme.MUTED), 'Show', self.key)
            reveal.triggered.connect(lambda: self.key.setEchoMode(
                QLineEdit.EchoMode.Normal if self.key.echoMode() == QLineEdit.EchoMode.Password
                else QLineEdit.EchoMode.Password))
            self.key.addAction(reveal, QLineEdit.ActionPosition.TrailingPosition)
            column.addWidget(self.key)

        self.address = None
        if spec.get('local') or spec.get('custom'):
            column.addWidget(label('Server address', 'eyebrow'))
            self.address = QLineEdit(self.options.get('base_url') or '')
            self.address.setPlaceholderText('http://127.0.0.1:8000/v1')
            column.addWidget(self.address)
            if spec.get('custom'):
                column.addWidget(label('API key (if the server needs one)', 'eyebrow'))
                self.key = QLineEdit()
                self.key.setEchoMode(QLineEdit.EchoMode.Password)
                self.key.setPlaceholderText('Optional')
                column.addWidget(self.key)

        self.image_model = self.edit_model = None
        if spec.get('images'):
            column.addWidget(label('Model for creating pictures', 'eyebrow'))
            self.image_model = model_box(spec['images'] + self.matching(), self.options['image_model'])
            column.addWidget(self.image_model)
        if spec.get('edits'):
            column.addWidget(label('Model for editing photos', 'eyebrow'))
            self.edit_model = model_box(spec['edits'] + self.matching(), self.options['edit_model'])
            column.addWidget(self.edit_model)

        check = QHBoxLayout()
        self.test_button = QPushButton(theme.icon('plug'), 'Test connection')
        self.test_button.clicked.connect(self.test)
        check.addWidget(self.test_button)
        self.result = label('', 'small', wrap=True)
        check.addWidget(self.result, 1)
        column.addLayout(check)
        column.addSpacing(6)

        buttons = QHBoxLayout()
        if connected:
            remove = QPushButton(theme.icon('trash-2', theme.DANGER), 'Disconnect')
            remove.setProperty('kind', 'danger')
            remove.clicked.connect(self.disconnect)
            buttons.addWidget(remove)
        buttons.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.save_button = QPushButton('Save')
        self.save_button.setProperty('kind', 'primary')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        column.addLayout(buttons)
        self.removed = False

    def matching(self):
        """Models from the last test that look like image models."""
        return [name for name in self.found if 'image' in name.lower()]

    def typed_key(self):
        return self.key.text().strip() if self.key is not None else ''

    def test(self):
        self.test_button.setEnabled(False)
        self.result.setText('Checking…')
        theme.restyle(self.result, role='small')
        key = self.typed_key() or None
        address = self.address.text().strip() if self.address is not None else None
        in_background(lambda: providers.test(self.provider, key, address), self.tested)

    def tested(self, answer, error):
        self.test_button.setEnabled(True)
        ok, message, names = answer if error is None else (False, str(error), [])
        self.result.setText(message)
        theme.restyle(self.result, role='small' if ok else 'error')
        if ok and names:
            self.found = names
            for box in (self.image_model, self.edit_model):
                if box is not None:
                    current = box.currentText()
                    for name in self.matching():
                        if box.findText(name) < 0:
                            box.addItem(name)
                    box.setCurrentText(current)

    def save(self):
        key = self.typed_key()
        if providers.needs_key(self.provider) and not key and not providers.key(self.provider):
            self.result.setText('Paste a key first.')
            theme.restyle(self.result, role='error')
            return
        values = dict(enabled=True)
        if self.image_model is not None:
            values['image_model'] = self.image_model.currentText().strip()
        if self.edit_model is not None:
            values['edit_model'] = self.edit_model.currentText().strip()
        if self.address is not None:
            values['base_url'] = self.address.text().strip()
        if self.found:
            values['models'] = self.found[:400]  # offered as suggestions for the assistant
        providers.save(self.provider, api_key=key or None, **values)
        self.accept()

    def disconnect(self):
        answer = QMessageBox.question(self, f'Disconnect {self.spec["label"]}?',
                                      'The saved key and settings for this service are removed from this PC.')
        if answer == QMessageBox.StandardButton.Yes:
            providers.disconnect(self.provider)
            self.removed = True
            self.accept()


class ProviderRow(Box):
    def __init__(self, provider, open_dialog):
        super().__init__()
        self.provider = provider
        spec = providers.PROVIDERS[provider]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 10)
        row.setSpacing(12)
        row.addWidget(mark(provider), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(spec['label'], 'value'))
        head.addWidget(label(uses(spec), 'small'))
        self.badge = label('', 'badge')
        head.addWidget(self.badge)
        head.addStretch()
        text.addLayout(head)
        self.details = label('', 'small', wrap=True)
        text.addWidget(self.details)
        row.addLayout(text, 1)
        self.button = QPushButton()
        self.button.clicked.connect(lambda: open_dialog(provider))
        row.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.show_state()

    def show_state(self):
        spec = providers.PROVIDERS[self.provider]
        on = providers.connected(self.provider)
        options = providers.options(self.provider)
        self.badge.setText('Connected')
        self.badge.setVisible(on)
        details = [spec['about']]
        if on and spec.get('images'):
            details.append(f'Creates with {options["image_model"]}.')
        if on and (spec.get('local') or spec.get('custom')):
            details.append(options['base_url'])
        self.details.setText(' '.join(details))
        self.button.setText('Manage' if on else 'Connect')


class ProvidersPage(QWidget):
    def __init__(self, notify, changed):
        super().__init__()
        self.notify, self.changed = notify, changed
        self.found = {}  # provider -> model names its last test listed
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, column = scroll_page(
            'Providers',
            'Use your own API keys to create and edit pictures in the cloud, which needs no graphics card, or '
            'to choose the model behind the editing assistant. Keys are encrypted on this PC and only ever '
            'sent to their own service.')
        outer.addWidget(scroll)

        self.rows = {}
        for title, names in GROUPS:
            frame = QFrame()
            frame.setProperty('card', True)
            box = QVBoxLayout(frame)
            box.setContentsMargins(20, 14, 20, 8)
            box.setSpacing(0)
            box.addWidget(label(title, 'heading'))
            box.addSpacing(4)
            for index, name in enumerate(names):
                if index:
                    box.addWidget(rule())
                row = ProviderRow(name, self.open_dialog)
                self.rows[name] = row
                box.addWidget(row)
            column.addWidget(frame)

        column.addWidget(self.assistant_card())
        column.addStretch()
        self.refresh()

    def assistant_card(self):
        frame = QFrame()
        frame.setProperty('card', True)
        box = QVBoxLayout(frame)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label('Editing assistant', 'heading'))
        self.assistant_badge = label('', 'badge')
        theme.restyle(self.assistant_badge, tone='accent')
        head.addWidget(self.assistant_badge)
        head.addStretch()
        box.addLayout(head)
        box.addWidget(label('The vision model that plans PhotoCraft edits and checks the results. It only '
                            'chooses which edits to run; the edits themselves stay exact. A cloud model sees '
                            'the photos you edit.', 'small', wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.assistant_provider = QComboBox()
        self.assistant_provider.setMinimumWidth(240)
        self.assistant_provider.currentIndexChanged.connect(self.assistant_picked)
        row.addWidget(self.assistant_provider)
        self.assistant_model = QComboBox()
        self.assistant_model.setEditable(True)
        self.assistant_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.assistant_model.lineEdit().setPlaceholderText('Model name')
        row.addWidget(self.assistant_model, 1)
        self.use_assistant = QPushButton('Use')
        self.use_assistant.clicked.connect(self.save_assistant)
        row.addWidget(self.use_assistant)
        box.addLayout(row)
        self.assistant_note = label('', 'small', wrap=True)
        self.assistant_note.hide()
        box.addWidget(self.assistant_note)
        return frame

    # Showing ---------------------------------------------------------------------------

    def refresh(self):
        for row in self.rows.values():
            row.show_state()
        chosen = providers.assistant()
        self.assistant_provider.blockSignals(True)
        self.assistant_provider.clear()
        self.assistant_provider.addItem(LOCAL, providers.LOCAL_ASSISTANT)
        for name, spec in providers.PROVIDERS.items():
            if spec.get('assistant') and (providers.connected(name) or name == chosen['provider']):
                self.assistant_provider.addItem(spec['label'], name)
        self.assistant_provider.setCurrentIndex(max(0, self.assistant_provider.findData(chosen['provider'])))
        self.assistant_provider.blockSignals(False)
        self.assistant_picked(keep=chosen['model'])
        current = LOCAL if chosen['provider'] == providers.LOCAL_ASSISTANT else (
            f'{providers.PROVIDERS[chosen["provider"]]["label"]} · {chosen["model"] or "no model set"}')
        self.assistant_badge.setText(current)
        self.show_assistant_note()

    def show_assistant_note(self):
        """Which model finds things in photos, and what the chosen models cannot do."""
        from image_studio.pipelines import models

        try:
            roles = models.settings()
            notes = [note for role in models.ROLES for note in models.warnings(role)]
            grounder = roles['grounder']
        except (ValueError, RuntimeError):
            self.assistant_note.hide()
            return
        if grounder.get('kind') == 'local' and roles['planner'].get('kind') != 'local':
            notes.insert(0, 'The bundled model still finds objects in photos, because it is trained for that.')
        self.assistant_note.setText(' '.join(notes))
        self.assistant_note.setVisible(bool(notes))

    def assistant_picked(self, _=None, keep=''):
        provider = self.assistant_provider.currentData()
        local = provider in (None, providers.LOCAL_ASSISTANT)
        self.assistant_model.clear()
        self.assistant_model.setEnabled(not local)
        if local:
            return
        spec = providers.PROVIDERS[provider]
        saved = providers.options(provider).get('models') or []
        for name in dict.fromkeys([*(spec.get('assistant_models') or []), *saved]):
            self.assistant_model.addItem(name)
        self.assistant_model.setCurrentText(keep or (spec.get('assistant_models') or [''])[0])

    # Changing --------------------------------------------------------------------------

    def open_dialog(self, provider):
        dialog = ProviderDialog(self, provider, self.found.get(provider))
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if dialog.found:
            self.found[provider] = dialog.found
        if not accepted:
            return
        label_ = providers.PROVIDERS[provider]['label']
        if dialog.removed:
            if providers.assistant()['provider'] == provider:
                providers.use_assistant(providers.LOCAL_ASSISTANT)
            self.notify(f'{label_} is disconnected.')
        else:
            self.notify(f'{label_} is connected.')
        self.refresh()
        self.changed()

    def save_assistant(self):
        provider = self.assistant_provider.currentData() or providers.LOCAL_ASSISTANT
        model = self.assistant_model.currentText().strip()
        if provider != providers.LOCAL_ASSISTANT and not model:
            self.notify('Enter the model name to use.', error=True)
            return
        providers.use_assistant(provider, model)
        self.refresh()
        self.changed()
        self.notify('The editing assistant now uses ' + (
            'the bundled model.' if provider == providers.LOCAL_ASSISTANT
            else f'{providers.PROVIDERS[provider]["label"]} ({model}).'))



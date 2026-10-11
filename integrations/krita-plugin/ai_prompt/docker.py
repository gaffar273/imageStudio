"""The AI panel: type what you want ("blur the background", "remove the man on the left",
"write SALE at the top"), and it is done with Krita's tools and Image Studio's AI, step by
step, each change as its own layer. The same requests can come from the browser."""
import html
import webbrowser
from krita import DockWidget
from . import ops
from .link import controller
from .qt import (QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QTextBrowser,
                 QToolButton, QVBoxLayout, QWidget, Qt, scoped)
from .runner import save_to_library

EXAMPLES = ['Blur the background', 'Make it warmer and brighter', 'Remove the background',
            'Replace the sky with a sunset', 'Add a vignette and film grain', 'Write "Hello" at the top in white']


class PromptBox(QPlainTextEdit):
    """Enter runs the prompt; Shift+Enter starts a new line."""
    def __init__(self, submit):
        super().__init__()
        self.submit = submit

    def keyPressEvent(self, event):
        enter = event.key() in (scoped(Qt, 'Key', 'Key_Return'), scoped(Qt, 'Key', 'Key_Enter'))
        shift = bool(event.modifiers() & scoped(Qt, 'KeyboardModifier', 'ShiftModifier'))
        if enter and not shift:
            self.submit()
            return
        super().keyPressEvent(event)


class AIPromptDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AI')
        self.runs = []             # [{id, text, steps: {index: {label, state, note}}, answers, outcome}]
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.log = QTextBrowser()
        self.log.setOpenLinks(False)
        self.log.anchorClicked.connect(self.example)
        self.log.setSizePolicy(scoped(QSizePolicy, 'Policy', 'Expanding'), scoped(QSizePolicy, 'Policy', 'Expanding'))
        self.prompt = PromptBox(self.run)
        self.prompt.setPlaceholderText('Describe an edit, e.g. blur the background and make it warmer')
        self.prompt.setFixedHeight(68)

        self.run_button = QPushButton('Run')
        self.run_button.setDefault(True)
        self.stop_button = QPushButton('Stop')
        self.undo_button = QPushButton('Undo')
        self.undo_button.setToolTip('Undo the last change (Ctrl+Z)')
        self.more = QToolButton()
        self.more.setText('...')
        self.more.setPopupMode(scoped(QToolButton, 'ToolButtonPopupMode', 'InstantPopup'))
        self.more.setMenu(self.options_menu())
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.addWidget(self.run_button, 3)
        buttons.addWidget(self.stop_button, 1)
        buttons.addWidget(self.undo_button, 1)
        buttons.addWidget(self.more)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.link = QLabel()
        self.link.setWordWrap(True)

        layout.addWidget(self.log, 1)
        layout.addWidget(self.prompt)
        layout.addLayout(buttons)
        layout.addWidget(self.progress)
        layout.addWidget(self.link)
        self.setWidget(root)

        self.run_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(lambda: controller().stop())
        self.undo_button.clicked.connect(lambda: controller().undo())
        controller().event.connect(self.on_event)
        controller().busy.connect(self.on_busy)
        self.on_busy(controller().run is not None)
        self.render()
        # The link lives in the extension; show its state here too.
        from . import link
        if link.extension is not None and link.extension.poller is not None:
            link.extension.poller.connection.connect(self.on_connection)
            self.on_connection(bool(link.extension.poller.connected), link.extension.viewer)

    def canvasChanged(self, canvas):
        pass

    def options_menu(self):
        menu = QMenu(self)
        models = menu.addMenu('New pictures with')
        for label, key in (('Accurate (Z-Image)', 'accurate'), ('Realistic (RealVisXL)', 'realistic')):
            action = models.addAction(label)
            action.setCheckable(True)
            action.setChecked(controller().options['model'] == key)
            action.triggered.connect(lambda _=False, key=key, menu=models: self.set_model(key, menu))
        for label, key in (('Check and retry new pictures', 'check'), ('Smart prompt', 'smart')):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(controller().options[key])
            action.toggled.connect(lambda value, key=key: controller().options.__setitem__(key, value))
        menu.addSeparator()
        menu.addAction('Save to Image Studio library').triggered.connect(self.save)
        menu.addAction('Open Image Studio in the browser').triggered.connect(
            lambda: webbrowser.open('http://127.0.0.1:7860'))
        menu.addAction('Clear this list').triggered.connect(self.clear)
        return menu

    def set_model(self, key, menu):
        controller().options['model'] = key
        for action, value in zip(menu.actions(), ('accurate', 'realistic')):
            action.setChecked(value == key)

    def save(self):
        try:
            self.link.setText(save_to_library(controller()))
        except ops.StepError as exc:
            self.link.setText(str(exc))

    def clear(self):
        self.runs = []
        self.render()

    def example(self, url):
        self.prompt.setPlainText(url.toString().removeprefix('example:').replace('%20', ' ').replace('%22', '"'))
        self.prompt.setFocus()

    def run(self):
        text = self.prompt.toPlainText().strip()
        if text:
            controller().submit(text)
            self.prompt.clear()

    def on_busy(self, busy):
        self.run_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.progress.setVisible(busy)

    def on_connection(self, connected, viewer):
        self.link.setText('Connected to Image Studio' + (' · shown in the browser' if viewer else '')
                          if connected else 'Image Studio is not running. Start it with "Start image generator.bat".')

    # ---- The list of requests --------------------------------------------------------

    def on_event(self, item):
        kind, run_id = item.get('kind'), item.get('run')
        run = next((run for run in self.runs if run['id'] == run_id), None)
        if kind == 'start':
            run = dict(id=run_id, text=item.get('text', ''), steps={}, answers=[], outcome=None, status='',
                       source=item.get('source'))
            self.runs.append(run)
            self.runs = self.runs[-30:]
        if run is None:
            if kind in ('status', 'failed'):
                self.link.setText(item.get('text', ''))
            return
        index = item.get('index')
        if kind == 'plan':
            for number, label in enumerate(item.get('labels') or []):
                run['steps'][number] = dict(label=label, state='waiting', note='')
        elif kind in ('step', 'progress', 'step_done', 'step_failed') and index is not None:
            step = run['steps'].setdefault(index, dict(label=item.get('label', ''), state='waiting', note=''))
            step['state'] = {'step': 'running', 'progress': 'running', 'step_done': 'done',
                             'step_failed': 'failed'}[kind]
            step['note'] = item.get('text', '')
        elif kind == 'say':
            run['answers'].append(item.get('text', ''))
        elif kind in ('done', 'failed', 'stopped'):
            run['outcome'] = (kind, item.get('text', ''))
        elif kind == 'status':
            run['status'] = item.get('text', '')
        self.render()

    def render(self):
        if not self.runs:
            links = ''.join(f'<p style="margin:4px 0"><a href="example:{html.escape(text)}">{html.escape(text)}</a></p>'
                            for text in EXAMPLES)
            self.log.setHtml(f'<p style="color:gray">Try:</p>{links}')
            return
        parts = []
        for run in self.runs:
            source = ' <span style="color:gray">(browser)</span>' if run.get('source') == 'browser' else ''
            parts.append(f'<p style="margin:10px 0 4px"><b>{html.escape(run["text"])}</b>{source}</p>')
            for _, step in sorted(run['steps'].items()):
                color = {'waiting': 'gray', 'running': '', 'done': '', 'failed': '#dc2626'}[step['state']]
                label = html.escape(step['label'])
                if step['state'] == 'running':
                    label = f'<b>{label}</b>'
                note = f' <span style="color:gray">{html.escape(step["note"])}</span>' if step['note'] else ''
                style = f' style="color:{color}"' if color else ''
                parts.append(f'<p style="margin:1px 0 1px 10px"><span{style}>{label}</span>{note}</p>')
            for answer in run['answers']:
                parts.append(f'<p style="margin:4px 0 4px 10px">{html.escape(answer)}</p>')
            if run['outcome'] and run['outcome'][0] != 'done':
                color = '#dc2626' if run['outcome'][0] == 'failed' else 'gray'
                parts.append(f'<p style="margin:2px 0 2px 10px;color:{color}">{html.escape(run["outcome"][1])}</p>')
            elif not run['steps'] and run['status'] and not run['outcome']:
                parts.append(f'<p style="margin:2px 0 2px 10px;color:gray">{html.escape(run["status"])}</p>')
        self.log.setHtml(''.join(parts))
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

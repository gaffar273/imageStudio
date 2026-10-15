"""This PC: what the computer can run, the engine's state, and where files are kept."""

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from image_studio.core import hardware, paths
from image_studio.desktop import feedback, theme
from image_studio.desktop.controls import scroll_page
from image_studio.desktop.engine import in_background
from image_studio.desktop.theme import label

TIERS = {
    'great': ('Great for local AI', ''),
    'good': ('Ready for local AI', ''),
    'limited': ('Limited', 'warn'),
    'cloud': ('Local models unavailable', 'off'),
}
FOLDERS = {
    'models_dir': (
        'Models',
        'IMAGE_STUDIO_WORK',
        'Downloaded models live here. They are large (tens of GB), so pick a drive with room.',
    ),
    'library_dir': ('Library', 'IMAGE_STUDIO_LIBRARY', 'Your pictures and their settings are saved here.'),
}


def card():
    frame = QFrame()
    frame.setProperty('card', True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(8)
    return frame, layout


def open_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SystemPage(QWidget):
    def __init__(self, client, engine, notify):
        super().__init__()
        self.client, self.engine, self.notify = client, engine, notify
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, layout = scroll_page('This PC', 'What this computer can run locally, the engine, and where '
                                                'files are kept.')
        outer.addWidget(scroll)

        frame, box = card()
        top = QHBoxLayout()
        top.addWidget(label('Local models', 'heading'))
        self.badge = label('Checking…', 'badge')
        top.addWidget(self.badge)
        top.addStretch()
        box.addLayout(top)
        self.verdict = label('Reading your hardware…', 'muted', wrap=True)
        box.addWidget(self.verdict)
        self.hardware = QGridLayout()
        self.hardware.setHorizontalSpacing(24)
        self.hardware.setVerticalSpacing(8)
        self.hardware.setColumnStretch(1, 1)
        box.addSpacing(6)
        box.addLayout(self.hardware)
        layout.addWidget(frame)

        frame, box = card()
        top = QHBoxLayout()
        top.addWidget(label('Engine', 'heading'))
        self.engine_badge = label('', 'badge')
        top.addWidget(self.engine_badge)
        top.addStretch()
        box.addLayout(top)
        self.engine_text = label('', 'muted', wrap=True)
        box.addWidget(self.engine_text)
        self.loaded = label('', 'small', wrap=True)
        box.addWidget(self.loaded)
        buttons = QHBoxLayout()
        self.release = QPushButton(theme.icon('memory-stick'), 'Free GPU memory')
        self.release.setToolTip('Unload every model so games and other programs get the video memory back.')
        self.release.clicked.connect(self.free_gpu)
        restart = QPushButton(theme.icon('refresh-cw'), 'Restart engine')
        restart.clicked.connect(self.engine.restart)
        log = QPushButton(theme.icon('file-text'), 'Engine log')
        log.clicked.connect(lambda: self.engine.log.exists() and QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.engine.log))))
        for widget in (self.release, restart, log):
            buttons.addWidget(widget)
        buttons.addStretch()
        box.addLayout(buttons)
        layout.addWidget(frame)

        frame, box = card()
        box.addWidget(label('Folders', 'heading'))
        self.folder_labels = {}
        for key, (name, variable, note) in FOLDERS.items():
            box.addSpacing(4)
            row = QHBoxLayout()
            row.addWidget(label(name, 'value'))
            path = label('', 'muted', selectable=True)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.folder_labels[key] = path
            row.addWidget(path, 1)
            change = QPushButton('Change…')
            change.clicked.connect(lambda _=False, key=key: self.change_folder(key))
            show = QPushButton(theme.icon('folder-open'), '')
            show.setToolTip('Open the folder')
            show.clicked.connect(lambda _=False, key=key: open_folder(self.folder(key)))
            row.addWidget(change)
            row.addWidget(show)
            box.addLayout(row)
            text = note + (f' Set by {variable}, which takes priority.' if os.environ.get(variable) else '')
            box.addWidget(label(text, 'small', wrap=True))
        layout.addWidget(frame)

        frame, box = card()
        top = QHBoxLayout()
        top.addWidget(label('Help and feedback', 'heading'))
        top.addStretch()
        top.addWidget(label(f'Version {feedback.version()}', 'small'))
        box.addLayout(top)
        box.addWidget(label(
            'Something not working, or a picture that should not have been made? Tell us. To report one '
            'picture, open it in Library and choose Report this picture.', 'small', wrap=True))
        buttons = QHBoxLayout()
        report = QPushButton(theme.icon('flag'), 'Report a problem')
        report.setToolTip(feedback.PUBLIC)
        report.clicked.connect(lambda: feedback.open_report(feedback.problem_report()))
        buttons.addWidget(report)
        buttons.addStretch()
        box.addLayout(buttons)
        layout.addWidget(frame)
        layout.addStretch()
        self.show_folders()
        self.show_engine(engine.state, engine.message)
        engine.changed.connect(self.show_engine)

    # Hardware --------------------------------------------------------------------------

    def refresh(self):
        in_background(hardware.summary, self.show_hardware)
        if self.engine.state == 'ready':
            self.client.get('/api/system', self.show_system, None)

    def show_hardware(self, summary, error):
        if error:
            self.verdict.setText(f'Could not read the hardware: {error}')
            return
        name, tone = TIERS[summary['tier']]
        self.badge.setText(name)
        self.badge.setProperty('tone', tone)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        extra = '' if summary['tier'] != 'cloud' else (
            ' Connect a cloud provider in Settings → Providers to create and edit pictures without one.')
        self.verdict.setText(summary['verdict'] + extra)
        while self.hardware.count():
            self.hardware.takeAt(0).widget().deleteLater()
        rows = []
        for gpu in summary['gpus']:
            memory = f'{gpu["vram_gb"]:.0f} GB' if gpu['vram_gb'] and gpu['vram_gb'] >= 1 else (
                'shared memory' if gpu['integrated'] else 'memory unknown'
            )
            role = 'used for AI' if gpu['vendor'] == 'NVIDIA' else (
                'built-in graphics' if gpu['integrated'] else 'not used for AI yet'
            )
            rows.append(('Graphics', f'{gpu["name"]} · {memory} · {role}'))
        if not summary['gpus']:
            rows.append(('Graphics', 'None found'))
        rows += [
            ('Processor', f'{summary["cpu"]} · {summary["cores"]} cores, {summary["threads"]} threads'),
            ('Memory', f'{summary["ram_gb"]:.0f} GB'),
            ('System', summary['system']),
        ]
        for index, (name, value) in enumerate(rows):
            self.hardware.addWidget(label(name, 'small'), index, 0, Qt.AlignmentFlag.AlignTop)
            self.hardware.addWidget(label(value, wrap=True, selectable=True), index, 1)

    # Engine ----------------------------------------------------------------------------

    def show_engine(self, state, message):
        names = {'ready': ('Running', ''), 'starting': ('Starting', 'warn'), 'failed': ('Stopped', 'off'),
                 'stopped': ('Stopped', 'off'), 'setup': ('Not set up', 'warn')}
        name, tone = names.get(state, (state, 'off'))
        self.engine_badge.setText(name)
        self.engine_badge.setProperty('tone', tone)
        self.engine_badge.style().unpolish(self.engine_badge)
        self.engine_badge.style().polish(self.engine_badge)
        where = f' Address: {self.client.base}' if state == 'ready' else ''
        self.engine_text.setText(message + where)
        self.release.setEnabled(state == 'ready')
        if state == 'ready':
            self.client.get('/api/system', self.show_system, None)
        else:
            self.loaded.setText('')

    def show_system(self, info):
        loaded = [name for name in (info.get('loaded'), info.get('assistant')) if name]
        text = 'Models in GPU memory: ' + (', '.join(loaded) if loaded else 'none')
        if info.get('active_job'):
            text += ' · a job is running'
        self.loaded.setText(text)
        for key in FOLDERS:
            if info.get(key) and Path(info[key]) != self.folder(key):
                self.folder_labels[key].setText(
                    f'{self.folder(key)}  (the engine still uses {info[key]}; restart it to switch)'
                )

    def free_gpu(self):
        self.client.post(
            '/api/system/release',
            None,
            lambda info: (self.show_system(info), self.notify('GPU memory freed.')),
            lambda error: self.notify(error, error=True),
        )

    # Folders ---------------------------------------------------------------------------

    @staticmethod
    def folder(key):
        _, variable, _ = FOLDERS[key]
        default = paths.default_models_dir() if key == 'models_dir' else paths.default_library_dir()
        return paths.chosen(variable, key, default)

    def show_folders(self):
        for key, widget in self.folder_labels.items():
            widget.setText(str(self.folder(key)))

    def change_folder(self, key):
        name = FOLDERS[key][0]
        chosen = QFileDialog.getExistingDirectory(self, f'Choose the {name.lower()} folder', str(self.folder(key)))
        if not chosen or Path(chosen) == self.folder(key):
            return
        paths.save_settings(**{key: str(Path(chosen))})
        self.show_folders()
        note = (
            ' Models already downloaded stay in the old folder; move them across if you want to keep them.'
            if key == 'models_dir'
            else ' Pictures already saved stay in the old folder.'
        )
        answer = QMessageBox.question(
            self,
            'Restart the engine?',
            f'The engine uses the new {name.lower()} folder after a restart.{note}\n\nRestart it now?',
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.engine.restart()

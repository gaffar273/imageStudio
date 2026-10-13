"""Models and tools the studio installs itself: what each one is for, its size, and the steps that fetch it.

Every step is a command of the engine's own Python (the model downloader, or the face pool
builder), run in the background with its output read for progress. Downloads resume where
they stopped, so a dropped connection is simply retried, the way the old setup scripts did.
The engine itself (ENGINE, an installed copy's first install) is set up by the app's Python.
"""

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from image_studio.core import engine_env, paths
from image_studio.core.catalog import ASSISTANT, BRAIN, FACE_REFERENCE, KONTEXT, MODELS, REPAIR, SEARCH
from image_studio.core.engine_env import app_python, engine_python

RETRIES = 40
RETRY_SECONDS = 10
GATED = 'one-time license acceptance'  # what the downloader says when a licence must be accepted first
FINAL = 3  # a step exits with this when trying again cannot help
HUB = 'https://huggingface.co/'


@dataclass
class Step:
    label: str
    args: list
    python: str = 'engine'  # 'search': the image search environment's own Python; 'app': the window's
    retry: bool = True  # downloads resume, so a failed one is tried again
    gpu: bool = False  # the engine's models are unloaded first


@dataclass
class Part:
    key: str
    title: str
    what: str
    size_gb: float  # download size, checked against the free space
    size: str
    page: str
    ready: object  # config -> bool
    note: str = ''
    needs: str = ''  # a part that must be installed first
    windows_only: bool = False
    steps: list = field(default_factory=list)


def model_ready(key):
    return lambda config: any(model['id'] == key and model['ready'] for model in config.get('models', []))


def flag(name):
    return lambda config: bool(config.get(name))


def download(key, label='Downloading'):
    return Step(label, ['-m', 'image_studio.cli.download_model', '--model', key])


PARTS = [
    Part('realistic', 'Realistic (RealVisXL 5.0)', 'The main model: photos of people and scenes.', 7, 'about 7 GB',
         HUB + MODELS['realistic']['repo'], model_ready('realistic'), steps=[download('realistic')]),
    Part('accurate', 'Accurate (Z-Image Turbo)', 'Follows long, detailed prompts best: counts, colors and positions.',
         14, 'about 14 GB to download, 10 GB on disk', HUB + MODELS['accurate']['repo'], model_ready('accurate'),
         steps=[download('accurate')]),
    Part('turbo', 'Turbo (SDXL Turbo)', 'Quick drafts in a few seconds.', 7, 'about 7 GB',
         HUB + MODELS['turbo']['repo'], model_ready('turbo'), steps=[download('turbo')]),
    Part('kontext', 'Photo editing (FLUX.1 Kontext)',
         'Changes what is in a photo: add, remove or replace things, in Edit image and PhotoCraft.', 17,
         'about 17 GB to download, 12 GB on disk', HUB + KONTEXT['repo'], flag('editing'),
         note='Its maker asks you to accept its licence on Hugging Face before downloading.',
         steps=[download('kontext')]),
    Part('assistant', 'Prompt assistant (Qwen3-VL 2B)',
         'Turns casual requests into clear prompts (Smart prompt) and finds the things you name in a photo.', 4.3,
         'about 4.3 GB', HUB + ASSISTANT['repo'], flag('assistant'), steps=[download('assistant')]),
    Part('brain', 'Editing brain (Qwen3.5 9B)',
         'Looks at the photo and plans typed edits in Krita and PhotoCraft.', 7.3, 'about 7.3 GB',
         HUB + BRAIN['repo'], flag('brain'), windows_only=True, steps=[download('brain')]),
    Part('segment', 'Outlines (SAM 2.1)', 'Traces the exact outline of a person or thing you select.', 0.45,
         'about 450 MB', 'https://docs.ultralytics.com/models/sam-2/', flag('segment'), steps=[download('segment')]),
    Part('repair', 'Face and hand repair', 'Finds faces and hands in a new picture so they can be redrawn.', 0.1,
         'about 100 MB', HUB + REPAIR['repo'], flag('repair'), steps=[download('repair')]),
    Part('search', 'Visual search (EmbeddingGemma 2)',
         'Finds pictures in My library by what is in them, not only by their prompt.', 2.5,
         'about 1.5 GB, plus 1 GB of libraries', HUB + SEARCH['repo'], flag('search'),
         steps=[
             Step('Setting up its environment', ['-m', 'venv', '{search_env}'], retry=False),
             Step('Installing its libraries', ['-m', 'pip', 'install', '-r', '{requirements}'], python='search'),
             download('search'),
         ]),
    Part('faces', 'Different faces in groups',
         'Gives each person in a group picture their own face during face repair.', 3.4,
         'about 3.4 GB, then 15 minutes on your GPU', HUB + FACE_REFERENCE['repo'], flag('references'),
         note='After the download it paints 48 portraits of invented people to use as references.',
         needs='realistic',
         steps=[
             download('faces'),
             Step('Painting the reference portraits', ['-m', 'image_studio.services.faces', 'build'], retry=False,
                  gpu=True),
         ]),
]
# The engine itself, in an installed copy: every part above runs on it.
ENGINE = Part('engine', 'Engine (PyTorch with CUDA)',
              'What every model runs on: PyTorch for NVIDIA graphics cards and the model libraries.', 6,
              'about 3.5 GB to download, 5 GB on disk', 'https://pytorch.org/',
              lambda config: engine_env.status() == 'ready',
              note='It goes in your user folder, apart from the models; uninstalling the app removes it.',
              steps=[Step('Setting up the engine', ['-m', 'image_studio.cli.setup_engine'], python='app')])
# The engine without PyTorch, for a PC with no NVIDIA card: it creates and edits through cloud providers.
# Same key as ENGINE: one engine either way, and installing ENGINE later adds to this one.
ENGINE_CLOUD = Part('engine', 'Engine in cloud mode',
                    'For a PC without an NVIDIA graphics card: Create and Edit work through the providers you '
                    'connect in Providers. The models below cannot run in this mode.', 0.3,
                    'about 60 MB to download, 210 MB on disk', '',
                    lambda config: engine_env.status() == 'ready',
                    note=ENGINE.note,
                    steps=[Step('Setting up the engine', ['-m', 'image_studio.cli.setup_engine', '--cloud'],
                                python='app')])
BY_KEY = {part.key: part for part in [ENGINE, *PARTS]}


def supported(part):
    return not part.windows_only or sys.platform == 'win32'


def free_gb(folder):
    """Free space on the drive that holds folder (or the nearest existing parent)."""
    folder = Path(folder)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    try:
        return shutil.disk_usage(folder).free / 1e9
    except OSError:
        return None


def search_python(models_dir):
    return Path(models_dir) / 'search-env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def plan(part, config, models_dir):
    """The steps still to run: parts already fetched (the face model, the search environment) are skipped."""
    steps = list(part.steps)
    if part.key == 'faces' and config.get('face_model'):
        steps = steps[1:]
    if part.key == 'search' and search_python(models_dir).exists():
        steps = steps[1:]
    values = dict(search_env=str(Path(models_dir) / 'search-env'),
                  requirements=str(paths.ROOT / 'backend' / 'requirements-search.txt'))
    return [Step(step.label, [arg.format(**values) for arg in step.args], step.python, step.retry, step.gpu)
            for step in steps]


PERCENT = re.compile(r'(\d{1,3})%\|')
AMOUNT = re.compile(r'\|\s*([\d.]+\s*[kMGT]?B?/[\d.]+\s*[kMGT]?B?)')
RATE = re.compile(r'([\d.]+\s*[kMGT]?B/s)')


def last_line(output):
    """The newest line of output; progress bars redraw one line with carriage returns."""
    for line in reversed(re.split(r'[\r\n]+', output)):
        if line.strip():
            return line.strip()
    return ''


def progress_of(line):
    """(text to show, percent or None) for one line of the downloader's output."""
    percent = PERCENT.search(line)
    if not percent:
        return line[:160], None
    name = line[:percent.start()].strip().rstrip(':').strip()
    details = [part.group(1) for part in (AMOUNT.search(line), RATE.search(line)) if part]
    text = ' · '.join([name or 'Downloading', *details])
    return text[:160], min(int(percent.group(1)), 100)


class Installer(QObject):
    """Runs one part's steps at a time in the background."""

    progress = Signal(str, str, object)  # part key, text, percent (None while unknown)
    finished = Signal(str, bool, str)  # part key, done, message (GATED when a licence must be accepted)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.key, self.steps, self.index, self.tries = None, [], 0, 0
        self.models_dir, self.token, self.output = '', '', ''
        self.release = None  # set by the page: frees the engine's GPU memory, then calls back
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.run_step)

    @property
    def running(self):
        return self.key is not None

    def start(self, part, config, models_dir, token=''):
        if self.running:
            raise RuntimeError('Another install is running.')
        self.key, self.models_dir, self.token = part.key, str(models_dir), token
        self.steps, self.index, self.tries = plan(part, config, models_dir), 0, 0
        if not self.steps:
            self.done(True, 'Already installed.')
            return
        self.run_step()

    def run_step(self):
        step = self.steps[self.index]
        if step.gpu and self.release is not None and self.tries == 0:
            self.progress.emit(self.key, 'Freeing the GPU…', None)
            self.release(self.launch)
            return
        self.launch()

    def launch(self):
        step = self.steps[self.index]
        self.output = ''
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('IMAGE_STUDIO_WORK', self.models_dir)  # the folder the engine uses
        environment.insert('PYTHONUNBUFFERED', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        if self.token:
            environment.insert('HF_TOKEN', self.token)
        self.process = QProcess(self)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(paths.ROOT))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.step_finished)
        self.process.errorOccurred.connect(self.failed_to_start)
        program = dict(search=lambda: str(search_python(self.models_dir)), app=app_python).get(
            step.python, engine_python)()
        count = f' ({self.index + 1} of {len(self.steps)})' if len(self.steps) > 1 else ''
        self.progress.emit(self.key, f'{step.label}{count}…', None)
        self.process.start(program, step.args)

    def read(self):
        if self.process is None:
            return
        self.output = (self.output + bytes(self.process.readAllStandardOutput().data()).decode('utf-8', 'replace'))
        self.output = self.output[-20000:]
        line = last_line(self.output)
        if line:
            text, percent = progress_of(line)
            self.progress.emit(self.key, text, percent)

    def failed_to_start(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process is not None:
            self.process = None
            self.done(False, 'The installer could not start Python.')

    def step_finished(self, code, status):
        if self.process is None:
            return  # cancelled
        self.read()
        self.process.deleteLater()
        self.process = None
        if code == 0 and status == QProcess.ExitStatus.NormalExit:
            self.index += 1
            self.tries = 0
            if self.index == len(self.steps):
                self.done(True, 'Installed.')
            else:
                self.run_step()
            return
        if GATED in self.output:
            self.done(False, GATED)
            return
        step = self.steps[self.index]
        self.tries += 1
        if step.retry and code != FINAL and self.tries < RETRIES:
            self.progress.emit(self.key, f'Connection dropped. Resuming in {RETRY_SECONDS} seconds '
                                         f'(try {self.tries + 1} of {RETRIES})…', None)
            self.retry_timer.start(RETRY_SECONDS * 1000)
            return
        self.done(False, last_line(self.output) or 'The install stopped.')

    def cancel(self):
        """Stop the running step (and anything it started). What was downloaded is kept for next time."""
        if not self.running:
            return
        self.retry_timer.stop()
        process, self.process = self.process, None
        if process is not None:
            try:
                parent = psutil.Process(process.processId())
                family = [*parent.children(recursive=True), parent]
            except psutil.Error:
                family = []
            for member in family:
                try:
                    member.kill()
                except psutil.Error:
                    pass
            process.waitForFinished(5000)
            process.deleteLater()
        self.done(False, 'Stopped. Install again to resume where it stopped.')

    def done(self, ok, message):
        key, self.key = self.key, None
        self.finished.emit(key, ok, message)

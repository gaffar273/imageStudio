"""Image search: find saved pictures by describing them, or pictures like a chosen one.

EmbeddingGemma 2 turns each picture and each typed search into 768 numbers in one shared
space, so a search matches what is in the picture, not only the words of its prompt. It
needs transformers 5 (the image models use 4.57), so it runs as a separate CPU process in
its own environment (search_worker.py); the GPU stays free. The process starts on the
first search and is closed after a few idle minutes to give back its memory."""

import json
import subprocess
import threading
from image_studio.core.catalog import ROOT, SEARCH, WORK

IMAGES = ROOT / 'images'
IDLE_SECONDS = 300
BACKGROUND_THREADS = 4
LOG = WORK / 'image-search.log'


def available():
    return (SEARCH['folder'] / 'download-complete.json').exists() and SEARCH['python'].exists()


class Worker:
    def __init__(self):
        self.process, self.timer = None, None
        self.lock = threading.Lock()

    def ask(self, request):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            try:
                if not self.process or self.process.poll() is not None:
                    self.start()
                self.process.stdin.write(json.dumps(request) + '\n')
                self.process.stdin.flush()
                reply = self.read()
            except OSError:
                self.close_locked()
                raise RuntimeError(f'Image search stopped unexpectedly. See {LOG}')
            self.timer = threading.Timer(IDLE_SECONDS, self.close)
            self.timer.daemon = True
            self.timer.start()
        if not reply['ok']:
            raise RuntimeError(reply['error'])
        return reply

    def start(self):
        log = LOG.open('w', encoding='utf-8')
        self.process = subprocess.Popen(
            [
                str(SEARCH['python']),
                '-I',
                str(ROOT / 'backend' / 'image_studio' / 'workers' / 'search_worker.py'),
                str(SEARCH['folder']),
                str(IMAGES),
                str(SEARCH['index']),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.close()
        self.read()  # Waits until the model is loaded.

    def read(self):
        line = self.process.stdout.readline()
        if not line:
            raise OSError('no answer')
        return json.loads(line)

    def close(self):
        with self.lock:
            self.close_locked()

    def close_locked(self):
        if self.process and self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


worker = Worker()


def unindexed():
    """Saved pictures the index has not read yet; checked without starting the model."""
    try:
        entries = json.loads((SEARCH['index'] / 'index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        entries = []
    known = {entry['name']: entry['mtime'] for entry in entries}
    return [path for path in IMAGES.glob('*.png') if known.get(path.name) != path.stat().st_mtime]


def index_new_images():
    """Read newly saved pictures in the background (about 5 s each on the CPU, with fewer
    threads so generation is not slowed), so a later search does not wait for them."""
    if not available() or worker.lock.locked() or not unindexed():
        return

    def run():
        try:
            worker.ask({'op': 'update', 'threads': BACKGROUND_THREADS})
        except RuntimeError:
            pass  # A search reports the problem when it is used.

    threading.Thread(target=run, daemon=True).start()


def search(text, limit):
    """[(file name, score)] for the pictures that best match the description, best first."""
    return worker.ask({'op': 'search', 'text': text, 'limit': limit})


def similar(name, limit):
    """[(file name, score)] for the pictures most like the named one, best first."""
    return worker.ask({'op': 'similar', 'name': name, 'limit': limit})

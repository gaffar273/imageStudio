"""Local link between Image Studio and Krita (the "AI" panel in krita-plugin/).

A small JSON server on 127.0.0.1 only, started by app.py. Two directions:

Krita -> Image Studio: GPU jobs. Krita posts a job (the picture or part of it as PNG, an
optional selection mask, a prompt); it runs through the same functions as the browser
app, sharing its GPU queue, and Krita polls for progress and collects the result.

    POST /jobs              {"kind": "plan" | "segment" | "edit" | "create" | "enhance" | "faces", ...}
    GET  /jobs/<id>         {"state": "running" | "done" | "error", "message", "progress", "image"?, ...}
    POST /jobs/<id>/cancel
    POST /library           {"image": b64 PNG, "name", "history": [...]} -> {"path"}  (save to Library)

Image Studio (browser) -> Krita: commands. Krita long-polls for them and reports back
what it has open and what each command is doing, which the browser shows live.

    GET  /krita/poll?wait=s {"commands": [...], "viewer": bool}   (Krita, every few seconds)
    POST /krita/state       {"state": {...}, "preview": b64 JPEG?}
    POST /krita/event       {"run", "kind", "text", ...}           (step started, done, failed...)

The browser app uses `link` directly; scripts can do the same over HTTP:

    POST /krita/command     {"kind": "prompt", "text": ...} | {"kind": "open", "path": ...} | undo, stop, save...
    GET  /krita/view        {"connected", "state", "events"} (?preview adds the picture as b64 JPEG)

    GET  /status            {"ok": true, "busy": n, "krita": bool}
"""

import base64
import collections
import io
import json
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from PIL import Image

PORT = 7861
MAX_BODY = 300 * 1024 * 1024
jobs = {}
jobs_lock = threading.Lock()
# Set by app.py: fn(image, info) -> saved path, for POST /library.
library_saver = None
_UNCHANGED = object()


def decode_png(text):
    return Image.open(io.BytesIO(base64.b64decode(text))) if text else None


def encode_png(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


class Job:
    def __init__(self, kind):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.state, self.message, self.progress, self.result = 'running', 'Waiting for the GPU...', 0.0, {}

    def __call__(self, value=None, desc=None, **_):
        """Progress callback with the signature of gr.Progress."""
        if isinstance(value, (int, float)):
            self.progress = float(value)
        if desc:
            self.message = desc

    def view(self):
        return dict(
            self.result, id=self.id, state=self.state, message=self.message, progress=round(self.progress, 3)
        )


class Link:
    """What Krita has open, what it is doing, and the commands waiting for it."""

    ALIVE = 20.0  # seconds since Krita's last poll that still count as connected
    VIEWER = 10.0  # seconds since the browser last looked that still count as watching

    def __init__(self):
        self.changed = threading.Condition()
        self.commands = []
        self.krita_seen = 0.0
        self.viewer_seen = 0.0
        self.state = None
        self.preview = None  # JPEG bytes of the open picture
        self.version = 0  # bumped whenever state, preview or events change
        self.preview_version = 0  # bumped when the preview changes
        self.events = collections.deque(maxlen=300)

    @property
    def connected(self):
        return time.monotonic() - self.krita_seen < self.ALIVE

    def send(self, kind, **payload):
        """Queue a command for Krita; returns its id."""
        command = dict(payload, kind=kind, id=uuid.uuid4().hex[:12], sent=time.time())
        with self.changed:
            self.commands.append(command)
            self.changed.notify_all()
        return command['id']

    def poll(self, wait):
        """Commands for Krita, waiting up to `wait` seconds for one to arrive."""
        deadline = time.monotonic() + wait
        watched = self.viewer
        with self.changed:
            self.krita_seen = time.monotonic()
            # Also answer at once when a browser starts watching, so Krita sends a preview.
            while not self.commands and time.monotonic() < deadline and self.viewer == watched:
                self.changed.wait(min(1.0, max(0.01, deadline - time.monotonic())))
                self.krita_seen = time.monotonic()
            commands, self.commands = self.commands, []
        return commands

    def watching(self):
        started = not self.viewer
        self.viewer_seen = time.monotonic()
        if started:
            with self.changed:
                self.changed.notify_all()

    @property
    def viewer(self):
        return time.monotonic() - self.viewer_seen < self.VIEWER

    def update(self, state=_UNCHANGED, preview=None):
        with self.changed:
            if state is not _UNCHANGED:
                self.state = state
                if state is None:
                    self.preview = None
                    self.preview_version += 1
            if preview is not None and self.state is not None:
                self.preview = preview
                self.preview_version += 1
            self.version += 1

    def event(self, item):
        item = dict(item, time=time.time())
        with self.changed:
            self.events.append(item)
            self.version += 1

    def run_events(self, run=None):
        """Events of one run (the latest when `run` is None), oldest first."""
        events = list(self.events)
        if run is None:
            starts = [item['run'] for item in events if item.get('kind') == 'start']
            run = starts[-1] if starts else None
        return [item for item in events if item.get('run') == run] if run else []


link = Link()


def start(handlers, stop):
    """Serve in a background thread. `handlers` maps a job kind to fn(request, progress)
    returning (image, message) or a dict (image, mask: PIL images; message; any JSON
    values); `stop` cancels the running GPU job."""

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/status':
                with jobs_lock:
                    busy = sum(job.state == 'running' for job in jobs.values())
                return self.reply(200, dict(ok=True, busy=busy, krita=link.connected))
            if url.path == '/krita/poll':
                wait = min(float(parse_qs(url.query).get('wait', ['10'])[0]), 25.0)
                commands = link.poll(wait)
                return self.reply(200, dict(commands=commands, viewer=link.viewer))
            if url.path == '/krita/view':
                link.watching()
                return self.reply(
                    200,
                    dict(
                        connected=link.connected,
                        state=link.state,
                        events=link.run_events(),
                        preview=base64.b64encode(link.preview).decode('ascii')
                        if link.preview and 'preview' in url.query
                        else None,
                    ),
                )
            job = jobs.get(url.path.removeprefix('/jobs/'))
            if job is None:
                return self.reply(404, dict(error='No such job.'))
            self.reply(200, job.view())

        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            if length > MAX_BODY:
                return self.reply(413, dict(error='The picture is too large to send.'))
            if self.path.startswith('/jobs/') and self.path.endswith('/cancel'):
                stop()
                return self.reply(200, dict(ok=True))
            try:
                request = json.loads(self.rfile.read(length) or b'{}')
            except ValueError:
                return self.reply(400, dict(error='The request is not valid JSON.'))
            if self.path == '/krita/state':
                preview = request.get('preview')
                link.update(request.get('state', _UNCHANGED), base64.b64decode(preview) if preview else None)
                return self.reply(200, dict(ok=True, viewer=link.viewer))
            if self.path == '/krita/event':
                link.event(request)
                return self.reply(200, dict(ok=True))
            if self.path == '/krita/command':
                if not link.connected:
                    return self.reply(409, dict(error='Krita is not connected.'))
                kind = request.pop('kind', None)
                if kind not in ('prompt', 'open', 'undo', 'stop', 'save', 'new_canvas', 'raise'):
                    return self.reply(400, dict(error='Unknown command.'))
                return self.reply(200, dict(id=link.send(kind, **request)))
            if self.path == '/library':
                if library_saver is None:
                    return self.reply(503, dict(error='The library is not available.'))
                try:
                    path = library_saver(decode_png(request['image']).convert('RGBA'), request)
                except Exception as exc:
                    traceback.print_exc()
                    return self.reply(500, dict(error=str(exc)))
                return self.reply(200, dict(path=str(path)))
            if self.path != '/jobs':
                return self.reply(404, dict(error='Unknown address.'))
            handler = handlers.get(request.get('kind'))
            if handler is None:
                return self.reply(400, dict(error='Unknown job kind.'))
            job = Job(request.get('kind'))
            with jobs_lock:
                # Keep only recent jobs; results are large.
                for old in [key for key, value in jobs.items() if value.state != 'running'][:-20]:
                    jobs.pop(old)
                jobs[job.id] = job

            def run():
                try:
                    out = handler(request, job)
                    if isinstance(out, tuple):
                        out = dict(image=out[0], message=out[1])
                    result = {
                        key: (encode_png(value) if isinstance(value, Image.Image) else value)
                        for key, value in out.items()
                        if key != 'message' and value is not None
                    }
                    job.result, job.message, job.progress = result, out.get('message') or 'Done.', 1.0
                    job.state = 'done'
                except Exception as exc:  # Reported to the editor instead of crashing the server.
                    traceback.print_exc()
                    job.state, job.message = 'error', str(exc) or exc.__class__.__name__

            threading.Thread(target=run, daemon=True).start()
            self.reply(200, dict(id=job.id))

    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

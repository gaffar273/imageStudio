"""The studio engine behind the app: starting it, talking to it, and closing it with the window.

The engine is the same local server the web version uses, run as a child process so the
models live outside the window's process (a crash in one never takes down the other).
The app starts it when it opens and stops it when it closes, which frees the GPU. An
engine that is already running (started by the web launcher) is used as it is and left
running afterwards. An installed copy whose engine is not set up yet waits in the 'setup'
state until Studio settings installs it.
"""

import json
import os
import socket
import subprocess
import sys
import threading

import psutil
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkAccessManager, QNetworkReply, QNetworkRequest

from image_studio.core import engine_env, paths
from image_studio.core.engine_env import engine_python
from image_studio.core.processes import own_family

TITLE = 'Local Image Studio'
DEFAULT_PORT = 7860
START_SECONDS = 240


class Client(QObject):
    """JSON and file requests to the engine, answered on the UI thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base = f'http://127.0.0.1:{DEFAULT_PORT}'
        self.network = QNetworkAccessManager(self)

    def url(self, path):
        return path if path.startswith('http') else self.base + path

    def request(self, method, path, body=None, done=None, failed=None, raw=False, timeout=30000):
        request = QNetworkRequest(QUrl(self.url(path)))
        request.setTransferTimeout(timeout)
        if body is None:
            reply = self.network.sendCustomRequest(request, method.encode()) if method != 'GET' else (
                self.network.get(request)
            )
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            reply = self.network.sendCustomRequest(request, method.encode(), json.dumps(body).encode('utf-8'))
        reply.finished.connect(lambda: self.finish(reply, done, failed, raw))
        return reply

    def get(self, path, done=None, failed=None, **options):
        return self.request('GET', path, None, done, failed, **options)

    def post(self, path, body=None, done=None, failed=None, **options):
        return self.request('POST', path, {} if body is None else body, done, failed, **options)

    def bytes(self, path, done=None, failed=None, **options):
        return self.request('GET', path, None, done, failed, raw=True, **options)

    def upload(self, path, filename, data, done=None, failed=None, timeout=300000):
        """POST one file as a form upload (field "file"), the way a browser sends it."""
        form = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)
        part = QHttpPart()
        safe = ''.join(char for char in filename if char not in '"\\\r\n') or 'image.png'
        part.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                       f'form-data; name="file"; filename="{safe}"')
        part.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/octet-stream')
        part.setBody(data)
        form.append(part)
        request = QNetworkRequest(QUrl(self.url(path)))
        request.setTransferTimeout(timeout)
        reply = self.network.post(request, form)
        form.setParent(reply)  # the form lives as long as the upload
        reply.finished.connect(lambda: self.finish(reply, done, failed, False))
        return reply

    @staticmethod
    def finish(reply, done, failed, raw):
        reply.deleteLater()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        payload = bytes(reply.readAll().data())
        if status is None or (status < 400 and reply.error() != QNetworkReply.NetworkError.NoError):
            if failed:
                failed(reply.errorString() or 'The engine did not answer.')
            return
        if status >= 400:
            try:
                detail = json.loads(payload).get('detail')
            except (ValueError, AttributeError):
                detail = None
            if failed:
                failed(detail if isinstance(detail, str) else f'The engine answered {status}.')
            return
        if done:
            if raw:
                done(payload)
                return
            try:
                value = json.loads(payload) if payload else None
            except ValueError:
                if failed:
                    failed('The engine sent an unreadable answer.')
                return
            done(value)


class _Relay(QObject):
    finished = Signal(object, object)


_running = set()


def in_background(work, done):
    """Run work() on a thread; done(result, error) is then called on the UI thread."""
    relay = _Relay()
    _running.add(relay)

    def deliver(result, error):
        _running.discard(relay)
        done(result, error)

    relay.finished.connect(deliver)

    def run():
        try:
            relay.finished.emit(work(), None)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, never lost in a thread
            relay.finished.emit(None, exc)

    threading.Thread(target=run, daemon=True).start()


def port_free(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def die_with_parent():
    """Linux: the engine gets SIGTERM if the app ends abruptly (runs in the child before exec)."""
    import ctypes
    import signal

    ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class _WindowsJob:
    """A Windows job object that closes the engine (and what it started) if the app ends abruptly."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in 'abcdef']

        class Basic(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', Basic),
                ('IoInfo', Counters),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended()
        # Close everything with the job; let Krita and PhotoCraft break away (core/processes.py).
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x0800
        self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))

    def add(self, pid):
        process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # set quota, terminate
        if process:
            self.kernel.AssignProcessToJobObject(self.handle, process)
            self.kernel.CloseHandle(process)


class Engine(QObject):
    """Finds or starts the engine and reports its state: starting, ready, stopped or failed."""

    changed = Signal(str, str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.state, self.message = 'stopped', ''
        self.process = None
        self.owned = False
        self.waited = 0
        self.log = paths.LOGS / 'engine.log'
        self.job = None
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.check)

    def set_state(self, state, message):
        self.state, self.message = state, message
        self.changed.emit(state, message)

    @property
    def port(self):
        return int(paths.load_settings().get('port') or DEFAULT_PORT)

    def start(self):
        if paths.INSTALLED:
            engine_env.repoint()
        if engine_env.needs_setup():
            missing = engine_env.status() == 'missing'
            self.set_state('setup', 'Set up the engine in Studio settings to start creating.' if missing else
                           'An update changed the engine. Finish it in Studio settings.')
            return
        self.set_state('starting', 'Connecting to the engine…')
        self.client.base = f'http://127.0.0.1:{self.port}'
        if port_free(self.port):  # nothing there: start at once (probing a closed port is slow on Windows)
            self.launch(self.port)
            return
        self.client.get('/api/health', self.found, lambda _: self.launch(free_port()), timeout=2500)

    def found(self, answer):
        if isinstance(answer, dict) and answer.get('title') == TITLE:
            self.owned = False
            self.set_state('ready', 'Engine connected (started outside the app).')
        else:  # another program owns the port
            self.launch(free_port())

    def launch(self, port):
        self.client.base = f'http://127.0.0.1:{port}'
        self.log.parent.mkdir(parents=True, exist_ok=True)
        options = dict(cwd=str(paths.ROOT), stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        if sys.platform == 'win32':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        else:
            options['start_new_session'] = True
            options['preexec_fn'] = die_with_parent
        environment = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        try:
            with self.log.open('w', encoding='utf-8') as log:
                self.process = subprocess.Popen(
                    [engine_python(), '-m', 'image_studio', '--port', str(port), '--no-browser'],
                    stdout=log, env=environment, **options,
                )
        except OSError as exc:
            self.set_state('failed', f'The engine could not start: {exc}')
            return
        if sys.platform == 'win32':
            try:
                self.job = self.job or _WindowsJob()
                self.job.add(self.process.pid)
            except OSError:
                pass  # the engine still closes with the app; only a hard crash would leave it
        self.owned = True
        self.waited = 0
        self.set_state('starting', 'Starting the engine…')
        self.timer.start()

    def check(self):
        self.waited += 1
        if self.process.poll() is not None:
            self.timer.stop()
            self.process = None
            # Another copy may have taken the port a moment earlier: use it if so.
            self.client.get(
                '/api/health', self.found_after_exit,
                lambda _: self.set_state('failed', 'The engine stopped while starting. See the engine log.'),
                timeout=2500,
            )
            return
        if self.waited * self.timer.interval() > START_SECONDS * 1000:
            self.timer.stop()
            self.stop()
            self.set_state('failed', 'The engine took too long to start. See the engine log.')
            return
        self.client.get('/api/health', self.started, None, timeout=400)

    def found_after_exit(self, answer):
        if isinstance(answer, dict) and answer.get('title') == TITLE:
            self.owned = False
            self.set_state('ready', 'Engine connected (started outside the app).')
        else:
            self.set_state('failed', 'The engine stopped while starting. See the engine log.')

    def started(self, answer):
        if self.state == 'starting' and isinstance(answer, dict) and answer.get('title') == TITLE:
            self.timer.stop()
            self.set_state('ready', 'Engine ready.')

    def stop(self):
        """Stop the engine if the app started it (its workers too, so the GPU is freed; never Krita or PhotoCraft)."""
        self.timer.stop()
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        try:
            family = own_family(psutil.Process(process.pid))
        except psutil.Error:
            return
        for member in family:
            try:
                member.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(family, timeout=10)
        for member in alive:
            try:
                member.kill()
            except psutil.Error:
                pass

    def pause(self, message):
        """Stop the engine while its environment changes, saying why; start() brings it back."""
        self.stop()
        self.set_state('stopped', message)

    def take_over(self):
        """Stop an engine started by the web launcher, so this app can start its own."""
        from image_studio.cli import manage

        existing = manage.running_process()
        if existing is None:
            return False
        family = own_family(existing)
        for member in family:
            try:
                member.terminate()
            except psutil.Error:
                pass
        psutil.wait_procs(family, timeout=15)
        return True

    def restart(self):
        if self.state == 'ready' and not self.owned and not self.take_over():
            self.set_state('failed', 'The engine was started elsewhere. Close it there, then start it here.')
            return
        self.stop()
        self.start()

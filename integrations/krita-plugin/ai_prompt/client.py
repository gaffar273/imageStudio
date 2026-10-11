"""Talking to Image Studio's bridge on this computer (127.0.0.1:7861, see bridge.py)."""
import json
import os
import queue
import threading
import time
import traceback
import urllib.error
import urllib.request
from .qt import QObject, pyqtSignal

BRIDGE = 'http://127.0.0.1:7861'
ERRORS = (urllib.error.URLError, OSError, ValueError)
LOG = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'krita', 'ai_prompt.log')


def log_error(where):
    """Append the current exception to %APPDATA%\\krita\\ai_prompt.log (kept short)."""
    try:
        text = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {where}\n{traceback.format_exc()}\n'
        old = open(LOG, encoding='utf-8').read()[-200000:] if os.path.exists(LOG) else ''
        with open(LOG, 'w', encoding='utf-8') as out:
            out.write(old + text)
    except OSError:
        pass


def call(path, body=None, timeout=30):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = urllib.request.Request(BRIDGE + path, data=data, method='POST' if data is not None else 'GET',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


class Sender:
    """Posts in the background, in order, so Krita never waits on the network."""
    def __init__(self):
        self.queue = queue.Queue()
        threading.Thread(target=self.loop, daemon=True).start()

    def post(self, path, body, replace=None):
        self.queue.put((path, body))

    def loop(self):
        while True:
            path, body = self.queue.get()
            # Only the newest state matters; skip older ones still waiting.
            if path == '/krita/state' and any(item[0] == path for item in list(self.queue.queue)):
                continue
            try:
                call(path, body, timeout=15)
            except ERRORS:
                pass


class Poller(QObject):
    """Long-polls the bridge for commands from the browser. Signals arrive on Krita's
    main thread, where the Krita API may be used."""
    commands = pyqtSignal(list)
    connection = pyqtSignal(bool, bool)     # connected, someone watching in the browser

    def __init__(self):
        super().__init__()
        self.connected = None
        self.viewer = False
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                reply = call('/krita/poll?wait=15', timeout=25)
            except ERRORS:
                self.report(False, False)
                time.sleep(3)
                continue
            self.report(True, bool(reply.get('viewer')))
            if reply.get('commands'):
                self.commands.emit(reply['commands'])

    def report(self, connected, viewer):
        if (connected, viewer) != (self.connected, self.viewer):
            self.connected, self.viewer = connected, viewer
            self.connection.emit(connected, viewer)


sender = Sender()

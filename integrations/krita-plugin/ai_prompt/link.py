"""Keeps Krita connected to Image Studio while Krita runs (whether or not the panel is
shown): runs commands from the browser and reports what is open, with a live preview
while the browser's Krita tab is watching."""
import hashlib
import os
from krita import Extension, Krita
from . import ops
from .client import Poller, log_error, sender
from .qt import QTimer, encode, raw_bytes
from .runner import Controller, b64, save_to_library

PREVIEW = 1280          # longest side of the picture sent to the browser
_controller = None
extension = None        # the running LinkExtension


def controller():
    global _controller
    if _controller is None:
        _controller = Controller()
    return _controller


class LinkExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.poller = None
        self.last_state = None
        self.last_look = None
        self.viewer = False

    def setup(self):
        global extension
        extension = self
        self.poller = Poller()
        self.poller.commands.connect(self.handle)
        self.poller.connection.connect(self.connection)
        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.publish)
        self.timer.start()
        controller().event.connect(self.after_event)
        Krita.instance().notifier().windowCreated.connect(self.show_panel)

    def createActions(self, window):
        pass

    def show_panel(self):
        """Show the AI panel the first time Krita opens with this plugin (once the
        window has its dockers)."""
        QTimer.singleShot(2500, self.reveal_panel)

    def reveal_panel(self):
        app = Krita.instance()
        if app.readSetting('ai_prompt', 'panel_shown', '') == 'yes':
            return
        for window in app.windows():
            for dock in window.dockers():
                if dock.objectName() == 'ai_prompt':
                    dock.show()
                    dock.raise_()
                    app.writeSetting('ai_prompt', 'panel_shown', 'yes')

    def connection(self, connected, viewer):
        self.viewer = viewer
        if connected:
            self.last_state = None      # send everything again after a reconnect
            self.last_look = None

    def after_event(self, item):
        if item.get('kind') in ('step_done', 'done', 'failed', 'stopped'):
            self.publish(force=True)

    def publish(self, force=False):
        """Send what is open when it changes, and a preview while the browser watches."""
        if not self.poller or not self.poller.connected:
            return
        try:
            self.send_state(force)
        except Exception:
            log_error('publish')

    def send_state(self, force):
        doc = ops.document()
        state = ops.state(doc)
        body = {}
        if force or state != self.last_state:
            body['state'] = state
            self.last_state = state
        if doc is not None and (self.viewer or force):
            # A small thumbnail tells cheaply whether the picture changed.
            look = hashlib.md5(raw_bytes(doc.thumbnail(48, 48))).hexdigest() + str(state)
            if force or look != self.last_look:
                self.last_look = look
                body['preview'] = b64(encode(ops.flat_preview(doc, PREVIEW), 'JPEG', 88))
                body.setdefault('state', state)
        if body:
            sender.post('/krita/state', body)

    def handle(self, commands):
        for command in commands:
            kind = command.get('kind')
            try:
                if kind == 'prompt':
                    controller().submit(command.get('text', ''), source='browser')
                elif kind == 'open':
                    self.open(command['path'])
                elif kind == 'stop':
                    controller().stop()
                elif kind == 'undo':
                    controller().undo()
                elif kind == 'save':
                    controller().publish(dict(run='save', kind='status', text=save_to_library(controller())))
                elif kind == 'new_canvas':
                    ops.new_canvas(1024, 1024)
                elif kind == 'raise':
                    window = Krita.instance().activeWindow()
                    if window is not None:
                        window.qwindow().showNormal()
                        window.qwindow().raise_()
                        window.qwindow().activateWindow()
            except Exception as exc:  # Reported to the browser instead of breaking the link.
                log_error(f'command {kind}')
                controller().publish(dict(run=command.get('id'), kind='failed', text=f'{kind}: {exc}'))
            self.publish(force=True)

    def open(self, path):
        app = Krita.instance()
        if not os.path.exists(path):
            raise ops.StepError(f'{path} does not exist.')
        doc = app.openDocument(path)
        window = app.activeWindow() or (app.windows()[0] if app.windows() else None)
        if window is None:
            window = app.openWindow()
            window.qwindow().show()
        window.addView(doc)
        # The AI steps exchange 8-bit RGB pictures.
        if (doc.colorModel(), doc.colorDepth()) != ('RGBA', 'U8'):
            doc.setColorSpace(*ops.RGB8)
        window.qwindow().raise_()
        window.qwindow().activateWindow()
        controller().history = []

"""One prompt, start to finish: Image Studio plans the steps, then each step runs here,
Krita's own tools at once and AI steps as GPU jobs on Image Studio. Progress goes to the
panel and to the browser (as events on the bridge)."""
import base64
import uuid
from . import ops
from .client import ERRORS, call, log_error, sender
from .qt import GRAY8, QImage, QObject, QTimer, encode, fit, pyqtSignal, scaled_exact

# Picture sent with a prompt so the planner and questions can see it.
PLAN_PREVIEW = 768
# Pictures sent for selecting by description are at most this large.
SEGMENT_LONGEST = 1536
# Extra picture around a selection for AI edits, as a share of its size.
CONTEXT = 0.5
AI_STEPS = {'select', 'ai_edit', 'ai_generate', 'remove_background', 'enhance', 'fix_faces', 'save_to_library',
            'say', 'new_canvas', 'grade'}


def b64(data):
    return base64.b64encode(data).decode('ascii')


def image_from(encoded):
    return QImage.fromData(base64.b64decode(encoded))


class Controller(QObject):
    """Runs one prompt at a time; the panel in every Krita window shows its events."""
    event = pyqtSignal(dict)
    busy = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.run = None
        self.history = []          # what was done to the picture, for the Library
        self.options = dict(model='accurate', check=True, smart=True)

    def publish(self, item):
        self.event.emit(item)
        sender.post('/krita/event', item)

    def submit(self, text, source='krita'):
        text = ' '.join(str(text).split())
        if not text:
            return
        if self.run is not None:
            self.publish(dict(run=self.run.id, kind='status', text='Busy with the last request. Stop it first.'))
            return
        self.run = Run(self, text, source)
        self.busy.emit(True)
        self.run.start()

    def finished(self):
        self.run = None
        self.busy.emit(False)

    def stop(self):
        if self.run is not None:
            self.run.stop()

    def undo(self):
        doc = ops.document()
        if doc is not None:
            ops.undo(doc)
            ops.settle(doc)


class Run:
    def __init__(self, controller, text, source):
        self.controller, self.text, self.source = controller, text, source
        self.id = uuid.uuid4().hex[:12]
        self.steps, self.labels, self.index = [], [], 0
        self.how = None            # who planned the steps: rules, planner, vision or fallback
        self.job = None            # (job id, function to call with the result)
        self.last_message = None
        self.stopped = False
        self.timer = QTimer()
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.poll)

    def emit(self, kind, **values):
        self.controller.publish(dict(values, run=self.id, kind=kind))

    # ---- Planning ------------------------------------------------------------------

    def start(self):
        self.emit('start', text=self.text, source=self.source)
        doc = ops.document()
        body = dict(kind='plan', prompt=self.text, state=ops.state(doc))
        if doc is not None:
            body['image'] = b64(encode(ops.preview(doc, PLAN_PREVIEW)))
        self.emit('status', text='Understanding your request...')
        try:
            self.submit(body, self.planned)
        except ops.StepError as exc:
            self.finish('failed', str(exc))

    def planned(self, result):
        self.steps = result.get('steps') or []
        self.labels = result.get('labels') or [step['op'] for step in self.steps]
        self.how = result.get('how')
        self.emit('plan', labels=self.labels, how=self.how)
        for note in result.get('notes') or []:
            self.emit('status', text=note)
        if not self.steps:
            return self.finish('failed', 'Nothing to do for that request.')
        self.next()

    # ---- Steps --------------------------------------------------------------------

    def next(self):
        while not self.stopped and self.index < len(self.steps):
            step, label = self.steps[self.index], self.labels[self.index]
            self.emit('step', index=self.index, label=label)
            try:
                if step['op'] in AI_STEPS:
                    if self.ai_step(step, label):
                        return      # waiting for Image Studio; poll() continues
                else:
                    doc = ops.need(ops.document())
                    note = ops.run_local(doc, step, label)
                    self.done(note)
            except ops.StepError as exc:
                return self.fail(str(exc))
            except Exception as exc:  # Keep Krita running whatever happens.
                log_error(f'step {step}')
                return self.fail(f'{exc.__class__.__name__}: {exc}')
        if not self.stopped:
            self.finish('done', 'Done.')

    def done(self, note=None):
        label = self.labels[self.index]
        if self.steps[self.index]['op'] not in ('say', 'undo', 'redo', 'save_to_library'):
            self.controller.history.append(label)
        self.emit('step_done', index=self.index, text=note or '')
        self.index += 1

    def fail(self, message):
        self.emit('step_failed', index=self.index, text=message)
        self.finish('failed', message)

    def finish(self, kind, text):
        self.timer.stop()
        self.job = None
        doc = ops.document()
        if doc is not None:
            ops.settle(doc)
        self.emit(kind, text=text)
        self.controller.finished()

    def stop(self):
        self.stopped = True
        if self.job is not None:
            try:
                call(f'/jobs/{self.job[0]}/cancel', {}, timeout=5)
            except ERRORS:
                pass
        self.finish('stopped', 'Stopped.')

    # ---- AI steps (GPU jobs on Image Studio) --------------------------------------

    def ai_step(self, step, label):
        """Start an AI step. Returns True while a job runs, False if it finished at once."""
        op = step['op']
        if op == 'say':
            self.emit('say', text=step['text'])
            self.done()
            return False
        if op == 'new_canvas':
            self.done(ops.new_canvas(step.get('width', 1024), step.get('height', 1024)))
            return False
        if op == 'save_to_library':
            self.done(save_to_library(self.controller))
            return False
        doc = ops.document()
        if doc is None:
            if op != 'ai_generate':
                raise ops.StepError('Open or create a picture first.')
            ops.new_canvas(1024, 1024)
            doc = ops.document()
        if op == 'select':
            target = step['target'].strip().lower()
            if target in ('all', 'everything', 'the whole picture', 'whole picture'):
                ops.select_all(doc)
                self.done()
                return False
            if target in ('none', 'nothing'):
                ops.deselect(doc)
                self.done()
                return False
            image = fit(ops.projection(doc), SEGMENT_LONGEST)
            self.submit(dict(kind='segment', target=step['target'], image=b64(encode(image))),
                        lambda result: self.selected(doc, result))
            return True
        if op == 'remove_background':
            image = fit(ops.projection(doc), SEGMENT_LONGEST)
            self.submit(dict(kind='segment', target='subject', image=b64(encode(image))),
                        lambda result: self.cut_out(doc, result))
            return True
        if op in ('ai_edit', 'ai_generate'):
            kind = 'edit' if op == 'ai_edit' else 'create'
            prompt = step['instruction'] if op == 'ai_edit' else step['description']
            # Planned instructions are already precise ("change the light, keep the sky"); the
            # small rewriting model only helps with the person's own words (the fallback).
            options = dict(smart=self.controller.options['smart'] and self.how == 'fallback')
            if kind == 'create':
                options.update(model=self.controller.options['model'], check=self.controller.options['check'],
                               attempts=3, repair=True)
            body, area = region_job(doc, kind, prompt, **options)
            area['name'] = label
            self.submit(body, lambda result: self.add_layer(area, result))
            return True
        if op == 'grade':
            body = dict(kind='grade', layers=step['layers'], image=b64(encode(ops.projection(doc))))
            self.submit(body, lambda result: self.add_grade(doc, label, result))
            return True
        if op in ('enhance', 'fix_faces'):
            body = dict(kind='enhance' if op == 'enhance' else 'faces', scale=step.get('scale', 1.0),
                        image=b64(encode(ops.projection(doc))))
            self.submit(body, lambda result: self.add_whole(doc, label, result))
            return True
        raise ops.StepError(f'Unknown step {op}.')

    def selected(self, doc, result):
        doc.setSelection(ops.mask_selection(doc, image_from(result['mask'])))
        ops.settle(doc)
        return result.get('message')

    def cut_out(self, doc, result):
        layer = ops.bottom_paint_layer(doc)
        mask = doc.createTransparencyMask('Cut out')
        layer.addChildNode(mask, None)
        mask.setSelection(ops.mask_selection(doc, image_from(result['mask'])))
        ops.settle(doc)
        return 'Background hidden with a mask on "%s"; paint the mask to adjust it.' % layer.name()

    def add_layer(self, area, result):
        image = image_from(result['image'])
        if (image.width(), image.height()) != (area['w'], area['h']):
            image = scaled_exact(image, area['w'], area['h'])
        ops.pixel_layer(area['doc'], area['name'], image, area['x'], area['y'])
        ops.settle(area['doc'])
        return result.get('message')

    def add_grade(self, doc, label, result):
        layers = [(item['name'], image_from(item['image']), image_from(item['mask']) if item.get('mask') else None,
                   item.get('opacity', 100)) for item in result.get('layers') or []]
        ops.add_grade(doc, label, layers)
        ops.settle(doc)
        return result.get('message')

    def add_whole(self, doc, label, result):
        image = image_from(result['image'])
        if (image.width(), image.height()) != (doc.width(), doc.height()):
            # Enlarged: the picture grows to the new size first, then the result goes on top.
            doc.scaleImage(image.width(), image.height(), int(doc.resolution()), int(doc.resolution()), 'Bicubic')
            ops.settle(doc)
        ops.pixel_layer(doc, label, image)
        ops.settle(doc)
        return result.get('message')

    # ---- Jobs ---------------------------------------------------------------------

    def submit(self, body, then):
        try:
            job = call('/jobs', body, timeout=60)['id']
        except ERRORS as exc:
            raise ops.StepError(f'Image Studio is not reachable. Start it with "Start image generator.bat". ({exc})')
        self.job = (job, then)
        self.last_message = None
        self.timer.start()

    def poll(self):
        if self.job is None:
            return self.timer.stop()
        job, then = self.job
        try:
            state = call(f'/jobs/{job}', timeout=120)
        except ERRORS as exc:
            return self.fail(f'Lost contact with Image Studio. ({exc})')
        if state['state'] == 'running':
            message = state.get('message') or 'Working...'
            if message != self.last_message:
                self.last_message = message
                kind = 'status' if not self.steps else 'progress'
                self.emit(kind, index=self.index if self.steps else None, text=message,
                          progress=state.get('progress', 0))
            return
        self.timer.stop()
        self.job = None
        planning = not self.steps
        if state['state'] == 'error':
            if planning:
                return self.finish('failed', state.get('message') or 'Failed.')
            return self.fail(state.get('message') or 'Failed.')
        if planning:
            return then(state)     # planned() runs the steps
        try:
            note = then(state)
        except ops.StepError as exc:
            return self.fail(str(exc))
        except Exception as exc:  # Keep Krita running whatever happens.
            log_error('applying a result')
            return self.fail(f'{exc.__class__.__name__}: {exc}')
        self.done(note)
        self.next()


def region_job(doc, kind, prompt, **options):
    """The bridge request for an AI edit or new picture, and where its result goes: the
    selection plus some surroundings (edits), the selection (new pictures), or everything."""
    width, height = doc.width(), doc.height()
    selection = ops.current_selection(doc)
    if selection is None:
        x, y, w, h = 0, 0, width, height
    else:
        x, y, w, h = selection.x(), selection.y(), selection.width(), selection.height()
        if kind == 'edit':
            # Include surroundings so the change matches the light and style around it.
            pad = int(max(w, h) * CONTEXT)
            left, top = max(0, x - pad), max(0, y - pad)
            x, y, w, h = left, top, min(width, x + w + pad) - left, min(height, y + h + pad) - top
    body = dict(options, kind=kind, prompt=prompt, width=w, height=h)
    if selection is not None:
        mask = QImage(bytes(selection.pixelData(x, y, w, h)), w, h, w, GRAY8).copy()
        body['mask'] = b64(encode(mask))
    if kind == 'edit':
        body['image'] = b64(encode(ops.projection(doc, x, y, w, h)))
    return body, dict(doc=doc, x=x, y=y, w=w, h=h)


def save_to_library(controller):
    doc = ops.need(ops.document())
    state = ops.state(doc)
    try:
        reply = call('/library', dict(image=b64(encode(ops.projection(doc))), name=state['name'],
                                      history=controller.history), timeout=60)
    except ERRORS as exc:
        raise ops.StepError(f'Could not save to the library. ({exc})')
    return 'Saved to the Image Studio library.' if reply.get('path') else reply.get('error', 'Not saved.')

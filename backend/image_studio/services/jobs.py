"""One browser render at a time, with progress, cancellation and retained results."""

import threading
import time
import uuid
from image_studio.core.engine import explain
from image_studio.services import workflows
from image_studio.services.runtime import render_session


class BusyError(Exception):
    pass


class JobStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None

    def submit(self, run):
        from image_studio.services import personal

        with self.lock:
            if personal.is_training():
                raise BusyError(
                    'The studio is learning your style (personal LoRA training). '
                    'See Settings for progress; it frees the GPU when done.'
                )
            if self.active or not render_session.acquire(blocking=False):
                raise BusyError('The studio is already rendering. Finish or stop the current job first.')
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = dict(
                id=job_id,
                state='running',
                progress=0,
                message='Preparing your image…',
                images=[],
                started=time.time(),
            )
            self.active = job_id
            workflows.engine.cancelled.clear()
            while len(self.jobs) > 100:
                del self.jobs[next(iter(self.jobs))]

        def progress(value=None, desc=None, **kwargs):
            with self.lock:
                if value is not None:
                    self.jobs[job_id]['progress'] = max(0, min(1, float(value)))
                if desc:
                    self.jobs[job_id]['message'] = desc

        def update(**values):
            with self.lock:
                self.jobs[job_id].update(values)

        def worker():
            try:
                run(progress, update)
                with self.lock:
                    cancelled = workflows.engine.cancelled.is_set()
                    update(
                        state='cancelled' if cancelled else 'done',
                        progress=1,
                        message='Generation stopped.' if cancelled else self.jobs[job_id]['message'],
                    )
            except Exception as exc:
                update(state='error', message=explain(exc))
            finally:
                with self.lock:
                    self.active = None
                    render_session.release()

        threading.Thread(target=worker, daemon=True, name=f'render-{job_id[:8]}').start()
        return self.get(job_id)

    def get(self, job_id):
        with self.lock:
            return dict(self.jobs[job_id])

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['state'] == 'running' and self.active == job_id:
                workflows.stop()
                job['message'] = 'Stopping after the current step…'
            return dict(job)


store = JobStore()

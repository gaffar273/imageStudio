"""The personal style LoRA: RealVisXL taught the look of the pictures marked as favorites.

Training takes the whole GPU for 10 to 25 minutes, so it runs either when asked (Settings,
"Train now") or overnight (between NIGHT_START and NIGHT_END, when the studio is idle and
enough new favorites have been added). While it runs, the render lock is held, so new
renders are refused with a clear message, and every model is unloaded first.

The work itself runs in a separate Python process (cli/personal_lora.py): the favorites
are copied, captioned by the vision assistant (what is in each picture, never its style, so
the style is what the LoRA learns), and a small LoRA is trained with training/lora. The
process ends when done, which frees every byte of GPU memory it used."""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

from image_studio.core.paths import ROOT, WORK

FOLDER = WORK / 'personal-lora'
DATA = FOLDER / 'data'
FINAL = FOLDER / 'final'
STATUS = FOLDER / 'status.json'
LOCK = FOLDER / 'training.lock'
LOG = WORK / 'personal-lora.log'

MIN_IMAGES = 12  # fewer favorites than this teach too little
NEW_TO_RETRAIN = 5  # retrain overnight after this many favorites changed
NIGHT_START, NIGHT_END = 1, 5  # local hours for overnight training
RANK = 8


def steps_for(count):
    """Training steps for `count` pictures: each seen about 40 times (mirrored too), 400 to 1200."""
    return max(400, min(1200, count * 40))


_lock = threading.Lock()
_live = dict(state='idle', message='', progress=0.0, started=None)


def ready():
    return (FINAL / 'pytorch_lora_weights.safetensors').exists()


def _saved():
    try:
        return json.loads(STATUS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save(**values):
    FOLDER.mkdir(parents=True, exist_ok=True)
    data = {**_saved(), **values}
    STATUS.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return data


def _pid_alive(pid):
    try:
        import psutil

        return psutil.pid_exists(int(pid))
    except (ImportError, ValueError):
        return False


def training_elsewhere():
    """True while a training run started outside this server (the command line) is running."""
    try:
        pid = int(LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def is_training():
    return _live['state'] == 'training' or training_elsewhere()


def changed_favorites():
    """How many favorites were added or removed since the last training."""
    from image_studio.services import memory

    now, then = set(memory.favorites()), set(_saved().get('images', []))
    return len(now ^ then)


def needed():
    from image_studio.services import memory

    count = len(memory.favorites())
    if count < MIN_IMAGES:
        return False
    return not ready() or changed_favorites() >= NEW_TO_RETRAIN


def status():
    from image_studio.services import memory

    saved = _saved()
    count = len(memory.favorites())
    return dict(
        ready=ready(),
        state='training' if is_training() else _live['state'],
        message=_live['message'] or saved.get('message', ''),
        progress=_live['progress'],
        favorites=count,
        minimum=MIN_IMAGES,
        trained_at=saved.get('trained_at'),
        trained_on=len(saved.get('images', [])),
        changed=changed_favorites() if saved.get('images') else count,
        nightly=saved.get('nightly', True),
        minutes=round(steps_for(max(count, 1)) * 1.1 / 60 + 3),
    )


def set_nightly(enabled):
    _save(nightly=bool(enabled))


STEP_LINE = re.compile(r'step (\d+)/(\d+)')


def _run(reason):
    """Unload every model, run the training process, then release the GPU."""
    from image_studio.services import assistant, workflows
    from image_studio.services.runtime import render_session

    try:
        workflows.engine.unload()
        assistant.release()
        _live.update(message='Copying and describing your favorites...', progress=0.02)
        FOLDER.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as log:
            log.write(f'\n==== {datetime.now():%Y-%m-%d %H:%M} personal LoRA ({reason}) ====\n')
            log.flush()
            process = subprocess.Popen(
                [sys.executable, '-m', 'image_studio.cli.personal_lora', '--run'],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            for line in process.stdout:
                log.write(line)
                log.flush()
                match = STEP_LINE.search(line)
                if match:
                    done, total = int(match[1]), int(match[2])
                    left = re.search(r'(\d+) min left', line)
                    _live.update(
                        progress=0.1 + 0.9 * done / total,
                        message=f'Learning your style: step {done} of {total}'
                        + (f', about {left[1]} min left' if left else ''),
                    )
                elif line.startswith('caption '):
                    _live.update(message='Describing your favorites: ' + line[8:].strip())
            code = process.wait()
        if code != 0:
            raise RuntimeError(f'Training stopped (code {code}). See {LOG.name} in the work folder.')
        _live.update(state='idle', progress=1.0, message='')
        _save(message=f'Learned your style from {len(_saved().get("images", []))} favorites.')
    except Exception as exc:
        _live.update(state='failed', message=str(exc) or exc.__class__.__name__)
        _save(message=_live['message'])
    finally:
        _live['started'] = None
        render_session.release()


def start(reason='manual', only_if_needed=False):
    """Start training in the background. Returns the status; raises ValueError when it
    cannot start (too few favorites, or the studio is busy)."""
    from image_studio.services import memory
    from image_studio.services.runtime import render_session

    with _lock:
        if is_training():
            return status()
        if only_if_needed and not needed():
            return status()
        if len(memory.favorites()) < MIN_IMAGES:
            raise ValueError(
                f'Mark at least {MIN_IMAGES} pictures as favorites first ({len(memory.favorites())} so far).'
            )
        if not render_session.acquire(blocking=False):
            raise ValueError('The studio is busy. Try again when the current job has finished.')
        _live.update(state='training', message='Starting...', progress=0.0, started=time.time())
    threading.Thread(target=_run, args=(reason,), daemon=True, name='personal-lora').start()
    return status()


def _nightly():
    """Train overnight when it is enabled and needed and nothing else is running."""
    from image_studio.services.jobs import store

    while True:
        time.sleep(600)
        try:
            hour = datetime.now().hour
            if (
                NIGHT_START <= hour < NIGHT_END
                and _saved().get('nightly', True)
                and store.active is None
                and needed()
            ):
                start('overnight', only_if_needed=True)
        except Exception as exc:  # Never let the timer die; report on the Settings page.
            _live.update(message=f'Overnight training could not start: {exc}')


threading.Thread(target=_nightly, daemon=True, name='personal-lora-nightly').start()

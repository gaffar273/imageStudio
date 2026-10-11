"""The engine's own Python environment in an installed copy, and which Python runs the engine.

A source checkout runs the engine with the Python the app was started with, which already
has PyTorch. An installed copy ships only a small Python for the window. PyTorch with CUDA
and the model libraries (several GB) go into their own environment in the user's data
folder, set up once from Studio settings (cli/setup_engine.py). The environment shares the
app's packages (fastapi, the studio itself), so an app update reaches the engine at once,
and an update that pins different libraries asks for a quick refresh.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

from image_studio.core import paths

REQUIREMENTS = [
    paths.ROOT / 'backend' / 'requirements-torch.txt',
    paths.ROOT / 'backend' / 'requirements-models.txt',
]
MARKER = 'image-studio-engine.json'


def env_python(env=None):
    env = Path(env or paths.ENGINE_ENV)
    return env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def console(executable):
    """python.exe rather than pythonw.exe, so a child process has output to read."""
    executable = Path(executable)
    if executable.stem.lower() == 'pythonw':
        python = executable.with_name('python.exe')
        if python.exists():
            return str(python)
    return str(executable)


def app_python():
    return console(sys.executable)


def engine_python():
    """The interpreter for the engine and the tools it runs (IMAGE_STUDIO_ENGINE_PYTHON overrides)."""
    override = os.environ.get('IMAGE_STUDIO_ENGINE_PYTHON')
    if override:
        return override
    return str(env_python()) if paths.INSTALLED else app_python()


def python_version():
    return f'{sys.version_info.major}.{sys.version_info.minor}'


def wanted():
    """What a ready environment matches: this Python's version and the pinned libraries."""
    digest = hashlib.sha256()
    for file in REQUIREMENTS:
        digest.update(file.read_bytes().replace(b'\r\n', b'\n'))
    return dict(python=python_version(), requirements=digest.hexdigest()[:16])


def recorded(env=None):
    """What setup_engine wrote when it last finished; {} when it never did."""
    try:
        values = json.loads((Path(env or paths.ENGINE_ENV) / MARKER).read_text(encoding='utf-8'))
        return values if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def base_home(env=None):
    """The Python installation the environment was made from (pyvenv.cfg), or None."""
    try:
        text = (Path(env or paths.ENGINE_ENV) / 'pyvenv.cfg').read_text(encoding='utf-8')
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition('=')
        if key.strip().lower() == 'home':
            return value.strip()
    return None


def same_base(env=None):
    """Whether the environment still points at the Python this app runs (the app may have moved)."""
    home = base_home(env)
    if not home or not Path(home).is_dir():
        return False
    base = Path(getattr(sys, '_base_executable', sys.executable)).parent
    try:
        return Path(home).samefile(base)
    except OSError:
        return False


def status(env=None):
    """'ready'; 'update' when an app update or a move changed what it needs; or 'missing'."""
    record = recorded(env)
    if not env_python(env).is_file() or not record:
        return 'missing'
    if {key: record.get(key) for key in ('python', 'requirements')} != wanted() or not same_base(env):
        return 'update'
    return 'ready'


def needs_setup():
    """True when this copy cannot start the engine until the environment is set up or refreshed."""
    return paths.INSTALLED and not os.environ.get('IMAGE_STUDIO_ENGINE_PYTHON') and status() != 'ready'

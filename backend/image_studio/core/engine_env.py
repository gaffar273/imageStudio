"""The engine's own Python environment in an installed copy, and which Python runs the engine.

A source checkout runs the engine with the Python the app was started with, which already
has PyTorch. An installed copy ships only a small Python for the window. PyTorch with CUDA
and the model libraries (several GB) go into their own environment in the user's data
folder, set up once from Studio settings (cli/setup_engine.py). The environment shares the
app's packages (fastapi, the studio itself), so an app update reaches the engine at once,
and an update that pins different libraries asks for a quick refresh.

A PC without an NVIDIA graphics card gets the engine in cloud mode instead: no PyTorch, only
what the engine's server loads (about 100 MB), so Create and Edit work through the providers
connected in Studio settings. Installing the full engine later adds to the same environment.
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
CLOUD_REQUIREMENTS = [paths.ROOT / 'backend' / 'requirements-cloud.txt']
KINDS = dict(full=REQUIREMENTS, cloud=CLOUD_REQUIREMENTS)  # 'cloud': no PyTorch, providers only
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


def wanted(kind='full'):
    """What a ready environment matches: this Python's version and the pinned libraries."""
    digest = hashlib.sha256()
    for file in KINDS[kind]:
        digest.update(file.read_bytes().replace(b'\r\n', b'\n'))
    return dict(python=python_version(), requirements=digest.hexdigest()[:16])


def recorded(env=None):
    """What setup_engine wrote when it last finished; {} when it never did."""
    try:
        values = json.loads((Path(env or paths.ENGINE_ENV) / MARKER).read_text(encoding='utf-8'))
        return values if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def kind(env=None):
    """'full' (PyTorch and the model libraries) or 'cloud' (providers only), as last set up."""
    return 'cloud' if recorded(env).get('kind') == 'cloud' else 'full'


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


def base_runtime():
    """The Python installation an environment is made from: the one this app runs.

    A Microsoft Store package is the exception. The environment's python.exe sits outside the
    package and only starts its base Python, and Windows lets nothing outside a package start
    a program inside it (reading its files is allowed). So a package makes the environment from
    a copy of its Python in the data folder (sync_runtime), and the engine runs outside the package."""
    if paths.PACKAGE:
        return paths.data_dir() / 'runtime'
    return Path(getattr(sys, '_base_executable', sys.executable)).parent


RUNTIME_MARKER = 'image-studio-build.json'


def runtime_stamp():
    """What a copy of the package's Python is made from: this build, at this package folder."""
    return json.dumps(dict(build=paths.BUILD_FILE.read_text(encoding='utf-8'), root=str(paths.ROOT)), indent=2)


def runtime_current():
    """Package only: whether the copied Python is this version's, from this package folder."""
    try:
        return (base_runtime() / RUNTIME_MARKER).read_text(encoding='utf-8') == runtime_stamp()
    except OSError:
        return False


def sync_runtime():
    """Package only: copy the package's Python to base_runtime() unless this version's copy is
    there; True when it is ready. The window's libraries (Qt) stay behind, the engine never
    loads them, and the studio's code is read from the package (only starting programs there
    is blocked)."""
    if runtime_current():
        return True
    import shutil

    source = Path(getattr(sys, '_base_executable', sys.executable)).parent
    target = base_runtime()
    try:
        (target / RUNTIME_MARKER).unlink(missing_ok=True)  # an interrupted copy is redone next time
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(
            source, target, ignore=shutil.ignore_patterns('PySide6*', 'shiboken6*')
        )
        # In the package the studio's code is found relative to this file; from the copy it is not.
        (target / 'Lib' / 'site-packages' / 'image-studio.pth').write_text(
            str(paths.ROOT / 'backend') + '\n', encoding='utf-8'
        )
        (target / RUNTIME_MARKER).write_text(runtime_stamp(), encoding='utf-8')
    except OSError:  # most likely an engine of the previous version still running
        return False
    return True


def make(env, clear=False, upgrade=False, with_pip=True):
    """Create or refresh the environment from base_runtime()."""
    import venv

    if not paths.PACKAGE:
        venv.EnvBuilder(system_site_packages=True, with_pip=with_pip, clear=clear, upgrade=upgrade).create(env)
        return
    if not sync_runtime():
        raise OSError(f'Python could not be copied to {base_runtime()}; close Image Studio and try again')
    import subprocess

    flags = ['--clear'] * clear + ['--upgrade'] * upgrade + ['--without-pip'] * (not with_pip)
    result = subprocess.run(
        [str(base_runtime() / 'python.exe'), '-m', 'venv', '--system-site-packages', *flags, str(env)],
        capture_output=True, text=True, errors='replace',
    )
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise OSError(lines[-1] if lines else f'python -m venv exited with {result.returncode}')


def same_base(env=None):
    """Whether the environment still points at the Python it is made from (the app may have moved)."""
    home = base_home(env)
    if not home or not Path(home).is_dir():
        return False
    if paths.PACKAGE and not runtime_current():
        return False
    try:
        return Path(home).samefile(base_runtime())
    except OSError:
        return False


def status(env=None):
    """'ready'; 'update' when an app update or a move changed what it needs; or 'missing'."""
    record = recorded(env)
    if not env_python(env).is_file() or not record:
        return 'missing'
    if {key: record.get(key) for key in ('python', 'requirements')} != wanted(kind(env)) or not same_base(env):
        return 'update'
    return 'ready'


def repoint(env=None):
    """Point a finished environment at this app's Python again when only the app's folder moved.

    A Microsoft Store update installs each version in a new folder (and its Python is copied
    again), so this happens after every update there; the libraries are unchanged, so it takes
    seconds rather than a setup run. Returns True when it repointed."""
    env = Path(env or paths.ENGINE_ENV)
    record = recorded(env)
    if not env_python(env).is_file() or not record or same_base(env):
        return False
    if {key: record.get(key) for key in ('python', 'requirements')} != wanted(kind(env)):
        return False  # the libraries changed too: Studio settings finishes the update
    try:
        make(env, upgrade=True, with_pip=False)
    except OSError:
        return False
    return same_base(env)


def removable():
    """What remove() deletes: the environment, and a package's copy of Python. Only folders that
    are what they should be, so an engine folder set to somewhere else never loses other files."""
    found = []
    env = Path(paths.ENGINE_ENV)
    if (env / 'pyvenv.cfg').is_file():
        found.append(env)
    if paths.PACKAGE and (base_runtime() / 'python.exe').is_file():
        found.append(base_runtime())
    return found


def remove():
    """Delete the engine's libraries (several GB), e.g. before the app is uninstalled: neither
    the installer's nor the Store's uninstall removes them for every case. Models, pictures and
    settings stay. Returns the bytes freed. Stop the engine first."""
    import shutil
    import time

    freed = 0
    for folder in removable():
        freed += sum(file.stat().st_size for file in folder.rglob('*') if file.is_file())
        for attempt in range(5):  # the engine's files can stay locked a moment after it exits
            try:
                shutil.rmtree(folder)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(1)
    return freed


def needs_setup():
    """True when this copy cannot start the engine until the environment is set up or refreshed."""
    return paths.INSTALLED and not os.environ.get('IMAGE_STUDIO_ENGINE_PYTHON') and status() != 'ready'

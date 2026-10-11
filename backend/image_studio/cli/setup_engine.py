"""Set up the engine's Python environment: PyTorch with CUDA and the model libraries.

Studio settings runs this in an installed copy (Install on the Engine row); it also works
by hand: `python -m image_studio.cli.setup_engine`. Running it again is always safe: it
finishes an interrupted setup, and after an app update installs only what changed.

Its output is shaped for the app's installer (desktop/installs.py): pip's download
progress is printed as "name: 45%| 1.2 GB/3.3 GB" lines.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import venv
from pathlib import Path

from image_studio.core import engine_env, paths

FINAL = 3  # exit code when trying again cannot help (the installer stops retrying)
DOWNLOADING = re.compile(r'^\s*Downloading (\S+)(?: \(([^)]+)\))?')
PROGRESS = re.compile(r'^Progress (\d+) of (\d+)$')
NETWORK = (
    'connection',
    'timed out',
    'timeout',
    'incompleteread',
    'max retries',
    'temporary failure',
    'getaddrinfo',
    'name resolution',
    'ssl',
    'remote end closed',
    'http error 5',
)
CHECK = (
    'import json, torch, torchvision, diffusers, transformers, cv2, numpy; '
    'print(json.dumps(dict(torch=torch.__version__, cuda=torch.cuda.is_available())))'
)


def amount(size):
    return f'{size / 1e9:.2f} GB' if size >= 1e8 else f'{size / 1e6:.0f} MB'


def package_name(target):
    """torch from '.../torch-2.11.0%2Bcu128-cp312-cp312-win_amd64.whl'."""
    return target.rstrip('/').rsplit('/', 1)[-1].split('-', 1)[0]


class Translator:
    """Turns pip's raw output into lines the app's installer shows."""

    def __init__(self):
        self.name = 'Downloading'

    def __call__(self, line):
        downloading = DOWNLOADING.match(line)
        if downloading:
            self.name = package_name(downloading.group(1))
            size = f' ({downloading.group(2)})' if downloading.group(2) else ''
            return f'Downloading {self.name}{size}'
        progress = PROGRESS.match(line.strip())
        if progress:
            current, total = int(progress.group(1)), int(progress.group(2))
            if not total:
                return None
            percent = min(100, current * 100 // total)
            return f'{self.name}: {percent}%| {amount(current)}/{amount(total)}'
        return line.strip() or None


def prepare(env):
    """Make the environment, or point an existing one at this app's Python again."""
    python = engine_env.env_python(env)
    record = engine_env.recorded(env)
    other_python = bool(record) and record.get('python') != engine_env.python_version()
    if python.is_file() and not other_python and engine_env.same_base(env):
        print('Checking the engine environment.', flush=True)
        return
    print('Making the engine environment.', flush=True)
    # Shares the app's own packages (the studio, fastapi); a newer Python means new libraries.
    venv.EnvBuilder(
        system_site_packages=True,
        with_pip=True,
        clear=other_python,
        upgrade=python.is_file() and not other_python,
    ).create(env)


def pip_install(python, requirements):
    """Install one requirements file; returns (exit code, the end of pip's output)."""
    args = [
        str(python),
        '-m',
        'pip',
        'install',
        '--disable-pip-version-check',
        '--no-cache-dir',
        '--no-warn-script-location',
        '--progress-bar',
        'raw',
        '-r',
        str(requirements),
    ]
    environment = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=environment,
    )
    translate, tail = Translator(), []
    for line in process.stdout:
        tail = (tail + [line.strip()])[-40:]
        shown = translate(line.rstrip('\r\n'))
        if shown:
            print(shown, flush=True)
    return process.wait(), '\n'.join(tail)


def check(python):
    """The installed versions, or None when the libraries do not load."""
    result = subprocess.run(
        [str(python), '-c', CHECK],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if result.returncode:
        print(
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'The libraries do not load.'
        )
        return None
    return json.loads(result.stdout.strip().splitlines()[-1])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Set up the engine: PyTorch with CUDA and the model libraries.'
    )
    parser.add_argument('--env', type=Path, default=paths.ENGINE_ENV, help='the folder for the environment')
    args = parser.parse_args(argv)
    env = args.env.expanduser().resolve()
    try:
        prepare(env)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'The engine environment could not be made in {env}: {exc}')
        return FINAL
    python = engine_env.env_python(env)
    for label, requirements in zip(('PyTorch', 'the model libraries'), engine_env.REQUIREMENTS):
        print(f'Installing {label}.', flush=True)
        code, output = pip_install(python, requirements)
        if code:
            network = any(word in output.lower() for word in NETWORK)
            print(output.strip().splitlines()[-1] if output.strip() else f'Installing {label} failed.')
            return 1 if network else FINAL
    print('Checking that the libraries load.', flush=True)
    versions = check(python)
    if versions is None:
        return FINAL
    if not versions['cuda']:
        print(
            'PyTorch is installed but cannot use an NVIDIA graphics card. Updating the NVIDIA driver '
            'usually fixes this.',
            flush=True,
        )
    record = dict(
        engine_env.wanted(),
        torch=versions['torch'],
        cuda=versions['cuda'],
        finished=time.strftime('%Y-%m-%d %H:%M:%S'),
    )
    (env / engine_env.MARKER).write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('The engine is ready.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

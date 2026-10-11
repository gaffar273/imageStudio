"""Build Image Studio for people who do not run it from source.

    python packaging/build.py      on Windows: the app folder, then the installer (Inno Setup 6)
    python3 packaging/build.py     on Linux: a .tar.gz with the app folder and install.sh

What goes in: a standalone Python (python-build-standalone, checked against its SHA-256),
the window's libraries (packaging/requirements-app.txt), the studio's code with the files it
reads at run time, an icon and a launcher. About 100 MB. The models and the engine's GPU
libraries are not included: the app installs those itself (core/engine_env.py).

Everything is made under build/ and the results land in dist/. Any Python 3.10+ runs this;
the downloaded Python does the rest.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / 'packaging'
BUILD = ROOT / 'build'
DIST = ROOT / 'dist'
RELEASE = 'https://github.com/astral-sh/python-build-standalone/releases/download/20250409/'
RUNTIMES = {
    'windows': (
        'cpython-3.12.10+20250409-x86_64-pc-windows-msvc-install_only.tar.gz',
        '5ac66ae49a2104efeba985c1dc1cb40987757ee81cc6c7f218d10b801f3276ed',
    ),
    'linux': (
        'cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only.tar.gz',
        'e9cf6f7da499a4400ba30ae1da8f7ef25ce97827bd8c1084717aa05438035186',
    ),
}
# What the app reads at run time, at the same places as in the repository (core/paths.py ROOT).
CONTENT = [
    'backend/image_studio',
    'backend/requirements-torch.txt',
    'backend/requirements-models.txt',
    'backend/requirements-search.txt',
    'integrations/krita-plugin',
    'training/lora',
    'README.md',
]
SKIP = shutil.ignore_patterns('__pycache__', '*.pyc', '*.log')
# Unused parts of Python and Qt: debug symbols, Tk, and Qt's QML/Quick, designer and build tools.
# The smoke test builds the whole window afterwards, so a needed file going missing fails the build.
TRIM_RUNTIME = ['*.pdb', 'idlelib', 'tkinter', 'turtledemo', 'tcl', 'tcl86t.dll', 'tk86t.dll', '_tkinter.pyd']
TRIM_QT = [
    '*Qt6Quick*',
    '*Qt6Qml*',
    '*Qt6Labs*',
    '*Qt6Lottie*',
    '*Qt6Designer*',
    '*Qt6Help*',
    '*Qt6Test*',
    '*Qt6Sql*',
    '*Qt6UiTools*',
    'QtQml*',
    'QtQuick*',
    'QtDesigner*',
    'QtHelp*',
    'QtTest*',
    'QtSql*',
    'QtUiTools*',
    '*pyside6qml*',
    '*.pyi',
    '*.exe',
    'opengl32sw.dll',
    'qml',
    'metatypes',
    'typesystems',
    'glue',
    'include',
    'doc',
    'translations',
    'scripts',
    'designer',
    'qmltooling',
    'sqldrivers',
]
CSC = (
    Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
)


def step(text):
    print(f'\n== {text}', flush=True)


def version():
    text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


def fetch(name, digest):
    """The runtime archive, downloaded once into build/cache and checked."""
    target = BUILD / 'cache' / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {name}')
        partial = target.with_suffix('.part')
        with (
            urllib.request.urlopen(RELEASE + name.replace('+', '%2B'), timeout=60) as response,
            partial.open('wb') as out,
        ):
            shutil.copyfileobj(response, out, 1 << 20)
        partial.replace(target)
    found = hashlib.sha256(target.read_bytes()).hexdigest()
    if found != digest:
        target.unlink()
        raise SystemExit(f'{name} does not match its published SHA-256; it was deleted. Run the build again.')
    return target


def python_in(app, platform):
    return app / 'runtime' / ('python.exe' if platform == 'windows' else 'bin/python3')


def site_packages(app, platform):
    return (
        app / 'runtime' / ('Lib/site-packages' if platform == 'windows' else 'lib/python3.12/site-packages')
    )


def run(args, **options):
    environment = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    for name in ('PYTHONHOME', 'PYTHONPATH'):
        environment.pop(name, None)
    subprocess.run([str(arg) for arg in args], check=True, env=environment, **options)


def unpack(archive, app):
    with tarfile.open(archive) as tar:
        options = dict(filter='data') if hasattr(tarfile, 'data_filter') else {}
        tar.extractall(app, **options)
    (app / 'python').rename(app / 'runtime')


def copy_content(app):
    for item in CONTENT:
        source, target = ROOT / item, app / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=SKIP)
        else:
            shutil.copy2(source, target)


def link_backend(app, platform):
    """A .pth file puts backend/ on the bundled Python's path; relative, so the folder can move."""
    packages = site_packages(app, platform)
    relative = os.path.relpath(app / 'backend', packages)
    (packages / 'image-studio.pth').write_text(relative.replace('\\', '/') + '\n', encoding='utf-8')


def windows_launcher(app, number):
    if not CSC.exists():
        raise SystemExit(f'The C# compiler that comes with Windows was not found at {CSC}.')
    numeric = '.'.join((re.findall(r'\d+', number) + ['0'] * 4)[:4])
    info = BUILD / 'launcher-version.cs'
    info.write_text(
        'using System.Reflection;\n'
        '[assembly: AssemblyTitle("Image Studio")]\n'
        '[assembly: AssemblyProduct("Image Studio")]\n'
        f'[assembly: AssemblyVersion("{numeric}")]\n'
        f'[assembly: AssemblyFileVersion("{numeric}")]\n'
        f'[assembly: AssemblyInformationalVersion("{number}")]\n',
        encoding='utf-8',
    )
    run(
        [
            CSC,
            '/nologo',
            '/optimize',
            '/target:winexe',
            f'/out:{app / "Image Studio.exe"}',
            f'/win32icon:{app / "image-studio.ico"}',
            '/reference:System.Windows.Forms.dll',
            PACKAGING / 'windows' / 'launcher.cs',
            info,
        ]
    )


def linux_launcher(app):
    for name in ('image-studio', 'install.sh'):
        target = app / name
        shutil.copy2(PACKAGING / 'linux' / name, target)
        target.write_bytes(target.read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(0o755)


def remove(folder, patterns):
    for pattern in patterns:
        for path in sorted(folder.rglob(pattern), reverse=True):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()


def trim(app, platform):
    runtime = app / 'runtime'
    before = folder_size(runtime)
    remove(runtime, TRIM_RUNTIME)
    remove(
        runtime / ('DLLs' if platform == 'windows' else 'lib/python3.12/lib-dynload'), ['_test*']
    )  # CPython's
    remove(site_packages(app, platform) / 'PySide6', TRIM_QT)
    print(f'Removed {(before - folder_size(runtime)) / 1e6:.0f} MB of unused files.')


def smoke_test(app, platform):
    """The bundled Python finds the studio, knows it is installed, and builds the whole window."""
    check = (
        'import json, PySide6; from image_studio.desktop.app import build; from image_studio.core import paths; '
        'app, window = build(); window.show(); app.processEvents(); '
        'print(json.dumps(dict(installed=paths.INSTALLED, root=str(paths.ROOT), qt=PySide6.__version__)))'
    )
    result = subprocess.run(
        [str(python_in(app, platform)), '-c', check],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1'),
    )
    if result.returncode:
        raise SystemExit('The built app does not start:\n' + result.stderr)
    found = json.loads(result.stdout.strip().splitlines()[-1])
    if not found['installed'] or Path(found['root']).resolve() != app.resolve():
        raise SystemExit(f'The built app looks for its files in the wrong place: {found}')
    print(f'The app loads (Qt {found["qt"]}).')


def inno_compiler():
    candidates = [shutil.which('ISCC')]
    for base in (
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('ProgramFiles'),
        os.environ.get('LOCALAPPDATA'),
    ):
        if base:
            candidates += [
                Path(base) / 'Inno Setup 6' / 'ISCC.exe',
                Path(base) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe',
            ]
    return next((Path(path) for path in candidates if path and Path(path).is_file()), None)


def folder_size(folder):
    return sum(file.stat().st_size for file in folder.rglob('*') if file.is_file())


def build(platform, installer):
    number = version()
    name = 'Image Studio' if platform == 'windows' else 'image-studio'
    app = BUILD / platform / name
    step(f'Image Studio {number} for {platform.title()}, in {app}')
    if app.exists():
        shutil.rmtree(app)
    app.mkdir(parents=True)
    archive = fetch(*RUNTIMES[platform])

    step('Unpacking Python')
    unpack(archive, app)
    python = python_in(app, platform)

    step("Installing the window's libraries")
    run(
        [
            python,
            '-m',
            'pip',
            'install',
            '--disable-pip-version-check',
            '--no-warn-script-location',
            '--no-cache-dir',
            '-r',
            PACKAGING / 'requirements-app.txt',
        ]
    )

    trim(app, platform)

    step('Copying the studio')
    copy_content(app)
    link_backend(app, platform)
    (app / 'build.json').write_text(
        json.dumps(
            dict(
                version=number,
                platform=platform,
                built=time.strftime('%Y-%m-%d %H:%M:%S'),
                python=re.search(r'cpython-([\d.]+)\+', archive.name).group(1),
            ),
            indent=2,
        ),
        encoding='utf-8',
    )
    run([python, '-m', 'compileall', '-q', '-j', '0', app / 'backend'])

    step('Icon and launcher')
    run([python, PACKAGING / 'make_icon.py', app])
    if platform == 'windows':
        windows_launcher(app, number)
    else:
        linux_launcher(app)
    smoke_test(app, platform)
    print(f'App folder: {folder_size(app) / 1e6:.0f} MB')

    DIST.mkdir(exist_ok=True)
    if platform == 'linux':
        step('Packing')
        target = DIST / f'image-studio-{number}-linux-x86_64.tar.gz'
        with tarfile.open(target, 'w:gz') as tar:
            tar.add(app, arcname=name)
        print(f'Done: {target} ({target.stat().st_size / 1e6:.0f} MB)')
        return
    if not installer:
        print(f'Done: {app} (run "Image Studio.exe" there)')
        return
    step('Installer')
    compiler = inno_compiler()
    if compiler is None:
        raise SystemExit(
            'Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php '
            '(or: winget install JRSoftware.InnoSetup), then build again. The app folder is ready '
            f'in {app}.'
        )
    run(
        [
            compiler,
            '/Q',
            f'/DAppVersion={number}',
            f'/DSourceDir={app}',
            f'/DOutputDir={DIST}',
            PACKAGING / 'windows' / 'image-studio.iss',
        ]
    )
    target = DIST / f'ImageStudio-{number}-Setup.exe'
    print(f'Done: {target} ({target.stat().st_size / 1e6:.0f} MB)')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--no-installer', action='store_true', help='Windows: stop after the app folder')
    args = parser.parse_args()
    platforms = {'win32': 'windows', 'linux': 'linux'}
    if sys.platform not in platforms:
        raise SystemExit(
            'Build on Windows or Linux (each builds its own; Python packages differ per system).'
        )
    build(platforms[sys.platform], not args.no_installer)


if __name__ == '__main__':
    main()

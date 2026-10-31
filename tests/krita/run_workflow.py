import json
import argparse
import os
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(
    description='Run the project workflow in an installed portable Krita, without a running user session.'
)
parser.add_argument('--krita', type=Path, default=root / 'build/test-tools/krita-x64-6.0.4')
portable = parser.parse_args().krita.resolve()
if not (portable / 'bin/krita.exe').is_file():
    raise SystemExit('Pass --krita with the path to an extracted official portable Krita folder.')
profile = root / 'build/krita-gui-profile'
output = root / 'build/krita-project-lab'
output.mkdir(exist_ok=True)
plugin = profile / 'pykrita/studio_project_test'
plugin.mkdir(parents=True, exist_ok=True)
config = dict(plugin=str(root / 'integrations/krita-plugin/ai_prompt'), out=str(output))
shutil.copy2(root / 'tests/krita/project_workflow.py', plugin / 'lab.py')
(plugin / '__init__.py').write_text(
    'import json\nfrom krita import Krita, Extension\nfrom PyQt6.QtCore import QTimer\nfrom PyQt6.QtWidgets import QApplication\n'
    'from . import lab\n'
    'class Test(Extension):\n'
    '    def setup(self):\n'
    '        QTimer.singleShot(5000, self.run)\n'
    '    def createActions(self, window): pass\n'
    '    def run(self):\n'
    f'        lab.main(json.loads({json.dumps(config)!r}))\n'
    '        QApplication.instance().quit()\n'
    'Krita.instance().addExtension(Test(Krita.instance()))\n',
    encoding='utf-8',
)
(profile / 'pykrita/studio_project_test.desktop').write_text(
    '[Desktop Entry]\nType=Service\nServiceTypes=Krita/PythonPlugin\nX-KDE-Library=studio_project_test\n'
    'X-Python-2-Compatible=false\nName=Isolated project test\nComment=Temporary project lifecycle test\n',
    encoding='utf-8',
)
shutil.copytree(plugin, portable / 'share/krita/pykrita/studio_project_test', dirs_exist_ok=True)
local = Path(os.environ['LOCALAPPDATA'])
settings = [local / 'kritarc', local / 'kritadisplayrc']
backups = {path: path.read_bytes() if path.exists() else None for path in settings}
check = subprocess.run(
    [
        'powershell',
        '-NoProfile',
        '-Command',
        'if (Get-Process krita -ErrorAction SilentlyContinue) { exit 1 }',
    ],
    capture_output=True,
)
if check.returncode:
    raise SystemExit('A user Krita session is open; do not change its settings for testing.')
try:
    (output / 'gui-report.json').unlink(missing_ok=True)
    settings[0].write_text('[python]\nenable_studio_project_test=true\n', encoding='utf-8')
    environment = dict(
        os.environ,
        PYTHONHOME=str(portable / 'python'),
        QT_QPA_PLATFORM='windows',
        QT_FORCE_STDERR_LOGGING='1',
        KRITA_PLUGIN_PATH=str(portable / 'lib'),
    )
    environment['PYTHONPATH'] = str(profile / 'pykrita')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen(
        [str(portable / 'bin/krita.exe'), '--nosplash', '--resource-location', str(profile)],
        cwd=portable / 'bin',
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=startup,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
    (output / 'gui.log').write_bytes(stdout + stderr)
    report = output / 'gui-report.json'
    print(
        report.read_text(encoding='utf-8')
        if report.exists()
        else (stdout + stderr).decode(errors='replace')[-5000:]
    )
    if not report.exists() or not json.loads(report.read_text(encoding='utf-8')).get('ok'):
        raise SystemExit(1)
finally:
    for path, contents in backups.items():
        if contents is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(contents)

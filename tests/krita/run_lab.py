"""Run Krita lab cases (see lab.py) in a headless Krita and print the report.

    python tests/krita/run_lab.py job.json

The job file needs "out" and "cases"; "plugin" defaults to this project's Krita plugin."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from image_studio.core.catalog import KRITA  # noqa: E402


def run(job, timeout=600):
    out = Path(job['out'])
    out.mkdir(parents=True, exist_ok=True)
    job = dict(job, plugin=job.get('plugin') or str(ROOT / 'integrations' / 'krita-plugin'))
    job_file = out / 'job.json'
    job_file.write_text(json.dumps(job, indent=1), encoding='utf-8')
    (out / 'report.json').unlink(missing_ok=True)
    # kritarunner imports scripts from Krita's own plugin folder.
    shutil.copy2(Path(__file__).with_name('lab.py'), KRITA.parents[1] / 'share' / 'krita' / 'pykrita' / 'studio_lab.py')
    env = dict(os.environ, PYTHONHOME=str(KRITA.parents[1] / 'python'))
    env.pop('PYTHONPATH', None)
    subprocess.run([str(KRITA.with_name('kritarunner.exe')), '-s', 'studio_lab', '-f', 'main', str(job_file)],
                   cwd=str(KRITA.parent), env=env, timeout=timeout, capture_output=True)
    report = out / 'report.json'
    if not report.exists():
        raise RuntimeError('Krita did not write a report; see kritarunner output.')
    return json.loads(report.read_text(encoding='utf-8'))


if __name__ == '__main__':
    for entry in run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))):
        print(json.dumps(entry, indent=1))

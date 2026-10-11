"""Start or stop only this project's local image app."""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
import psutil

from image_studio.core.paths import ROOT, WORK, FRONTEND

PID_FILE = WORK / 'image-studio-process.json'
URL = 'http://127.0.0.1:7860'


def running_process():
    try:
        saved = json.loads(PID_FILE.read_text())
        process = psutil.Process(saved['pid'])
        if abs(process.create_time() - saved['created']) > 0.1:
            return None
        if 'image_studio' not in process.cmdline() and str(ROOT / 'app.py') not in process.cmdline():
            return None
        return process
    except (OSError, ValueError, KeyError, psutil.Error):
        return None


def start_krita():
    """Start Krita with the latest AI panel (installed while Krita is closed)."""
    from image_studio.core.catalog import krita_executable

    krita = krita_executable()
    if krita is None:
        print('Krita is not installed. Get it free from krita.org.')
        return
    if any(
        (process.info.get('name') or '').lower() in ('krita.exe', 'krita')
        for process in psutil.process_iter(['name'])
    ):
        print('Krita is already open.')
        return
    from image_studio.core.processes import launch_detached
    from image_studio.integrations import install_krita_plugin

    install_krita_plugin.main()
    launch_detached([str(krita)], cwd=str(krita.parent))
    print('Starting Krita...')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--krita', action='store_true', help='also start Krita with the AI panel')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    existing = running_process()
    if args.stop:
        if existing:
            from image_studio.core.processes import own_family

            children = own_family(existing)[1:]  # Krita and PhotoCraft stay open
            for child in children:
                child.terminate()
            existing.terminate()
            _, alive = psutil.wait_procs([existing, *children], timeout=20)
            for process in alive:
                process.kill()
            print('Image Studio stopped. GPU memory released.')
        else:
            print('Image Studio is not running.')
        return
    if not existing:
        if not (FRONTEND / 'index.html').exists():
            raise RuntimeError('Build the React frontend first: cd frontend, npm ci, then npm run build.')
        with (WORK / 'image-studio.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen(
                [sys.executable, '-m', 'image_studio', '--no-browser'],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        existing = psutil.Process(child.pid)
        PID_FILE.write_text(json.dumps(dict(pid=child.pid, created=existing.create_time())))
    for _ in range(90):
        if not existing.is_running():
            raise RuntimeError(f'App stopped during startup. See {WORK / "image-studio.log"}')
        try:
            with urllib.request.urlopen(URL + '/api/health', timeout=2) as response:
                config = json.load(response)
            if config.get('title') != 'Local Image Studio':
                raise RuntimeError('Port 7860 is being used by another app.')
            if args.krita:
                start_krita()
            if not args.no_browser:
                webbrowser.open(URL)
            print(f'Image Studio is ready: {URL}')
            return
        except (OSError, ValueError):
            time.sleep(1)
    raise RuntimeError(f'App startup timed out. See {WORK / "image-studio.log"}')


if __name__ == '__main__':
    main()

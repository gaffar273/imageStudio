import sys
from pathlib import Path

# Without a console (pythonw, as the installed launcher runs it) keep what goes wrong in a log.
if sys.stderr is None or Path(sys.executable).stem.lower() == 'pythonw':
    from image_studio.core import paths

    paths.LOGS.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(paths.LOGS / 'app.log', 'w', encoding='utf-8', buffering=1)

from image_studio.desktop.app import main

main()

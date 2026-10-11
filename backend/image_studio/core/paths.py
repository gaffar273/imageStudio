"""Stable paths, independent of the shell's working directory."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(os.environ.get('IMAGE_STUDIO_WORK', ROOT.parent.parent / 'work')).resolve()
IMAGES = ROOT / 'images'
FRONTEND = ROOT / 'frontend' / 'dist'
CACHE = WORK / 'studio-cache'

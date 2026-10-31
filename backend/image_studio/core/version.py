"""The app version, shared by the desktop window and engine without importing Qt."""

import json
import re

from image_studio.core import paths


def current(source_label=False):
    try:
        value = json.loads(paths.BUILD_FILE.read_text(encoding='utf-8'))['version']
        if isinstance(value, str):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        text = (paths.ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        value = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)
        return value + (' (source)' if source_label else '')
    except (OSError, AttributeError):
        return 'unknown'

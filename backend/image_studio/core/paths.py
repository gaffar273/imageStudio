"""Where the studio keeps models and pictures, on any Windows or Linux machine.

Each folder comes from, in order: an environment variable, the user's settings file
(written by the desktop app), then a default. A source checkout that sits next to an
existing ../../work folder keeps using it and its images/ folder, so older setups
need no migration.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / 'frontend' / 'dist'


def config_dir():
    """Per-user settings: %APPDATA%\\Image Studio or ~/.config/image-studio."""
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'Image Studio'
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'image-studio'


def data_dir():
    """Per-user data (models, caches, logs): %LOCALAPPDATA%\\Image Studio or ~/.local/share/image-studio."""
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Image Studio'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'image-studio'


SETTINGS_FILE = config_dir() / 'settings.json'


def load_settings():
    try:
        values = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        return values if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    """Merge values into the settings file; None removes a key."""
    settings = load_settings()
    settings.update(values)
    settings = {key: value for key, value in settings.items() if value is not None}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    temporary.replace(SETTINGS_FILE)
    return settings


def default_models_dir():
    legacy = ROOT.parent.parent / 'work'
    return legacy.resolve() if legacy.is_dir() else data_dir() / 'models'


def default_library_dir():
    legacy = ROOT / 'images'
    if legacy.is_dir():
        return legacy
    pictures = Path.home() / 'Pictures'
    return (pictures if pictures.is_dir() else data_dir()) / 'Image Studio'


def chosen(variable, key, default):
    value = os.environ.get(variable) or load_settings().get(key)
    return Path(value).expanduser().resolve() if value else default


WORK = chosen('IMAGE_STUDIO_WORK', 'models_dir', default_models_dir())
IMAGES = chosen('IMAGE_STUDIO_LIBRARY', 'library_dir', default_library_dir())
CACHE = WORK / 'studio-cache'
LOGS = data_dir() / 'logs'

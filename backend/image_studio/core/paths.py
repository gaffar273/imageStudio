"""Where the studio keeps models and pictures, on any Windows or Linux machine.

Each folder comes from, in order: an environment variable, the user's settings file
(written by the desktop app), then a default. A source checkout that sits next to an
existing ../../work folder keeps using it and its images/ folder, so older setups
need no migration. An installed copy (packaging/build.py writes build.json next to its
backend/ folder) never looks for those.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / 'frontend' / 'dist'
BUILD_FILE = ROOT / 'build.json'
INSTALLED = BUILD_FILE.is_file()


def package_family():
    """The Microsoft Store package this process runs in (its family name), or None outside one.

    Processes the app starts (the engine, its tools) run in the same package. The package
    folder is read-only and moves with every update; the manifest turns off the AppData
    redirection (packaging/windows/AppxManifest.xml), so the folders below are the real ones."""
    if sys.platform != 'win32':
        return None
    import ctypes

    length = ctypes.c_uint32(0)
    get = ctypes.windll.kernel32.GetCurrentPackageFamilyName
    if get(ctypes.byref(length), None) != 122:  # ERROR_INSUFFICIENT_BUFFER; 15700 means no package
        return None
    name = ctypes.create_unicode_buffer(length.value)
    return name.value if get(ctypes.byref(length), name) == 0 else None


PACKAGE = package_family()


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
    return legacy.resolve() if legacy.is_dir() and not INSTALLED else data_dir() / 'models'


def default_library_dir():
    legacy = ROOT / 'images'
    if legacy.is_dir() and not INSTALLED:
        return legacy
    pictures = pictures_dir()
    return (pictures if pictures and pictures.is_dir() else data_dir()) / 'Image Studio'


def pictures_dir():
    """The user's Pictures folder where the system keeps it (often moved into OneDrive on Windows)."""
    if sys.platform == 'win32':
        import ctypes
        import uuid
        from ctypes import wintypes

        folder_id = uuid.UUID('{33E28130-4E1E-4676-835A-98395C3BC3BB}')  # FOLDERID_Pictures
        found = ctypes.c_wchar_p()
        shell = ctypes.windll.shell32
        shell.SHGetKnownFolderPath.argtypes = [
            ctypes.c_char_p,
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        try:
            if shell.SHGetKnownFolderPath(folder_id.bytes_le, 0, None, ctypes.byref(found)) == 0:
                return Path(found.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(found)
    else:
        try:  # what xdg-user-dirs set, e.g. XDG_PICTURES_DIR="$HOME/Bilder"
            text = (
                Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'user-dirs.dirs'
            ).read_text()
            for line in text.splitlines():
                if line.startswith('XDG_PICTURES_DIR='):
                    return Path(line.split('=', 1)[1].strip().strip('"').replace('$HOME', str(Path.home())))
        except OSError:
            pass
    return Path.home() / 'Pictures'


def chosen(variable, key, default):
    value = os.environ.get(variable) or load_settings().get(key)
    return Path(value).expanduser().resolve() if value else default


WORK = chosen('IMAGE_STUDIO_WORK', 'models_dir', default_models_dir())
IMAGES = chosen('IMAGE_STUDIO_LIBRARY', 'library_dir', default_library_dir())
CACHE = WORK / 'studio-cache'
LOGS = data_dir() / 'logs'
# The engine's own Python (PyTorch and the model libraries) in an installed copy, set up
# from Studio settings on first run (core/engine_env.py).
ENGINE_ENV = chosen('IMAGE_STUDIO_ENGINE_ENV', 'engine_dir', data_dir() / 'engine')

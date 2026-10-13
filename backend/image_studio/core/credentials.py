"""API keys for model providers, kept out of settings.json.

Keys live in credentials.json next to the settings file. On Windows each key is encrypted
with DPAPI for the signed-in user, so the file is useless on another account or machine.
Elsewhere the file is readable by its owner only (0600), as ssh and most CLIs do.
An environment variable named by the provider always wins over a stored key.
"""

import base64
import json
import os
import sys

from image_studio.core import paths

FILE_NAME = 'credentials.json'


def _file():
    return paths.config_dir() / FILE_NAME


def _blob(data):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    return Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), Blob, buffer


def _dpapi(data, encrypt):
    import ctypes

    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    source, Blob, _keep = _blob(data)
    result = Blob()
    call = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    # (data in, description, entropy, reserved, prompt, flags: no UI, data out)
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):
        raise OSError('Windows could not protect the key.' if encrypt else 'Windows could not read the key.')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(result.pbData)


def _seal(value):
    data = value.encode('utf-8')
    if sys.platform == 'win32':
        return 'dpapi:' + base64.b64encode(_dpapi(data, True)).decode('ascii')
    return 'plain:' + base64.b64encode(data).decode('ascii')


def _open(stored):
    kind, _, payload = str(stored).partition(':')
    data = base64.b64decode(payload)
    if kind == 'dpapi':
        return _dpapi(data, False).decode('utf-8')
    return data.decode('utf-8')


def _load():
    try:
        values = json.loads(_file().read_text(encoding='utf-8'))
        return values if isinstance(values, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(values):
    target = _file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(values, indent=2), encoding='utf-8')
    if sys.platform != 'win32':
        os.chmod(temporary, 0o600)
    temporary.replace(target)


def get(name, env=None):
    """The key for name: the environment variable first, then the stored key, else ''."""
    if env and os.environ.get(env):
        return os.environ[env]
    stored = _load().get(name)
    if not stored:
        return ''
    try:
        return _open(stored)
    except (OSError, ValueError):
        return ''  # sealed for another account or machine


def put(name, value):
    values = _load()
    if value:
        values[name] = _seal(value)
    else:
        values.pop(name, None)
    _save(values)


def delete(name):
    put(name, '')


def stored(name):
    """Whether a key is saved for name (not counting environment variables)."""
    return bool(_load().get(name))

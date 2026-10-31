"""Managed, autosaved Krita projects with original sources and portable backups."""

import io
import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from PIL import Image

from image_studio.core.paths import data_dir
from image_studio.integrations import bridge, photocraft_projects as sources
from image_studio.services import image_imports

ROOT = data_dir() / 'projects' / 'krita'
LOCK = threading.RLock()


def folder_for(ident):
    if not re.fullmatch('[a-f0-9]{32}', ident):
        raise ValueError('Invalid project ID.')
    return ROOT / ident


def save(data):
    folder = folder_for(data['id'])
    temporary = folder / 'project.json.tmp'
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(folder / 'project.json')


def load(ident):
    try:
        return json.loads((folder_for(ident) / 'project.json').read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError('Project not found.') from exc


def public(data):
    folder = folder_for(data['id'])
    native = folder / 'project.kra'
    saved_at = native.stat().st_mtime if native.exists() else None
    assets = [
        {**asset, 'thumbnail': f'/api/krita/projects/{data["id"]}/assets/{asset["id"]}/thumbnail'}
        for asset in data.get('assets', [])
    ]
    return {
        **data,
        'assets': assets,
        'updated': max(data['updated'], saved_at or 0),
        'saved_at': saved_at,
        'preview': f'/api/krita/projects/{data["id"]}/thumbnail?v={saved_at or 0}',
        'images': len(assets),
        'can_restore': bool(data.get('checkpoints')),
    }


def current(state):
    path = (state or {}).get('path')
    if not path:
        return None
    source = Path(path)
    if source.name != 'project.kra' or source.parent.parent.resolve() != ROOT.resolve():
        return None
    try:
        data = public(load(source.parent.name))
        data['saved'] = not state.get('modified', True)
        data['save_error'] = state.get('save_error')
        return data
    except (ValueError, OSError):
        return None


def recent():
    result = []
    for path in ROOT.glob('*/project.json'):
        try:
            data = public(load(path.parent.name))
            if data['saved_at']:
                result.append(data)
        except (ValueError, KeyError, OSError):
            continue
    return sorted(result, key=lambda row: row['updated'], reverse=True)


def require_connected():
    if not bridge.link.connected:
        raise ValueError('Open Krita to connect before opening a project.')
    if not bridge.link.capabilities.get('projects'):
        raise ValueError('Close Krita and reopen it from Image Studio to enable project saving.')


def send(kind, timeout=60, **payload):
    """Report success only after Krita confirms that its native save/close actually succeeded."""
    require_connected()
    command = bridge.link.send(kind, **payload)
    deadline = time.monotonic() + timeout
    with bridge.link.changed:
        while time.monotonic() < deadline:
            answer = next(
                (
                    event
                    for event in reversed(bridge.link.events)
                    if event.get('run') == command and event.get('kind') in {'done', 'failed'}
                ),
                None,
            )
            if answer is not None:
                if answer['kind'] == 'failed':
                    raise ValueError(answer.get('text') or 'Krita could not save the project.')
                return answer
            bridge.link.changed.wait(min(1, max(0, deadline - time.monotonic())))
    raise ValueError(
        'Krita has not confirmed this operation. The project has not been marked as saved; check Krita and retry.'
    )


def create(name, width=1600, height=1000, contents=None, filename=None, use_current=False):
    require_connected()
    if not name.strip():
        raise ValueError('Give the project a name.')
    with LOCK:
        ident = uuid.uuid4().hex
        folder = folder_for(ident)
        folder.mkdir(parents=True)
        data = dict(
            id=ident,
            name=name.strip()[:150],
            width=width,
            height=height,
            assets=[],
            created=time.time(),
            updated=time.time(),
            checkpoints=[],
        )
        source = None
        if contents is not None:
            if Path(filename or '').suffix.lower() == '.kra':
                validate_native(contents)
                source = folder / 'source.kra'
                source.write_bytes(contents)
            else:
                asset = sources.store_asset(folder, filename or 'image.png', contents)
                data['assets'].append(asset)
                data['width'], data['height'] = asset['width'], asset['height']
                source = folder / 'assets' / asset['file']
        save(data)
        answer = send(
            'project_new',
            project_id=ident,
            path=str(folder / 'project.kra'),
            source=str(source) if source else None,
            name=data['name'],
            width=data['width'],
            height=data['height'],
            use_current=use_current,
        )
        data['width'], data['height'] = (
            answer.get('width', data['width']),
            answer.get('height', data['height']),
        )
        save(data)
        return public(data)


def action(ident, action):
    with LOCK:
        data = load(ident)
        folder = folder_for(ident)
        path = folder / 'project.kra'
        if not path.is_file():
            raise ValueError('This project does not have a saved Krita document yet.')
        if action in {'open', 'save', 'close'}:
            send('project_' + action, project_id=ident, path=str(path), name=data['name'])
        elif action == 'clear':
            send('project_save', project_id=ident, path=str(path))
            history = folder / 'history'
            history.mkdir(exist_ok=True)
            checkpoint = uuid.uuid4().hex
            shutil.copy2(path, history / f'{checkpoint}.kra')
            data.setdefault('checkpoints', []).append(checkpoint)
            save(data)
            send('project_clear', project_id=ident, path=str(path), name=data['name'])
        elif action == 'restore':
            if not data.get('checkpoints'):
                raise ValueError('There is no earlier canvas to restore.')
            restore = folder / 'history' / f'{data["checkpoints"][-1]}.kra'
            send('project_save', project_id=ident, path=str(path))
            checkpoint = uuid.uuid4().hex
            shutil.copy2(path, folder / 'history' / f'{checkpoint}.kra')
            data['checkpoints'].append(checkpoint)
            save(data)
            send('project_restore', project_id=ident, path=str(path), name=data['name'], source=str(restore))
        else:
            raise ValueError('Unknown project action.')
        data['updated'] = time.time()
        save(data)
        return public(data)


def rename(ident, name):
    if not name.strip():
        raise ValueError('Give the project a name.')
    with LOCK:
        data = load(ident)
        data['name'], data['updated'] = name.strip()[:150], time.time()
        save(data)
        return public(data)


def import_assets(ident, files):
    if not 1 <= len(files) <= image_imports.MAX_FILES:
        raise ValueError('Choose between 1 and 16 images at a time.')
    with LOCK:
        data = load(ident)
        added = []
        folder = folder_for(ident)
        try:
            for name, contents in files:
                added.append(sources.store_asset(folder, name, contents))
            data['assets'] += added
            data['updated'] = time.time()
            save(data)
        except Exception:
            for asset in added:
                (folder / 'assets' / asset['file']).unlink(missing_ok=True)
                (folder / 'assets' / f'{asset["id"]}-thumb.png').unlink(missing_ok=True)
            raise
        return public(data)


def place_asset(ident, asset_id, fit=False, x=None, y=None, as_canvas=False):
    with LOCK:
        data = load(ident)
        asset = sources.asset_for(data, asset_id)
        folder = folder_for(ident)
        path, source = folder / 'project.kra', folder / 'assets' / asset['file']
        if as_canvas:
            send('project_save', project_id=ident, path=str(path))
            history = folder / 'history'
            history.mkdir(exist_ok=True)
            checkpoint = uuid.uuid4().hex
            shutil.copy2(path, history / f'{checkpoint}.kra')
            data.setdefault('checkpoints', []).append(checkpoint)
            save(data)
        send(
            'project_canvas' if as_canvas else 'project_place',
            project_id=ident,
            path=str(path),
            name=data['name'],
            source=str(source),
            image_name=Path(asset['name']).stem,
            fit=fit,
            x=x,
            y=y,
        )
        return public(data)


def layer_action(ident, layer_id, operation, values=None):
    data = load(ident)
    if not re.fullmatch('[a-fA-F0-9-]{36}', layer_id):
        raise ValueError('Invalid layer ID.')
    send(
        'project_layer',
        project_id=ident,
        path=str(folder_for(ident) / 'project.kra'),
        layer_id=layer_id,
        operation=operation,
        values=values or {},
    )
    return public(data)


def layer_preview(ident, layer_id, version, part):
    if part not in {'above', 'image', 'below'} or not re.fullmatch('[a-fA-F0-9-]{36}', layer_id):
        raise ValueError('Invalid layer preview.')
    with LOCK:
        folder = folder_for(ident)
        directory = folder / 'previews'
        directory.mkdir(exist_ok=True)
        prefix = directory / f'{version}-{layer_id}'
        target = Path(str(prefix) + f'-{part}.png')
        if not target.is_file():
            send(
                'project_layer_preview',
                project_id=ident,
                path=str(folder / 'project.kra'),
                layer_id=layer_id,
                prefix=str(prefix),
            )
        return target


def thumbnail(ident):
    folder = folder_for(ident)
    with zipfile.ZipFile(folder / 'project.kra') as source:
        name = 'preview.png' if 'preview.png' in source.namelist() else 'mergedimage.png'
        with Image.open(io.BytesIO(source.read(name))) as image:
            image.thumbnail((480, 320))
            output = io.BytesIO()
            image.save(output, 'PNG')
            return output.getvalue()


def validate_native(contents):
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as source:
            if 'maindoc.xml' not in source.namelist() or source.read('mimetype') != b'application/x-krita':
                raise ValueError('Choose a native Krita project file (.kra).')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError('This is not a valid Krita project file.') from exc


def save_for_export(ident):
    """Save through Krita when connected; reject a stale export while another project is active."""
    if bridge.link.connected:
        action(ident, 'save')
    elif not (folder_for(ident) / 'project.kra').is_file():
        raise ValueError('Connect Krita and save the project first.')


def archive(ident):
    with LOCK:
        save_for_export(ident)
        data = load(ident)
        folder = folder_for(ident)
        target = folder / f'project-{uuid.uuid4().hex}.istudio'
        files = ['project.kra']
        files += [f'assets/{a["file"]}' for a in data['assets']]
        files += [f'assets/{a["id"]}-thumb.png' for a in data['assets']]
        files += [f'history/{key}.kra' for key in data.get('checkpoints', [])]
        temporary = target.with_suffix('.tmp')
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as output:
                output.writestr(
                    'project.json',
                    json.dumps(dict(format=sources.FORMAT, version=1, editor='krita', project=data)),
                )
                for name in files:
                    output.write(folder / name, name)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def import_archive(contents):
    require_connected()
    if not contents or len(contents) > sources.MAX_PROJECT_BYTES:
        raise ValueError('Choose a project under 500 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as incoming:
            entries = incoming.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > 20000
                or len(names) != len(set(names))
                or sum(e.file_size for e in entries) > sources.MAX_UNPACKED_BYTES
            ):
                raise ValueError('This project is too large or has duplicate files.')
            if incoming.getinfo('project.json').file_size > 5_000_000:
                raise ValueError('Invalid project metadata.')
            manifest = json.loads(incoming.read('project.json'))
            if (
                manifest.get('format') != sources.FORMAT
                or manifest.get('version') != 1
                or manifest.get('editor') != 'krita'
            ):
                raise ValueError('Open PhotoCraft projects from the PhotoCraft projects screen.')
            data = manifest['project']
            expected = {'project.json', 'project.kra'}
            for asset in data.get('assets', []):
                aid, filename = asset['id'], asset['file']
                if not re.fullmatch('[a-f0-9]{32}', aid) or not re.fullmatch(aid + r'\.[a-z0-9]+', filename):
                    raise ValueError('Invalid project image.')
                expected.update({f'assets/{filename}', f'assets/{aid}-thumb.png'})
            for checkpoint in data.get('checkpoints', []):
                if not re.fullmatch('[a-f0-9]{32}', checkpoint):
                    raise ValueError('Invalid project history.')
                expected.add(f'history/{checkpoint}.kra')
            if set(names) != expected:
                raise ValueError('The project contains missing or unexpected files.')
            data['id'], data['updated'] = uuid.uuid4().hex, time.time()
            folder = folder_for(data['id'])
            folder.mkdir(parents=True)
            for name in expected - {'project.json'}:
                path = folder / name
                path.parent.mkdir(exist_ok=True)
                with incoming.open(name) as source, path.open('wb') as output:
                    shutil.copyfileobj(source, output)
            save(data)
        return action(data['id'], 'open')
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('This project file is damaged or unsupported.') from exc

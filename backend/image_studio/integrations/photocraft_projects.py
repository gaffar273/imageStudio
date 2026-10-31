"""Durable PhotoCraft projects, source images, and portable project files."""

import copy
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from PIL import Image

from image_studio.services import image_imports

FORMAT = 'image-studio-project'
MAX_PROJECT_BYTES = 500_000_000
MAX_UNPACKED_BYTES = 2_000_000_000
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}


def workspace():
    from . import photocraft_workspace

    return photocraft_workspace


def migrate(root, legacy, ident):
    """Copy an older cache workspace on first open, keeping the previous copy intact."""
    target, source = root / ident, legacy / ident
    if not target.exists() and source.is_dir() and root != legacy:
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / f'.migrate-{uuid.uuid4().hex}'
        try:
            shutil.copytree(source, temporary)
            temporary.rename(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def store_asset(folder, name, contents, thumbnail=None, background=False):
    """Keep the uploaded original; thumbnails never replace source pixels."""
    ident = uuid.uuid4().hex
    directory = folder / 'assets'
    directory.mkdir(exist_ok=True)
    if thumbnail is None:
        image = image_imports.decode_layer(contents)
    else:
        with Image.open(thumbnail) as preview:
            image = preview.convert('RGBA')
    try:
        width, height = image.size
        suffix = Path(name).suffix.lower()
        if not background and suffix not in IMAGE_SUFFIXES:
            suffix = '.png'
            buffer = io.BytesIO()
            image.save(buffer, 'PNG')
            contents = buffer.getvalue()
        source = f'{ident}{suffix}'
        image.thumbnail((240, 160))
        image.save(directory / f'{ident}-thumb.png')
        (directory / source).write_bytes(contents)
    finally:
        image.close()
    return dict(
        id=ident,
        name=Path(name).name[:200],
        file=source,
        width=width,
        height=height,
        created=time.time(),
        background=background,
    )


def public_assets(data):
    return [
        {**asset, 'thumbnail': f'/api/photocraft/workspaces/{data["id"]}/assets/{asset["id"]}/thumbnail'}
        for asset in data.get('assets', [])
    ]


def asset_for(data, ident):
    if not re.fullmatch('[a-f0-9]{32}', ident):
        raise ValueError('Invalid image ID.')
    asset = next((item for item in data.get('assets', []) if item['id'] == ident), None)
    if asset is None:
        raise ValueError('This image is not in the project.')
    return asset


def import_assets(ident, expected, files, cancelled=None):
    ws = workspace()
    with ws.LOCK:
        data = ws.load(ident)
        ws.require_revision(data, expected)
        if not 1 <= len(files) <= image_imports.MAX_FILES:
            raise ValueError('Choose between 1 and 16 images at a time.')
        folder, added = ws.folder_for(ident), []
        try:
            for name, contents in files:
                ws.check_cancel(cancelled)
                added.append(store_asset(folder, name, contents))
            ws.check_cancel(cancelled)
            data['assets'] = data.get('assets', []) + added
            data['updated'] = time.time()
            ws.save(data)
        except Exception:
            for asset in added:
                (folder / 'assets' / asset['file']).unlink(missing_ok=True)
                (folder / 'assets' / f'{asset["id"]}-thumb.png').unlink(missing_ok=True)
            raise
        return ws.public(data)


def rename(ident, name):
    name = name.strip()
    if not name or len(name) > 150:
        raise ValueError('Give the project a name between 1 and 150 characters.')
    ws = workspace()
    with ws.LOCK:
        data = ws.load(ident)
        data['name'], data['updated'] = name, time.time()
        ws.save(data)
        return ws.public(data)


def clear_canvas(ident, expected, cancelled=None, asset_id=None):
    """A fresh canvas inside the same project; source images and undo history remain available."""
    ws = workspace()
    with ws.LOCK:
        data = ws.load(ident)
        ws.require_revision(data, expected)
        folder, state = ws.folder_for(ident), ws.current(data)['state']
        with ws.Engine(folder, cancelled) as engine:
            if asset_id is None:
                engine.call(
                    'doc.new',
                    dict(width=state['width'], height=state['height'], name=data['name'], background='white'),
                )
                title = 'Clear canvas'
            else:
                asset = asset_for(data, asset_id)
                engine.call('doc.open', {'path': str(folder / 'assets' / asset['file'])})
                title = f'Use {asset["name"]} as canvas'
            revision = ws.snapshot(engine, folder, title, [])
        try:
            ws.check_cancel(cancelled)
        except ws.Cancelled:
            ws._discard(folder, revision)
            raise
        return ws._commit(data, data['cursor'] + 1, [revision], None)


def place_asset(ident, expected, asset_id, fit=False, x=None, y=None, cancelled=None):
    ws = workspace()
    with ws.LOCK:
        data = ws.load(ident)
        ws.require_revision(data, expected)
        asset = asset_for(data, asset_id)
        source = ws.folder_for(ident) / 'assets' / asset['file']
        return ws.add_layers(
            ident,
            expected,
            [(asset['name'], source.read_bytes())],
            cancelled,
            fit=fit,
            center=None if x is None or y is None else [x, y],
            record_sources=False,
        )


def archive(ident, expected):
    ws = workspace()
    with ws.LOCK:
        data = copy.deepcopy(ws.load(ident))
        ws.require_revision(data, expected)
        data.pop('desktop', None)
        folder = ws.folder_for(ident)
        target = folder / f'project-{uuid.uuid4().hex}.istudio'
        temporary = target.with_suffix('.tmp')
        paths = []
        for revision in data['history']:
            paths += [f'{revision["id"]}.pcraft', f'{revision["id"]}.png']
            detail = f'{revision["id"]}-detail.png'
            if (folder / detail).is_file():
                paths.append(detail)
        for asset in data.get('assets', []):
            paths += [f'assets/{asset["file"]}', f'assets/{asset["id"]}-thumb.png']
        paths += [path.name for path in folder.glob('plan-*.json')]
        try:
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr('project.json', json.dumps(dict(format=FORMAT, version=1, project=data)))
                for name in paths:
                    output.write(folder / name, name)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def import_archive(contents):
    """Restore into a new project so opening an older backup cannot overwrite newer work."""
    ws = workspace()
    if not contents or len(contents) > MAX_PROJECT_BYTES:
        raise ValueError('Choose an Image Studio project under 500 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as source:
            entries = source.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > 20000
                or len(set(names)) != len(names)
                or sum(e.file_size for e in entries) > MAX_UNPACKED_BYTES
            ):
                raise ValueError('This project archive is too large or has duplicate files.')
            if 'project.json' not in names or source.getinfo('project.json').file_size > 5_000_000:
                raise ValueError('This is not an Image Studio project.')
            manifest = json.loads(source.read('project.json'))
            if manifest.get('format') != FORMAT or manifest.get('version') != 1:
                raise ValueError('This project format is not supported.')
            if manifest.get('editor', 'photocraft') != 'photocraft':
                raise ValueError('Open this project from the Krita projects screen.')
            data = manifest['project']
            history, assets = data['history'], data.get('assets', [])
            if (
                not isinstance(history, list)
                or not 1 <= len(history) <= 5000
                or not 0 <= data['cursor'] < len(history)
            ):
                raise ValueError('The project history is invalid.')
            expected = {'project.json'}
            for revision in history:
                rid, state = revision['id'], revision['state']
                if (
                    not re.fullmatch('[a-f0-9]{32}', rid)
                    or not 1 <= state['width'] <= 8192
                    or not 1 <= state['height'] <= 8192
                ):
                    raise ValueError('The project contains an invalid revision.')
                expected.update({f'{rid}.pcraft', f'{rid}.png'})
                if f'{rid}-detail.png' in names:
                    expected.add(f'{rid}-detail.png')
            if len({r['id'] for r in history}) != len(history):
                raise ValueError('The project history contains duplicate revisions.')
            for asset in assets:
                aid, filename = asset['id'], asset['file']
                if not re.fullmatch('[a-f0-9]{32}', aid) or not re.fullmatch(aid + r'\.[a-z0-9]+', filename):
                    raise ValueError('The project contains an invalid source image.')
                expected.update({f'assets/{filename}', f'assets/{aid}-thumb.png'})
            expected.update(name for name in names if re.fullmatch(r'plan-[a-f0-9]{32}\.json', name))
            if set(names) != expected:
                raise ValueError('The project contains missing or unexpected files.')
            data['id'], data['name'], data['updated'] = uuid.uuid4().hex, str(data['name'])[:150], time.time()
            data.pop('desktop', None)
            data['schema'], data['assets'] = 2, assets
            folder = ws.folder_for(data['id'])
            folder.mkdir(parents=True)
            try:
                for name in expected - {'project.json'}:
                    target = folder / name
                    target.parent.mkdir(exist_ok=True)
                    with source.open(name) as incoming, target.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                ws.save(data)
            except Exception:
                shutil.rmtree(folder)
                raise
            return ws.public(data)
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('This project file is damaged or is not an Image Studio project.') from exc

"""Saved-image metadata and constrained paths for the public API."""

import json
from pathlib import Path
from image_studio.core.paths import IMAGES
from image_studio.core.engine import json_safe


def image_path(name):
    if Path(name).name != name or '/' in name or '\\' in name or not name.lower().endswith('.png'):
        raise ValueError('Invalid image name.')
    path = (IMAGES / name).resolve()
    if path.parent != IMAGES.resolve() or not path.is_file():
        raise FileNotFoundError('Image not found.')
    return path


def item(path):
    try:
        metadata = json_safe(json.loads(path.with_suffix('.json').read_text(encoding='utf-8')))
    except (OSError, ValueError):
        metadata = {}
    return dict(
        name=path.name,
        url=f'/images/{path.name}',
        thumbnail=f'/api/library/{path.name}/thumbnail',
        created=path.stat().st_mtime,
        **{'metadata': metadata},
    )


def list_images(query=''):
    IMAGES.mkdir(parents=True, exist_ok=True)
    paths = sorted(IMAGES.glob('*.png'), key=lambda path: path.stat().st_mtime, reverse=True)
    items = [item(path) for path in paths]
    if query.strip():
        words = query.lower().split()
        items = [
            entry for entry in items if all(word in json.dumps(entry['metadata']).lower() for word in words)
        ]
    return items

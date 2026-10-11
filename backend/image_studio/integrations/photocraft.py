"""Local PhotoCraft edits through its CLI; originals never become output paths."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

from image_studio.core.paths import CACHE, IMAGES
from image_studio.services import agent


def executable():
    override = os.environ.get('IMAGE_STUDIO_PHOTOCRAFT_CLI')
    candidates = (
        [override]
        if override
        else [
            shutil.which('photocraft-cli'),
            str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PhotoCraft/photocraft-cli.exe'),
        ]
    )
    return next((Path(path) for path in candidates if path and Path(path).is_file()), None)


def available():
    return executable() is not None


def plan(prompt):
    """Only translate complete understood requests; never silently drop a clause."""
    text = re.sub(r'\s+', ' ', prompt.strip().lower()).rstrip('.!')
    prefix = 'layer.newAdjustmentLayer.'
    presets = {
        'professional polish': [
            ('curves', {'points': [[0, 0], [64, 58], [192, 201], [255, 255]]}),
            ('vibrance', {'vibrance': 16, 'saturation': 3}),
        ],
        'warm portrait': [
            ('photoFilter', {'filter': 'warming85', 'density': 14}),
            ('vibrance', {'vibrance': 10}),
        ],
        'cinematic teal and orange': [('colorLookup', {'lut': 'tealOrange'})],
        'soft faded film': [('colorLookup', {'lut': 'fadedFilm'})],
    }
    if text in presets:
        return [(prefix + name, params, text.title()) for name, params in presets[text]]
    steps = agent.quick_plan(prompt)
    if not steps:
        raise ValueError(
            'Try “professional polish”, “make it brighter and warmer”, or “make it grayscale”. '
            'Use AI content editing or the Krita canvas for other requests.'
        )
    commands = []
    for step in steps:
        op = step['op']
        amount = step.get('amount', 0)
        if op in ('brightness', 'contrast'):
            name, params = 'brightnessContrast', {op: max(-50, amount) if op == 'contrast' else amount}
        elif op == 'saturation':
            name, params = 'vibrance', {'saturation': amount}
        elif op == 'hue':
            name, params = 'hueSaturation', {'hue': step['degrees']}
        elif op == 'warmth':
            name, params = (
                'photoFilter',
                {'filter': 'warming85' if amount >= 0 else 'cooling80', 'density': abs(amount)},
            )
        elif op == 'tint':
            name, params = 'colorBalance', {'midtones': [0, -amount, 0]}
        elif op == 'black_and_white':
            name, params = 'blackWhite', {}
        elif op == 'sepia':
            name, params = 'photoFilter', {'filter': 'sepia', 'density': step['strength']}
        elif op == 'invert_colors':
            name, params = 'invert', {}
        elif op == 'posterize':
            name, params = 'posterize', {'levels': step['levels']}
        elif op == 'threshold':
            name, params = 'threshold', {'level': step['level']}
        else:
            raise ValueError(
                f'PhotoCraft text editing does not yet support “{op.replace("_", " ")}”. '
                'Use AI content editing or the Krita canvas for this request.'
            )
        commands.append((prefix + name, params, agent.summary(step)))
    if not commands:
        raise ValueError('Describe a light or color adjustment first.')
    return commands


def run_cli(args, cancelled=None, timeout=120):
    cli = executable()
    if cli is None:
        raise ValueError('PhotoCraft CLI was not found. Install PhotoCraft or choose AI content editing.')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = subprocess.Popen(
        [str(cli), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancelled is not None and cancelled.is_set():
                return None
            if time.monotonic() >= deadline:
                raise RuntimeError('PhotoCraft took too long to finish this edit.')
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError(
                'PhotoCraft could not complete the edit: ' + stderr.decode('utf-8', errors='replace')[-1500:]
            )
        return stdout.decode('utf-8', errors='replace')
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def edit(image, prompt, commands, progress, cancelled, source_document=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='photocraft-', dir=CACHE) as folder:
        folder = Path(folder)
        source, document, preview = (folder / name for name in ('source.png', 'edit.psd', 'edit.png'))
        image.save(source)
        args = ['run', str(source_document or source)]
        for command, params, label in commands:
            args += [
                '--cmd',
                command,
                '--params',
                json.dumps(params),
                '--cmd',
                'layer.renameLayer',
                '--params',
                json.dumps({'name': label}),
            ]
        args += ['--out', str(document)]
        progress(0.15, desc='Applying editable PhotoCraft adjustment layers…')
        if run_cli(args, cancelled) is None:
            return None
        progress(0.7, desc='Rendering the PhotoCraft preview…')
        if run_cli(['convert', document, preview], cancelled) is None:
            return None
        with Image.open(preview) as check:
            check.load()
            if check.size != image.size:
                raise RuntimeError('PhotoCraft returned an unexpected image size.')
        if cancelled.is_set():
            return None
        target = IMAGES / f'photocraft_{uuid.uuid4().hex}.png'
        metadata = {
            'prompt': prompt,
            'model': 'PhotoCraft',
            'mode': 'edit',
            'width': image.width,
            'height': image.height,
            'total_seconds': round(time.monotonic() - started, 2),
            'adjustments': [label for _, _, label in commands],
            'layered_document': target.with_suffix('.psd').name,
        }
        shutil.copy2(document, target.with_suffix('.psd'))
        target.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        shutil.copy2(preview, target)
        return target


def open_document(path):
    cli = executable()
    desktop = cli.with_name('photocraft.exe' if os.name == 'nt' else 'photocraft') if cli else None
    if desktop is None or not desktop.is_file():
        raise ValueError('The PhotoCraft desktop application was not found.')
    subprocess.Popen([str(desktop), str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

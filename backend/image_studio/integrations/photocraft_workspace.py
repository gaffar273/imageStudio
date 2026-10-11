"""Registry-driven PhotoCraft workspace with isolated, atomic document revisions.

Requests are planned in the PhotoCraft edit language (photocraft_intents), compiled into exact
commands, applied in one headless transaction, then measured and reviewed. Native files are
retained, and failed batches never advance history.
"""

import functools
import json
import math
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from PIL import Image

from image_studio.core.paths import CACHE
from image_studio.integrations import (
    photocraft,
    photocraft_intents,
    photocraft_macros,
    photocraft_planner,
    photocraft_specs,
)
from image_studio.services import brain

ROOT = CACHE / 'photocraft-workspaces'
LOCK = threading.RLock()
EDIT_FAMILIES = {
    'edit',
    'select',
    'layer',
    'image',
    'paint',
    'tools',
    'filter',
    'gradient',
    'type',
    'shape',
    'path',
    'color',
    'brush',
    'channel',
    'pattern',
    'layerComp',
    'count',
    'measurementLog',
    'notes',
    'history',
    'style',
    'tool',
    'cloneSource',
    'slice',
    'timeline',
}
BLOCKED = {'edit.undo', 'edit.redo', 'edit.stepBackward', 'edit.stepForward'}


class Cancelled(RuntimeError):
    pass


class Engine:
    """One short-lived headless engine, with bounded reads and a private file root."""

    def __init__(self, folder, cancelled=None):
        cli = photocraft.executable()
        if not cli:
            raise ValueError('Install PhotoCraft with its command-line tool first.')
        self.cancelled = cancelled
        self.serial = 0
        self.replies = queue.Queue()
        self.process = subprocess.Popen(
            [
                str(cli),
                'serve',
                '--automation-read-root',
                str(folder),
                '--automation-write-root',
                str(folder),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

        def read():
            try:
                for line in self.process.stdout:
                    self.replies.put(json.loads(line))
            except (OSError, ValueError) as exc:
                self.replies.put(exc)
            finally:
                self.replies.put(RuntimeError('PhotoCraft closed its connection.'))

        threading.Thread(target=read, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.process.kill()
        self.process.wait(timeout=10)
        self.process.stdin.close()
        self.process.stdout.close()

    def call(self, method, params=None, timeout=180):
        check_cancel(self.cancelled)
        self.serial += 1
        payload = json.dumps({'id': self.serial, 'method': method, 'params': params or {}}, allow_nan=False)
        if len(payload.encode()) > 900_000:
            raise ValueError('This command is too large for PhotoCraft automation.')
        self.process.stdin.write((payload + '\n').encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            check_cancel(self.cancelled)
            try:
                reply = self.replies.get(timeout=0.15)
            except queue.Empty:
                continue
            if isinstance(reply, Exception):
                raise reply
            if reply.get('id') != self.serial:
                raise RuntimeError('PhotoCraft response did not match the command.')
            if not reply.get('ok'):
                raise ValueError(str(reply.get('error', 'PhotoCraft rejected the command.')))
            return reply.get('result')
        raise RuntimeError('PhotoCraft timed out; the current revision was preserved.')


def check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise Cancelled('Edit stopped. The previous revision is unchanged.')


def folder_for(workspace_id):
    if not re.fullmatch('[a-f0-9]{32}', workspace_id):
        raise ValueError('Invalid workspace ID.')
    return ROOT / workspace_id


def load(workspace_id):
    folder = folder_for(workspace_id)
    try:
        return json.loads((folder / 'workspace.json').read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError('Workspace not found.') from exc


def save(data):
    folder = folder_for(data['id'])
    temporary = folder / 'workspace.tmp'
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(folder / 'workspace.json')


def current(data):
    return data['history'][data['cursor']]


def public(data):
    revision = current(data)
    return {
        **data,
        'revision': revision['id'],
        'state': revision['state'],
        'preview': f'/api/photocraft/workspaces/{data["id"]}/preview/{revision["id"]}',
        'original': f'/api/photocraft/workspaces/{data["id"]}/preview/{data["history"][0]["id"]}',
        'can_undo': data['cursor'] > 0,
        'can_redo': data['cursor'] < len(data['history']) - 1,
    }


def recent():
    if not ROOT.exists():
        return []
    result = []
    for path in ROOT.glob('*/workspace.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            result.append({'id': data['id'], 'name': data['name'], 'updated': data['updated']})
        except (ValueError, KeyError, OSError):
            continue
    return sorted(result, key=lambda value: value['updated'], reverse=True)[:30]


def restriction(command):
    family = command.split('.')[0]
    if command in BLOCKED or family == 'history':
        return 'Use workspace Undo/Redo; native engine history is local to each transaction.'
    if family not in EDIT_FAMILIES:
        return 'Use the document controls or PhotoCraft desktop for this application-level command.'
    if re.search(
        r'(^|\.)(import|export|load|save|install|open|close|reset|replaceContents|editContents)(\.|$)',
        command,
        re.IGNORECASE,
    ):
        return 'This external-resource operation belongs in PhotoCraft desktop.'
    return ''


@functools.lru_cache(maxsize=1)
def registry():
    commands = json.loads(photocraft.run_cli(['commands', '--json']))
    return [
        {
            **command,
            'category': '.'.join(command['id'].split('.')[:2]),
            'runnable': not restriction(command['id']),
            'reason': restriction(command['id']),
            'fields': photocraft_specs.parse(command['params']),
        }
        for command in commands
    ]


def capabilities():
    commands = registry() if photocraft.available() else []
    return {
        'installed': photocraft.available(),
        'brain': brain.available(),
        'marked_area': True,
        'commands': commands,
        'discovered': len(commands),
        'runnable': sum(item['runnable'] for item in commands),
        'vocabulary': {name: {'group': group, 'label': label}
                       for name, (group, label) in photocraft_intents.ACTIONS.items()},
        'looks': sorted(photocraft_intents.RECIPES) + photocraft_intents.LUTS,
        'note': 'Registry access is not verified feature parity. Some commands need a selection, '
        'a specific layer type, resources, or the desktop application.',
    }


def validate_steps(steps, folder):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError('An edit must contain between 1 and 32 commands.')
    lookup = {command['id']: command for command in registry()}

    def inspect(value, key='', depth=0):
        if depth > 12:
            raise ValueError('Command parameters are nested too deeply.')
        if isinstance(value, dict):
            for child, item in value.items():
                inspect(item, child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 10000:
                raise ValueError('Too many points in one command.')
            for item in value:
                inspect(item, key, depth + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Command values must be finite.')
        elif isinstance(value, (int, float)) and key.lower() in {
            'width',
            'height',
            'targetwidth',
            'targetheight',
        }:
            if not 1 <= value <= 8192:
                raise ValueError('Workspace dimensions must be between 1 and 8192 pixels.')
        elif isinstance(value, str):
            if len(value) > 20000:
                raise ValueError('A command parameter is too long.')
            # Files are selected by the workspace, never by generated command parameters.
            if key.lower() in {'file', 'filename', 'filepath', 'directory', 'folder', 'url', 'uri'}:
                raise ValueError('External files and URLs must be opened through the document controls.')
            if key.lower() == 'path' and (':' in value or '/' in value or '\\' in value or '..' in value):
                raise ValueError('Only document vector-path names are accepted in editing commands.')

    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('The plan contains an unknown PhotoCraft command.')
        command, params = step.get('command'), step.get('params', {})
        if not isinstance(params, dict):
            raise ValueError('Command parameters must be a JSON object.')  # noqa: TRY004
        if command in photocraft_macros.NAMES:
            inner = params.get('command')
            if inner is not None and (inner not in lookup or lookup[inner]['reason']):
                raise ValueError('The plan contains an unknown PhotoCraft command.')
            inspect(params)
            continue
        if command not in lookup:
            raise ValueError('The plan contains an unknown PhotoCraft command.')
        reason = lookup[command]['reason']
        if reason:
            raise ValueError(reason)
        inspect(params)
    return steps


def snapshot(engine, folder, label, steps):
    state = engine.call('doc.inspect')
    if state['width'] * state['height'] > 40_000_000:
        raise ValueError('This workspace supports documents up to 40 megapixels.')
    revision_id = uuid.uuid4().hex
    engine.call('doc.save', {'path': str(folder / f'{revision_id}.pcraft')})
    engine.call('doc.render', {'path': str(folder / f'{revision_id}.png'), 'maxSide': 1600})
    return {'id': revision_id, 'label': label, 'created': time.time(), 'state': state, 'steps': steps}


def create(contents=None, filename='Untitled', width=1600, height=1000, cancelled=None):
    workspace_id = uuid.uuid4().hex
    folder = folder_for(workspace_id)
    folder.mkdir(parents=True)
    with Engine(folder, cancelled) as engine:
        if contents is not None:
            suffix = Path(filename).suffix.lower()
            if suffix not in {
                '.png',
                '.jpg',
                '.jpeg',
                '.webp',
                '.tif',
                '.tiff',
                '.psd',
                '.psb',
                '.pcraft',
                '.ora',
                '.bmp',
            }:
                raise ValueError('Use PNG, JPEG, WebP, TIFF, PSD, PSB, PCraft, ORA, or BMP.')
            source = folder / ('import' + suffix)
            source.write_bytes(contents)
            engine.call('doc.open', {'path': str(source)})
        else:
            engine.call(
                'doc.new', {'width': width, 'height': height, 'name': filename, 'background': 'white'}
            )
        revision = snapshot(engine, folder, 'Original', [])
    data = {
        'id': workspace_id,
        'name': Path(filename).name[:150],
        'history': [revision],
        'cursor': 0,
        'updated': time.time(),
    }
    save(data)
    return public(data)


def require_revision(data, expected):
    if current(data)['id'] != expected:
        raise ValueError('The document changed. Review a fresh plan before applying it.')


def trust_measurements(verdicts, checks):
    """The visual review cannot see small tone changes (it called a measured +8 of 255 on a shirt
    “identical”), so where every measurement of a requirement passed, its “not done” becomes unclear."""
    measured = {}
    for check in checks:
        if check.get('measured'):
            measured.setdefault(check['requirement'], []).append(check['passed'])
    for verdict in verdicts:
        results = measured.get(verdict['requirement'])
        if verdict['verdict'] == 'not done' and results and all(results):
            verdict['verdict'] = 'unclear'
            verdict['note'] = (f'{verdict["note"]} The measurement above did find the change, so trust it; '
                               'small tone changes are hard to see.').strip()
    return verdicts


def apply(workspace_id, expected, steps, label, progress, cancelled, plan=None):
    """Run every step in one engine session; history only advances when all succeed. With a
    plan, the result is measured against each requirement and reviewed by the brain."""
    with LOCK:
        data = load(workspace_id)
        require_revision(data, expected)
        folder = folder_for(workspace_id)
        validate_steps(steps, folder)
        before = current(data)['state']
        outcomes = {}
        context = {'progress': lambda desc='', **kwargs: progress(0.4, desc=desc)}
        with Engine(folder, cancelled) as engine:
            engine.call('doc.open', {'path': str(folder / f'{expected}.pcraft')})
            area = plan.get('area') if plan else None
            if area:
                from .photocraft_area import mask_for
                mask_for(area, before['width'], before['height'])
                engine.call('doc.render', {'path': str(folder / '_area-before.png'),
                                          'maxSide': max(before['width'], before['height'])})
            for index, step in enumerate(steps):
                progress(0.05 + 0.6 * index / max(1, len(steps)), desc=step.get('label') or step['command'])
                params = step.get('params', {})
                try:
                    if step['command'] in photocraft_macros.NAMES:
                        result = photocraft_macros.run(engine, folder, step['command'], params, context)
                    elif step['command'] == 'select.deselect' and not engine.call('doc.inspect').get('hasSelection'):
                        result = None  # a studio step already deselected
                    else:
                        result = engine.call('engine.execute', {'command': step['command'], 'params': params})
                except ValueError as exc:
                    raise ValueError(
                        f'Step {index + 1} ({step.get("label") or step["command"]}) failed: {exc}. '
                        'The previous revision is unchanged.'
                    ) from exc
                context['last'] = result if isinstance(result, dict) else {}
                if step['command'] == 'studio.text':
                    for requirement in step.get('requirements', []):
                        outcomes[('text', requirement)] = result
            if engine.call('doc.inspect').get('hasSelection'):
                engine.call('engine.execute', {'command': 'select.deselect', 'params': {}})
            if area:
                from .photocraft_area import check_boundary
                check_boundary(engine, folder, area, folder / '_area-before.png', before['width'], before['height'])
            revision = snapshot(engine, folder, label[:200], steps)
        check_cancel(cancelled)
        if plan and plan.get('edits'):
            canvas = photocraft_intents.Canvas(*(plan.get('result_size') or (0, 0)))
            revision['checks'] = photocraft_intents.verify(
                plan['edits'], before, revision['state'], canvas, outcomes)
            if area:
                revision['checks'].append({'requirement': 0, 'measured': True, 'passed': True,
                                           'check': 'Pixels outside your marked area are unchanged (full resolution)'})
            revision['requirements'] = plan['requirements']
            geometry = any(photocraft_intents.group(edit) == 'geometry' for edit in plan['edits'])
            with Image.open(folder / f'{expected}.png') as old, Image.open(folder / f'{revision["id"]}.png') as new:
                revision['checks'] += photocraft_intents.measure(
                    plan['edits'], plan.get('regions', []), old.copy(), new.copy(), geometry)
            revision['notes'] = [
                f'Text color chosen for readability ({value["color"]})'
                + (' with a soft shadow' if value.get('auto_shadow') else '')
                for key, value in outcomes.items()
                if key[0] == 'text' and plan['edits'][key[1]]['color'] in ('', 'auto')
            ]
            if plan.get('planner') not in ('manual', 'preset', 'rules') and brain.available():
                progress(0.8, desc='Checking the result against each requirement…')
                try:
                    with Image.open(folder / f'{expected}.png') as old, \
                            Image.open(folder / f'{revision["id"]}.png') as new:
                        applied = sorted({i for step in steps for i in step.get('requirements', [])})
                        verdicts = photocraft_planner.review(
                            [plan['requirements'][i] for i in applied], plan.get('preserve', []),
                            old.copy(), new.copy())
                        for verdict in verdicts:
                            if verdict['requirement'] is not None:
                                verdict['requirement'] = applied[verdict['requirement']]
                        revision['review'] = trust_measurements(verdicts, revision['checks'])
                except (RuntimeError, ValueError, OSError) as exc:
                    revision['review_error'] = str(exc)[:300]
        check_cancel(cancelled)
        data['history'] = data['history'][: data['cursor'] + 1] + [revision]
        data['cursor'] += 1
        data['updated'] = time.time()
        save(data)
        return public(data)


def move_history(workspace_id, expected, direction):
    with LOCK:
        data = load(workspace_id)
        require_revision(data, expected)
        cursor = data['cursor'] + direction
        if not 0 <= cursor < len(data['history']):
            raise ValueError('No further revision in that direction.')
        data['cursor'] = cursor
        data['updated'] = time.time()
        save(data)
        return public(data)


def export(workspace_id, revision_id, format):
    data = load(workspace_id)
    if revision_id not in {revision['id'] for revision in data['history']}:
        raise ValueError('Revision not found.')
    if format not in {'pcraft', 'psd', 'png', 'jpg', 'tif', 'webp'}:
        raise ValueError('Unsupported export format.')
    folder = folder_for(workspace_id)
    native = folder / f'{revision_id}.pcraft'
    if format == 'pcraft':
        return native
    target = folder / f'{revision_id}.export.{format}'
    with LOCK:
        if not target.exists():
            photocraft.run_cli(['convert', native, target], timeout=180)
    return target


def desktop(workspace_id, expected):
    with LOCK:
        data = load(workspace_id)
        require_revision(data, expected)
        folder = folder_for(workspace_id)
        # Each handoff gets its own copy; never overwrite an unsaved desktop session.
        copy_id = uuid.uuid4().hex
        target = folder / f'desktop-{copy_id}.pcraft'
        shutil.copy2(folder / f'{expected}.pcraft', target)
        photocraft.open_document(target)
        data['desktop'] = {'file': target.name, 'base': expected}
        save(data)
        return public(data)


def sync_desktop(workspace_id, expected, cancelled):
    with LOCK:
        data = load(workspace_id)
        require_revision(data, expected)
        handoff = data.get('desktop')
        if not handoff or handoff['base'] != expected:
            raise ValueError(
                'Open the current revision in PhotoCraft first, then save it there before syncing.'
            )
        folder = folder_for(workspace_id)
        with Engine(folder, cancelled) as engine:
            engine.call('doc.open', {'path': str(folder / handoff['file'])})
            revision = snapshot(engine, folder, 'Saved changes from PhotoCraft desktop', [])
        check_cancel(cancelled)
        data['history'] = data['history'][: data['cursor'] + 1] + [revision]
        data['cursor'] += 1
        data['updated'] = time.time()
        data.pop('desktop', None)
        save(data)
        return public(data)


def command_candidates(text, limit=28):
    stopwords = {
        'the',
        'and',
        'image',
        'photo',
        'picture',
        'make',
        'keep',
        'unchanged',
        'exact',
        'must',
        'with',
        'from',
        'apart',
        'only',
        'then',
        'this',
        'that',
        'add',
        'increase',
        'decrease',
        'change',
        'all',
        'top',
        'bottom',
        'center',
        'centered',
    }
    words = set(re.findall('[a-z]{3,}', text.lower())) - stopwords
    synonyms = {
        'bright': 'brightness exposure',
        'warm': 'photoFilter colorBalance temperature',
        'text': 'type.create type.setStyle',
        'crop': 'image.crop',
        'background': 'select.subject select.inverse',
        'sky': 'select.sky',
        'sharp': 'smartSharpen',
        'cinematic': 'colorLookup curves',
        'rotate': 'imageRotation',
        'size': 'imageSize',
        'mask': 'layerMask select',
    }
    for key, extra in synonyms.items():
        if any(key in word for word in words):
            words.update(extra.lower().split())
    preferred = set()
    shortcuts = {
        'text|title|caption|font|word|write': ['type.create', 'type.setStyle'],
        'crop|square|aspect': ['image.crop'],
        'vibran': ['layer.newAdjustmentLayer.vibrance'],
        'bright|exposure': [
            'layer.newAdjustmentLayer.brightnessContrast',
            'layer.newAdjustmentLayer.exposure',
        ],
        'warm|cool': ['layer.newAdjustmentLayer.photoFilter'],
        'curve|contrast': ['layer.newAdjustmentLayer.curves', 'layer.newAdjustmentLayer.brightnessContrast'],
        'saturat': ['layer.newAdjustmentLayer.hueSaturation'],
        'black and white|grayscale': ['layer.newAdjustmentLayer.blackWhite'],
        'sky': ['select.sky'],
        'background|subject|person': ['select.subject', 'select.inverse'],
        'object|select': ['select.object', 'select.rect'],
        'resize|resolution': ['image.imageSize'],
        'sharp': ['filter.sharpen.smartSharpen'],
    }
    for pattern, ids in shortcuts.items():
        if re.search(pattern, text, re.IGNORECASE):
            preferred.update(ids)

    def score(item):
        name = (item['id'] + ' ' + item['label']).lower()
        return (100 if item['id'] in preferred else 0) + sum(
            8 if word in name else 0.1 if word in item['params'].lower() else 0 for word in words
        )

    eligible = [item for item in registry() if item['runnable']]
    chosen = sorted(eligible, key=score, reverse=True)[:limit]
    mandatory = {
        'select.deselect',
        'layer.select',
        'layer.setProps',
        'layer.duplicate',
        'layer.smartObjects.convertToSmartObject',
        'layer.renameLayer',
    }
    return list(
        {item['id']: item for item in chosen + [c for c in eligible if c['id'] in mandatory]}.values()
    )


def explain(edit, steps, index):
    """One plain sentence about what an edit will do, for the plan review."""
    own = [step['label'] for step in steps if index in step.get('requirements', [])
           and step['label'] != 'Add to the selection'
           and not step['command'].startswith(('select.deselect', 'studio.select', 'studio.require', 'layer.renameLayer'))]
    return ' → '.join(own[:4]) or 'Not planned'


def compile_plan(data, prompt, edits, preserve, questions, notes, preview, planner, boxes=None, area=None):
    """Compile normalized edits against the current document; finds objects when needed."""
    state = current(data)['state']
    boxes = dict(boxes or {})
    wanted = set() if area else {query for query in (photocraft_planner.needs_boxes(edit) for edit in edits) if query}
    missing = sorted(query for query in wanted if query.lower() not in boxes)
    if missing:
        if not brain.available():
            raise ValueError('Finding objects needs the editing brain. Install it, or choose the whole image.')
        hints = {photocraft_planner.needs_boxes(edit): edit['quote'] for edit in edits}
        boxes.update(photocraft_planner.locate(preview, missing, state, hints))
    if area:
        from .photocraft_area import compile_area
        steps, compile_notes, blocking, regions, expert_indices, canvas = compile_area(
            edits, state, area, fonts(), photocraft_macros.ai_available())
        edits = [{**edit, 'target': 'area', 'object': 'Marked area',
                  'action': 'blur' if edit['action'] == 'blur_background' else edit['action']} for edit in edits]
        preserve = [*preserve, 'Everything outside your marked area']
        notes = [*notes, 'Your marked area overrides automatic target detection for every change in this plan.']
    else:
        steps, compile_notes, blocking, regions, expert_indices, canvas = photocraft_intents.compile_edits(
            edits, state, fonts(), boxes, photocraft_macros.ai_available())
    for index in expert_indices:
        edit = edits[index]
        if not brain.available():
            blocking.append(f'“{edit["quote"]}” needs the editing brain to choose PhotoCraft tools.')
            continue
        found, expert_notes = photocraft_planner.expert(
            edit, preview, state, command_candidates(edit['quote'] + ' ' + edit['choice']))
        if not found:
            blocking.append(f'No PhotoCraft tool matched “{edit["quote"]}”.')
        for step in found:
            steps.append({**step, 'requirements': [index]})
        compile_notes += expert_notes
    uncovered = photocraft_intents.uncovered_clauses(prompt, edits, preserve) if planner != 'manual' else []
    return {
        'summary': '; '.join(edit['quote'] for edit in edits)[:400] or prompt[:400],
        'requirements': [edit['quote'] for edit in edits],
        'edits': [{**edit, 'explain': explain(edit, steps, index)} for index, edit in enumerate(edits)],
        'preserve': preserve,
        'questions': questions,
        'notes': notes + compile_notes,
        'unresolved': blocking + [f'Not understood: “{clause}”' for clause in uncovered],
        'regions': regions,
        'steps': steps,
        'boxes': boxes,
        'planner': planner,
        'result_size': [canvas.width, canvas.height],
        'area': area,
    }


RULE_ACTIONS = {'brightness': 'brightness', 'contrast': 'contrast', 'saturation': 'saturation',
                'warmth': 'temperature', 'black_and_white': 'black_and_white', 'sepia': 'sepia',
                'invert_colors': 'invert'}


def rule_edits(prompt):
    """Edits for short requests the instant rules understand completely (“make it brighter
    and warmer”), so they need no planner pass; None when any part needs the planner."""
    from image_studio.services import agent

    steps = agent.quick_plan(prompt)
    if not steps or len(prompt) > 120:
        return None
    edits = []
    for step in steps:
        action = RULE_ACTIONS.get(step['op'])
        if action is None:
            return None
        value = step.get('amount', 0)
        strength = 'subtle' if abs(value) <= 15 else 'strong' if abs(value) >= 60 else 'moderate'
        written = re.search(r'(-?\d+(?:\.\d+)?)\s*%', prompt)
        edits.append(photocraft_intents.blank(
            action, quote=prompt, strength=strength,
            direction='none' if action in ('black_and_white', 'sepia', 'invert') else
            'decrease' if value < 0 else 'increase',
            value=abs(float(written.group(1))) if written and len(steps) == 1 else None))
    return edits


def smart_plan(workspace_id, expected, prompt, progress, cancelled, area=None):
    data = load(workspace_id)
    require_revision(data, expected)
    folder = folder_for(workspace_id)
    check_cancel(cancelled)
    with Image.open(folder / f'{expected}.png') as image:
        preview = image.copy()
    state = current(data)['state']
    preset = photocraft_intents.presets(prompt)
    instant = rule_edits(prompt)
    if preset:
        result = compile_plan(data, prompt, preset, [], [], [], preview, 'preset', area=area)
    elif instant:
        result = compile_plan(data, prompt, instant, [], [], [], preview, 'rules', area=area)
    elif brain.available():
        progress(0.1, desc='Reading your image and every part of your request…')
        edits, preserve, questions, notes = photocraft_planner.understand(prompt, preview, state, area=area)
        check_cancel(cancelled)
        if not edits:
            raise ValueError('I could not find an edit in that request. Describe what should change.')
        progress(0.45, desc='Finding the things you named and measuring the document…')
        result = compile_plan(data, prompt, edits, preserve, questions, notes, preview, 'Qwen3.5 vision', area=area)
    else:
        if area:
            raise ValueError('Try “make it brighter and warmer” in the marked area, or install the editing brain '
                             'for more detailed requests.')
        # Without the brain, only requests the instant rules fully understand are planned.
        quick = photocraft.plan(prompt)
        result = {
            'summary': prompt, 'requirements': [prompt], 'edits': [], 'preserve': [], 'questions': [], 'notes': [],
            'unresolved': [], 'regions': [], 'boxes': {}, 'planner': 'rules',
            'steps': [{'command': command, 'params': params, 'label': label, 'requirements': [0]}
                      for command, params, label in quick],
        }
    check_cancel(cancelled)
    if result['steps']:
        validate_steps(result['steps'], folder)
    elif not result['unresolved']:
        result['unresolved'].append('No executable commands were planned.')
    # The revision and plan are server-owned; applying an old plan cannot edit a newer photo.
    result.update(id=uuid.uuid4().hex, revision=expected, prompt=prompt, created=time.time())
    require_revision(load(workspace_id), expected)
    (folder / f'plan-{result["id"]}.json').write_text(json.dumps(result), encoding='utf-8')
    return result


def manual_plan(workspace_id, expected, edits, label):
    """A plan for the manual panels (Adjust, Looks, Crop, Select, Text…), which send the
    same edit language as the planner with trusted slider values."""
    data = load(workspace_id)
    require_revision(data, expected)
    folder = folder_for(workspace_id)
    clean = []
    for raw in edits:
        if not isinstance(raw, dict) or raw.get('action') not in photocraft_intents.ACTIONS:
            raise ValueError('Unknown edit.')
        fields = {key: raw[key] for key in ('target', 'object', 'direction', 'strength', 'text', 'color',
                                            'position', 'size', 'aspect', 'choice', 'quote') if key in raw}
        value = raw.get('value')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)):
            raise ValueError('Edit values must be numbers.')
        edit = photocraft_intents.blank(raw['action'], **fields, value=value)
        for key, options in (('target', photocraft_intents.TARGETS), ('direction', photocraft_intents.DIRECTIONS),
                             ('strength', photocraft_intents.STRENGTHS)):
            if edit[key] not in options:
                raise ValueError(f'Invalid {key}.')
        for key in ('object', 'text', 'color', 'aspect', 'choice', 'quote'):
            edit[key] = str(edit[key])[:300]
        clean.append(edit)
    if not 1 <= len(clean) <= 16:
        raise ValueError('Send between 1 and 16 edits.')
    with Image.open(folder / f'{expected}.png') as image:
        preview = image.copy()
    result = compile_plan(data, label, clean, [], [], [], preview, 'manual')
    result.update(id=uuid.uuid4().hex, revision=expected, prompt=label, created=time.time())
    if result['steps']:
        validate_steps(result['steps'], folder)
    return result


def load_plan(workspace_id, plan_id, partial=False):
    if not re.fullmatch('[a-f0-9]{32}', plan_id):
        raise ValueError('Invalid plan ID.')
    try:
        result = json.loads((folder_for(workspace_id) / f'plan-{plan_id}.json').read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError('Plan not found. Create a fresh plan.') from exc
    if result['unresolved'] and not (partial and result['steps']):
        raise ValueError('Resolve the unanswered details before applying this plan.')
    return result


def goto(workspace_id, expected, index):
    with LOCK:
        data = load(workspace_id)
        require_revision(data, expected)
        if not 0 <= index < len(data['history']):
            raise ValueError('That revision does not exist.')
        data['cursor'] = index
        data['updated'] = time.time()
        save(data)
        return public(data)


@functools.lru_cache(maxsize=1)
def _fonts():
    import tempfile

    with tempfile.TemporaryDirectory(dir=CACHE) as folder, Engine(Path(folder)) as engine:
        engine.call('doc.new', {'width': 8, 'height': 8, 'name': 'fonts'})
        return tuple(engine.call('engine.execute', {'command': 'type.fonts', 'params': {}})['families'])


def fonts():
    try:
        return list(_fonts()) if photocraft.available() else []
    except (RuntimeError, ValueError, OSError):
        return []

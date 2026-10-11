"""One-time source migration; backs up original source before moving it."""

import ast
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent.parent / 'work'
backup = WORK / 'image-studio-backups' / 'before-react.zip'
backup.parent.mkdir(parents=True, exist_ok=True)
if backup.exists():
    raise SystemExit('Source backup already exists; migration must only run once.')
with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in ROOT.rglob('*'):
        if (
            path.is_file()
            and path.suffix in {'.py', '.bat', '.md', '.txt', '.json', '.jpg'}
            and 'images' not in path.parts
            and '__pycache__' not in path.parts
        ):
            archive.write(path, path.relative_to(ROOT))

groups = {
    'core': ['catalog', 'engine'],
    'services': [
        'agent',
        'assistant',
        'checker',
        'faces',
        'finish',
        'layout',
        'repair',
        'search',
        'segment',
        'style',
        'variety',
    ],
    'integrations': ['bridge', 'install_krita_plugin'],
    'cli': ['manage', 'download_model'],
    'workers': ['search_worker'],
}
mapping = {name: f'image_studio.{group}.{name}' for group, names in groups.items() for name in names}
base = ROOT / 'backend' / 'image_studio'
for group in [*groups, 'api']:
    folder = base / group
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '__init__.py').write_text(f'"""Image Studio {group}."""\n', encoding='utf-8')
(base / '__init__.py').write_text('"""Local Image Studio backend."""\n', encoding='utf-8')


def imports(text):
    for name, module in mapping.items():
        text = re.sub(rf'(?m)^(\s*)from {name} import ', rf'\1from {module} import ', text)
        parent, leaf = module.rsplit('.', 1)
        text = re.sub(
            rf'(?m)^(\s*)import {name}(?=\s*(?:as\s+\w+)?\s*$)', rf'\1from {parent} import {leaf}', text
        )
    return text


for group, names in groups.items():
    for name in names:
        source = ROOT / f'{name}.py'
        text = imports(source.read_text(encoding='utf-8'))
        if name == 'catalog':
            text = text.replace(
                "ROOT = Path(__file__).resolve().parent\nWORK = ROOT.parent.parent / 'work'",
                'from image_studio.core.paths import ROOT, WORK',
            )
        if name == 'search':
            text = text.replace(
                "str(ROOT / 'search_worker.py')",
                "str(ROOT / 'backend' / 'image_studio' / 'workers' / 'search_worker.py')",
            )
        if name == 'install_krita_plugin':
            text = text.replace(
                "SOURCE = Path(__file__).resolve().parent / 'krita-plugin'",
                "from image_studio.core.paths import ROOT\n\nSOURCE = ROOT / 'integrations' / 'krita-plugin'",
            )
        (base / group / source.name).write_text(text, encoding='utf-8')
        source.unlink()

source = (ROOT / 'app.py').read_text(encoding='utf-8')
tree = ast.parse(source)
remove = {
    'make_app',
    'select_history',
    'reuse_settings',
    'send_to_editor',
    'change_model',
    'html_escape',
    'link_html',
    'layers_html',
    'steps_html',
    'krita_view',
    'toggle',
}
parts = []
lines = source.splitlines(keepends=True)
for node in tree.body:
    if isinstance(node, ast.If) and '__name__' in ast.get_source_segment(source, node.test):
        continue
    if isinstance(node, ast.FunctionDef) and node.name in remove:
        continue
    if isinstance(node, (ast.Import, ast.ImportFrom)) and any(n.name in {'ui', 'gradio'} for n in node.names):
        continue
    text = ''.join(lines[node.lineno - 1 : node.end_lineno])
    if 'GRADIO_' in text:
        continue
    parts.append(text)
text = imports('\n\n'.join(parts))
text = (
    text.replace('gr.Error', 'ValueError').replace('gr.update', 'dict').replace('gr.Progress()', 'Progress()')
)
text = text.replace("'gradio-cache'", "'studio-cache'")
text = 'from image_studio.services.progress import Progress\n' + text
(base / 'services' / 'workflows.py').write_text(text, encoding='utf-8')
(ROOT / 'app.py').unlink()
(ROOT / 'ui.py').unlink()

for folder in ['integrations', 'training', 'docs', 'docs/screenshots', 'scripts/windows', 'tests']:
    (ROOT / folder).mkdir(parents=True, exist_ok=True)


def move(source, target):
    src, dst = (ROOT / source).resolve(), (ROOT / target).resolve()
    if not src.is_relative_to(ROOT) or not dst.is_relative_to(ROOT):
        raise ValueError('Migration target outside workspace')
    shutil.move(str(src), str(dst))


move('krita-plugin', 'integrations/krita-plugin')
move('lora_train', 'training/lora')
for path in (ROOT / 'training/lora').glob('*.py'):
    text = imports(path.read_text(encoding='utf-8'))
    text = text.replace('parents[1]', 'parents[2]').replace('str(APP))', "str(APP / 'backend'))")
    path.write_text(text, encoding='utf-8')
for name in ['app-preview.jpg', 'realistic-preview.jpg']:
    move(name, f'docs/screenshots/{name}')
move('verification.json', 'docs/legacy-verification.json')
move('README.md', 'docs/model-guide.md')
move('requirements-search.txt', 'backend/requirements-search.txt')
move('requirements.txt', 'backend/requirements-models.txt')
for path in ROOT.glob('*.bat'):
    text = path.read_text(encoding='utf-8')
    for name in ['manage', 'download_model', 'faces', 'install_krita_plugin']:
        text = text.replace(f'{name}.py', '-m ' + mapping[name])
    text = text.replace('requirements-search.txt', 'backend\\requirements-search.txt')
    if path.name.startswith(('Download', 'Build')):
        text = text.replace('cd /d "%~dp0"', 'cd /d "%~dp0..\\.."')
        target = ROOT / 'scripts/windows' / path.name
        target.write_text(text, encoding='utf-8')
        path.unlink()
    else:
        path.write_text(text, encoding='utf-8')
print(f'Migrated sources. Backup: {backup}')

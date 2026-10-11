"""Krita lab: runs AI-panel steps inside a real, headless Krita (kritarunner) so they can be
checked on real pictures without opening Krita. Started by run_lab.py, which copies this
file next to Krita's own Python plugins and passes a job file:

    {"out": "<folder>", "cases": [{"name": "warm", "image": "<png>", "steps": [{"op": ...}],
                                   "mask": "<png, optional selection>", "code": "<python, optional>"}]}

Each case opens the picture, makes the selection from `mask` if given, runs `steps` with the
plugin's ops.run_local, runs `code` (with doc, ops, app in scope; its `result` is reported),
and saves the merged picture to <out>/<name>.png. Results go to <out>/report.json."""
import importlib
import json
import os
import sys
import traceback
import types


def load_ops(plugin_dir):
    """The plugin's ops module, without running the package __init__ (which adds the panel)."""
    package = types.ModuleType('ai_prompt')
    package.__path__ = [os.path.join(plugin_dir, 'ai_prompt')]
    sys.modules['ai_prompt'] = package
    return importlib.import_module('ai_prompt.ops')


def open_picture(app, ops, path):
    """A new document holding the picture as its one layer. (kritarunner has no file import
    plugins loaded, so Qt reads the file.)"""
    from ai_prompt.qt import QByteArray, QImage, raw_bytes, ARGB32
    image = QImage(path)
    if image.isNull():
        raise RuntimeError(f'Qt could not read {path}')
    image = image.convertToFormat(ARGB32)
    doc = app.createDocument(image.width(), image.height(), 'lab', 'RGBA', 'U8', '', 300.0)
    doc.setBatchmode(True)
    layer = doc.rootNode().childNodes()[0]
    layer.setName('Background')
    layer.setPixelData(QByteArray(raw_bytes(image)), 0, 0, image.width(), image.height())
    doc.setActiveNode(layer)
    return doc


def main(args):
    job_path = args[0] if isinstance(args, list) else args
    job = json.load(open(job_path, encoding='utf-8'))
    report = []
    log = open(os.path.join(job['out'], 'progress.log'), 'w', encoding='utf-8', buffering=1)

    def say(text):
        log.write(text + '\n')

    try:
        from krita import Krita
        ops = load_ops(job['plugin'])
        app = Krita.instance()
        for case in job['cases']:
            entry = dict(name=case['name'])
            doc = None
            try:
                say(f'{case["name"]}: open')
                doc = open_picture(app, ops, case['image'])
                say('  settle')
                ops.settle(doc)
                if case.get('mask'):
                    from ai_prompt.qt import QImage
                    doc.setSelection(ops.mask_selection(doc, QImage(case['mask'])))
                notes = []
                for step in case.get('steps', []):
                    say(f'  step {step}')
                    label = step.get('label') or step['op']
                    notes.append(ops.run_local(doc, step, label))
                if case.get('code'):
                    say('  code')
                    scope = dict(doc=doc, ops=ops, app=app, result=None)
                    exec(case['code'], scope)
                    entry['result'] = scope.get('result')
                say('  save')
                ops.settle(doc)
                path = os.path.join(job['out'], case['name'] + '.png')
                ops.projection(doc).save(path)
                entry.update(ok=True, notes=notes, image=path,
                             layers=[(node.name(), node.type(), depth) for node, depth in ops.walk(doc.rootNode())])
            except Exception:
                entry.update(ok=False, error=traceback.format_exc())
            finally:
                if doc is not None:
                    doc.close()
            report.append(entry)
    except Exception:
        report.append(dict(name='lab', ok=False, error=traceback.format_exc()))
    with open(os.path.join(job['out'], 'report.json'), 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1, default=str)

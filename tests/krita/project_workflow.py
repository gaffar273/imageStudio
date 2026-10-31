import importlib
import json
import os
import shutil
import sys
import traceback
import types


def main(config):
    class Report(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            with open(config['out'] + '/gui-report.json', 'w', encoding='utf-8') as output:
                json.dump(self, output, indent=2)

    report = Report()
    report['started'] = True
    try:
        package = types.ModuleType('ai_prompt')
        package.__path__ = [config['plugin']]
        sys.modules['ai_prompt'] = package
        ops = importlib.import_module('ai_prompt.ops')
        link_module = importlib.import_module('ai_prompt.link')
        from krita import Krita, Selection
        from ai_prompt.qt import QImage, QColor, ARGB32

        app = Krita.instance()
        link = link_module.LinkExtension(app)
        manager = link.projects
        events = []
        manager.publish = events.append
        manager.busy = lambda: False
        ident = 'a' * 32
        folder = config['out'] + '/' + ident
        os.makedirs(folder, exist_ok=True)
        command = dict(project_id=ident, path=folder + '/project.kra', name='Real Krita project', id='test')

        def run(kind, **extra):
            manager.handle(dict(command, kind=kind, **extra))

        run('project_new', width=300, height=200)
        doc = ops.document()
        assert doc is not None and os.path.getsize(command['path']) > 0
        report['create'] = True
        source = folder + '/source.png'
        image = QImage(30, 20, ARGB32)
        image.fill(QColor(255, 0, 0, 128))
        image.save(source, 'PNG')
        run('project_place', source=source, image_name='Transparent source', fit=False, x=100, y=80)
        doc = ops.document()
        layer = doc.activeNode()
        report['placement'] = [
            layer.bounds().x(),
            layer.bounds().y(),
            layer.bounds().width(),
            layer.bounds().height(),
        ]
        assert layer.bounds().width() == 30 and layer.bounds().height() == 20
        selection = Selection()
        selection.select(85, 70, 15, 20, 255)
        mask = doc.createTransparencyMask('Editable mask')
        layer.addChildNode(mask, None)
        mask.setSelection(selection)
        layer.setOpacity(210)
        manager.save_doc(doc, force=True)
        run(
            'project_layer',
            layer_id=layer.uniqueId().toString().strip('{}'),
            operation='transform',
            values=dict(dx=20, dy=10, scaleX=200, scaleY=200),
        )
        doc = ops.document()
        before = [(node.name(), node.type(), node.opacity()) for node, depth in ops.walk(doc.rootNode())]
        checkpoint = folder + '/before-clear.kra'
        shutil.copy2(command['path'], checkpoint)
        run('project_close')
        report['closed_first'] = True
        run('project_open')
        report['opened_first'] = True
        doc = ops.document()
        views = len(app.activeWindow().views())
        run('project_open')
        assert len(app.activeWindow().views()) == views
        report['reopen_reuses_existing_view'] = True
        after = [(node.name(), node.type(), node.opacity()) for node, depth in ops.walk(doc.rootNode())]
        assert before == after and any(row[1] == 'transparencymask' for row in after)
        report['save_reopen_layers_masks'] = after
        run('project_clear')
        assert len(ops.document().rootNode().childNodes()) == 1
        run('project_restore', source=checkpoint)
        doc = ops.document()
        assert [
            (node.name(), node.type(), node.opacity()) for node, depth in ops.walk(doc.rootNode())
        ] == before
        report['clear_restore'] = True
        layer = next(node for node, depth in ops.walk(doc.rootNode()) if node.name() == 'Transparent source')
        prefix = folder + '/layer-test'
        saved = open(command['path'], 'rb').read()
        real_projection = ops.projection

        def projection_with_autosave(document):
            manager.auto_save()  # Simulate a timer firing while the transient clone is visible.
            return real_projection(document)

        ops.projection = projection_with_autosave
        try:
            run('project_layer_preview', layer_id=layer.uniqueId().toString().strip('{}'), prefix=prefix)
        finally:
            ops.projection = real_projection
        assert open(command['path'], 'rb').read() == saved
        assert all(os.path.isfile(prefix + '-' + part + '.png') for part in ['below', 'image', 'above'])
        assert QImage(prefix + '-above.png').pixelColor(0, 0).alpha() == 0
        assert [
            (node.name(), node.type(), node.opacity()) for node, depth in ops.walk(doc.rootNode())
        ] == before
        report['non_mutating_live_preview'] = True
        layer.setName('Autosaved source')
        doc.setModified(True)
        manager.saved_at[os.path.abspath(command['path'])] -= 10
        manager.auto_save()
        assert not doc.modified()
        run('project_close')
        run('project_open')
        assert any(node.name() == 'Autosaved source' for node, depth in ops.walk(ops.document().rootNode()))
        report['autosave'] = True
        run('project_close')
        color_doc = app.createDocument(40, 30, '16-bit project', 'RGBA', 'U16', '', 300.0)
        app.activeWindow().addView(color_doc)
        color_command = dict(
            project_id='b' * 32,
            path=config['out'] + '/' + 'b' * 32 + '/project.kra',
            name='16-bit project',
            id='color',
        )
        os.makedirs(os.path.dirname(color_command['path']), exist_ok=True)
        manager.save_as(color_doc, color_command)
        color_doc.close()
        manager.handle(dict(color_command, kind='project_open'))
        assert ops.document().colorDepth() == 'U16'
        report['preserved_16_bit_color'] = True
        manager.handle(dict(color_command, kind='project_close'))
        report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    with open(config['out'] + '/gui-report.json', 'w', encoding='utf-8') as output:
        json.dump(report, output, indent=2)

"""Native Krita project operations. A successful acknowledgement means the KRA was saved."""

import os
import time

from krita import Krita

from . import ops
from .qt import QPointF, fit


def node_id(node):
    return node.uniqueId().toString().strip('{}') if node is not None else None


class Manager:
    def __init__(self, link, publish, busy):
        self.link, self.publish, self.busy = link, publish, busy
        self.managed, self.saved_at, self.errors = {}, {}, {}
        self.depth, self.autosaving = 0, False

    def register(self, command):
        path = os.path.abspath(command['path'])
        if (
            os.path.basename(path) != 'project.kra'
            or os.path.basename(os.path.dirname(path)) != command['project_id']
        ):
            raise ops.StepError('Invalid project destination.')
        self.managed[path] = dict(id=command['project_id'], name=command.get('name', 'Project'))
        return path

    def save_doc(self, doc, force=False):
        path = os.path.abspath(doc.fileName()) if doc.fileName() else ''
        if path not in self.managed:
            return
        if doc.modified() or force:
            doc.waitForDone()
            previous = doc.batchmode()
            try:
                doc.setBatchmode(True)
                if force:
                    doc.setModified(True)
                if not doc.save():
                    raise ops.StepError(
                        'Krita could not save this project. It is still open; check disk space and retry Save.'
                    )
            except Exception as exc:
                self.errors[path] = str(exc)
                raise
            finally:
                doc.setBatchmode(previous)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise ops.StepError('The project file was not written. The document remains open.')
        self.saved_at[path] = time.monotonic()
        self.errors.pop(path, None)

    def save_as(self, doc, command):
        path = self.register(command)
        doc.waitForDone()
        previous = doc.batchmode()
        try:
            doc.setBatchmode(True)
            doc.setName(command.get('name') or 'Project')
            if not doc.saveAs(path) or not os.path.isfile(path):
                raise ops.StepError(
                    'Krita could not save the project. The document remains open so its contents are available.'
                )
        except Exception as exc:
            self.errors[path] = str(exc)
            raise
        finally:
            doc.setBatchmode(previous)
        doc.setAutosave(True)
        self.saved_at[path] = time.monotonic()
        self.errors.pop(path, None)

    def auto_save(self):
        if self.busy() or self.depth or self.autosaving:
            return
        self.autosaving = True
        try:
            self._auto_save()
        finally:
            self.autosaving = False

    def _auto_save(self):
        for doc in Krita.instance().documents():
            path = os.path.abspath(doc.fileName()) if doc.fileName() else ''
            if (
                path not in self.managed
                or not doc.modified()
                or time.monotonic() - self.saved_at.get(path, 0) < 5
            ):
                continue
            try:
                self.save_doc(doc)
            except Exception as exc:
                # Keep retrying, but report a persistent save failure only once until it changes.
                text = str(exc)
                self.saved_at[path] = time.monotonic()
                if self.errors.get(path) != text:
                    self.errors[path] = text
                    self.publish(dict(run='autosave', kind='failed', text=text))

    def current(self, command):
        path = self.register(command)
        doc = ops.need(ops.document())
        if not doc.fileName() or os.path.abspath(doc.fileName()) != path:
            raise ops.StepError('The active Krita project changed. Open the intended project and try again.')
        return doc

    def handle(self, command):
        if self.busy():
            raise ops.StepError('Wait for the current edit to finish before changing the project.')
        self.depth += 1
        try:
            self._handle(command)
        finally:
            self.depth -= 1

    def _handle(self, command):
        kind = command['kind']
        if kind in {'project_new', 'project_open'}:
            current = ops.document()
            if current is not None:
                self.save_doc(current)
            if kind == 'project_new':
                if command.get('use_current'):
                    doc = ops.need(current)
                elif command.get('source'):
                    doc = self.link.open(command['source'], normalize=False)
                else:
                    doc = ops.new_canvas(command['width'], command['height'], return_document=True)
                self.save_as(doc, command)
            else:
                path = self.register(command)
                already = next(
                    (
                        d
                        for d in Krita.instance().documents()
                        if d.fileName() and os.path.abspath(d.fileName()) == path
                    ),
                    None,
                )
                if already is not None:
                    windows = Krita.instance().windows()
                    existing = next(
                        (
                            (window, view)
                            for window in windows
                            for view in window.views()
                            if view.document() == already
                        ),
                        None,
                    )
                    if existing:
                        window, view = existing
                        window.showView(view)
                        window.activate()
                    else:
                        Krita.instance().activeWindow().addView(already)
                    doc = already
                else:
                    doc = self.link.open(path, normalize=False)
                doc.setAutosave(True)
        else:
            doc = self.current(command)
            if kind == 'project_save':
                self.save_doc(doc, force=True)
            elif kind == 'project_close':
                self.save_doc(doc, force=True)
                if not doc.close():
                    raise ops.StepError('Krita did not close the project.')
                doc = None
            elif kind in {'project_clear', 'project_canvas', 'project_restore'}:
                self.save_doc(doc, force=True)
                previous = doc
                if kind == 'project_clear':
                    doc = ops.new_canvas(doc.width(), doc.height(), return_document=True)
                else:
                    doc = self.link.open(command['source'], normalize=False)
                self.save_as(doc, command)
                previous.close()
            elif kind == 'project_place':
                ops.place_images(
                    doc,
                    [dict(path=command['source'], name=command['image_name'])],
                    fit=command.get('fit', False),
                    x=command.get('x'),
                    y=command.get('y'),
                )
                self.save_doc(doc, force=True)
            elif kind == 'project_layer':
                self.layer(doc, command)
                if command['operation'] != 'select':
                    self.save_doc(doc, force=True)
            elif kind == 'project_layer_preview':
                self.preview(doc, command)
            else:
                raise ops.StepError('Unknown project operation.')
        if kind != 'project_layer_preview':
            self.link.publish(force=True)
        readonly = (
            kind == 'project_layer_preview' or kind == 'project_layer' and command['operation'] == 'select'
        )
        message = (
            'Layer preview ready.'
            if kind == 'project_layer_preview'
            else 'Layer selected.'
            if readonly
            else ('Project saved.' if doc is not None else 'Project closed.')
        )
        self.publish(
            dict(
                run=command['id'],
                kind='done',
                text=message,
                silent=kind == 'project_layer_preview',
                project_id=command['project_id'],
                width=doc.width() if doc is not None else 0,
                height=doc.height() if doc is not None else 0,
            )
        )

    def layer(self, doc, command):
        node = next(
            (node for node, _ in ops.walk(doc.rootNode()) if node_id(node) == command['layer_id']), None
        )
        if node is None:
            raise ops.StepError('This layer is no longer in the project.')
        values, operation = command.get('values', {}), command['operation']
        ops.activate(doc, node)
        if operation == 'select':
            return
        if node.locked():
            raise ops.StepError('Unlock this layer in Krita before changing it.')
        if operation == 'transform':
            rect = node.bounds()
            if rect.width() <= 0 or rect.height() <= 0:
                raise ops.StepError('This layer has no visible image to move.')
            width = max(1, round(rect.width() * values.get('scaleX', 100) / 100))
            height = max(1, round(rect.height() * values.get('scaleY', 100) / 100))
            left = rect.x() + rect.width() / 2 + values.get('dx', 0) - width / 2
            top = rect.y() + rect.height() / 2 + values.get('dy', 0) - height / 2
            if width != rect.width() or height != rect.height():
                node.scaleNode(QPointF(rect.x(), rect.y()), width, height, 'Bicubic')
                doc.waitForDone()
            now, position = node.bounds(), node.position()
            node.move(round(position.x() + left - now.x()), round(position.y() + top - now.y()))
        elif operation == 'visibility':
            node.setVisible(values['visible'])
        elif operation == 'opacity':
            node.setOpacity(round(values['opacity'] * 255 / 100))
        elif operation == 'delete':
            node.remove()
        doc.refreshProjection()
        doc.waitForDone()

    def preview(self, doc, command):
        original = list(doc.rootNode().childNodes())
        index = next((i for i, node in enumerate(original) if node_id(node) == command['layer_id']), None)
        if index is None:
            raise ops.StepError('Live arrangement previews are available for top-level image layers.')
        prefix = os.path.abspath(command['prefix'])
        directory = os.path.dirname(os.path.abspath(command['path']))
        if os.path.commonpath([prefix, directory]) != directory:
            raise ops.StepError('Invalid preview destination.')
        copy = doc.clone()
        copy.setBatchmode(True)
        copy.setAutosave(False)
        try:
            nodes = list(copy.rootNode().childNodes())
            for part, indices in [
                ('below', range(index)),
                ('image', [index]),
                ('above', range(index + 1, len(nodes))),
            ]:
                for i, node in enumerate(nodes):
                    node.setVisible(bool(original[i].visible() and i in indices))
                copy.refreshProjection()
                copy.waitForDone()
                # Krita's thumbnail substitutes a checkerboard for an empty projection. Use
                # actual RGBA pixels so an empty "above" stack stays transparent while dragging.
                if not fit(ops.projection(copy), 1280).save(prefix + '-' + part + '.png', 'PNG'):
                    raise ops.StepError('Could not create the layer preview.')
        finally:
            copy.close()

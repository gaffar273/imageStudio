"""PhotoCraft studio: a layered document you change by describing edits or with the tool panels.

The same studio as the web version, on the same engine endpoints. PhotoCraft does every
pixel change; this screen shows the document, its layers and history, and sends commands.
"""

import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import HEADER_HEIGHT, Box, Range, Thumb
from image_studio.desktop.create import POLL_MS, rule
from image_studio.desktop.engine import in_background
from image_studio.desktop.library import save_to
from image_studio.desktop.photocraft_tools import (
    AdjustPanel,
    AssistantPanel,
    CommandsPanel,
    CropPanel,
    FiltersPanel,
    LooksPanel,
    PipelinesPanel,
    SelectPanel,
    TextPanel,
    describe_layer,
    filter_name,
    flatten,
    readable,
    when,
)
from image_studio.desktop.theme import label

TOOLS = [
    ('assistant', 'Assistant', 'sparkles', AssistantPanel),
    ('pipelines', 'Pipelines', 'zap', PipelinesPanel),
    ('adjust', 'Adjust', 'sliders-horizontal', AdjustPanel),
    ('looks', 'Looks', 'palette', LooksPanel),
    ('crop', 'Crop', 'crop', CropPanel),
    ('select', 'Select', 'scan-search', SelectPanel),
    ('text', 'Text', 'type', TextPanel),
    ('filters', 'Filters', 'wand-sparkles', FiltersPanel),
    ('all', 'All tools', 'command', CommandsPanel),
]
CANVAS_SIZES = [
    ('Landscape 1600 × 1000', 1600, 1000), ('Square 1080 × 1080', 1080, 1080),
    ('Portrait 1080 × 1350', 1080, 1350), ('Story 1080 × 1920', 1080, 1920),
    ('Full HD 1920 × 1080', 1920, 1080), ('A4 at 150 ppi 1240 × 1754', 1240, 1754),
]
EXPORTS = [('psd', 'PSD · layered, for Photoshop'), ('pcraft', 'PCraft · native, every layer'),
           ('tif', 'TIFF · print'), ('png', 'PNG · lossless'), ('jpg', 'JPEG · sharing'), ('webp', 'WebP · web')]
BLENDS = ['Normal', 'Multiply', 'Screen', 'Overlay', 'Soft Light', 'Hard Light', 'Darken', 'Lighten', 'Color Dodge',
          'Color Burn', 'Difference', 'Hue', 'Saturation', 'Color', 'Luminosity']
DOCUMENTS = 'Photos and documents (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.psd *.psb *.pcraft *.ora *.bmp)'
SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.psd', '.psb', '.pcraft', '.ora', '.bmp'}
MAX_FILE = 100_000_000
ZOOMS = [0, 25, 50, 100, 200]
WIDE = 1180  # below this page width the layers and the tool panel take turns
MARK_LIMIT = 100
POINT_LIMIT = 2000


def stroke(points, box):
    """A mark's points (0..1 of the document) as a path over box."""
    path = QPainterPath(QPointF(box.left() + points[0][0] * box.width(), box.top() + points[0][1] * box.height()))
    for x, y in points[1:]:
        path.lineTo(box.left() + x * box.width(), box.top() + y * box.height())
    return path


class ElidedLabel(QLabel):
    """One line of text that ends in … when the room runs out, instead of being cut off."""

    def __init__(self, text, role):
        super().__init__()
        self.setProperty('role', role)
        self.full = text
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full = text
        self.setToolTip(text if len(text) > 30 else '')
        self.fit()

    def fit(self):
        super().setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideMiddle, self.width()))

    def text(self):
        return self.full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


class DocumentCanvas(QWidget):
    """The document preview: fitted or zoomed, a draggable before/after split, plan regions and marked areas."""

    marks_changed = Signal()
    drawing_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.current = self.original = None  # QPixmaps of the preview renders
        self.document_size = None  # the document's real size in pixels
        self.zoom = 0  # 0 fits the space
        self.compare = False
        self.split = 0.5
        self.regions, self.highlight = [], None
        self.marks = []  # dict(tool, points [(x, y) as 0..1], size as a share of the width)
        self.tool = None  # the marking tool while marking is on
        self.tool_choice = 'brush'
        self.brush = 0.03
        self.draft = None
        self.pointer = None
        self.dragging = False
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)

    def set_document(self, size):
        if size != self.document_size:
            self.document_size = size
            self.set_zoom(self.zoom)
        self.update()

    def set_zoom(self, zoom):
        self.zoom = zoom
        if zoom and self.document_size:
            self.setMinimumSize(round(self.document_size.width() * zoom / 100) + 40,
                                round(self.document_size.height() * zoom / 100) + 40)
        else:
            self.setMinimumSize(200, 200)
        self.update()

    def set_tool(self, tool):
        if self.draft is not None and tool != self.draft['tool']:
            self.finish(False)
        self.tool = tool
        self.setCursor(Qt.CursorShape.CrossCursor if tool or self.compare else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_marks(self, marks):
        self.marks = marks
        self.update()
        self.marks_changed.emit()

    def target(self):
        if self.document_size is None or self.current is None:
            return QRectF()
        area = QRectF(self.rect()).adjusted(20, 20, -20, -20)
        width, height = self.document_size.width(), self.document_size.height()
        scale = self.zoom / 100 if self.zoom else min(area.width() / width, area.height() / height)
        box = QRectF(0, 0, width * scale, height * scale)
        box.moveCenter(area.center())
        if box.left() < area.left():
            box.moveLeft(area.left())
        if box.top() < area.top():
            box.moveTop(area.top())
        return box

    def at(self, position):
        box = self.target()
        return (min(max((position.x() - box.left()) / box.width(), 0), 1),
                min(max((position.y() - box.top()) / box.height(), 0), 1))

    # Painting a marked area or moving the split ---------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.target().isEmpty():
            return
        if self.compare:
            self.dragging = True
            self.move_split(event.position())
        elif self.tool and self.draft is None and len(self.marks) < MARK_LIMIT:
            self.draft = dict(tool=self.tool, size=self.brush, points=[self.at(event.position())])
            self.drawing_changed.emit(True)
            self.update()

    def move_split(self, position):
        box = self.target()
        self.split = min(max((position.x() - box.left()) / box.width(), 0), 1)
        self.update()

    def mouseMoveEvent(self, event):
        self.pointer = event.position()
        if self.dragging:
            self.move_split(event.position())
        elif self.draft is not None:
            points, box = self.draft['points'], self.target()
            point = self.at(event.position())
            last = points[-1]
            if len(points) < POINT_LIMIT and ((point[0] - last[0]) * box.width()) ** 2 + (
                    (point[1] - last[1]) * box.height()) ** 2 >= 1:
                points.append(point)
        if self.tool or self.draft is not None:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.dragging = False
        if self.draft is not None:
            self.finish(True)

    def finish(self, commit):
        mark, self.draft = self.draft, None
        self.drawing_changed.emit(False)
        if commit and mark and (mark['tool'] != 'lasso' or len(mark['points']) >= 3):
            self.set_marks([*self.marks, mark])
        else:
            self.update()

    def leaveEvent(self, event):
        self.pointer = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.CANVAS))
        box = self.target()
        if box.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(box.adjusted(-1, -1, 1, 1), QColor(0, 0, 0, 28))  # a hairline, so white photos stand out
        painter.drawPixmap(box, self.current, QRectF(self.current.rect()))
        if self.compare and self.original is not None and not self.original.isNull():
            self.paint_compare(painter, box)
            return
        if not self.marks and self.draft is None:
            self.paint_regions(painter, box)
        if self.marks or self.draft is not None:
            self.paint_marks(painter, box)
        if self.tool in ('brush', 'erase') and self.pointer is not None and box.contains(self.pointer):
            radius = self.brush * box.width() / 2
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
            painter.drawEllipse(self.pointer, radius, radius)
            painter.setPen(QPen(QColor('#f3f5f1'), 1.2))
            painter.drawEllipse(self.pointer, radius, radius)

    def paint_compare(self, painter, box):
        x = box.left() + box.width() * self.split
        painter.save()
        painter.setClipRect(QRectF(box.left(), box.top(), x - box.left(), box.height()))
        painter.drawPixmap(box, self.original, QRectF(self.original.rect()))
        painter.restore()
        painter.setPen(QPen(QColor('#f3f5f1'), 2))
        painter.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
        painter.setBrush(QColor('#f3f5f1'))
        painter.drawEllipse(QPointF(x, box.center().y()), 9, 9)
        for text, left in (('Original', True), ('Current', False)):
            width = painter.fontMetrics().horizontalAdvance(text) + 16
            tag = QRectF(box.left() + 10 if left else box.right() - 10 - width, box.top() + 10, width, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(tag, 6, 6)
            painter.setPen(QColor('#f3f5f1'))
            painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)

    def paint_regions(self, painter, box):
        for region in self.regions:
            on = self.highlight is None or self.highlight == region.get('requirement')
            color = QColor(theme.ACCENT)
            color.setAlpha(255 if on else 70)
            for index, (x, y, w, h) in enumerate(region.get('boxes') or []):
                area = QRectF(box.left() + x * box.width(), box.top() + y * box.height(), w * box.width(),
                              h * box.height())
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
                painter.drawRoundedRect(area, 4, 4)
                if index == 0 and on and region.get('label'):
                    text = region['label']
                    width = painter.fontMetrics().horizontalAdvance(text) + 12
                    tag = QRectF(area.left(), max(area.top() - 22, box.top()), width, 20)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(theme.ACCENT))
                    painter.drawRoundedRect(tag, 4, 4)
                    painter.setPen(QColor(theme.ON_ACCENT))
                    painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)

    def paint_marks(self, painter, box):
        # Marks go on a layer of their own, so erasing takes away only what was marked.
        ratio = self.devicePixelRatioF()
        layer = QImage(self.size() * ratio, QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        brush = QPainter(layer)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.setClipRect(box)
        lime = QColor(theme.ACCENT)
        for mark in [*self.marks, *([self.draft] if self.draft else [])]:
            erase = mark['tool'] == 'erase'
            brush.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear if erase
                                     else QPainter.CompositionMode.CompositionMode_SourceOver)
            path = stroke(mark['points'], box)
            if mark['tool'] == 'lasso':
                if self.draft is mark:
                    brush.setPen(QPen(lime, 2))
                    brush.setBrush(Qt.BrushStyle.NoBrush)
                    brush.drawPath(path)
                else:
                    path.closeSubpath()
                    path.setFillRule(Qt.FillRule.OddEvenFill)
                    brush.fillPath(path, lime)
            else:
                brush.setPen(QPen(lime, mark['size'] * box.width(), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
                if len(mark['points']) == 1:
                    brush.drawPoint(path.pointAtPercent(0))
                else:
                    brush.drawPath(path)
        brush.end()
        painter.setOpacity(0.5)
        painter.drawImage(0, 0, layer)
        painter.setOpacity(1)


class LayerRow(QFrame):
    """One layer: an eye to hide or show it, and its name, kind and details; clicking selects it."""

    def __init__(self, layer, depth, active, studio):
        super().__init__()
        self.layer, self.studio = layer, studio
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f'LayerRow {{ background: {theme.ACCENT_SOFT if active else "transparent"}; '
            f'border: 1px solid {theme.ACCENT_LINE if active else "transparent"}; border-radius: 7px; }} '
            'QLabel { background: transparent; }')
        row = QHBoxLayout(self)
        row.setContentsMargins(4 + depth * 14, 3, 8, 3)
        row.setSpacing(6)
        visible = layer.get('visible', True)
        self.eye = QPushButton(theme.icon('eye' if visible else 'eye-off', theme.TEXT if visible else theme.MUTED), '')
        self.eye.setProperty('kind', 'flat')
        name = readable(layer.get('name'))
        self.eye.setToolTip(f'{"Hide" if visible else "Show"} {name}')
        self.eye.clicked.connect(lambda: studio.commands(
            [dict(command='layer.setProps', params=dict(layer=layer['id'], visible=not visible),
                  label=f'{"Hide" if visible else "Show"} {name}')], f'{"Hide" if visible else "Show"} {name}'))
        row.addWidget(self.eye)
        kind = label('')
        kind.setPixmap(theme.icon(self.kind_icon(), theme.MUTED).pixmap(14, 14))
        row.addWidget(kind)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = label('', 'value' if active else '')
        title.setText(title.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 170 - depth * 14))
        title.setMinimumWidth(40)
        text.addWidget(title)
        details = [layer.get('kind', '')]
        if layer.get('hasMask'):
            details.append('mask')
        filters = len(layer.get('smartFilters') or [])
        if filters:
            details.append(f'{filters} filter{"s" if filters > 1 else ""}')
        if (layer.get('opacity') or 1) < 1:
            details.append(f'{round(layer["opacity"] * 100)}%')
        if layer.get('clipped'):
            details.append('clipped')
        text.addWidget(label(' · '.join(details), 'small'))
        row.addLayout(text, 1)
        if not visible:
            title.setProperty('role', 'muted')
        self.setToolTip(name)

    def kind_icon(self):
        layer = self.layer
        if layer.get('kind') == 'Type':
            return 'type'
        if layer.get('kind') == 'Adjustment':
            return 'sliders-horizontal'
        if layer.get('kind') == 'Fill':
            return 'square'
        if str(layer.get('name', '')).startswith(('AI', 'Removed')):
            return 'sparkles'
        return 'image'

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            name = readable(self.layer.get('name'))
            self.studio.commands([dict(command='layer.select', params=dict(layer=self.layer['id']),
                                       label=f'Select {name}')], f'Select {name}')


class Inspector(QWidget):
    """Layers with the selected one's properties, the revision history, and the PhotoCraft desktop hand-off."""

    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.setObjectName('Panel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(300)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(10)
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.tabs = QButtonGroup(self)
        for index, (text, icon) in enumerate((('Layers', 'layers'), ('History', 'history'))):
            button = QPushButton(theme.icon(icon), text)
            button.setCheckable(True)
            button.setProperty('kind', 'tile')
            self.tabs.addButton(button, index)
            tabs.addWidget(button, 1)
        self.tabs.button(0).setChecked(True)
        self.tabs.idClicked.connect(lambda index: self.pages.setCurrentIndex(index))
        column.addLayout(tabs)
        self.pages = QStackedWidget()
        column.addWidget(self.pages, 1)

        self.layer_scroll = QScrollArea()
        self.layer_scroll.setWidgetResizable(True)
        self.layer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layers = Box()
        layers_column = QVBoxLayout(layers)
        layers_column.setContentsMargins(0, 0, 6, 0)
        layers_column.setSpacing(10)
        self.layer_list = Box()
        self.layer_rows = QVBoxLayout(self.layer_list)
        self.layer_rows.setContentsMargins(0, 0, 0, 0)
        self.layer_rows.setSpacing(2)
        layers_column.addWidget(self.layer_list)
        self.properties = self.build_properties()
        layers_column.addWidget(self.properties)
        layers_column.addStretch()
        self.layer_scroll.setWidget(layers)
        self.pages.addWidget(self.layer_scroll)

        history = QScrollArea()
        history.setWidgetResizable(True)
        history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list = Box()
        self.history_rows = QVBoxLayout(self.history_list)
        self.history_rows.setContentsMargins(0, 0, 4, 0)
        self.history_rows.setSpacing(2)
        history.setWidget(self.history_list)
        self.pages.addWidget(history)

        column.addWidget(rule())
        column.addWidget(label('CONTINUE IN PHOTOCRAFT', 'eyebrow'))
        column.addWidget(label('Open a native copy for hands-on painting. Save it there, then bring the changes back.',
                               'small', wrap=True))
        row = QHBoxLayout()
        self.desktop = QPushButton(theme.icon('folder-open'), 'Open desktop')
        self.desktop.clicked.connect(lambda: studio.operation(dict(action='desktop')))
        row.addWidget(self.desktop)
        self.sync_button = QPushButton(theme.icon('refresh-cw'), 'Sync saved changes')
        self.sync_button.clicked.connect(lambda: studio.operation(dict(action='sync')))
        row.addWidget(self.sync_button)
        row.addStretch()
        column.addLayout(row)
        self.shown = None
        self.opacity_timer = QTimer(self)
        self.opacity_timer.setSingleShot(True)
        self.opacity_timer.setInterval(500)
        self.opacity_timer.timeout.connect(self.set_opacity)

    def build_properties(self):
        box = QFrame()
        box.setProperty('card', True)
        column = QVBoxLayout(box)
        column.setContentsMargins(12, 10, 12, 12)
        column.setSpacing(6)
        column.addWidget(label('SELECTED LAYER', 'eyebrow'))
        self.description = label('', 'small', wrap=True)
        column.addWidget(self.description)
        column.addWidget(label('Name', 'small'))
        self.name = QLineEdit()
        self.name.editingFinished.connect(self.rename)
        column.addWidget(self.name)
        self.opacity = Range('Opacity', 0, 100)
        self.opacity.changed.connect(lambda _: None if self.opacity.slider.isSliderDown() else self.opacity_timer.start())
        self.opacity.slider.sliderReleased.connect(self.set_opacity)
        column.addWidget(self.opacity)
        column.addWidget(label('Blend mode', 'small'))
        self.blend = QComboBox()
        self.blend.addItems(BLENDS)
        self.blend.activated.connect(self.set_blend)
        column.addWidget(self.blend)
        self.filters = Box()
        self.filter_rows = QVBoxLayout(self.filters)
        self.filter_rows.setContentsMargins(0, 4, 0, 0)
        self.filter_rows.setSpacing(2)
        column.addWidget(self.filters)
        self.delete = QPushButton(theme.icon('trash-2', theme.DANGER), 'Delete layer')
        self.delete.setProperty('kind', 'danger')
        self.delete.clicked.connect(self.delete_layer)
        column.addWidget(self.delete, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def active(self):
        document = self.studio.document
        if document is None:
            return None
        state = document['state']
        return next((layer for layer, _ in flatten(state.get('layers')) if layer.get('id') == state.get('activeLayer')),
                    None)

    def run(self, command, params, title):
        self.studio.commands([dict(command=command, params=params, label=title)], title)

    def rename(self):
        layer, name = self.active(), self.name.text().strip()
        if layer is not None and name and name != readable(layer.get('name')) and not self.studio.busy:
            self.run('layer.renameLayer', dict(layer=layer['id'], name=name), f'Rename to {name}')

    def set_opacity(self):
        self.opacity_timer.stop()
        layer = self.active()
        if layer is not None and round((layer.get('opacity') or 0) * 100) != self.opacity.value():
            self.run('layer.setProps', dict(layer=layer['id'], opacity=self.opacity.value() / 100),
                     'Change layer opacity')

    def set_blend(self, _):
        layer, blend = self.active(), self.blend.currentText()
        if layer is not None and blend != (layer.get('blend') or 'Normal'):
            self.run('layer.setProps', dict(layer=layer['id'], blend=blend), f'Blend {blend}')

    def delete_layer(self):
        layer = self.active()
        if layer is None:
            return
        name = readable(layer.get('name'))
        answer = QMessageBox.question(self, 'Delete layer', f'Delete the layer “{name}”? You can undo this.')
        if answer == QMessageBox.StandardButton.Yes:
            self.run('layer.delete', dict(layer=layer['id']), f'Delete {name}')

    def show_document(self):
        studio, document = self.studio, self.studio.document
        key = (document and document['revision'], document and document['cursor'], studio.busy)
        if key == self.shown:
            return
        self.shown = key
        busy = studio.busy
        AssistantPanel.clear(self.layer_rows)
        AssistantPanel.clear(self.history_rows)
        layers = flatten(document['state'].get('layers')) if document else []
        active = self.active()
        if document is None:
            empty = label('Your layers will appear here. Every edit gets its own named layer, so you can hide, fade '
                          'or delete it later.', 'small', wrap=True)
            self.layer_rows.addWidget(empty)
            self.history_rows.addWidget(label('Your revisions will appear here. Click one to return to it.', 'small',
                                              wrap=True))
        for layer, depth in layers:
            row = LayerRow(layer, depth, layer is active, studio)
            row.setEnabled(not busy)
            self.layer_rows.addWidget(row)
        for index, entry in enumerate((document or {}).get('history') or []):
            current = index == document['cursor']
            button = QPushButton(theme.icon('check', theme.ACCENT) if current else theme.icon('history', theme.MUTED), '')
            button.setMinimumWidth(10)
            text = f'{index + 1}.  {readable(entry.get("label"))}'
            button.setText(' ' + button.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 215)
                           .replace('&', '&&'))
            button.setStyleSheet('text-align: left;' + (f' color: {theme.MUTED};' if index > document['cursor'] else ''))
            button.setToolTip(f'{readable(entry.get("label"))} · {when(entry.get("created"))}')
            button.setEnabled(not busy and not current)
            button.setCheckable(True)
            button.setChecked(current)
            button.clicked.connect(lambda _=False, index=index: studio.operation(dict(action='goto', index=index)))
            self.history_rows.addWidget(button)
        self.history_rows.addStretch()

        self.properties.setVisible(active is not None)
        if active is not None:
            self.description.setText(readable(describe_layer(active)))
            if not self.name.hasFocus():
                self.name.setText(readable(active.get('name')))
            self.opacity.setValue(round((active.get('opacity') if active.get('opacity') is not None else 1) * 100))
            self.blend.setCurrentText(active.get('blend') or 'Normal')
            AssistantPanel.clear(self.filter_rows)
            filters = active.get('smartFilters') or []
            self.filters.setVisible(bool(filters))
            if filters:
                self.filter_rows.addWidget(label('Smart filters', 'small'))
            for index, item in enumerate(filters):
                box = QCheckBox(filter_name(item.get('command', '')))
                box.setChecked(bool(item.get('visible', True)))
                box.toggled.connect(lambda on, index=index, layer=active['id']: self.run(
                    'layer.smartFilter.setVisible', dict(layer=layer, index=index, visible=on), 'Toggle smart filter'))
                self.filter_rows.addWidget(box)
            for widget in (self.name, self.opacity, self.blend, self.filters):
                widget.setEnabled(not busy)
            self.delete.setEnabled(not busy and len(layers) > 1)
        self.desktop.setEnabled(document is not None and not busy)
        self.sync_button.setVisible(bool(document and document.get('desktop')))
        self.sync_button.setEnabled(not busy)


class PhotoCraftPage(QWidget):
    def __init__(self, client, library, notify, store):
        super().__init__()
        self.client, self.library, self.notify = client, library, notify
        self.store = store  # returns the QSettings the studio is remembered in
        self.ready = False
        self.capabilities = None
        self.document = None
        self.plan_data = None
        self.job = None  # the latest job
        self.active = None  # the job being followed
        self.job_kind = ''
        self.pending = False  # a request is on its way
        self.failures = 0
        self.area = False  # the assistant edits only the marked area
        self.renders = {}  # preview images by address (revisions never change)
        self.wanted = {}  # the preview addresses the canvas is waiting for
        self.recent = []
        self.side = 'tools'  # in a narrow window: which of the tool panel and the layers is shown
        self.show_layers = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.top_bar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.rail())
        self.tool_area = QWidget()
        self.tool_area.setObjectName('Panel')
        self.tool_area.setProperty('side', 'left')
        self.tool_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.tool_area.setFixedWidth(352)  # room for the scroll bar on short windows
        tool_column = QVBoxLayout(self.tool_area)
        tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_stack = QStackedWidget()
        tool_column.addWidget(self.tool_stack)
        self.panels = {}
        for key, _, _, kind in TOOLS:
            self.panels[key] = kind(self)
            self.tool_stack.addWidget(self.panels[key])
        body.addWidget(self.tool_area)
        body.addWidget(self.stage(), 1)
        self.inspector = Inspector(self)
        body.addWidget(self.inspector)
        layout.addLayout(body, 1)
        self.assistant = self.panels['assistant']

        self.setAcceptDrops(True)
        for keys, action in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo),
                             ('Ctrl+O', self.choose_file), ('Ctrl+Return', self.plan_shortcut),
                             ('Ctrl+Enter', self.plan_shortcut)):
            shortcut = QShortcut(QKeySequence(keys), self, action)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # text boxes keep their own
        library.changed.connect(self.show_library)
        self.poller = QTimer(self)
        self.poller.setSingleShot(True)
        self.poller.timeout.connect(self.poll)
        try:
            saved = json.loads(self.store().value('photocraft/settings', '{}') or '{}')
        except (TypeError, ValueError):
            saved = {}
        saved = saved if isinstance(saved, dict) else {}
        self.show_layers = saved.get('layers', True) is not False
        self.choose_tool(saved.get('tool') if saved.get('tool') in self.panels else 'assistant', remember=False)
        self.render()

    # Layout ----------------------------------------------------------------------------

    def top_bar(self):
        bar = QWidget()
        bar.setObjectName('PageHeader')
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        bar.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 0, 16, 0)
        row.setSpacing(6)
        title = QVBoxLayout()
        title.setSpacing(0)
        self.title = ElidedLabel('PhotoCraft', 'heading')
        title.addWidget(self.title)
        self.subtitle = ElidedLabel('', 'small')
        title.addWidget(self.subtitle)
        row.addLayout(title, 1)

        def icon_button(icon, tip, slot):
            button = QPushButton(theme.icon(icon), '')
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
            return button

        self.undo_button = icon_button('undo-2', 'Undo (Ctrl + Z)', self.undo)
        self.redo_button = icon_button('redo-2', 'Redo (Ctrl + Y)', self.redo)
        row.addSpacing(6)
        self.compare = QPushButton(theme.icon('arrow-left-right'), 'Compare')
        self.compare.setCheckable(True)
        self.compare.setToolTip('Drag across the photo to compare the original with the current version')
        self.compare.toggled.connect(self.set_compare)
        row.addWidget(self.compare)
        self.zoom = QComboBox()
        for zoom in ZOOMS:
            self.zoom.addItem(f'{zoom}%' if zoom else 'Fit', zoom)
        self.zoom.setToolTip('Zoom')
        self.zoom.currentIndexChanged.connect(lambda _: self.canvas.set_zoom(self.zoom.currentData()))
        row.addWidget(self.zoom)
        row.addSpacing(6)

        self.open_button = QToolButton()
        self.open_button.setText('Open')
        self.open_button.setIcon(theme.icon('folder-open'))
        self.open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.open_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.open_menu = QMenu(self.open_button)
        self.open_menu.aboutToShow.connect(self.fill_open_menu)
        self.open_button.setMenu(self.open_menu)
        row.addWidget(self.open_button)
        self.export_button = QToolButton()
        self.export_button.setText('Export')
        self.export_button.setIcon(theme.icon('arrow-down-to-line', theme.ON_ACCENT))
        self.export_button.setProperty('kind', 'primary')
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.export_button)
        for kind, text in EXPORTS:
            menu.addAction(text, lambda kind=kind: self.export(kind))
        self.export_button.setMenu(menu)
        row.addWidget(self.export_button)
        self.layers_button = icon_button('panel-right', 'Show or hide the layers', self.flip_layers)
        self.layers_button.setCheckable(True)
        return bar

    def rail(self):
        rail = QWidget()
        rail.setObjectName('Sidebar')
        rail.setFixedWidth(76)
        column = QVBoxLayout(rail)
        column.setContentsMargins(6, 10, 6, 10)
        column.setSpacing(4)
        self.rail_buttons = QButtonGroup(self)
        for index, (key, text, icon, _) in enumerate(TOOLS):
            button = QToolButton()
            button.setText(text)
            button.setIcon(theme.icon(icon, theme.MUTED))
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setProperty('rail', True)
            button.setProperty('tool', key)
            button.setMinimumWidth(64)
            button.clicked.connect(lambda _=False, key=key: self.choose_tool(key))
            self.rail_buttons.addButton(button, index)
            column.addWidget(button)
        column.addStretch()
        return rail

    def stage(self):
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(16, 14, 16, 12)
        column.setSpacing(10)
        self.picker = self.library_picker()
        column.addWidget(self.picker)
        self.stack = QStackedLayout()
        self.stack.addWidget(self.empty_state())
        self.canvas = DocumentCanvas()
        self.canvas.marks_changed.connect(self.marks_changed)
        self.canvas.drawing_changed.connect(lambda _: self.sync())
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setWidget(self.canvas)
        self.scroller.setStyleSheet(f'QScrollArea {{ background: {theme.CANVAS}; border-radius: 10px; }}')
        self.stack.addWidget(self.scroller)
        holder = Box()
        holder.setLayout(self.stack)
        column.addWidget(holder, 1)

        self.status = QFrame()
        self.status.setProperty('card', True)
        status = QVBoxLayout(self.status)
        status.setContentsMargins(12, 6, 6, 8)
        status.setSpacing(4)
        line = QHBoxLayout()
        self.dot = label('')
        line.addWidget(self.dot)
        self.message = label('Ready. Each edit lands on its own layer; the original is kept.', 'small', wrap=True)
        self.message.setMinimumWidth(100)
        line.addWidget(self.message, 1)
        self.stop = QPushButton(theme.icon('square', theme.MUTED), 'Stop')
        self.stop.setProperty('kind', 'flat')
        self.stop.clicked.connect(self.cancel)
        line.addWidget(self.stop)
        status.addLayout(line)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        status.addWidget(self.progress)
        column.addWidget(self.status)
        return area

    def empty_state(self):
        target = QFrame()
        target.setProperty('stage', True)
        column = QVBoxLayout(target)
        column.setContentsMargins(28, 24, 28, 24)
        column.setSpacing(8)
        column.addStretch(1)
        symbol = label('')
        symbol.setPixmap(theme.icon('layers', theme.FAINT).pixmap(38, 38))
        symbol.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(symbol)
        for text, role in (('Open a photo or document', 'heading'),
                           (('Then describe the edit, or use the tools on the left. Every change lands on its own '
                             'layer, and every revision is kept.'), 'muted')):
            widget = label(text, role, wrap=True)
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(widget)
        column.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.empty_open = QPushButton(theme.icon('upload', theme.ON_ACCENT), 'Open a file…')
        self.empty_open.setProperty('kind', 'primary')
        self.empty_open.clicked.connect(self.choose_file)
        buttons.addWidget(self.empty_open)
        self.empty_library = QPushButton(theme.icon('images'), 'From the library')
        self.empty_library.clicked.connect(self.open_picker)
        buttons.addWidget(self.empty_library)
        buttons.addStretch()
        column.addLayout(buttons)
        self.empty_note = label('PSD · PSB · PCraft · TIFF · PNG · JPEG · WebP · drop a file here', 'small', wrap=True)
        self.empty_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.empty_note)
        column.addStretch(1)
        return target

    def library_picker(self):
        picker = QFrame()
        picker.setProperty('card', True)
        column = QVBoxLayout(picker)
        column.setContentsMargins(12, 8, 8, 10)
        column.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label('Open from your library', 'value'))
        head.addStretch()
        close = QPushButton(theme.icon('x', theme.MUTED), '')
        close.setProperty('kind', 'flat')
        close.setToolTip('Close')
        close.clicked.connect(lambda: picker.setVisible(False))
        head.addWidget(close)
        column.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(104)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip = Box()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.picks, self.pick_items = [], []
        for index in range(24):
            thumb = Thumb(self.library.model, 84)
            thumb.setFixedWidth(84)
            thumb.clicked.connect(lambda _=False, index=index: self.open_library(self.pick_items[index]))
            row.addWidget(thumb)
            self.picks.append(thumb)
        row.addStretch()
        scroll.setWidget(strip)
        column.addWidget(scroll)
        picker.setVisible(False)
        return picker

    def open_picker(self):
        self.picker.setVisible(True)
        self.show_library()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def arrange(self):
        """Wide: the tools and the layers side by side. Narrow: they take turns, so the photo keeps its room."""
        wide = self.width() >= WIDE
        self.tool_area.setVisible(wide or self.side == 'tools')
        self.inspector.setVisible(self.show_layers if wide else self.side == 'layers')
        self.layers_button.setChecked(not self.inspector.isHidden())

    # Settings and simple state ----------------------------------------------------------

    def remember(self):
        tool = self.rail_buttons.checkedButton()
        self.store().setValue('photocraft/settings', json.dumps(dict(
            tool=tool.property('tool') if tool else 'assistant', layers=self.show_layers,
            workspace=self.document['id'] if self.document else None,
            job=self.active)))

    def saved(self):
        try:
            value = json.loads(self.store().value('photocraft/settings', '{}') or '{}')
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def choose_tool(self, key, remember=True):
        for button in self.rail_buttons.buttons():
            on = button.property('tool') == key
            button.setChecked(on)
            icon = next(icon for tool, _, icon, _ in TOOLS if tool == button.property('tool'))
            button.setIcon(theme.icon(icon, theme.ACCENT if on else theme.MUTED))
        self.tool_stack.setCurrentWidget(self.panels[key])
        self.side = 'tools'
        self.arrange()
        self.update_marking()
        if remember:
            self.remember()

    def flip_layers(self):
        if self.width() >= WIDE:
            self.show_layers = not self.show_layers
        else:
            self.side = 'tools' if self.side == 'layers' else 'layers'
        self.arrange()
        self.remember()

    @property
    def busy(self):
        return self.pending or self.active is not None

    def set_compare(self, on):
        self.canvas.compare = on
        if on and self.area:
            self.set_area(False)
        self.update_marking()

    def set_area(self, on):
        self.area = on
        if on:
            self.compare.setChecked(False)
        self.plan_data = None
        self.canvas.highlight = None
        self.update_marking()
        self.render()

    def set_area_tool(self, tool):
        self.canvas.tool_choice = tool
        self.compare.setChecked(False)
        self.update_marking()
        self.sync()

    def set_brush(self, size):
        self.canvas.brush = size
        self.canvas.update()

    def update_marking(self):
        marking = (self.area and self.tool_stack.currentWidget() is self.assistant and not self.busy
                   and not self.canvas.compare and self.document is not None)
        self.canvas.set_tool(self.canvas.tool_choice if marking else None)

    def marks_changed(self):
        self.plan_data = None
        self.canvas.highlight = None
        self.render()

    def undo_mark(self):
        if self.canvas.marks and not self.busy:
            self.canvas.set_marks(self.canvas.marks[:-1])

    def clear_marks(self):
        if self.canvas.marks and not self.busy:
            self.canvas.set_marks([])

    def set_highlight(self, requirement):
        self.canvas.highlight = requirement
        self.canvas.update()

    def discard_plan(self):
        self.plan_data = None
        self.render()

    # Drawing everything from the state ------------------------------------------------

    def render(self):
        document = self.document
        installed = bool((self.capabilities or {}).get('installed'))
        if document is not None:
            state = document['state']
            self.title.setText(readable(document['name']))
            self.subtitle.setText(f'{state["width"]} × {state["height"]} px · {state.get("mode", "")} '
                                  f'{state.get("depth", "")}-bit · revision {document["cursor"] + 1} of '
                                  f'{len(document["history"])}')
        else:
            self.title.setText('PhotoCraft studio')
            self.subtitle.setText('PhotoCraft is not installed on this PC' if self.capabilities and not installed
                                  else 'Open a photo or document to begin')
        self.stack.setCurrentIndex(1 if document is not None else 0)
        plan = self.plan_data
        self.canvas.regions = (plan.get('regions') or []) if plan and document and plan.get(
            'revision') == document['revision'] else []
        self.update_marking()
        self.sync()

    def sync(self):
        """Enable what applies to the document and the job, everywhere on the page."""
        document, busy = self.document, self.busy
        installed = bool((self.capabilities or {}).get('installed'))
        self.undo_button.setEnabled(bool(document and document.get('can_undo')) and not busy)
        self.redo_button.setEnabled(bool(document and document.get('can_redo')) and not busy)
        self.compare.setEnabled(document is not None)
        self.zoom.setEnabled(document is not None)
        self.open_button.setEnabled(self.ready and not busy)
        self.export_button.setVisible(document is not None)
        for button in (self.empty_open, self.empty_library):
            button.setEnabled(self.ready and installed and not busy)
        if self.ready and self.capabilities and not installed:
            self.empty_note.setText('PhotoCraft was not found on this PC. Install it, then restart the studio.')
        for thumb in self.picks:
            thumb.setEnabled(not busy and installed)
        running = self.job is not None and self.job.get('state') == 'running'
        self.stop.setVisible(running and self.active is not None)
        self.progress.setVisible(busy)
        self.progress.setValue(max(40, int(((self.job or {}).get('progress') or 0) * 1000)) if running else 40)
        color = theme.WARN if busy else theme.DANGER if (self.job or {}).get('state') == 'error' else theme.ACCENT
        self.dot.setText(f'<span style="color:{color}">●</span>')
        for panel in self.panels.values():
            panel.sync()
        self.inspector.show_document()

    def say(self, text):
        self.message.setText(readable(text))

    # Previews -------------------------------------------------------------------------

    def show_document(self, document):
        """Take a new version of the document: its marks and stale plan belong to the old one."""
        old = self.document
        self.document = document
        if old is None or document is None or old['id'] != document['id'] or old['revision'] != document['revision']:
            if self.canvas.marks or self.canvas.draft:
                self.canvas.draft = None
                self.canvas.set_marks([])
            if self.area:
                self.area = False
            if old is None or document is None or old['id'] != document['id']:
                self.zoom.setCurrentIndex(0)
        if document is None:
            self.canvas.current = self.canvas.original = None
            self.canvas.set_document(None)
        else:
            state = document['state']
            self.canvas.document_size = None
            self.canvas.set_document(QSize(state['width'], state['height']))
            self.fetch(document['preview'], 'current')
            self.fetch(document['original'], 'original')
        self.remember()
        self.render()

    def fetch(self, address, role):
        self.wanted[role] = address
        if address in self.renders:
            self.shown(role, address)
            return

        def loaded(data):
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                return
            if len(self.renders) > 40:
                self.renders.pop(next(iter(self.renders)))
            self.renders[address] = pixmap
            for kind, wanted in self.wanted.items():
                if wanted == address:
                    self.shown(kind, address)

        self.client.bytes(address, loaded, lambda error: self.notify(f'Could not load the preview: {error}',
                                                                     error=True), timeout=120000)

    def shown(self, role, address):
        setattr(self.canvas, role, self.renders[address])
        if role == 'current':
            self.canvas.set_zoom(self.canvas.zoom)
        self.canvas.update()

    # The engine -----------------------------------------------------------------------

    def engine_ready(self):
        self.ready = True
        self.client.get('/api/photocraft/capabilities', self.got_capabilities,
                        lambda error: self.notify(error, error=True), timeout=120000)
        self.client.get('/api/photocraft/fonts', lambda answer: self.panels['text'].set_fonts(answer.get('fonts') or []),
                        None, timeout=60000)
        self.load_recent()
        saved = self.saved()
        if self.document is None and saved.get('workspace'):
            self.client.get(f'/api/photocraft/workspaces/{saved["workspace"]}',
                            lambda document: self.document is None and self.show_document(document), None)
        if saved.get('job') and self.active is None:
            self.follow(saved['job'], 'resume')
        self.render()

    def engine_gone(self):
        self.ready = False
        self.poller.stop()
        self.active, self.pending = None, False
        self.render()

    def refresh(self):
        if self.ready:
            self.load_recent()
            self.show_library()

    def load_recent(self):
        self.client.get('/api/photocraft/workspaces', lambda answer: setattr(self, 'recent', answer.get('workspaces')
                                                                             or []), None)

    def got_capabilities(self, capabilities):
        self.capabilities = capabilities
        commands = capabilities.get('commands') or []
        self.panels['filters'].set_commands(commands)
        self.panels['all'].set_commands(commands, capabilities.get('discovered') or len(commands))
        self.panels['pipelines'].set_pipelines(capabilities.get('pipelines') or [])
        self.render()

    def submit(self, path, body, kind):
        """Start a studio job; while it runs the page follows it."""
        if self.busy:
            self.notify('Wait for the current edit to finish first.', error=True)
            return
        self.pending = True
        self.job_kind = kind
        self.render()

        def started(job):
            self.pending = False
            self.follow(job['id'], kind, job)

        def refused(error):
            self.pending = False
            self.say(error)
            self.notify(error, error=True)
            self.render()

        self.client.post(path, body, started, refused, timeout=120000)

    def follow(self, job_id, kind, job=None):
        self.active, self.failures, self.job_kind = job_id, 0, kind
        self.job = job or dict(id=job_id, state='running', progress=0, message='Working…')
        self.say(self.job.get('message') or '')
        self.remember()
        self.render()
        self.poll()

    def poll(self):
        if self.active is None:
            return
        job_id = self.active
        self.client.get(f'/api/jobs/{job_id}', lambda job: self.polled(job_id, job),
                        lambda error: self.lost(job_id, error), timeout=15000)

    def polled(self, job_id, job):
        if job_id != self.active:
            return
        self.failures = 0
        self.job = job
        self.say(job.get('message') or '')
        if job['state'] == 'running':
            self.sync()
            self.poller.start(POLL_MS)
            return
        self.active = None
        self.accept(job)
        self.remember()

    def accept(self, job):
        """A finished job: its new document version and plan, or why it failed."""
        if job.get('state') == 'error':
            self.notify(readable(job.get('message')), error=True)
        if job.get('workspace'):
            plan = self.plan_data
            self.show_document(job['workspace'])
            if plan and plan.get('revision') != job['workspace']['revision']:
                self.plan_data = None
        if job.get('plan'):
            self.plan_data = job['plan']
        if job.get('workspace') and job.get('state') == 'done':
            self.load_recent()
        self.render()

    def lost(self, job_id, error):
        if job_id != self.active:
            return
        self.failures += 1
        if self.failures >= 5 or 'not found' in error.lower():
            self.active = None
            if self.job and self.job.get('state') == 'running':
                self.job = dict(self.job, state='error', message=f'Lost track of the edit: {error}')
            self.say(f'Lost track of the edit: {error}')
            self.remember()
            self.render()
            return
        self.say('Connection interrupted. Reconnecting…')
        self.poller.start(2500)

    def cancel(self):
        if self.active:
            self.client.post(f'/api/jobs/{self.active}/cancel', {}, lambda _: self.say('Stopping after the current '
                                                                                      'step…'),
                             lambda error: self.notify(error, error=True))

    # What the panels ask for -------------------------------------------------------------

    def edits(self, edits, title):
        if self.document is not None:
            self.submit(f'/api/photocraft/workspaces/{self.document["id"]}/edits',
                        dict(revision=self.document['revision'], edits=edits, label=title[:200]), 'edit')

    def commands(self, commands, title):
        self.operation(dict(commands=commands, label=title[:200]))

    def operation(self, body):
        if self.document is not None:
            self.submit(f'/api/photocraft/workspaces/{self.document["id"]}/operation',
                        dict(revision=self.document['revision'], **body), body.get('action') or 'edit')

    def plan(self, prompt):
        if self.document is None:
            return
        area = dict(marks=[dict(tool=mark['tool'], size=mark['size'], points=[list(point) for point in mark['points']])
                           for mark in self.canvas.marks]) if self.area else None
        self.plan_data = None
        self.canvas.highlight = None
        self.submit(f'/api/photocraft/workspaces/{self.document["id"]}/plan',
                    dict(revision=self.document['revision'], prompt=prompt, area=area), 'plan')

    def plan_shortcut(self):
        if self.tool_stack.currentWidget() is self.assistant:
            self.assistant.plan()

    def apply_plan(self, partial):
        if self.plan_data is not None:
            self.operation(dict(plan_id=self.plan_data['id'], partial=partial))

    def undo(self):
        if self.area and self.canvas.marks and self.tool_stack.currentWidget() is self.assistant:
            self.undo_mark()  # while marking, Ctrl + Z takes back a mark
        elif self.document and self.document.get('can_undo') and not self.busy:
            self.operation(dict(action='undo'))

    def redo(self):
        if self.document and self.document.get('can_redo') and not self.busy:
            self.operation(dict(action='redo'))

    # Opening documents ------------------------------------------------------------------

    def fill_open_menu(self):
        menu = self.open_menu
        menu.clear()
        installed = bool((self.capabilities or {}).get('installed'))
        action = menu.addAction(theme.icon('upload'), 'A photo or document on this PC…', self.choose_file)
        action.setShortcut(QKeySequence('Ctrl+O'))
        menu.addAction(theme.icon('images'), 'A picture from my library', self.open_picker)
        recent = menu.addMenu(theme.icon('history'), 'Recent documents')
        for item in self.recent[:12]:
            recent.addAction(f'{readable(item["name"])}  ·  {when(item.get("updated"))}',
                             lambda ident=item['id']: self.open_workspace(ident))
        recent.setEnabled(bool(self.recent))
        blank = menu.addMenu(theme.icon('plus'), 'New blank canvas')
        for text, width, height in CANVAS_SIZES:
            blank.addAction(text, lambda width=width, height=height: self.new_canvas(width, height))
        for item in menu.actions():
            item.setEnabled(installed and item.isEnabled())

    def new_canvas(self, width, height):
        self.plan_data = None
        self.submit('/api/photocraft/workspaces', dict(name='Untitled canvas', width=width, height=height), 'open')

    def open_workspace(self, ident):
        if self.busy:
            return
        self.plan_data = None
        self.client.get(f'/api/photocraft/workspaces/{ident}', self.show_document,
                        lambda error: self.notify(error, error=True))

    def choose_file(self):
        if self.busy or not self.ready:
            return
        start = Path.home() / 'Pictures'
        path, _ = QFileDialog.getOpenFileName(self, 'Open a photo or document', str(start if start.is_dir() else ''),
                                              DOCUMENTS)
        if path:
            self.open_file(path)

    def open_file(self, path):
        path = Path(path)
        if path.suffix.lower() not in SUFFIXES:
            self.notify('Use PNG, JPEG, WebP, TIFF, PSD, PSB, PCraft, ORA or BMP.', error=True)
            return
        try:
            size = path.stat().st_size
            if not 0 < size <= MAX_FILE:
                raise ValueError('Choose a document under 100 MB.')
            data = path.read_bytes()
        except (OSError, ValueError) as exc:
            self.notify(str(exc), error=True)
            return
        self.upload(path.name, data)

    def upload(self, name, data):
        if self.busy:
            self.notify('Wait for the current edit to finish first.', error=True)
            return
        self.pending = True
        self.job_kind = 'open'
        self.plan_data = None
        self.say('Opening your document…')
        self.render()

        def started(job):
            self.pending = False
            self.picker.setVisible(False)
            self.follow(job['id'], 'open', job)

        def refused(error):
            self.pending = False
            self.say(error)
            self.notify(error, error=True)
            self.render()

        self.client.upload('/api/photocraft/workspaces/import', name, data, started, refused)

    def open_library(self, item):
        """A library picture opens without being downloaded; a PhotoCraft edit comes with its layers."""
        if item is None:
            return
        self.plan_data = None
        self.picker.setVisible(False)
        self.submit('/api/photocraft/workspaces/from-library', dict(name=item['name']), 'open')

    def open_image(self, image, name):
        """A photo that is not in the library (dropped or pasted into Edit), sent as a PNG."""
        if self.busy:
            self.notify('Wait for the current edit to finish first.', error=True)
            return

        def prepared(data, error):
            if error is not None:
                self.notify(str(error), error=True)
                return
            self.upload(str(Path(name).with_suffix('.png').name), data)

        in_background(lambda: png_bytes(image), prepared)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if not self.busy and any(url.isLocalFile() for url in mime.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())
                event.acceptProposedAction()
                return

    def export(self, kind):
        document = self.document
        if document is not None:
            save_to(self, self.client, self.notify,
                    f'/api/photocraft/workspaces/{document["id"]}/export/{document["revision"]}/{kind}',
                    readable(document['name']) or 'photocraft', f'.{kind}', 'Export')

    def show_library(self):
        items = sorted(self.library.all, key=lambda item: item['created'], reverse=True)[:len(self.picks)]
        self.pick_items = items
        if self.picker.isHidden():
            return
        for index, thumb in enumerate(self.picks):
            thumb.setVisible(index < len(items))
            thumb.set_item(items[index] if index < len(items) else None)


def png_bytes(image):
    """A picture as PNG file bytes (the import takes files, not data addresses)."""
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    data = bytes(buffer.data().data())
    if len(data) > MAX_FILE:
        raise ValueError('This picture is too large to open. Please use a smaller one.')
    return data

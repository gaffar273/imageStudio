"""Small form controls shared by the screens: switches, sliders, fold-out sections, thumbnails."""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.theme import label


def cover(target, pixmap):
    """The part of pixmap that fills target without distortion, like CSS object-fit: cover."""
    scale = max(target.width() / pixmap.width(), target.height() / pixmap.height())
    width, height = target.width() / scale, target.height() / scale
    return QRectF((pixmap.width() - width) / 2, (pixmap.height() - height) / 2, width, height)


class Box(QWidget):
    """A plain container. (A bare QWidget would paint the page background over a panel.)"""


HEADER_HEIGHT = 56


class PageHeader(QWidget):
    """The bar along the top of every screen: its name, a short note, and the screen's own actions."""

    def __init__(self, title, note=''):
        super().__init__()
        self.setObjectName('PageHeader')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 0, 16, 0)
        row.setSpacing(8)
        self.title = label(title, 'title')
        row.addWidget(self.title)
        self.note = label(note, 'muted')
        self.note.setVisible(bool(note))
        row.addSpacing(4)
        row.addWidget(self.note)
        row.addStretch()
        self.actions = row

    def add(self, widget):
        self.actions.addWidget(widget)
        return widget

    def set_note(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))


CONTENT_WIDTH = 880


def scroll_page(title, note=''):
    """A scrolling settings page: its title, a line saying what it is for, then the column to fill.

    Returns (page, column). The column is kept to a readable width on wide windows."""
    from PySide6.QtWidgets import QScrollArea

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    outer = QWidget()
    scroll.setWidget(outer)
    row = QHBoxLayout(outer)
    row.setContentsMargins(32, 26, 32, 32)
    body = QWidget()
    body.setMaximumWidth(CONTENT_WIDTH)
    row.addWidget(body, 1)
    row.addStretch(0)
    column = QVBoxLayout(body)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(14)
    column.addWidget(label(title, 'title'))
    if note:
        text = label(note, 'muted', wrap=True)
        column.addWidget(text)
    column.addSpacing(4)
    return scroll, column


def rule(vertical=False):
    """A one-pixel divider."""
    line = QFrame()
    line.setProperty('rule', True)
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


class Toast(QFrame):
    """A short message near the bottom of the window that goes away by itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('Toast')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 9, 16, 9)
        row.setSpacing(9)
        self.symbol = QLabel()
        row.addWidget(self.symbol)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(560)
        row.addWidget(self.text)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        parent.installEventFilter(self)
        self.hide()

    def show_message(self, text, error=False):
        self.text.setText(text)
        self.symbol.setPixmap(theme.icon('circle-alert' if error else 'check', '#ffffff').pixmap(16, 16))
        theme.restyle(self, tone='error' if error else '')
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.timer.start(8000 if error else 4000)

    def place(self):
        """Centered over the screens, just under their header bar, where it covers no buttons."""
        parent = self.parentWidget()
        left = parent.width() - (self.offset() or parent.width())
        self.move(left + (parent.width() - left - self.width()) // 2, HEADER_HEIGHT + 10)

    def offset(self):
        """The width of the screens beside the sidebar (the whole window when there is none)."""
        pages = getattr(self.parentWidget().window(), 'pages', None)
        return pages.width() if pages is not None else 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False


class Flow(QLayout):
    """Lays widgets out in rows, wrapping to the next row when the width runs out; hidden ones take no room."""

    def __init__(self, spacing=6):
        super().__init__()
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)  # spare room in a column goes to its stretch, not between the rows

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def arrange(self, rect, move):
        x, y, row = rect.x(), rect.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, row = rect.x(), y + row + self.spacing(), 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row = max(row, hint.height())
        return y + row - rect.y()


class Switch(QAbstractButton):
    """An on/off switch, drawn like the web studio's toggles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 20)

    def sizeHint(self):
        return QSize(36, 20)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        if not self.isEnabled():
            painter.setOpacity(0.4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACCENT if on else '#d4d4db'))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 35, 19), 9.5, 9.5)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(QPointF(26 if on else 10, 10), 7.5, 7.5)


class Toggle(QWidget):
    """A titled switch with an optional line of explanation; the whole row is clickable."""

    toggled = Signal(bool)

    def __init__(self, title, description=''):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = label(title)
        text.addWidget(self.title)
        self.description = label(description, 'small', wrap=True)
        self.description.setVisible(bool(description))
        text.addWidget(self.description)
        row.addLayout(text, 1)
        self.switch = Switch()
        self.switch.toggled.connect(self.toggled)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.switch.toggle()

    def isChecked(self):
        return self.switch.isChecked()

    def setChecked(self, on):
        self.switch.setChecked(on)

    def set_description(self, text):
        self.description.setText(text)
        self.description.setVisible(bool(text))

    def changeEvent(self, event):
        super().changeEvent(event)
        self.title.setProperty('role', '' if self.isEnabled() else 'muted')
        self.title.style().polish(self.title)


class Range(QWidget):
    """A labelled slider over a number range, with the value shown on the right."""

    changed = Signal(object)

    def __init__(self, title, minimum, maximum, step=1):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 2, 0, 2)
        column.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(title))
        top.addStretch()
        self.shown = label('', 'value')
        top.addWidget(self.shown)
        column.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.valueChanged.connect(self.moved)
        column.addWidget(self.slider)
        self.step = step
        self.set_range(minimum, maximum)

    @property
    def whole(self):
        return float(self.step).is_integer() and float(self.minimum).is_integer()

    def set_range(self, minimum, maximum):
        value = self.value() if hasattr(self, 'minimum') else minimum
        self.minimum, self.maximum = minimum, maximum
        self.slider.blockSignals(True)
        self.slider.setRange(0, round((maximum - minimum) / self.step))
        self.slider.blockSignals(False)
        self.setValue(min(max(value, minimum), maximum))

    def value(self):
        value = self.minimum + self.slider.value() * self.step
        return round(value) if self.whole else round(value, 4)

    def setValue(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(round((min(max(value, self.minimum), self.maximum) - self.minimum) / self.step))
        self.slider.blockSignals(False)
        self.show_value()

    def show_value(self):
        value = self.value()
        self.shown.setText(str(value) if self.whole else f'{value:.2f}'.rstrip('0').rstrip('.'))

    def moved(self, _):
        self.show_value()
        self.changed.emit(self.value())


class Section(QWidget):
    """A heading that folds its body open and closed."""

    def __init__(self, title, icon):
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.header = QPushButton(theme.icon(icon, theme.MUTED), f'  {title}')
        self.header.setProperty('kind', 'fold')
        self.header.setCheckable(True)
        self.header.toggled.connect(self.fold)
        inside = QHBoxLayout(self.header)
        inside.setContentsMargins(0, 0, 10, 0)
        inside.addStretch()
        self.chevron = QLabel()
        self.chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inside.addWidget(self.chevron)
        column.addWidget(self.header)
        self.content = Box()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(4, 4, 4, 8)
        self.body.setSpacing(10)
        column.addWidget(self.content)
        self.fold(False)

    def fold(self, open_):
        self.content.setVisible(open_)
        self.chevron.setPixmap(theme.icon('chevron-down' if open_ else 'chevron-right', theme.MUTED).pixmap(14, 14))

    def set_open(self, open_):
        self.header.setChecked(open_)


class Thumb(QAbstractButton):
    """One library picture as a rounded, cropped thumbnail; it repaints when the picture arrives."""

    def __init__(self, model, height=150):
        super().__init__()
        self.model, self.item = model, None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.setMinimumWidth(min(height, 96))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        model.thumbnail_ready.connect(self.arrived)

    def set_item(self, item):
        self.item = item
        if item is not None:
            prompt = (item.get('metadata') or {}).get('request') or (item.get('metadata') or {}).get('prompt')
            self.setToolTip((prompt or item['name'])[:300])
            self.model.thumbnail(item)
        self.update()

    def arrived(self, key):
        if self.item is not None and self.model.key(self.item) == key:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        shape = QPainterPath()
        shape.addRoundedRect(box, 10, 10)
        painter.setClipPath(shape)
        pixmap = self.model.thumbs.get(self.model.key(self.item)) if self.item else None
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(box, pixmap, cover(box, pixmap))
        else:
            painter.fillRect(box, QColor(theme.RAISED))
        painter.setClipping(False)
        if self.underMouse() or self.hasFocus():
            painter.setPen(QPen(QColor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box, 10, 10)


def shape_icon(width, height, color=theme.MUTED):
    """A small outlined rectangle in the given proportions, for picking an image format."""
    result = QIcon()
    for side in (18, 36):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = (side - 4) / max(width, height)
        w, h = width * scale, height * scale
        painter.setPen(QPen(QColor(color), side / 12))
        painter.drawRoundedRect(QRectF((side - w) / 2, (side - h) / 2, w, h), side / 12, side / 12)
        painter.end()
        result.addPixmap(pixmap)
    return result

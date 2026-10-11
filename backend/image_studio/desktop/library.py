"""My library: every saved picture, searchable, with its details."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.theme import label

CELL = 210  # target card width; the grid divides the row evenly
HEART = 32


def searchable(item):
    meta = item.get('metadata') or {}
    return f"{meta.get('prompt') or ''} {meta.get('request') or ''}".lower()


def prompt_of(item):
    meta = item.get('metadata') or {}
    return meta.get('request') or meta.get('prompt') or ''


class LibraryModel(QAbstractListModel):
    """The visible pictures; thumbnails are fetched only when a card is first painted."""

    thumbnail_ready = Signal(str)  # the key of a thumbnail that just arrived (other screens show them too)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.items = []
        self.favorites = set()
        self.thumbs = {}
        self.loading = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            text = prompt_of(item)
            return text[:300] + ('…' if len(text) > 300 else '') if text else item['name']
        return None

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    @staticmethod
    def key(item):
        return f'{item["name"]}:{item.get("created")}'

    def thumbnail(self, item):
        key = self.key(item)
        if key not in self.thumbs and key not in self.loading:
            self.loading.add(key)
            self.client.bytes(
                item['thumbnail'],
                lambda data, key=key: self.loaded(key, data),
                lambda _, key=key: self.loaded(key, b''),
                timeout=60000,
            )
        return self.thumbs.get(key)

    def loaded(self, key, data):
        self.loading.discard(key)
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self.thumbs[key] = pixmap  # a null pixmap marks a failed one, so it is not retried
        self.thumbnail_ready.emit(key)
        for row, item in enumerate(self.items):
            if self.key(item) == key:
                index = self.index(row)
                self.dataChanged.emit(index, index)


def save_to(parent, client, notify, path, name, suffix, caption):
    """Ask where to save, then download the engine's file at path there."""
    start = Path.home() / 'Pictures'
    target, _ = QFileDialog.getSaveFileName(
        parent, caption, str((start if start.is_dir() else Path.home()) / Path(name).with_suffix(suffix).name),
        f'*{suffix}',
    )
    if not target:
        return

    def write(data):
        try:
            Path(target).write_bytes(data)
            notify(f'Saved {Path(target).name}.')
        except OSError as exc:
            notify(f'Could not save: {exc}', error=True)

    client.bytes(path, write, lambda error: notify(error, error=True), timeout=300000)


def cover(target, pixmap):
    """The part of pixmap that fills target without distortion, like CSS object-fit: cover."""
    scale = max(target.width() / pixmap.width(), target.height() / pixmap.height())
    width, height = target.width() / scale, target.height() / scale
    return QRectF((pixmap.width() - width) / 2, (pixmap.height() - height) / 2, width, height)


class CardDelegate(QStyledItemDelegate):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

    def sizeHint(self, option, index):
        return self.parent().gridSize()

    @staticmethod
    def card(rect):
        return rect.adjusted(6, 6, -6, -6)

    @classmethod
    def heart(cls, rect):
        card = cls.card(rect)
        return QRect(card.right() - HEART - 8, card.top() + 8, HEART, HEART)

    def paint(self, painter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        card = QRectF(self.card(option.rect))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        favorite = item['name'] in self.model.favorites
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        shape = QPainterPath()
        shape.addRoundedRect(card, 12, 12)
        painter.setClipPath(shape)
        pixmap = self.model.thumbnail(item)
        if pixmap is not None and not pixmap.isNull():
            painter.drawPixmap(card, pixmap, cover(card, pixmap))
        else:
            painter.fillRect(card, QColor(theme.RAISED))
        if hovered:
            shade = QRectF(card.left(), card.top() + card.height() * 0.5, card.width(), card.height() * 0.5)
            gradient = QLinearGradient(shade.topLeft(), shade.bottomLeft())
            gradient.setColorAt(0, QColor(0, 0, 0, 0))
            gradient.setColorAt(1, QColor(0, 0, 0, 210))
            painter.fillRect(shade, gradient)
            text = index.data(Qt.ItemDataRole.DisplayRole) or ''
            font = painter.font()
            font.setPointSizeF(9)
            painter.setFont(font)
            box = card.adjusted(12, 0, -12, -10)
            metrics = painter.fontMetrics()
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(box.width() * 2 - 30))
            painter.setPen(QColor('#f3f5f1'))
            painter.drawText(box, Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, text)
        if hovered or favorite:
            heart = QRectF(self.heart(option.rect))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(18, 20, 20, 190))
            painter.drawEllipse(heart)
            symbol = theme.icon('heart', theme.LIME, theme.LIME) if favorite else theme.icon('heart', '#f3f5f1')
            symbol.paint(painter, heart.adjusted(8, 8, -8, -8).toRect())
        painter.setClipping(False)
        if option.state & QStyle.StateFlag.State_HasFocus and self.parent().hasFocus():
            painter.setPen(QColor(theme.LIME))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 12, 12)
        painter.restore()


class Grid(QListView):
    opened = Signal(int)
    favorite = Signal(int)

    def __init__(self, model):
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(CardDelegate(model, self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(40)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setGridSize(QSize(CELL, CELL))

    def resizeEvent(self, event):
        # The viewport's new width, less the room Qt keeps for a scroll bar when laying out.
        width = event.size().width() - self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self)
        columns = max(1, width // CELL)
        side = width // columns
        if self.gridSize().width() != side:
            self.setGridSize(QSize(side, side))
        super().resizeEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            if CardDelegate.heart(self.visualRect(index)).contains(event.position().toPoint()):
                self.favorite.emit(index.row())
            else:
                self.opened.emit(index.row())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.opened.emit(self.currentIndex().row())
            return
        super().keyPressEvent(event)


class ImageView(QWidget):
    """A picture fitted to the space, centered."""

    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.setMinimumSize(320, 320)

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#0d0f0f'))
        if self.pixmap is None or self.pixmap.isNull():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self.rect().adjusted(20, 20, -20, -20)
        size = self.pixmap.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(area.center())
        painter.drawPixmap(target, self.pixmap)


class ImageDetails(QDialog):
    """One picture large, with its prompt and settings; arrow keys move through the library."""

    def __init__(self, page, items, row):
        super().__init__(page.window())
        self.page, self.items, self.row = page, items, row
        self.setWindowTitle('Image details')
        self.resize(1180, 760)
        self.request = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = ImageView()
        layout.addWidget(self.view, 1)

        side = QWidget()
        side.setObjectName('Panel')
        side.setFixedWidth(380)
        column = QVBoxLayout(side)
        column.setContentsMargins(24, 22, 24, 22)
        column.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label('YOUR CREATION', 'eyebrow'))
        top.addStretch()
        close = QPushButton(theme.icon('x', theme.MUTED), '')
        close.setProperty('kind', 'flat')
        close.setToolTip('Close (Esc)')
        close.clicked.connect(self.close)
        top.addWidget(close)
        column.addLayout(top)
        column.addWidget(label('A moment, made real.', 'title'))
        self.date = label('', 'muted')
        column.addWidget(self.date)
        column.addSpacing(6)
        column.addWidget(label('PROMPT', 'eyebrow'))
        self.prompt = label('', wrap=True, selectable=True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.prompt)
        scroll.setMaximumHeight(170)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        column.addWidget(scroll)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.facts = {}
        for position, name in enumerate(['Dimensions', 'Seed', 'Steps', 'Render time', 'Photo style', 'Model']):
            cell = QVBoxLayout()
            cell.setSpacing(1)
            cell.addWidget(label(name, 'small'))
            value = label('—', 'value', selectable=True)
            self.facts[name] = value
            cell.addWidget(value)
            grid.addLayout(cell, position // 2, position % 2)
        column.addLayout(grid)
        column.addSpacing(8)

        def button(text, icon, action, kind=''):
            widget = QPushButton(theme.icon(icon, theme.INK if kind == 'primary' else theme.TEXT), text)
            if kind:
                widget.setProperty('kind', kind)
            widget.clicked.connect(action)
            column.addWidget(widget)
            return widget

        button('Save a copy…', 'arrow-down-to-line', self.save_copy, 'primary')
        if page.edit:
            button('Edit image', 'square-pen', self.edit_image)
        if page.reuse:
            button('Use these settings', 'rotate-ccw', self.use_settings)
        self.psd = button('Save layered PSD…', 'layers', self.save_psd)
        button('Copy prompt', 'file-text', self.copy_prompt)
        button('Open in Krita', 'image-plus', self.open_in_krita)
        self.similar = button('Find similar images', 'search', self.find_similar)
        button('Show in folder', 'folder-open', self.show_in_folder)
        self.heart = QPushButton()
        self.heart.setProperty('kind', 'flat')
        self.heart.clicked.connect(self.toggle_favorite)
        column.addWidget(self.heart)
        column.addStretch()
        column.addWidget(label('← → to move through your library', 'small'))
        layout.addWidget(side)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.browse(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.browse(1))
        self.show_item()

    @property
    def item(self):
        return self.items[self.row]

    def browse(self, step):
        row = self.row + step
        if 0 <= row < len(self.items):
            self.row = row
            self.show_item()

    def show_item(self):
        item = self.item
        meta = item.get('metadata') or {}
        self.date.setText(datetime.fromtimestamp(item['created']).strftime('%d %b %Y, %H:%M'))
        self.prompt.setText(prompt_of(item) or 'No prompt saved for this image.')
        seconds = meta.get('total_seconds')
        facts = {
            'Dimensions': f'{meta["width"]} × {meta["height"]}' if meta.get('width') else '—',
            'Seed': str(meta.get('seed', '—')),
            'Steps': str(meta.get('steps', '—')),
            'Render time': f'{seconds}s' if seconds is not None else '—',
            'Photo style': meta.get('style') or 'Original',
            'Model': (meta.get('model') or 'Unknown').split('/')[-1],
        }
        for name, value in facts.items():
            self.facts[name].setText(value)
        self.psd.setVisible(bool(meta.get('layered_document')))
        self.similar.setEnabled(bool(self.page.config.get('search')))
        self.similar.setToolTip('' if self.similar.isEnabled() else 'Install the image search model first.')
        self.update_heart()
        self.view.set_pixmap(self.page.model.thumbs.get(LibraryModel.key(item)))
        name = item['name']
        self.page.client.bytes(
            item['url'], lambda data, name=name: self.full_image(name, data), None, timeout=120000
        )

    def full_image(self, name, data):
        if name != self.item['name']:
            return  # moved on to another picture meanwhile
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.view.set_pixmap(pixmap)

    def update_heart(self):
        favorite = self.item['name'] in self.page.model.favorites
        self.heart.setIcon(theme.icon('heart', theme.LIME, theme.LIME) if favorite else theme.icon('heart'))
        self.heart.setText('Saved to favorites' if favorite else 'Save to favorites')

    def toggle_favorite(self):
        self.page.toggle_favorite(self.item['name'], self.update_heart)

    def save_to(self, path, suffix, caption):
        save_to(self, self.page.client, self.page.notify, path, self.item['name'], suffix, caption)

    def save_copy(self):
        self.save_to(f'/api/library/{quote(self.item["name"])}/download', '.png', 'Save a copy')

    def save_psd(self):
        self.save_to(f'/api/photocraft/{quote(self.item["name"])}/download', '.psd', 'Save layered PSD')

    def copy_prompt(self):
        QGuiApplication.clipboard().setText(prompt_of(self.item))
        self.page.notify('Prompt copied.')

    def open_in_krita(self):
        self.page.client.post(
            '/api/krita',
            dict(action='open', image=self.item['name']),
            lambda answer: self.page.notify(answer.get('message') or 'Sent to Krita.'),
            lambda error: self.page.notify(error, error=True),
        )

    def use_settings(self):
        item = self.item
        self.close()
        self.page.reuse(item)

    def edit_image(self):
        item = self.item
        self.close()
        self.page.edit(item)

    def find_similar(self):
        name = self.item['name']
        self.close()
        self.page.find_similar(name)

    def show_in_folder(self):
        folder = self.page.library_dir
        if not folder:
            self.page.notify('The engine has not reported its library folder yet.', error=True)
            return
        path = Path(folder) / self.item['name']
        if sys.platform == 'win32':
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class LibraryPage(QWidget):
    changed = Signal()  # the pictures or favorites changed

    def __init__(self, client, notify):
        super().__init__()
        self.client, self.notify = client, notify
        self.reuse = None  # set by the window: load a picture's settings into Create
        self.edit = None  # set by the window: open a picture in Edit
        self.all, self.results, self.results_label = [], None, ''
        self.config, self.library_dir = {}, ''
        self.oldest = False
        self.ready = False
        self.model = LibraryModel(client, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 0)
        layout.setSpacing(6)
        layout.addWidget(label('A COLLECTION OF POSSIBILITIES', 'eyebrow'))
        layout.addWidget(label('Made by your imagination.', 'title'))
        layout.addWidget(label('Every experiment, happy accident, and beautiful idea. Right here.', 'muted'))
        layout.addSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.everything = QPushButton('All creations')
        self.favorites_only = QPushButton(theme.icon('folder-heart'), 'Favorites')
        group = QButtonGroup(self)
        for widget in (self.everything, self.favorites_only):
            widget.setCheckable(True)
            group.addButton(widget)
            bar.addWidget(widget)
        self.everything.setChecked(True)
        group.buttonClicked.connect(lambda _: self.apply())
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search your creations…')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(theme.icon('search', theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.apply())
        self.search.returnPressed.connect(self.visual_search)
        bar.addWidget(self.search, 1)
        self.visual = QPushButton(theme.icon('sparkles'), 'Visual search')
        self.visual.setToolTip('Find pictures by what is in them, not only their prompt words.')
        self.visual.clicked.connect(self.visual_search)
        bar.addWidget(self.visual)
        self.sort = QPushButton(theme.icon('arrow-down-wide-narrow'), '')
        self.sort.clicked.connect(self.flip_sort)
        bar.addWidget(self.sort)
        reload = QPushButton(theme.icon('refresh-cw'), '')
        reload.setToolTip('Reload the library')
        reload.clicked.connect(self.refresh)
        bar.addWidget(reload)
        layout.addLayout(bar)

        self.banner = QFrame()
        self.banner.setProperty('banner', True)
        line = QHBoxLayout(self.banner)
        line.setContentsMargins(14, 6, 6, 6)
        self.banner_text = label('')
        line.addWidget(self.banner_text, 1)
        back = QPushButton('Show all')
        back.setProperty('kind', 'flat')
        back.clicked.connect(self.clear_results)
        line.addWidget(back)
        self.banner.hide()
        layout.addWidget(self.banner)
        layout.addSpacing(4)

        self.stack = QStackedLayout()
        self.grid = Grid(self.model)
        self.grid.opened.connect(self.open_details)
        self.grid.favorite.connect(lambda row: self.toggle_favorite(self.model.items[row]['name']))
        self.stack.addWidget(self.grid)
        empty = QWidget()
        column = QVBoxLayout(empty)
        column.addStretch(1)
        self.empty_icon = QPushButton(theme.icon('images', theme.MUTED), '')
        self.empty_icon.setProperty('kind', 'flat')
        self.empty_icon.setIconSize(QSize(40, 40))
        self.empty_icon.setEnabled(False)
        column.addWidget(self.empty_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = label('', 'heading')
        self.empty_text = label('', 'muted', wrap=True)
        for widget in (self.empty_title, self.empty_text):
            widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(widget)
        column.addStretch(2)
        self.stack.addWidget(empty)
        layout.addLayout(self.stack, 1)
        self.update_sort()
        self.waiting('Waiting for the engine…', 'Your library appears as soon as the engine is ready.')

    # Loading -------------------------------------------------------------------------

    def engine_ready(self):
        self.ready = True
        self.refresh()

    def engine_gone(self):
        self.ready = False

    def refresh(self):
        if not self.ready:
            return
        self.client.get('/api/config', self.configured, None)
        self.client.get('/api/system', lambda info: setattr(self, 'library_dir', info.get('library_dir', '')))
        self.client.get('/api/favorites', self.got_favorites, None)
        self.client.get('/api/library', self.got_library, self.failed)

    def configured(self, config):
        self.config = config or {}
        self.visual.setEnabled(bool(self.config.get('search')))
        self.visual.setToolTip(
            'Find pictures by what is in them, not only their prompt words.'
            if self.visual.isEnabled()
            else 'Visual search needs the image search model. It will be installable from the Models page.'
        )

    def got_favorites(self, answer):
        self.model.favorites = set(answer.get('names') or [])
        self.apply()
        self.changed.emit()

    def got_library(self, answer):
        self.all = answer.get('images') or []
        self.apply()
        self.changed.emit()

    def failed(self, error):
        self.notify(f'Could not load the library: {error}', error=True)

    # Showing ---------------------------------------------------------------------------

    def waiting(self, title, text):
        self.empty_title.setText(title)
        self.empty_text.setText(text)
        self.stack.setCurrentIndex(1)

    def apply(self):
        favorites = self.model.favorites
        source = self.results if self.results is not None else self.all
        words = self.search.text().lower().split()
        only_favorites = self.favorites_only.isChecked()
        visible = [
            item
            for item in source
            if (not only_favorites or item['name'] in favorites)
            and all(word in searchable(item) for word in words)
        ]
        if self.results is None:
            visible.sort(key=lambda item: item['created'], reverse=not self.oldest)
        self.model.set_items(visible)
        self.everything.setText(f'All creations  {len(self.all)}')
        self.favorites_only.setText(f'Favorites  {len(favorites)}')
        if visible:
            self.stack.setCurrentIndex(0)
        elif words:
            self.waiting('Nothing matches.', 'Try a different word, or press Enter for a visual search.')
        elif only_favorites:
            self.waiting('No favorites yet.', 'Click the heart on a picture to keep it here.')
        else:
            self.waiting('No creations here yet.', 'Create your first image to begin your collection.')

    def flip_sort(self):
        self.oldest = not self.oldest
        self.update_sort()
        self.apply()

    def update_sort(self):
        self.sort.setToolTip('Oldest first (click for newest first)' if self.oldest else 'Newest first (click for oldest first)')

    def open_details(self, row):
        self.show_details(list(self.model.items), row)

    def show_details(self, items, row):
        ImageDetails(self, items, row).exec()

    def toggle_favorite(self, name, then=None):
        def saved(answer):
            self.model.favorites = set(answer.get('names') or [])
            self.apply()
            self.changed.emit()
            if then:
                then()

        self.client.post(
            '/api/favorites',
            dict(name=name, favorite=name not in self.model.favorites),
            saved,
            lambda error: self.notify(error, error=True),
        )

    # Visual search ---------------------------------------------------------------------

    def visual_search(self):
        query = self.search.text().strip()
        if not query or not self.config.get('search'):
            return
        self.visual.setEnabled(False)
        self.visual.setText('Searching…')
        self.client.get(
            f'/api/library/search?q={quote(query)}',
            lambda answer: self.show_results(answer, f'Pictures that look like “{query}”'),
            self.search_failed,
            timeout=180000,
        )

    def find_similar(self, name):
        self.client.get(
            f'/api/library/search?similar={quote(name)}',
            lambda answer: self.show_results(answer, 'Pictures similar to the one you chose'),
            self.search_failed,
            timeout=180000,
        )
        self.notify('Looking for similar pictures…')

    def show_results(self, answer, title):
        self.visual.setEnabled(True)
        self.visual.setText('Visual search')
        self.results = answer.get('images') or []
        self.banner_text.setText(f'{title} · {len(self.results)} found, best match first')
        self.banner.show()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.everything.setChecked(True)
        self.apply()

    def search_failed(self, error):
        self.visual.setEnabled(True)
        self.visual.setText('Visual search')
        self.notify(error, error=True)

    def clear_results(self):
        self.results = None
        self.banner.hide()
        self.apply()

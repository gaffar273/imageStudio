"""Project home, named canvas creation, and an image bin shared by both editors."""

from PySide6.QtCore import QMimeData, QSize, Qt
from shiboken6 import isValid
from PySide6.QtGui import QDrag, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.theme import label

ASSET_MIME = 'application/x-image-studio-project-image'


class NewProjectDialog(QDialog):
    def __init__(self, parent, editor='PhotoCraft'):
        super().__init__(parent)
        self.setWindowTitle(f'New {editor} project')
        self.setMinimumWidth(390)
        column = QVBoxLayout(self)
        column.addWidget(label('Start a project', 'heading'))
        column.addWidget(
            label('Your images and edits will be saved together on this computer.', 'small', wrap=True)
        )
        form = QFormLayout()
        self.name = QLineEdit('Untitled project')
        self.name.setMaxLength(150)
        self.name.selectAll()
        form.addRow('Project name', self.name)
        self.width, self.height = QSpinBox(), QSpinBox()
        for field, value in ((self.width, 1600), (self.height, 1000)):
            field.setRange(1, 8192)
            field.setSuffix(' px')
            field.setValue(value)
        form.addRow('Canvas width', self.width)
        form.addRow('Canvas height', self.height)
        column.addLayout(form)
        presets = QHBoxLayout()
        for title, width, height in [
            ('Landscape', 1600, 1000),
            ('Square', 1080, 1080),
            ('Portrait', 1080, 1350),
        ]:
            button = QPushButton(title)
            button.clicked.connect(
                lambda _=False, w=width, h=height: (self.width.setValue(w), self.height.setValue(h))
            )
            presets.addWidget(button)
        column.addLayout(presets)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Create project')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.size_note = label('', 'small', wrap=True)
        column.addWidget(self.size_note)

        def validate():
            valid = self.width.value() * self.height.value() <= 40_000_000
            self.size_note.setText('Choose a canvas of at most 40 megapixels.' if not valid else '')
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                valid and bool(self.name.text().strip())
            )

        self.name.textChanged.connect(validate)
        self.width.valueChanged.connect(validate)
        self.height.valueChanged.connect(validate)
        column.addWidget(buttons)

    def values(self):
        return dict(name=self.name.text().strip(), width=self.width.value(), height=self.height.value())


class ProjectHome(QWidget):
    def __init__(self, client, editor, new, open_file, from_image, open_project):
        super().__init__()
        self.client, self.open_project, self.editor = client, open_project, editor
        self.projects = []
        column = QVBoxLayout(self)
        column.setContentsMargins(32, 28, 32, 24)
        column.setSpacing(16)
        column.addWidget(label(f'{editor} projects', 'heading'))
        column.addWidget(
            label(
                'Start something new or continue where you left off. Your images, layers and edits stay together.',
                'muted',
                wrap=True,
            )
        )
        row = QHBoxLayout()
        self.new = QPushButton(theme.icon('plus', theme.ON_ACCENT), 'New project…')
        self.new.setProperty('kind', 'primary')
        self.new.clicked.connect(new)
        self.open = QPushButton(theme.icon('folder-open'), 'Open project file…')
        self.open.clicked.connect(open_file)
        self.photo = QPushButton(theme.icon('image'), 'Start from an image…')
        self.photo.clicked.connect(from_image)
        for button in (self.new, self.open, self.photo):
            row.addWidget(button)
        row.addStretch()
        column.addLayout(row)
        self.note = label(
            'Projects are saved automatically. Save a project file when you want a portable copy or backup.',
            'small',
            wrap=True,
        )
        column.addWidget(self.note)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search your projects…')
        self.search.textChanged.connect(self.filter)
        column.addWidget(self.search)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setIconSize(QSize(230, 130))
        self.list.setSpacing(12)
        self.list.setWordWrap(True)
        self.list.setStyleSheet(
            'QListWidget { border: none; background: transparent; } QListWidget::item { padding: 10px; border-radius: 10px; }'
        )
        self.list.itemClicked.connect(lambda item: open_project(item.data(Qt.ItemDataRole.UserRole)))
        column.addWidget(self.list, 1)
        self.empty = label(
            'No projects yet. Create one above, then import the images you want to work with.',
            'muted',
            wrap=True,
        )
        column.addWidget(self.empty)

    def set_projects(self, projects):
        self.projects = projects
        self.list.clear()
        for project in projects:
            dimensions = f'{project["width"]} × {project["height"]}' if project.get('width') else ''
            item = QListWidgetItem(
                f'{project["name"]}\n{dimensions} · {project.get("images", 0)} source images'
            )
            item.setData(Qt.ItemDataRole.UserRole, project['id'])
            item.setSizeHint(QSize(260, 190))
            item.setIcon(theme.icon('layers' if self.editor == 'PhotoCraft' else 'brush'))
            self.list.addItem(item)
            if project.get('preview'):

                def loaded(data, item=item, ident=project['id']):
                    # The list may have been refreshed while the thumbnail was loading.
                    if not any(self.list.item(i) is item for i in range(self.list.count())):
                        return
                    pixmap = QPixmap()
                    if pixmap.loadFromData(data):
                        item.setIcon(QIcon(pixmap))

                self.client.bytes(project['preview'], loaded, None)
        self.filter()

    def filter(self):
        query = self.search.text().casefold()
        visible = 0
        for index in range(self.list.count()):
            item = self.list.item(index)
            show = query in item.text().casefold()
            item.setHidden(not show)
            visible += show
        self.empty.setVisible(not visible)
        self.empty.setText(
            'No projects match your search.'
            if self.projects
            else 'No projects yet. Create one above, then import the images you want to work with.'
        )

    def set_ready(self, ready, busy=False):
        for button in (self.new, self.open, self.photo):
            button.setEnabled(ready and not busy)
        self.list.setEnabled(ready and not busy)


class AssetTile(QFrame):
    def __init__(self, asset, client, place, enabled):
        super().__init__()
        self.asset, self.press = asset, None
        self.setFixedWidth(156)
        self.setProperty('card', True)
        column = QVBoxLayout(self)
        column.setContentsMargins(7, 6, 7, 6)
        column.setSpacing(3)
        self.preview = QLabel()
        self.preview.setFixedHeight(56)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(self.preview)
        title = label(asset['name'], 'small')
        title.setToolTip(asset['name'])
        title.setFixedHeight(18)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(title)
        menu = QMenu(self)
        menu.addAction('Place at original size', lambda: place(asset, fit=False))
        menu.addAction('Fit inside canvas', lambda: place(asset, fit=True))
        menu.addSeparator()
        menu.addAction('Use as new canvas', lambda: place(asset, as_canvas=True))
        button = QToolButton()
        button.setText('Place…')
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        button.setEnabled(enabled)
        column.addWidget(button)
        self.setEnabled(enabled)

        def loaded(data):
            if not isValid(self.preview):
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.preview.setPixmap(
                    pixmap.scaled(
                        138,
                        56,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        client.bytes(asset['thumbnail'], loaded, None)

    def mousePressEvent(self, event):
        self.press = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None

    def mouseMoveEvent(self, event):
        if self.press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self.press).manhattanLength() < QApplication.startDragDistance():
            return
        mime = QMimeData()
        mime.setData(ASSET_MIME, self.asset['id'].encode('ascii'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        if self.preview.pixmap() is not None:
            drag.setPixmap(self.preview.pixmap())
        self.press = None
        drag.exec(Qt.DropAction.CopyAction)


class ProjectAssets(QFrame):
    def __init__(self, client, place, import_images):
        super().__init__()
        self.client, self.place = client, place
        self.key = None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(label('Project images', 'eyebrow'))
        row.addWidget(label('Drag onto the canvas, or choose Place…', 'small'), 1)
        self.import_button = QPushButton(theme.icon('plus'), 'Import images…')
        self.import_button.clicked.connect(import_images)
        row.addWidget(self.import_button)
        column.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(144)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip = QWidget()
        self.row = QHBoxLayout(self.strip)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.scroll.setWidget(self.strip)
        column.addWidget(self.scroll)

    def show_assets(self, assets, busy):
        self.import_button.setEnabled(not busy)
        key = (tuple(asset['id'] for asset in assets), busy)
        if key == self.key:
            return
        self.key = key
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for asset in assets:
            self.row.addWidget(AssetTile(asset, self.client, self.place, not busy))
        if not assets:
            self.row.addWidget(
                label(
                    'Import your source images here. They are saved with the project; the canvas changes only when you place one.',
                    'small',
                    wrap=True,
                )
            )
        self.row.addStretch()

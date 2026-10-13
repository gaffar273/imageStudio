"""Colors, the style sheet and icons: a light, quiet look where the pictures carry the color."""

import functools
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel

ICONS = Path(__file__).with_name('icons')

BG = '#ffffff'  # page content
PANEL = '#f8f8fa'  # sidebar and side panels
RAISED = '#f0f0f3'  # hover fills, chips, placeholders
STAGE = '#f2f2f5'  # behind pictures
CANVAS = '#e7e7ec'  # behind a photo being edited, a shade darker so white photos keep their edges
FIELD = '#ffffff'  # text boxes and drop-downs
LINE = '#e6e6eb'
LINE_STRONG = '#d6d6dd'
TEXT = '#17171c'
MUTED = '#686874'
FAINT = '#a3a3ad'
ACCENT = '#2563eb'
ACCENT_HOVER = '#1d4ed8'
ACCENT_SOFT = '#edf2ff'
ACCENT_LINE = '#c4d4fb'
ON_ACCENT = '#ffffff'  # text and icons on the accent
SUCCESS = '#15803d'
SUCCESS_SOFT = '#e8f6ed'
WARN = '#b45309'
WARN_SOFT = '#fdf3e1'
DANGER = '#d93025'
DANGER_SOFT = '#fdeceb'
SELECTION = '#d6e3ff'


@functools.cache
def icon(name, color=TEXT, fill='none'):
    """A lucide icon (icons/, ISC licence) drawn in one color, sharp at any screen scale."""
    svg = (ICONS / f'{name}.svg').read_text(encoding='utf-8')
    svg = svg.replace('fill="none"', f'fill="{fill}"').replace('currentColor', color)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 96):
        pixmap = QPixmap(QSize(size, size))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


def arrow():
    """The drop-down arrow and the check mark as colored files, since style sheets take images by path only."""
    folder = Path(tempfile.gettempdir()) / 'image-studio'
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, color in (('chevron-down', MUTED), ('check', ON_ACCENT)):
            (folder / f'{name}-light.svg').write_text(
                (ICONS / f'{name}.svg').read_text(encoding='utf-8').replace('currentColor', color), encoding='utf-8')
    except OSError:
        return ''
    return (f'QComboBox::down-arrow {{ image: url({(folder / "chevron-down-light.svg").as_posix()}); width: 14px; '
            f'height: 14px; }}\nQCheckBox::indicator:checked {{ '
            f'image: url({(folder / "check-light.svg").as_posix()}); }}')


def font_family():
    return 'Segoe UI Variable Text' if sys.platform == 'win32' else ''


KEEP = {word.upper(): word for word in ('AI', 'PSD', 'PC', 'HDR', 'RGB', 'LUT', 'GPU', 'JPEG', 'PNG', 'PhotoCraft',
                                        'Krita', 'FLUX', 'SAM')}


def sentence(text):
    """'PAINT NEW CONTENT WITH AI' -> 'Paint new content with AI' (names and acronyms kept)."""
    words = text.lower().split(' ')
    words = [KEEP.get(word.upper().strip('.,:;()'), word) for word in words]
    if words and words[0] and words[0] not in KEEP.values():
        words[0] = words[0][0].upper() + words[0][1:]
    return ' '.join(words)


def label(text, role='', wrap=False, selectable=False):
    """A QLabel with one of the text roles styled below (title, section, muted, ...).

    'eyebrow' is the small heading over a group of controls; it reads in sentence case, so
    an all-capitals text is turned into one ("IMAGE FORMAT" -> "Image format")."""
    if role == 'eyebrow' and text.isupper():
        text = sentence(text)
    widget = QLabel(text)
    if role:
        widget.setProperty('role', role)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def restyle(widget, **properties):
    """Change style properties (role, tone, kind…) and apply them at once."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QToolTip {{ background: #1f1f26; color: #ffffff; border: none; padding: 5px 8px; border-radius: 6px; }}

#Sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
#Sidebar QWidget {{ background: transparent; }}
#Panel {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
#Panel[side="left"] {{ border-left: none; border-right: 1px solid {LINE}; }}
#Panel QLabel, #Panel QScrollArea, #Panel QScrollArea > QWidget > QWidget, #Panel QSlider {{
    background: transparent;
}}
#PageHeader {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
#PageHeader QLabel {{ background: transparent; }}
#Toast {{ background: #1f1f26; border-radius: 9px; }}
#Toast QLabel {{ background: transparent; color: #ffffff; }}
#Toast[tone="error"] {{ background: #b3261e; }}
#EngineCard {{ background: {BG}; border: 1px solid {LINE}; border-radius: 9px; }}
#EngineCard QLabel {{ background: transparent; }}
#Hero QLabel {{ background: transparent; }}

QPushButton[nav="true"] {{
    text-align: left; padding: 7px 10px; border: none; border-radius: 7px;
    background: transparent; color: {MUTED};
}}
QPushButton[nav="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{ background: #e9e9ee; color: {TEXT}; font-weight: 600; }}

QPushButton {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 7px; padding: 6px 12px; color: {TEXT};
}}
QPushButton:hover {{ background: #f6f6f8; border-color: #c6c6cf; }}
QPushButton:pressed {{ background: {RAISED}; }}
QPushButton:disabled {{ color: {FAINT}; background: {PANEL}; border-color: {LINE}; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-color: {ACCENT_LINE}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:disabled {{ background: #b9cdf8; border-color: #b9cdf8; color: #ffffff; }}
QPushButton[kind="flat"] {{ background: transparent; border: none; color: {MUTED}; padding: 5px 8px; }}
QPushButton[kind="flat"]:hover {{ color: {TEXT}; background: {RAISED}; }}
QPushButton[kind="flat"]:disabled {{ color: {FAINT}; background: transparent; }}
QPushButton[kind="link"] {{ background: transparent; border: none; color: {ACCENT}; padding: 2px 0; }}
QPushButton[kind="link"]:hover {{ color: {ACCENT_HOVER}; text-decoration: underline; }}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton[kind="danger"]:hover {{ background: {DANGER_SOFT}; border-color: #f3b8b3; }}
QPushButton[kind="primary"][size="large"] {{ padding: 9px 16px; font-size: 10.5pt; border-radius: 8px; }}
QPushButton[kind="chip"] {{
    border-radius: 12px; padding: 4px 11px; font-size: 9pt; color: {MUTED}; background: {RAISED}; border: none;
}}
QPushButton[kind="chip"]:hover {{ color: {TEXT}; background: #e6e6eb; }}
QPushButton[kind="tile"] {{ padding: 6px 8px; }}
QPushButton[kind="segment"] {{ padding: 6px 4px; }}
QPushButton[kind="fold"] {{
    text-align: left; padding: 8px 10px; background: transparent; border: 1px solid {LINE}; color: {TEXT};
}}
QPushButton[kind="fold"]:hover {{ background: {RAISED}; }}
QPushButton[kind="fold"]:checked {{ background: {FIELD}; color: {TEXT}; border-color: {LINE}; font-weight: 600; }}
QPushButton[kind="tab"] {{
    text-align: left; padding: 7px 10px; border: none; border-radius: 7px; background: transparent; color: {MUTED};
}}
QPushButton[kind="tab"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[kind="tab"]:checked {{ background: #e9e9ee; color: {TEXT}; font-weight: 600; }}

QToolButton {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 7px; padding: 5px 11px; color: {TEXT};
}}
QToolButton:hover {{ background: #f6f6f8; border-color: #c6c6cf; }}
QToolButton:disabled {{ color: {FAINT}; background: {PANEL}; border-color: {LINE}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[kind="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; font-weight: 600; }}
QToolButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QToolButton[rail="true"] {{
    background: transparent; border: none; border-radius: 7px; padding: 7px 2px; color: {MUTED}; font-size: 8.5pt;
}}
QToolButton[rail="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QToolButton[rail="true"]:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu {{ background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ background: transparent; padding: 6px 26px 6px 12px; border-radius: 5px; color: {TEXT}; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {LINE_STRONG}; border-radius: 4px; background: {FIELD};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: {LINE}; background: {PANEL}; }}
QSpinBox {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 7px; padding: 5px 8px; min-height: 20px;
}}
QSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QComboBox {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 7px; padding: 5px 10px; min-height: 20px;
    color: {TEXT};
}}
QComboBox:hover {{ border-color: #c6c6cf; }}
QComboBox:focus, QComboBox:on {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: {FAINT}; background: {PANEL}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; outline: none; padding: 4px;
}}
QSlider::groove:horizontal {{ height: 4px; background: #e2e2e8; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #ffffff; border: 1px solid {LINE_STRONG}; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ border-color: {ACCENT}; }}
QSlider::sub-page:horizontal:disabled {{ background: {LINE_STRONG}; }}
QSlider::handle:horizontal:disabled {{ background: {PANEL}; border-color: {LINE}; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {FIELD}; border: 1px solid {LINE_STRONG}; border-radius: 7px; padding: 6px 10px;
    selection-background-color: {SELECTION}; selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {PANEL}; color: {FAINT}; }}

QListView, QListWidget {{ background: {BG}; border: none; outline: none; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #d4d4db; border-radius: 3px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #babac3; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #d4d4db; border-radius: 3px; min-width: 40px; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}

QFrame[card="true"] {{ background: {BG}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[banner="true"] {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT_LINE}; border-radius: 8px; }}
QFrame[banner="true"] QLabel {{ background: transparent; }}
QFrame[stage="true"] {{ background: {STAGE}; border: none; border-radius: 10px; }}
QFrame[stage="true"] QLabel {{ background: transparent; }}
QFrame[rule="true"] {{ background: {LINE}; border: none; }}

QLabel[role="title"] {{ font-size: 14pt; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: 20pt; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="eyebrow"] {{ color: {MUTED}; font-size: 9pt; font-weight: 600; }}
QLabel[role="group"] {{ color: {FAINT}; font-size: 8.5pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="small"] {{ color: {MUTED}; font-size: 9pt; }}
QLabel[role="value"] {{ font-weight: 600; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="badge"], QWidget QLabel[role="badge"] {{
    background: {SUCCESS_SOFT}; color: {SUCCESS}; border-radius: 9px;
    padding: 1px 8px; font-size: 8.5pt; font-weight: 600;
}}
QWidget QLabel[role="badge"][tone="warn"] {{ background: {WARN_SOFT}; color: {WARN}; }}
QWidget QLabel[role="badge"][tone="off"] {{ background: {RAISED}; color: {MUTED}; }}
QWidget QLabel[role="badge"][tone="accent"] {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QWidget QLabel[role="badge"][tone="error"] {{ background: {DANGER_SOFT}; color: {DANGER}; }}

QProgressBar {{ background: #e6e6eb; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QDialog {{ background: {BG}; }}
QMessageBox QLabel {{ background: transparent; }}
"""

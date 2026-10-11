"""Colors, the style sheet and icons, matching the web studio's dark look."""

import functools
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel

ICONS = Path(__file__).with_name('icons')

BG = '#121414'
PANEL = '#191c1b'
RAISED = '#212524'
LINE = '#2a2e2b'
TEXT = '#e5e8e3'
MUTED = '#898f89'
LIME = '#c4f477'
INK = '#121414'  # text on lime
WARN = '#f2c46b'
DANGER = '#f08a7a'


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
        for name, color in (('chevron-down', MUTED), ('check', INK)):
            (folder / f'{name}.svg').write_text(
                (ICONS / f'{name}.svg').read_text(encoding='utf-8').replace('currentColor', color), encoding='utf-8')
    except OSError:
        return ''
    return (f'QComboBox::down-arrow {{ image: url({(folder / "chevron-down.svg").as_posix()}); width: 14px; '
            f'height: 14px; }}\nQCheckBox::indicator:checked {{ image: url({(folder / "check.svg").as_posix()}); }}')


def font_family():
    return 'Segoe UI Variable Text' if sys.platform == 'win32' else ''


def label(text, role='', wrap=False, selectable=False):
    """A QLabel with one of the text roles styled below (title, eyebrow, muted, ...)."""
    widget = QLabel(text)
    if role:
        widget.setProperty('role', role)
    if role == 'eyebrow':
        font = widget.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        widget.setFont(font)
    widget.setWordWrap(wrap)
    if selectable:
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; padding: 5px 8px; }}

#Sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
#Sidebar QWidget {{ background: transparent; }}
#Panel {{ background: {PANEL}; border-left: 1px solid {LINE}; }}
#Panel[side="left"] {{ border-left: none; border-right: 1px solid {LINE}; }}
#Panel QLabel, #Panel QScrollArea, #Panel QScrollArea > QWidget > QWidget, #Panel QSlider {{
    background: transparent;
}}
#Hero QLabel {{ background: transparent; }}
QPushButton[nav="true"] {{
    text-align: left; padding: 9px 12px; border: none; border-radius: 8px;
    background: transparent; color: {MUTED};
}}
QPushButton[nav="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{ background: rgba(196, 244, 119, 0.10); color: {LIME}; }}

QPushButton {{
    background: {RAISED}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: #3d433f; background: #262b29; }}
QPushButton:pressed {{ background: #1c201f; }}
QPushButton:disabled {{ color: #5b605c; background: {PANEL}; }}
QPushButton:checked {{ background: rgba(196, 244, 119, 0.12); color: {LIME}; border-color: #4d5d36; }}
QPushButton[kind="primary"] {{ background: {LIME}; color: {INK}; border: none; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: #d2fa92; }}
QPushButton[kind="primary"]:disabled {{ background: #3b4630; color: #7d8a6a; }}
QPushButton[kind="flat"] {{ background: transparent; border: none; color: {MUTED}; padding: 6px 8px; }}
QPushButton[kind="flat"]:hover {{ color: {TEXT}; }}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton[kind="primary"][size="large"] {{ padding: 11px 16px; font-size: 11pt; border-radius: 10px; }}
QPushButton[kind="chip"] {{ border-radius: 13px; padding: 4px 10px; font-size: 9pt; color: {MUTED}; }}
QPushButton[kind="chip"]:hover {{ color: {TEXT}; }}
QPushButton[kind="tile"] {{ padding: 7px 8px; }}
QPushButton[kind="segment"] {{ padding: 6px 4px; }}
QPushButton[kind="fold"] {{
    text-align: left; padding: 9px 10px; background: transparent; border: 1px solid {LINE}; color: {TEXT};
}}
QPushButton[kind="fold"]:checked {{ background: {RAISED}; color: {TEXT}; border-color: {LINE}; }}

QToolButton {{
    background: {RAISED}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 12px;
}}
QToolButton:hover {{ border-color: #3d433f; background: #262b29; }}
QToolButton:disabled {{ color: #5b605c; background: {PANEL}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[kind="primary"] {{ background: {LIME}; color: {INK}; border: none; font-weight: 600; }}
QToolButton[kind="primary"]:hover {{ background: #d2fa92; }}
QToolButton[rail="true"] {{
    background: transparent; border: none; border-radius: 8px; padding: 7px 2px; color: {MUTED}; font-size: 8.5pt;
}}
QToolButton[rail="true"]:hover {{ background: {RAISED}; color: {TEXT}; }}
QToolButton[rail="true"]:checked {{ background: rgba(196, 244, 119, 0.10); color: {LIME}; }}
QMenu {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ background: transparent; padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: #4d5d36; }}
QMenu::item:disabled {{ color: #5b605c; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #4a514b; border-radius: 4px; background: {PANEL}; }}
QCheckBox::indicator:hover {{ border-color: #86a85b; }}
QCheckBox::indicator:checked {{ background: {LIME}; border-color: {LIME}; }}
QCheckBox::indicator:disabled {{ border-color: {LINE}; }}
QSpinBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 5px 8px; min-height: 20px;
}}
QSpinBox:focus {{ border-color: #86a85b; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QComboBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 10px; min-height: 20px;
}}
QComboBox:hover {{ border-color: #3d433f; }}
QComboBox:focus {{ border-color: #86a85b; }}
QComboBox:disabled {{ color: #5b605c; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {RAISED}; border: 1px solid {LINE}; selection-background-color: #4d5d36; outline: none;
}}
QSlider::groove:horizontal {{ height: 4px; background: {RAISED}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {LIME}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::sub-page:horizontal:disabled {{ background: #3b4630; }}
QSlider::handle:horizontal:disabled {{ background: #5b605c; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: #4d5d36;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: #86a85b; }}

QListView {{ background: {BG}; border: none; outline: none; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #333834; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #454b46; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #333834; border-radius: 4px; min-width: 40px; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}

QFrame[card="true"] {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[banner="true"] {{ background: rgba(196, 244, 119, 0.08); border: 1px solid #3b4630; border-radius: 10px; }}
QFrame[banner="true"] QLabel {{ background: transparent; }}

QLabel[role="title"] {{ font-size: 21pt; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: 30pt; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 12.5pt; font-weight: 600; }}
QLabel[role="eyebrow"] {{ color: {LIME}; font-size: 8pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="small"] {{ color: {MUTED}; font-size: 9pt; }}
QLabel[role="value"] {{ font-weight: 600; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="badge"] {{
    background: rgba(196, 244, 119, 0.12); color: {LIME}; border-radius: 9px;
    padding: 2px 9px; font-size: 9pt; font-weight: 600;
}}
QLabel[role="badge"][tone="warn"] {{ background: rgba(242, 196, 107, 0.12); color: {WARN}; }}
QLabel[role="badge"][tone="off"] {{ background: {RAISED}; color: {MUTED}; }}

QProgressBar {{ background: {RAISED}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {LIME}; border-radius: 3px; }}

QDialog {{ background: {BG}; }}
QMessageBox QLabel {{ background: transparent; }}
"""

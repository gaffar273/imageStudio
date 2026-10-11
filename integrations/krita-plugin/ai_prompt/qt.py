"""Qt names for Krita 6 (PyQt6) and Krita 5 (PyQt5), and picture helpers."""
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, QSize, Qt, QTimer,
                              pyqtSignal)
    from PyQt6.QtGui import (QAction, QColor, QFont, QImage, QPainter, QRadialGradient, QTextCursor)
    from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu,
                                 QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QTextBrowser, QToolButton,
                                 QVBoxLayout, QWidget)
    QT6 = True
except ImportError:  # Krita 5
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, QSize, Qt, QTimer,
                              pyqtSignal)
    from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QRadialGradient, QTextCursor
    from PyQt5.QtWidgets import (QAction, QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu,
                                 QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QTextBrowser, QToolButton,
                                 QVBoxLayout, QWidget)
    QT6 = False


def scoped(cls, enum, name):
    """An enum value by its PyQt6 scoped name, falling back to the PyQt5 short name."""
    return getattr(getattr(cls, enum), name) if hasattr(cls, enum) else getattr(cls, name)


ARGB32 = scoped(QImage, 'Format', 'Format_ARGB32')
GRAY8 = scoped(QImage, 'Format', 'Format_Grayscale8')


def encode(image, kind='PNG', quality=-1):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(scoped(QIODevice, 'OpenModeFlag', 'WriteOnly'))
    image.save(buffer, kind, quality)
    buffer.close()
    return bytes(data)


def raw_bytes(image):
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    return bytes(pointer)


def fit(image, longest):
    """The image scaled down (never up) so its longest side is at most `longest`."""
    if max(image.width(), image.height()) <= longest:
        return image
    return image.scaled(longest, longest, scoped(Qt, 'AspectRatioMode', 'KeepAspectRatio'),
                        scoped(Qt, 'TransformationMode', 'SmoothTransformation'))


def scaled_exact(image, width, height):
    return image.scaled(width, height, scoped(Qt, 'AspectRatioMode', 'IgnoreAspectRatio'),
                        scoped(Qt, 'TransformationMode', 'SmoothTransformation'))

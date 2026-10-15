"""The app icon (a white aperture on the accent-blue tile, as on the website) as image-studio.ico and image-studio.png.

Run by build.py with the bundled Python, which has Qt: python make_icon.py OUTPUT_FOLDER
With --store it writes the Microsoft Store package's logos instead (AppxManifest.xml names them).
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from image_studio.desktop import theme
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256)


def tile(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.ACCENT))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    svg = (theme.ICONS / 'aperture.svg').read_text(encoding='utf-8').replace('currentColor', theme.ON_ACCENT)
    if size <= 32:  # thin strokes vanish at small sizes
        svg = svg.replace('stroke-width="2"', 'stroke-width="2.6"')
    margin = size * (0.12 if size <= 32 else 0.18)
    QSvgRenderer(QByteArray(svg.encode('utf-8'))).render(
        painter, QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    )
    painter.end()
    return image


def png(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data.data())


def ico(images):
    """An .ico holding one PNG per size (Windows Vista and later read these)."""
    header = struct.pack('<HHH', 0, 1, len(images))
    entries, blobs = b'', b''
    offset = 6 + 16 * len(images)
    for size, blob in images:
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return header + entries + blobs


def padded(size, share):
    """The tile at share of the size, centred on a clear square (Start's larger tiles)."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    inner = round(size * share)
    painter = QPainter(image)
    painter.drawImage((size - inner) // 2, (size - inner) // 2, tile(inner))
    painter.end()
    return image


def store_logos(out):
    """Every size Windows asks a package for. The taskbar and Start's list use the target sizes;
    "unplated" ones are drawn as they are, without a coloured plate behind them."""
    files = {}
    for scale in (100, 125, 150, 200, 400):
        files[f'Square44x44Logo.scale-{scale}.png'] = tile(44 * scale // 100)
        files[f'Square150x150Logo.scale-{scale}.png'] = padded(150 * scale // 100, 0.6)
        files[f'StoreLogo.scale-{scale}.png'] = tile(50 * scale // 100)
    for size in (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256):
        files[f'Square44x44Logo.targetsize-{size}.png'] = tile(size)
        files[f'Square44x44Logo.targetsize-{size}_altform-unplated.png'] = tile(size)
        files[f'Square44x44Logo.targetsize-{size}_altform-lightunplated.png'] = tile(size)
    for name, image in files.items():
        (out / name).write_bytes(png(image))


def main():
    store = '--store' in sys.argv
    out = Path([arg for arg in sys.argv[1:] if arg != '--store'][0])
    out.mkdir(parents=True, exist_ok=True)
    QGuiApplication([])
    if store:
        store_logos(out)
        return
    images = [(size, png(tile(size))) for size in SIZES]
    (out / 'image-studio.ico').write_bytes(ico(images))
    (out / 'image-studio.png').write_bytes(images[-1][1])


if __name__ == '__main__':
    main()

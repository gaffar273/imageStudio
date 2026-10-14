"""Krita's own tools as steps (see agent.py in Image Studio for the list).

Light, color and effect steps add filter layers: non-destructive adjustment layers that
you can hide, change (Layer Properties), mask or delete later. They affect the layers
below them, and only the selected area when there is a selection. Every other step
adds a layer as well (text, fills, vignette, grain, AI results), so the original picture
is never painted over; canvas steps (crop, resize, rotate, flip) are ordinary Krita
operations that Ctrl+Z undoes."""
import math
from xml.sax.saxutils import escape
from krita import Krita, Selection
from .qt import (ARGB32, GRAY8, QByteArray, QColor, QImage, QPainter, QPointF, QRadialGradient, Qt, raw_bytes,
                 scaled_exact, scoped)

RGB8 = ('RGBA', 'U8', 'sRGB-elle-V2-srgbtrc.icc')


class StepError(Exception):
    """A step that cannot run; the message is shown to the person."""


def app():
    return Krita.instance()


def document():
    return app().activeDocument()


def need(doc):
    if doc is None:
        raise StepError('Open or create a picture first.')
    return doc


def settle(doc):
    doc.waitForDone()
    doc.refreshProjection()


def current_selection(doc):
    selection = doc.selection()
    if selection is None or selection.width() <= 0 or selection.height() <= 0:
        return None
    return selection


def full_selection(doc):
    selection = Selection()
    selection.select(0, 0, doc.width(), doc.height(), 255)
    return selection


def scale_px(doc, value):
    """A size given for a picture about 1500 pixels across, for this picture's size."""
    return max(1, round(value * max(doc.width(), doc.height()) / 1500))


_active = {}  # the layer each document's steps last made active (Krita has none without a window)


def activate(doc, node):
    doc.setActiveNode(node)
    _active[id(doc)] = node


def active_node(doc):
    """The active layer; in a headless Krita, the one the last step made active."""
    node = doc.activeNode()
    if node is None:
        node = _active.get(id(doc))
    return node


def insert(doc, node, above=None):
    """Add `node` above the active layer (or `above`) and make it active."""
    reference = above or active_node(doc)
    if reference is None or reference.parentNode() is None:
        root = doc.rootNode()
        children = root.childNodes()
        root.addChildNode(node, children[-1] if children else None)
    else:
        reference.parentNode().addChildNode(node, reference)
    activate(doc, node)
    return node


def gray_bytes(image):
    """The pixels of a Grayscale8 image, without the padding at the end of each row."""
    data = raw_bytes(image)
    width, line = image.width(), image.bytesPerLine()
    if line == width:
        return data
    return b''.join(data[row * line:row * line + width] for row in range(image.height()))


def mask_selection(doc, mask):
    """A selection from a grayscale mask (QImage) the size of the picture."""
    mask = mask.convertToFormat(GRAY8)
    if (mask.width(), mask.height()) != (doc.width(), doc.height()):
        mask = scaled_exact(mask, doc.width(), doc.height())
    selection = Selection()
    selection.resize(doc.width(), doc.height())
    selection.setPixelData(QByteArray(gray_bytes(mask)), 0, 0, doc.width(), doc.height())
    return selection


def pixel_node(doc, name, image, x=0, y=0):
    """A paint layer holding `image` (QImage) at x, y, not yet in the layer stack."""
    image = image.convertToFormat(ARGB32)
    layer = doc.createNode(name, 'paintlayer')
    if (layer.colorModel(), layer.colorDepth()) != RGB8[:2]:
        layer.setColorSpace(*RGB8)
    # ARGB32 is stored as B, G, R, A bytes, the same order as Krita's 8-bit RGBA layers.
    layer.setPixelData(QByteArray(raw_bytes(image)), x, y, image.width(), image.height())
    return layer


def pixel_layer(doc, name, image, x=0, y=0, above=None):
    """A new paint layer holding `image` (QImage) at x, y."""
    return insert(doc, pixel_node(doc, name, image, x, y), above)


def filter_node(doc, label, name, selection, **props):
    """A filter layer limited to `selection`, not yet in the layer stack."""
    found = app().filter(name)
    if found is None:
        raise StepError(f'This Krita has no {name} filter.')
    config = found.configuration()
    for key, value in props.items():
        config.setProperty(key, value)
    found.setConfiguration(config)
    return doc.createFilterLayer(label, found, selection)


def adjustment(doc, label, name, **props):
    """A filter layer: the filter applied to everything below, inside the selection."""
    return insert(doc, filter_node(doc, label, name, current_selection(doc) or full_selection(doc), **props))


def levels(in_black=0.0, in_white=1.0, gamma=1.0, out_black=0.0, out_white=1.0):
    return f'{in_black:.4f};{in_white:.4f};{gamma:.4f};{out_black:.4f};{out_white:.4f}'


EXTRA_COLORS = {'golden': '#d4a72c', 'cream': '#f3e5c0', 'terracotta': '#c8643c', 'mustard': '#d8a31a',
                'rust': '#b7410e', 'burgundy': '#800020', 'sand': '#d8c49a', 'peach': '#ffcba4',
                'mint': '#98e0b8', 'charcoal': '#36454f', 'ochre': '#cc7722', 'sky blue': '#87ceeb'}


def mixed(color, other, share):
    """`color` moved `share` of the way to `other` (QColor.lighter overshoots light colors to white)."""
    return QColor(*(round(a + (b - a) * share) for a, b in zip(color.getRgb()[:3], other.getRgb()[:3])))


def color_of(name, default='white'):
    """A color from a CSS name, #rrggbb, a few common paint names, or "light"/"dark" + one."""
    text = ' '.join(str(name).lower().split())
    color = QColor(EXTRA_COLORS.get(text, text.replace(' ', '')))
    if color.isValid():
        return color
    shade, _, base = text.partition(' ')
    color = QColor(EXTRA_COLORS.get(base, base.replace(' ', '')))
    if color.isValid() and shade in ('light', 'pale', 'soft', 'pastel', 'baby'):
        return mixed(color, QColor('white'), 0.45 if shade in ('pastel', 'baby') else 0.3)
    if color.isValid() and shade in ('dark', 'deep'):
        return mixed(color, QColor('black'), 0.35)
    color = QColor(EXTRA_COLORS.get(text.split()[-1], text.split()[-1])) if text else QColor(default)
    return color if color.isValid() else QColor(default)


def find_layer(doc, name):
    """The layer named `name` (exact, then partial, ignoring case), or the active one."""
    if not name or str(name).lower() in ('active', 'this', 'current', 'this layer', 'the active layer'):
        return active_node(doc)
    wanted = str(name).lower().strip().strip('"')
    nodes = list(walk(doc.rootNode()))
    for node, _ in nodes:
        if node.name().lower() == wanted:
            return node
    for node, _ in nodes:
        if wanted in node.name().lower():
            return node
    raise StepError(f'There is no layer called "{name}".')


def walk(node, depth=0):
    """Every layer and mask, top first, with its depth in groups."""
    for child in reversed(node.childNodes()):
        yield child, depth
        yield from walk(child, depth + 1)


def bottom_paint_layer(doc):
    """The layer to cut out: the active paint layer, else the lowest paint layer."""
    active = active_node(doc)
    if active is not None and active.type() == 'paintlayer':
        return active
    paint = [node for node, depth in walk(doc.rootNode()) if node.type() == 'paintlayer' and depth == 0]
    if not paint:
        raise StepError('There is no paint layer to cut out.')
    return paint[-1]


def trigger(name, times=1):
    action = app().action(name)
    if action is None:
        raise StepError(f'Krita has no "{name}" command here.')
    for _ in range(times):
        action.trigger()


# ---- Steps ---------------------------------------------------------------------------

def new_canvas(width=1024, height=1024, **_):
    doc = app().createDocument(int(width), int(height), 'Untitled', 'RGBA', 'U8', '', 300.0)
    # A new document already has one empty layer; it becomes the white background.
    layers = doc.rootNode().childNodes()
    background = layers[0] if layers else doc.createNode('Background', 'paintlayer')
    if not layers:
        doc.rootNode().addChildNode(background, None)
    background.setName('Background')
    image = QImage(int(width), int(height), ARGB32)
    image.fill(QColor('white'))
    background.setPixelData(QByteArray(raw_bytes(image)), 0, 0, int(width), int(height))
    window = app().activeWindow()
    if window is not None:
        window.addView(doc)
    activate(doc, background)
    settle(doc)
    return f'New {width} × {height} canvas.'


def combine(doc, selection, mode='replace'):
    """Make `selection` the document's selection, or add it to, take it from or intersect it with
    the current one."""
    current = current_selection(doc)
    if mode in ('add', 'subtract', 'intersect') and current is not None:
        getattr(current, mode)(selection)
        selection = current
    elif mode in ('subtract', 'intersect'):
        selection = Selection()  # taken from, or overlapping, nothing
    doc.setSelection(selection)


def require_selection(doc, what, **_):
    """Stop when a selection a pipeline needs came out empty: in Krita an empty selection means
    the whole picture, so the next filter would change everything."""
    if current_selection(doc) is None:
        raise StepError(f'Could not find {what} in the picture.')


def select_box(doc, x, y, w, h, ellipse=False, mode='replace', feather=0, **_):
    """A rectangle (or the ellipse inside it) in percent of the picture, kept inside the canvas."""
    left, top = round(doc.width() * x / 100), round(doc.height() * y / 100)
    width, height = max(1, round(doc.width() * w / 100)), max(1, round(doc.height() * h / 100))
    if ellipse:
        mask = QImage(doc.width(), doc.height(), GRAY8)
        mask.fill(QColor(0, 0, 0))
        painter = QPainter(mask)
        painter.setRenderHint(scoped(QPainter, 'RenderHint', 'Antialiasing'))
        painter.setPen(scoped(Qt, 'PenStyle', 'NoPen'))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(left, top, width, height)
        painter.end()
        selection = mask_selection(doc, mask)
    else:
        selection = Selection()
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(doc.width(), left + width), min(doc.height(), top + height)
        selection.select(x0, y0, max(1, x1 - x0), max(1, y1 - y0), 255)
    if feather:
        selection.feather(scale_px(doc, feather))
    combine(doc, selection, mode)


def select_all(doc):
    doc.setSelection(full_selection(doc))


def deselect(doc, **_):
    try:
        trigger('deselect')
    except StepError:
        doc.setSelection(Selection())


def invert_selection(doc, **_):
    selection = current_selection(doc)
    if selection is None:
        return deselect(doc)
    selection.invert()
    doc.setSelection(selection)


def grow_selection(doc, pixels, **_):
    selection = current_selection(doc)
    if selection is not None:
        selection.grow(scale_px(doc, pixels), scale_px(doc, pixels))
        doc.setSelection(selection)


def feather_selection(doc, pixels, **_):
    selection = current_selection(doc)
    if selection is not None:
        selection.feather(scale_px(doc, pixels))
        doc.setSelection(selection)


def brightness(doc, amount, label, **_):
    adjustment(doc, label, 'levels', lightness=levels(gamma=2 ** (amount / 60)))


def contrast(doc, amount, label, **_):
    if amount >= 0:
        cut = amount * 0.0028
        adjustment(doc, label, 'levels', lightness=levels(cut, 1 - cut))
    else:
        cut = -amount * 0.0035
        adjustment(doc, label, 'levels', lightness=levels(out_black=cut, out_white=1 - cut))


def saturation(doc, amount, label, **_):
    adjustment(doc, label, 'hsvadjustment', type=0, s=int(amount), h=0, v=0)


def hue(doc, degrees, label, **_):
    adjustment(doc, label, 'hsvadjustment', type=1, h=int(degrees), s=0, v=0)


def warmth(doc, amount, label, **_):
    shift = round(amount * 0.5)
    adjustment(doc, label, 'colorbalance', cyan_red_midtones=shift, yellow_blue_midtones=-shift,
               cyan_red_highlights=shift // 2, yellow_blue_highlights=-shift // 2)


def tint(doc, amount, label, **_):
    adjustment(doc, label, 'colorbalance', magenta_green_midtones=-round(amount * 0.5))


def black_and_white(doc, label, **_):
    adjustment(doc, label, 'desaturate', type=1)


def sepia(doc, strength, label, **_):
    layer = adjustment(doc, label, 'hsvadjustment', type=1, colorize=True, h=32, s=28, v=0)
    layer.setOpacity(round(255 * strength / 100))


def colorize(doc, color, label, **_):
    found = color_of(color, 'blue')
    adjustment(doc, label, 'hsvadjustment', type=1, colorize=True, h=max(0, found.hslHue()),
               s=max(20, round(found.hslSaturationF() * 60)), v=0)


def selection_lightness(doc, selection):
    """The average HSL lightness (0 to 1) of the picture inside the selection."""
    x, y, w, h = selection.x(), selection.y(), selection.width(), selection.height()
    image = projection(doc, x, y, w, h)
    data, line = raw_bytes(image), image.bytesPerLine()
    mask = bytes(selection.pixelData(x, y, w, h))
    step = max(1, round(max(w, h) / 256))
    total = count = 0
    for row in range(0, h, step):
        for col in range(0, w, step):
            if mask[row * w + col] > 127:
                index = row * line + col * 4
                b, g, r = data[index], data[index + 1], data[index + 2]
                total += (max(r, g, b) + min(r, g, b)) / 510
                count += 1
    return total / count if count else 0.5


def recolor_selection(doc, color, label, **_):
    """Give the selected object a new color as a Hue/Saturation colorize layer: its texture,
    shading and highlights stay, and its lightness moves toward the new color's."""
    selection = current_selection(doc)
    if selection is None:
        raise StepError('Select what to recolor first.')
    target = color_of(color, 'red')
    now, wanted = selection_lightness(doc, selection), target.lightnessF()
    # Krita's colorize scales lightness down (l * (1 + v)) or up toward white (l + (1 - l) * v).
    # Only part of the way: matching a pastel fully (+83) washed the walls' texture out in tests;
    # lightening flattens detail sooner than darkening, so it moves less.
    if wanted < now:
        shift = max(-75, (wanted / max(now, 0.05) - 1) * 100 * 0.9)
    else:
        shift = min(35, (wanted - now) / max(1 - now, 0.05) * 100 * 0.45)
    shift = round(shift)
    soft = selection.duplicate()
    soft.feather(scale_px(doc, 2))
    # Colorfulness is the target's chroma at the surface's new lightness: HSL saturation alone
    # makes a pastel (pale, high-saturation) come out hot pink. Painted surfaces in daylight are
    # rarely fully saturated, so 80% of it (pure red at full strength read as flat paint).
    light = now * (1 + shift / 100) if shift < 0 else now + (1 - now) * shift / 100
    rgb = target.getRgb()[:3]
    chroma = (max(rgb) - min(rgb)) / 255
    saturation = min(1.0, chroma / max(0.05, 1 - abs(2 * light - 1))) * 80
    insert(doc, filter_node(doc, label, 'hsvadjustment', soft, type=1, colorize=True, h=max(0, target.hslHue()),
                            s=round(saturation), v=shift))
    return f'{target.name()}, lightness {shift:+d}'


def add_grade(doc, label, layers, selection=None):
    """A grade from Image Studio as a group on top of the picture: one layer per grade layer
    (the picture as graded up to that point), each with its mask and opacity, so any part
    can be hidden, faded or repainted. `layers`: [(name, QImage, QImage mask or None, 0..100)].
    With a `selection`, the whole group shows only there."""
    group = doc.createGroupLayer(label)
    root = doc.rootNode()
    children = root.childNodes()
    root.addChildNode(group, children[-1] if children else None)
    below = None
    for name, image, mask, opacity in layers:
        if (image.width(), image.height()) != (doc.width(), doc.height()):
            image = scaled_exact(image, doc.width(), doc.height())
        layer = pixel_node(doc, name, image)
        layer.setOpacity(round(255 * max(0, min(100, opacity)) / 100))
        group.addChildNode(layer, below)
        if mask is not None:
            transparency = doc.createTransparencyMask('Where')
            layer.addChildNode(transparency, None)
            transparency.setSelection(mask_selection(doc, mask))
        below = layer
    if selection is not None:
        where = doc.createTransparencyMask('Selection')
        group.addChildNode(where, None)
        where.setSelection(selection)
    activate(doc, group)
    return group


def auto_levels(doc, label, **_):
    """Levels from the whole picture's lightness: the darkest and brightest 0.5% become
    black and white, and the midtones move toward middle grey. (Krita's autocontrast
    filter measures each tile on its own, which leaves visible blocks.)"""
    image = preview(doc, 256).convertToFormat(ARGB32)
    data = raw_bytes(image)
    counts = [0] * 256
    for index in range(0, len(data), 4):
        if data[index + 3] > 8:
            counts[(data[index] * 29 + data[index + 1] * 150 + data[index + 2] * 77) >> 8] += 1
    total = sum(counts)
    if not total:
        raise StepError('The picture is empty.')

    def percentile(share):
        running = 0
        for value, count in enumerate(counts):
            running += count
            if running >= share * total:
                return value
        return 255
    low, high, middle = percentile(0.005), percentile(0.995), percentile(0.5)
    if high - low < 8:
        raise StepError('The picture has almost no tones to spread.')
    black, white = low / 255, high / 255
    # Gamma that maps the median to about 0.47 after stretching.
    stretched = min(0.95, max(0.05, (middle / 255 - black) / (white - black)))
    gamma = min(2.0, max(0.5, math.log(stretched) / math.log(0.47)))
    adjustment(doc, label, 'levels', lightness=levels(black, white, 1 / gamma))
    return f'black {low}, white {high}'


def invert_colors(doc, label, **_):
    adjustment(doc, label, 'invert')


def posterize(doc, levels, label, **_):
    adjustment(doc, label, 'posterize', steps=int(levels))


def threshold(doc, level, label, **_):
    adjustment(doc, label, 'threshold', threshold=int(level))


def blur(doc, radius, label, **_):
    size = scale_px(doc, radius)
    adjustment(doc, label, 'gaussian blur', horizRadius=size, vertRadius=size, lockAspect=True)


def motion_blur(doc, angle, length, label, **_):
    adjustment(doc, label, 'motion blur', blurAngle=int(angle), blurLength=scale_px(doc, length))


def lens_blur(doc, radius, label, **_):
    adjustment(doc, label, 'lens blur', irisRadius=scale_px(doc, radius))


def sharpen(doc, amount, label, **_):
    adjustment(doc, label, 'unsharp', amount=round(amount / 40, 2), halfSize=max(1, scale_px(doc, 2)),
               threshold=2, lightnessOnly=True)


def denoise(doc, strength, label, **_):
    adjustment(doc, label, 'waveletnoisereducer', threshold=round(1 + strength * 0.12, 2))


def pixelate(doc, size, label, **_):
    size = scale_px(doc, size)
    adjustment(doc, label, 'pixelize', pixelWidth=size, pixelHeight=size)


def oil_paint(doc, size, label, **_):
    adjustment(doc, label, 'oilpaint', brushSize=int(size), smooth=30)


def emboss(doc, label, **_):
    adjustment(doc, label, 'emboss', depth=30)


def edges(doc, label, **_):
    adjustment(doc, label, 'edge detection')


def round_corners(doc, radius, label, **_):
    adjustment(doc, label, 'roundcorners', radius=scale_px(doc, radius))


def vignette(doc, amount, label, **_):
    width, height = doc.width(), doc.height()
    image = QImage(width, height, ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    radius = math.hypot(width, height) / 2
    gradient = QRadialGradient(QPointF(width / 2, height / 2), radius)
    gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
    gradient.setColorAt(0.5, QColor(0, 0, 0, 0))
    gradient.setColorAt(1.0, QColor(0, 0, 0, round(255 * min(1.0, amount / 80))))
    painter.fillRect(image.rect(), gradient)
    painter.end()
    layer = pixel_layer(doc, label, image)
    layer.setBlendingMode('multiply')


def grain(doc, amount, label, **_):
    """Grey noise on a mid-grey layer in Overlay mode: texture without changing the light."""
    width, height = doc.width(), doc.height()
    image = QImage(width, height, ARGB32)
    image.fill(QColor(128, 128, 128))
    layer = pixel_layer(doc, label, image)
    noise = app().filter('noise')
    config = noise.configuration()
    for key, value in dict(level=100, opacity=100, grayscale=True).items():
        config.setProperty(key, value)
    noise.setConfiguration(config)
    noise.apply(layer, 0, 0, width, height)
    layer.setBlendingMode('overlay')
    layer.setOpacity(round(255 * min(1.0, amount / 100 * 0.25)))
    selection = current_selection(doc)
    if selection is not None:
        mask = doc.createTransparencyMask('Selection')
        layer.addChildNode(mask, None)
        mask.setSelection(selection)


def fill(doc, color, opacity, label, **_):
    image = QImage(doc.width(), doc.height(), ARGB32)
    image.fill(color_of(color))
    layer = pixel_layer(doc, label, image)
    layer.setOpacity(round(255 * opacity / 100))
    selection = current_selection(doc)
    if selection is not None:
        mask = doc.createTransparencyMask('Selection')
        layer.addChildNode(mask, None)
        mask.setSelection(selection)


def add_text(doc, text, position, size, color, font, label, **_):
    width, height = doc.width(), doc.height()
    px = max(8, round(height * size / 100))
    margin = round(min(width, height) * 0.05)
    horizontal = ('start', margin) if 'left' in position else ('end', width - margin) if 'right' in position else (
        'middle', width / 2)
    lines = str(text).split('\\n') if '\\n' in str(text) else str(text).split('\n')
    block = px * 1.15 * (len(lines) - 1)
    if position.startswith('top'):
        y = margin + px * 0.85
    elif position.startswith('bottom'):
        y = height - margin - block
    else:
        y = height / 2 + px * 0.35 - block / 2
    fill_color = color_of(color).name()
    outline = '#000000' if color_of(color).lightness() > 128 else '#ffffff'
    spans = ''.join(f'<tspan x="{horizontal[1]:.1f}" dy="{0 if index == 0 else px * 1.15:.1f}">{escape(line)}</tspan>'
                    for index, line in enumerate(lines))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<text x="{horizontal[1]:.1f}" y="{y:.1f}" text-anchor="{horizontal[0]}" '
           f'style="font-family:{escape(font)};font-size:{px}px;font-weight:bold;fill:{fill_color};'
           f'stroke:{outline};stroke-opacity:0.25;stroke-width:{max(1, px // 40)}px">{spans}</text></svg>')
    layer = doc.createVectorLayer(label)
    insert(doc, layer)
    layer.addShapesFromSvg(svg)


def crop(doc, aspect, **_):
    try:
        a, b = (float(part) for part in str(aspect).replace('x', ':').replace('/', ':').split(':')[:2])
        target = a / b
    except (ValueError, ZeroDivisionError):
        raise StepError(f'"{aspect}" is not a shape like 16:9.')
    width, height = doc.width(), doc.height()
    if width / height > target:
        new_w, new_h = round(height * target), height
    else:
        new_w, new_h = width, round(width / target)
    doc.crop((width - new_w) // 2, (height - new_h) // 2, new_w, new_h)
    settle(doc)
    return f'{new_w} × {new_h}'


def crop_rect(doc, x, y, w, h, **_):
    """Crop to a rectangle in pixels (a pipeline's exact frame)."""
    x, y = max(0, int(x)), max(0, int(y))
    w, h = min(int(w), doc.width() - x), min(int(h), doc.height() - y)
    if w < 1 or h < 1:
        raise StepError('The crop is outside the picture.')
    doc.crop(x, y, w, h)
    settle(doc)
    return f'{w} × {h}'


def canvas_size(doc, x, y, w, h, **_):
    """A larger (or smaller) canvas; x and y place the old picture's corner, so negative values
    add room on the left and top. New room is transparent."""
    doc.resizeImage(int(x), int(y), int(w), int(h))
    settle(doc)
    return f'{int(w)} × {int(h)}'


def crop_to_selection(doc, **_):
    selection = current_selection(doc)
    if selection is None:
        raise StepError('Nothing is selected to crop to.')
    doc.crop(selection.x(), selection.y(), selection.width(), selection.height())
    settle(doc)
    deselect(doc)
    return f'{selection.width()} × {selection.height()}'


def resize(doc, scale=0, width=0, height=0, **_):
    w, h = doc.width(), doc.height()
    if scale:
        new_w, new_h = round(w * scale / 100), round(h * scale / 100)
    elif width and height:
        new_w, new_h = int(width), int(height)
    elif width:
        new_w, new_h = int(width), round(h * width / w)
    elif height:
        new_w, new_h = round(w * height / h), int(height)
    else:
        raise StepError('Give a size in percent or pixels.')
    if not (8 <= new_w <= 16000 and 8 <= new_h <= 16000):
        raise StepError('That size is too small or too large.')
    doc.scaleImage(new_w, new_h, int(doc.resolution()), int(doc.resolution()), 'Bicubic')
    settle(doc)
    return f'{new_w} × {new_h}'


def rotate(doc, degrees, **_):
    doc.rotateImage(math.radians(degrees))
    settle(doc)
    return f'{doc.width()} × {doc.height()}'


def flip(doc, direction, **_):
    trigger('mirrorImageVertical' if direction == 'vertical' else 'mirrorImageHorizontal')
    settle(doc)


def new_layer(doc, name, **_):
    insert(doc, doc.createNode(name or 'Layer', 'paintlayer'))


def duplicate_layer(doc, **_):
    node = active_node(doc)
    if node is None:
        raise StepError('There is no layer to copy.')
    copy = node.duplicate()
    copy.setName(f'{node.name()} copy')
    insert(doc, copy, node)


def delete_layer(doc, layer, **_):
    node = find_layer(doc, layer)
    if node is None:
        raise StepError('There is no layer to delete.')
    if node.parentNode() is not None and node.parentNode() == doc.rootNode() and len(doc.rootNode().childNodes()) <= 1:
        raise StepError('The last layer cannot be deleted.')
    name = node.name()
    node.remove()
    return f'Deleted "{name}".'


def rename_layer(doc, name, **_):
    node = need_node(doc)
    node.setName(name)


def select_layer(doc, layer, **_):
    activate(doc, find_layer(doc, layer))


def need_node(doc):
    node = active_node(doc)
    if node is None:
        raise StepError('Select a layer first.')
    return node


def layer_opacity(doc, opacity, **_):
    need_node(doc).setOpacity(round(255 * opacity / 100))


def blend_mode(doc, mode, **_):
    from_name = {'normal': 'normal', 'multiply': 'multiply', 'screen': 'screen', 'overlay': 'overlay',
                 'soft light': 'soft_light', 'hard light': 'hard_light', 'color': 'color', 'hue': 'hue',
                 'saturation': 'saturation', 'luminosity': 'luminize', 'darken': 'darken', 'lighten': 'lighten',
                 'color dodge': 'dodge', 'color burn': 'burn', 'add': 'add', 'subtract': 'subtract',
                 'difference': 'diff', 'exclusion': 'exclusion', 'divide': 'divide'}
    need_node(doc).setBlendingMode(from_name.get(mode, 'normal'))


def hide_layer(doc, layer, **_):
    find_layer(doc, layer).setVisible(False)


def show_layer(doc, layer, **_):
    find_layer(doc, layer).setVisible(True)


def move_layer(doc, dx, dy, **_):
    node = need_node(doc)
    position = node.position()
    node.move(position.x() + round(doc.width() * dx / 100), position.y() + round(doc.height() * dy / 100))


def send_to_back(doc, **_):
    """Move the active layer under everything else in its group."""
    node = need_node(doc)
    parent = node.parentNode()
    if parent is None:
        return
    # childNodes() lists bottom first; addChildNode(node, None) would put it on top.
    others = [child for child in parent.childNodes() if child != node]
    parent.setChildNodes([node] + others)
    activate(doc, node)


def filter_layer(doc, filter, props, label, **_):
    """A Krita filter layer with the settings a pipeline computed (hue/saturation, colour balance)."""
    adjustment(doc, label, filter, **props)


def paint_fill(doc, color, label, **_):
    """A new paint layer with the colour painted where the selection is (soft edges kept as
    transparency), so later steps can blur or mask the paint itself, as PhotoCraft's fill does."""
    image = QImage(doc.width(), doc.height(), ARGB32)
    image.fill(color_of(color))
    selection = current_selection(doc)
    if selection is not None:
        alpha = QImage(doc.width(), doc.height(), GRAY8)
        alpha.fill(QColor(0, 0, 0))
        data = bytes(selection.pixelData(selection.x(), selection.y(), selection.width(), selection.height()))
        part = QImage(data, selection.width(), selection.height(), selection.width(), GRAY8)
        painter = QPainter(alpha)
        painter.drawImage(selection.x(), selection.y(), part)
        painter.end()
        image.setAlphaChannel(alpha)
    pixel_layer(doc, label, image)


def apply_filter(doc, filter, props, label, **_):
    """A Krita filter applied to the active layer's own pixels (a layer a pipeline painted, such as
    a shadow), inside the selection if there is one."""
    node = need_node(doc)
    if node.type() != 'paintlayer':
        raise StepError(f'{label} needs a paint layer.')
    found = app().filter(filter)
    if found is None:
        raise StepError(f'This Krita has no {filter} filter.')
    config = found.configuration()
    for key, value in props.items():
        config.setProperty(key, value)
    found.setConfiguration(config)
    selection = current_selection(doc)
    if selection is not None:
        found.apply(node, selection.x(), selection.y(), selection.width(), selection.height())
    else:
        found.apply(node, 0, 0, doc.width(), doc.height())


def mask_from_selection(doc, invert, label, **_):
    """Hide the active layer outside the selection (or inside it, with `invert`) with a mask,
    as a cut-out does; the paint layer under the active filter layers is used when the active
    layer is not one."""
    selection = current_selection(doc)
    if selection is None:
        raise StepError('Nothing is selected to mask with.')
    node = active_node(doc)
    if node is None or node.type() != 'paintlayer':
        node = bottom_paint_layer(doc)
    where = selection.duplicate()
    if invert:
        where.invert()
    mask = doc.createTransparencyMask(label)
    node.addChildNode(mask, None)
    mask.setSelection(where)


def merge_down(doc, **_):
    need_node(doc).mergeDown()


def flatten(doc, **_):
    doc.flatten()


def undo(doc, times=1, **_):
    trigger('edit_undo', int(times))


def redo(doc, times=1, **_):
    trigger('edit_redo', int(times))


LOCAL = {name: function for name, function in globals().items() if callable(function) and name in {
    'select_box', 'invert_selection', 'grow_selection', 'feather_selection', 'deselect', 'brightness', 'contrast',
    'saturation', 'hue', 'warmth', 'tint', 'black_and_white', 'sepia', 'colorize', 'auto_levels', 'invert_colors',
    'posterize', 'threshold', 'blur', 'motion_blur', 'lens_blur', 'sharpen', 'denoise', 'grain', 'pixelate',
    'oil_paint', 'emboss', 'edges', 'vignette', 'round_corners', 'crop', 'crop_to_selection', 'resize', 'rotate',
    'flip', 'new_layer', 'duplicate_layer', 'delete_layer', 'rename_layer', 'select_layer', 'layer_opacity',
    'blend_mode', 'hide_layer', 'show_layer', 'move_layer', 'merge_down', 'flatten', 'fill', 'add_text', 'undo',
    'redo', 'recolor_selection', 'crop_rect', 'canvas_size', 'send_to_back', 'filter_layer', 'mask_from_selection',
    'require_selection', 'paint_fill', 'apply_filter'}}


def run_local(doc, step, label):
    """Run one of Krita's own steps; returns a short note or None."""
    arguments = {key: value for key, value in step.items() if key not in ('op', 'label')}
    note = LOCAL[step['op']](doc, label=label, **arguments)
    settle(doc)
    return note


# ---- Document state for Image Studio ----------------------------------------------------

def state(doc):
    """What the browser and the planner need to know about the open picture."""
    if doc is None:
        return None
    active = doc.activeNode()
    layers = [dict(name=node.name(), type=node.type(), visible=node.visible(), depth=depth,
                   opacity=round(node.opacity() * 100 / 255), active=active is not None and node == active)
              for node, depth in walk(doc.rootNode()) if node.type() != 'selectionmask'][:60]
    import os
    return dict(name=os.path.basename(doc.fileName()) if doc.fileName() else doc.name() or 'Untitled',
                path=doc.fileName(), width=doc.width(), height=doc.height(), layers=layers,
                selection=current_selection(doc) is not None, color=f'{doc.colorModel()} {doc.colorDepth()}')


def projection(doc, x=0, y=0, w=None, h=None):
    """The visible picture (all layers merged) as an 8-bit QImage."""
    w = doc.width() if w is None else w
    h = doc.height() if h is None else h
    return doc.projection(x, y, w, h).convertToFormat(ARGB32)


def preview(doc, longest):
    return doc.thumbnail(longest, longest)


def flat_preview(doc, longest):
    """The preview over a light checkerboard, as editors show transparency (for JPEG)."""
    image = preview(doc, longest).convertToFormat(ARGB32)
    board = QImage(image.width(), image.height(), ARGB32)
    board.fill(QColor(255, 255, 255))
    painter = QPainter(board)
    cell = max(8, round(max(image.width(), image.height()) / 64))
    for y in range(0, image.height(), cell):
        for x in range((y // cell) % 2 * cell, image.width(), cell * 2):
            painter.fillRect(x, y, cell, cell, QColor(232, 232, 236))
    painter.drawImage(0, 0, image)
    painter.end()
    return board

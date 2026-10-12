"""The PhotoCraft studio's tool panels: Assistant, Adjust, Looks, Crop, Select, Text, Filters and All tools.

Each panel turns its controls into the same edits or commands the web studio sends; the
studio page posts them and every pixel change happens inside PhotoCraft.
"""

import json
import re
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QIntValidator, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from image_studio.desktop import theme
from image_studio.desktop.controls import Box, Flow, Range, shape_icon
from image_studio.desktop.theme import label

TARGETS = [('whole image', 'Whole image'), ('main subject', 'Subject'), ('background', 'Background'), ('sky', 'Sky')]
STRENGTHS = [('subtle', 'Subtle'), ('moderate', 'Moderate'), ('strong', 'Strong')]
ADJUSTMENTS = [
    ('LIGHT', [('exposure', 'Exposure (EV)', -3, 3, 0.05), ('brightness', 'Brightness', -100, 100, 1),
               ('contrast', 'Contrast', -50, 100, 1), ('highlights', 'Highlights', -100, 100, 1),
               ('shadows', 'Shadows', -100, 100, 1), ('whites', 'Whites', -100, 100, 1),
               ('blacks', 'Blacks', -100, 100, 1)]),
    ('COLOR', [('temperature', 'Temperature', -100, 100, 1), ('tint', 'Tint', -100, 100, 1),
               ('vibrance', 'Vibrance', -100, 100, 1), ('saturation', 'Saturation', -100, 100, 1),
               ('hue_shift', 'Hue', -180, 180, 1)]),
    ('PRESENCE', [('texture', 'Texture', -100, 100, 1), ('clarity', 'Clarity', -100, 100, 1),
                  ('dehaze', 'Dehaze', -100, 100, 1)]),
    ('DETAIL & EFFECTS', [('sharpen', 'Sharpening', 0, 150, 1), ('noise_reduction', 'Noise reduction', 0, 100, 1),
                          ('grain', 'Grain', 0, 100, 1), ('vignette', 'Vignette', -100, 100, 1)]),
]
LOOKS = [
    ('professional polish', 'Professional polish', '#6b8f71', '#d9c9a3'),
    ('warm portrait', 'Warm portrait', '#a8643a', '#f2c38b'),
    ('cinematic', 'Cinematic', '#1d5c63', '#e0894a'),
    ('moody', 'Moody', '#1c2229', '#5c6670'),
    ('dramatic', 'Dramatic', '#111111', '#8a8f99'),
    ('bright and airy', 'Bright & airy', '#dfe8ee', '#fff6e8'),
    ('vintage', 'Vintage film', '#8c7a5b', '#d8c7a0'),
    ('matte', 'Matte', '#4c4c4c', '#bdb7aa'),
    ('hdr', 'HDR detail', '#25476a', '#e6b54a'),
    ('bleachBypass', 'Bleach bypass', '#5a5f5c', '#c9cbc4'),
    ('crossProcess', 'Cross process', '#2f7a5f', '#e8d35a'),
    ('dayForNight', 'Day for night', '#0f1f3d', '#3d5a8a'),
    ('warm', 'Warm', '#b56b2a', '#f5c27a'),
    ('cool', 'Cool', '#2a5fb5', '#9cc7f5'),
    ('monoContrast', 'Noir', '#000000', '#dddddd'),
]
ASPECTS = ['1:1', '4:5', '5:4', '3:2', '2:3', '16:9', '9:16', '3:1']
KEEP = [('center', 'The center'), ('subject', 'The main subject (found by AI)'), ('object', 'A named object…'),
        ('top', 'The top'), ('bottom', 'The bottom'), ('left', 'The left side'), ('right', 'The right side')]
POSITIONS = ['top left', 'top', 'top right', 'left', 'center', 'right', 'bottom left', 'bottom', 'bottom right']
TEXT_SIZES = [('small', 'Small'), ('medium', 'Medium'), ('large', 'Large'), ('huge', 'Huge'), ('points', 'Exact pt')]
TEXT_STYLES = ['bold', 'italic', 'shadow', 'outline', 'glow']
FILTER_GROUPS = [
    ('BLUR', ['filter.blur.gaussianBlur', 'filter.blur.lensBlur', 'filter.blur.motionBlur',
              'filter.blurGallery.tiltShift', 'filter.blurGallery.irisBlur', 'filter.blurGallery.spinBlur',
              'filter.blur.surfaceBlur', 'filter.blur.radialBlur']),
    ('SHARPEN', ['filter.sharpen.smartSharpen', 'filter.sharpen.unsharpMask', 'filter.other.highPass']),
    ('NOISE', ['filter.noise.reduceNoise', 'filter.noise.addNoise', 'filter.noise.dustAndScratches',
               'filter.noise.median']),
    ('DEVELOP', ['filter.cameraRaw', 'filter.lensCorrection']),
    ('LIGHT', ['filter.render.relight', 'filter.render.lightingEffects', 'filter.render.lensFlare']),
    ('ARTISTIC', ['filter.stylize.oilPaint', 'filter.gallery.watercolor', 'filter.gallery.coloredPencil',
                  'filter.gallery.cutout', 'filter.gallery.dryBrush', 'filter.gallery.posterEdges',
                  'filter.gallery.inkOutlines', 'filter.gallery.paintDaubs', 'filter.gallery.sumiE']),
    ('STYLIZE', ['filter.stylize.emboss', 'filter.stylize.findEdges', 'filter.stylize.solarize',
                 'filter.stylize.diffuse', 'filter.stylize.wind', 'filter.stylize.tiles']),
]
EXAMPLES = [
    'Professional polish',
    'Crop to 4:5 keeping the subject in frame, warm it slightly and add “SUMMER” at the top in white',
    'Blur the background, brighten the subject a little and add a subtle vignette',
    'Make the sky dramatic, deepen the blues and remove the small object on the left',
    'Cut out the subject and put it on a pastel pink background',
]
TARGET_WORDS = {'whole image': 'Whole image', 'main subject': 'Subject', 'background': 'Background', 'sky': 'Sky',
                'color': 'Color range', 'shadows': 'Shadows', 'midtones': 'Midtones', 'highlights': 'Highlights',
                'area': 'Area', 'layer': 'Layer'}
MAX_PROMPT = 6000


# Pure rules -------------------------------------------------------------------------------

def readable(text):
    """PhotoCraft sends some text with its UTF-8 read as Windows-1252 ("Â·" for "·"); show it as meant."""
    text = str(text or '')
    if any(sign in text for sign in ('Ã', 'Â', 'â€')):
        try:
            return text.encode('cp1252').decode('utf-8')
        except UnicodeError:
            pass
    return text


def plain(command_label):
    return readable(command_label).replace('…', '').strip()


def flatten(layers, depth=0):
    """Every layer with its nesting depth, top to bottom, groups before what is inside them."""
    result = []
    for layer in layers or []:
        result.append((layer, depth))
        result.extend(flatten(layer.get('children'), depth + 1))
    return result


def adjust_edits(values, target):
    """The Adjust sliders that moved, as edits, and a history label for them."""
    changed = [(action, value) for action, value in values.items() if value]
    edits = [dict(action=action, value=abs(value), direction='increase' if value > 0 else 'decrease', target=target,
                  quote='lighten the edges' if action == 'vignette' and value > 0 else f'{action} {value}')
             for action, value in changed]
    shown = ', '.join(f'{action.replace("_", " ")} {"+" if value > 0 else ""}{value}' for action, value in changed)
    return edits, f'Adjust: {shown}'


def crop_edit(aspect, keep, named=''):
    named = named.strip()
    target = 'main subject' if keep == 'subject' else 'object' if keep == 'object' and named else 'whole image'
    return dict(action='crop_aspect', aspect=aspect, target=target, object=named if keep == 'object' else '',
                position='center' if keep == 'center' else keep, quote=f'crop to {aspect}')


def text_edit(words, position, size, points, color, font, styles):
    """Add text: a named size, or an exact point size; no color means a readable one is chosen."""
    exact = size == 'points'
    return dict(action='add_text', text=words.strip(), position=position, size='' if exact else size,
                value=points if exact else None, quote=f'{points}pt' if exact else 'add text', color=color or '',
                choice=' '.join(part for part in [font, *styles] if part))


def field_title(name):
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', name)[:1].upper() + re.sub(r'([a-z])([A-Z])', r'\1 \2', name)[1:]


def filter_name(command):
    return re.sub(r'([A-Z])', r' \1', command.split('.')[-1]).strip().capitalize()


def describe_layer(layer):
    if layer.get('text'):
        text = layer['text']
        return f'“{readable(text.get("text"))}” · {text.get("font")} {round(text.get("sizePt") or 0)} pt'
    if layer.get('adjustment'):
        name, values = next(iter(layer['adjustment'].items()), ('', {}))
        shown = [f'{key} {round(value, 2) if isinstance(value, float) else value}'
                 for key, value in (values or {}).items() if isinstance(value, (int, float, str, bool))][:4]
        return ' · '.join([name, *shown])
    return layer.get('kind', '')


# Small controls ---------------------------------------------------------------------------

class Segmented(QWidget):
    """A row of mutually exclusive buttons; value() is the chosen id."""

    changed = Signal(str)

    def __init__(self, options, value, columns=0):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        columns = columns or len(options)
        self.group = QButtonGroup(self)
        self.ids = []
        for index, (key, text) in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty('kind', 'segment')
            button.setMinimumWidth(10)
            self.group.addButton(button, index)
            self.ids.append(key)
            grid.addWidget(button, index // columns, index % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        self.group.idClicked.connect(lambda index: self.changed.emit(self.ids[index]))
        self.setValue(value)

    def value(self):
        return self.ids[max(self.group.checkedId(), 0)]

    def setValue(self, value):
        self.group.button(self.ids.index(value)).setChecked(True)

    def button(self, key):
        return self.group.button(self.ids.index(key))


class ColorButton(QPushButton):
    """A color swatch; clicking it opens the color chooser."""

    changed = Signal(str)

    def __init__(self, color, title='Choose a color'):
        super().__init__()
        self.title = title
        self.setFixedSize(44, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.choose)
        self.set_color(color)

    def set_color(self, color):
        self.color = color
        self.setToolTip(color)
        self.update()

    def choose(self):
        chosen = QColorDialog.getColor(QColor(self.color), self, self.title)
        if chosen.isValid():
            self.set_color(chosen.name())
            self.changed.emit(self.color)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isEnabled() else 0.4)
        painter.setPen(QColor(theme.LIME if self.underMouse() else theme.LINE))
        painter.setBrush(QColor(self.color))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)


class Card(QFrame):
    """A clickable card with wrapping text (a push button cannot wrap)."""

    clicked = Signal()

    def __init__(self, text):
        super().__init__()
        self.setProperty('card', True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 10, 8)
        self.text = label(text, 'muted', wrap=True)
        row.addWidget(self.text, 1)
        arrow = label('')
        arrow.setPixmap(theme.icon('chevron-right', theme.MUTED).pixmap(12, 12))
        row.addWidget(arrow)

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()

    def enterEvent(self, event):
        self.text.setProperty('role', '')
        self.text.style().polish(self.text)

    def leaveEvent(self, event):
        self.text.setProperty('role', 'muted')
        self.text.style().polish(self.text)


def swatch(start, end):
    """A small rounded gradient, the preview of a look."""
    result = QIcon()
    for side in (18, 36):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, side, side)
        gradient.setColorAt(0, QColor(start))
        gradient.setColorAt(1, QColor(end))
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(0, 0, side, side), side / 4, side / 4)
        painter.fillPath(shape, gradient)
        painter.end()
        result.addPixmap(pixmap)
    return result


# Panels -----------------------------------------------------------------------------------

class Panel(QScrollArea):
    """One tool's controls, scrolling; buttons registered with act() follow the document and the job."""

    def __init__(self, studio, title, intro):
        super().__init__()
        self.studio = studio
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        self.column = QVBoxLayout(body)
        self.column.setContentsMargins(20, 18, 16, 18)
        self.column.setSpacing(10)
        self.column.addWidget(label(title, 'heading'))
        self.column.addWidget(label(intro, 'muted', wrap=True))
        self.guarded = []  # (button, extra condition)

    def act(self, button, ready=None):
        self.guarded.append((button, ready))
        return button

    def button(self, text, slot, icon=None, kind='', ready=None):
        text = text.replace('&', '&&')  # a lone & would mark a keyboard shortcut
        widget = QPushButton(theme.icon(icon, theme.INK if kind == 'primary' else theme.TEXT), text) if icon else (
            QPushButton(text))
        if kind:
            widget.setProperty('kind', kind)
        widget.clicked.connect(slot)
        return self.act(widget, ready)

    def heading(self, text, layout=None):
        (layout or self.column).addSpacing(6)
        (layout or self.column).addWidget(label(text, 'eyebrow'))

    def sync(self):
        free = self.studio.document is not None and not self.studio.busy
        for button, ready in self.guarded:
            button.setEnabled(free and (ready is None or bool(ready())))

    def edits(self, edits, title):
        self.studio.edits(edits, title)


class AssistantPanel(Panel):
    """Describe an edit in words, review how it was understood, then apply it."""

    def __init__(self, studio):
        super().__init__(studio, 'Describe your edit',
                         'Say what to change, where, and how much. Name what must stay untouched. Every detail '
                         'is read.')
        self.show_steps = False
        self.heading('APPLY PROMPT TO')
        self.scope = Segmented([('whole', 'Whole image'), ('area', 'Mark an area')], 'whole')
        self.scope.button('area').setIcon(theme.icon('lasso'))
        self.scope.changed.connect(lambda value: studio.set_area(value == 'area'))
        self.column.addWidget(self.scope)
        self.area_note = label('Restart the studio after the current edit finishes to enable area marking.', 'small',
                               wrap=True)
        self.column.addWidget(self.area_note)

        self.area = Box()
        area = QVBoxLayout(self.area)
        area.setContentsMargins(0, 0, 0, 0)
        area.setSpacing(8)
        self.tool = Segmented([('brush', 'Brush'), ('lasso', 'Lasso'), ('erase', 'Erase')], 'brush')
        for key, icon in (('brush', 'brush'), ('lasso', 'lasso'), ('erase', 'eraser')):
            self.tool.button(key).setIcon(theme.icon(icon))
        self.tool.changed.connect(studio.set_area_tool)
        area.addWidget(self.tool)
        self.brush_size = Range('Brush size (% of the width)', 0.3, 15, 0.1)
        self.brush_size.setValue(3)
        self.brush_size.changed.connect(lambda value: studio.set_brush(value / 100))
        area.addWidget(self.brush_size)
        self.area_help = label('', 'small', wrap=True)
        area.addWidget(self.area_help)
        row = QHBoxLayout()
        self.undo_mark = QPushButton(theme.icon('undo-2'), 'Undo mark')
        self.undo_mark.setToolTip('Take back the last mark (Ctrl + Z)')
        self.undo_mark.clicked.connect(studio.undo_mark)
        row.addWidget(self.undo_mark)
        self.clear_marks = QPushButton(theme.icon('eraser'), 'Clear marks')
        self.clear_marks.clicked.connect(studio.clear_marks)
        row.addWidget(self.clear_marks)
        area.addLayout(row)
        self.area_state = label('', 'small', wrap=True)
        area.addWidget(self.area_state)
        self.column.addWidget(self.area)

        self.column.addSpacing(4)
        self.prompt = QPlainTextEdit()
        self.prompt.setFixedHeight(120)
        self.prompt.setTabChangesFocus(True)
        self.prompt.setPlaceholderText(
            'Warm only the sky a little, blur the background, add “SUMMER” at the top in white at 48 pt, then '
            'crop to 4:5. Keep the person unchanged.')
        self.prompt.textChanged.connect(self.prompt_changed)
        self.column.addWidget(self.prompt)
        foot = QHBoxLayout()
        self.planner = label('', 'small')
        foot.addWidget(self.planner, 1)
        self.plan_button = QPushButton(theme.icon('send', theme.INK), 'Plan')
        self.plan_button.setProperty('kind', 'primary')
        self.plan_button.clicked.connect(self.plan)
        foot.addWidget(self.plan_button)
        self.column.addLayout(foot)

        self.examples = Box()
        examples = QVBoxLayout(self.examples)
        examples.setContentsMargins(0, 6, 0, 0)
        examples.setSpacing(6)
        examples.addWidget(label('TRY', 'eyebrow'))
        self.example_cards = []
        for text in EXAMPLES:
            card = Card(text)
            card.clicked.connect(lambda text=text: self.set_prompt(text))
            examples.addWidget(card)
            self.example_cards.append(card)
        self.column.addWidget(self.examples)

        self.plan_box = Box()
        self.plan_layout = QVBoxLayout(self.plan_box)
        self.plan_layout.setContentsMargins(0, 6, 0, 0)
        self.plan_layout.setSpacing(8)
        self.column.addWidget(self.plan_box)
        self.check_box = Box()
        self.check_layout = QVBoxLayout(self.check_box)
        self.check_layout.setContentsMargins(0, 6, 0, 0)
        self.check_layout.setSpacing(6)
        self.column.addWidget(self.check_box)
        self.column.addStretch()
        self.shown = None  # what the plan and check sections were last built from

    def set_prompt(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        cursor = self.prompt.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.prompt.setTextCursor(cursor)

    def prompt_changed(self):
        text = self.prompt.toPlainText()
        if len(text) > MAX_PROMPT:
            self.prompt.setPlainText(text[:MAX_PROMPT])
            return
        self.sync()

    def can_plan(self):
        studio = self.studio
        return (studio.document is not None and not studio.busy and not studio.canvas.draft
                and bool(self.prompt.toPlainText().strip()) and (not studio.area or bool(studio.canvas.marks)))

    def plan(self):
        if self.can_plan():
            self.studio.plan(self.prompt.toPlainText())

    def sync(self):
        super().sync()
        studio = self.studio
        capabilities = studio.capabilities or {}
        available = bool(capabilities.get('marked_area', True))
        free = not studio.busy
        self.scope.setValue('area' if studio.area else 'whole')
        self.scope.button('whole').setEnabled(free)
        self.scope.button('area').setEnabled(free and studio.document is not None and available)
        self.area_note.setVisible(not available)
        self.area.setVisible(studio.area)
        self.tool.setValue(studio.canvas.tool_choice)
        for key in ('brush', 'lasso', 'erase'):
            self.tool.button(key).setEnabled(free)
        self.brush_size.setVisible(studio.canvas.tool_choice != 'lasso')
        self.brush_size.setEnabled(free)
        marks = len(studio.canvas.marks)
        self.area_help.setText(
            ('Draw a closed loop around each spot.' if studio.canvas.tool_choice == 'lasso'
             else 'Paint over the spots you want to change.')
            + ' You can mark several spots. Only the green area will be edited.')
        self.undo_mark.setEnabled(free and bool(marks))
        self.clear_marks.setEnabled(free and bool(marks))
        self.area_state.setText('Marked area only · outside protected' if marks else 'Mark the photo before planning.')
        self.planner.setText('Local vision planner · Ctrl + Enter' if capabilities.get('brain')
                             else 'Planner not installed · presets only')
        self.plan_button.setEnabled(self.can_plan())
        self.plan_button.setText('Planning…' if studio.busy and studio.job_kind == 'plan' else 'Plan')
        self.examples.setVisible(studio.plan_data is None)
        document = studio.document
        key = (json.dumps(studio.plan_data, sort_keys=True) if studio.plan_data else '',
               document and document['revision'], studio.busy, self.show_steps)
        if key != self.shown:
            self.shown = key
            self.build_plan()
            self.build_check()

    # The plan and the result check are rebuilt whenever what they show changes.

    @staticmethod
    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)  # gone at once, not only when the deletion comes round
                widget.deleteLater()
            elif item.layout():
                AssistantPanel.clear(item.layout())

    def note(self, layout, text, icon='info', color=theme.MUTED):
        row = QHBoxLayout()
        row.setSpacing(8)
        mark = label('')
        mark.setPixmap(theme.icon(icon, color).pixmap(13, 13))
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label(text, 'small', wrap=True, selectable=True), 1)
        layout.addLayout(row)

    def build_plan(self):
        layout, plan, studio = self.plan_layout, self.studio.plan_data, self.studio
        self.clear(layout)
        self.plan_box.setVisible(plan is not None)
        if plan is None:
            return
        edits, steps = plan.get('edits') or [], plan.get('steps') or []
        count = len(edits) or len(steps)
        head = QHBoxLayout()
        head.addWidget(label(f'I UNDERSTOOD {count} CHANGE{"" if count == 1 else "S"}', 'eyebrow'))
        head.addStretch()
        discard = QPushButton('Discard')
        discard.setProperty('kind', 'flat')
        discard.clicked.connect(studio.discard_plan)
        head.addWidget(discard)
        layout.addLayout(head)
        for index, edit in enumerate(edits):
            layout.addWidget(EditCard(index, edit, studio.set_highlight))
        if plan.get('preserve'):
            self.note(layout, 'Kept unchanged: ' + '; '.join(plan['preserve']), 'lock', theme.LIME)
        for text in [*(plan.get('questions') or []), *(plan.get('notes') or [])]:
            self.note(layout, text)
        unresolved = plan.get('unresolved') or []
        if unresolved:
            title = 'Not included in this plan' if steps else 'Nothing can be applied yet'
            self.note(layout, f'{title}: ' + ' '.join(unresolved)
                      + ' Rephrase and plan again, or apply the parts that were understood.',
                      'triangle-alert', theme.WARN)
        toggle = QPushButton(theme.icon('chevron-down' if self.show_steps else 'chevron-right', theme.MUTED),
                             f'{len(steps)} engine steps')
        toggle.setProperty('kind', 'flat')
        toggle.clicked.connect(self.flip_steps)
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        if self.show_steps:
            for step in steps:
                text = f'<code>{step["command"]}</code> {step.get("label", "")}'
                if step.get('expert'):
                    text += ' <i>· settings chosen by AI</i>'
                line = label(text, 'small', wrap=True)
                line.setTextFormat(Qt.TextFormat.RichText)
                line.setToolTip(json.dumps(step.get('params'), indent=1)[:1500])
                layout.addWidget(line)
        if studio.document and plan.get('revision') != studio.document['revision']:
            self.note(layout, 'The document changed since this plan. Plan again to apply it to the current version.')
        elif steps:
            text = 'Apply the understood parts' if unresolved else (
                f'Apply {len(edits) or ""} change{"" if len(edits) == 1 else "s"}'.replace('  ', ' '))
            apply = QPushButton(theme.icon('sparkles', theme.INK), ' ' + text)
            apply.setProperty('kind', 'primary')
            apply.setProperty('size', 'large')
            apply.setEnabled(not studio.busy)
            apply.clicked.connect(lambda: studio.apply_plan(bool(unresolved)))
            layout.addWidget(apply)

    def flip_steps(self):
        self.show_steps = not self.show_steps
        self.sync()

    def build_check(self):
        layout, document = self.check_layout, self.studio.document
        self.clear(layout)
        revision = document['history'][document['cursor']] if document and document['cursor'] > 0 else None
        checks = (revision or {}).get('checks') or []
        review = (revision or {}).get('review') or []
        notes = (revision or {}).get('notes') or []
        visible = bool(checks or review or notes)
        self.check_box.setVisible(visible)
        if not visible:
            return
        failed = sum(not check.get('passed') for check in checks) + sum(
            verdict.get('verdict') == 'not done' for verdict in review)
        head = QHBoxLayout()
        head.addWidget(label('RESULT CHECK', 'eyebrow'))
        head.addStretch()
        summary = label(f'{failed} item{"s" if failed > 1 else ""} to look at' if failed else 'Everything checked out',
                        'value')
        summary.setStyleSheet(f'color: {theme.WARN if failed else theme.LIME};')
        head.addWidget(summary)
        layout.addLayout(head)
        for check in checks:
            passed = check.get('passed')
            self.note(layout, check.get('check') or '', 'check' if passed else 'x',
                      theme.LIME if passed else theme.DANGER)
        if review:
            layout.addWidget(label('AI visual review (can be wrong; measured checks above are exact)', 'small',
                                   wrap=True))
            requirements = revision.get('requirements') or []
            for verdict in review:
                state = verdict.get('verdict')
                item = verdict.get('item')
                if not item and isinstance(verdict.get('requirement'), int) and verdict['requirement'] < len(
                        requirements):
                    item = requirements[verdict['requirement']]
                icon, color = {'done': ('check', theme.LIME), 'not done': ('x', theme.DANGER)}.get(
                    state, ('circle-help', theme.WARN))
                self.note(layout, f'{item or ""}: {verdict.get("note") or state}', icon, color)
        for text in notes:
            self.note(layout, text)


class EditCard(QFrame):
    """One understood change; pointing at it outlines where it applies on the photo."""

    def __init__(self, index, edit, highlight):
        super().__init__()
        self.index, self.highlight = index, highlight
        self.setProperty('card', True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        number = label(str(index + 1), 'badge')
        row.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(3)
        if edit.get('quote'):
            column.addWidget(label(f'“{edit["quote"]}”', 'value', wrap=True))
        if edit.get('explain'):
            column.addWidget(label(edit['explain'], 'small', wrap=True))
        chips = [(edit.get('action') or '').replace('_', ' ')]
        target = edit.get('target')
        if target and target != 'whole image':
            chips.append(edit.get('object') or TARGET_WORDS.get(target, target))
        if edit.get('value') is not None:
            chips.append(str(edit['value']))
        elif edit.get('strength') and edit['strength'] != 'moderate':
            chips.append(edit['strength'])
        chips += [edit[key] for key in ('color', 'position') if edit.get(key)]
        column.addWidget(label(' · '.join(chip for chip in chips if chip), 'small', wrap=True))
        row.addLayout(column, 1)

    def enterEvent(self, event):
        self.highlight(self.index)

    def leaveEvent(self, event):
        self.highlight(None)


class AdjustPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Adjust',
                         'Light, color and detail, developed non-destructively. Choose where it applies.')
        self.target = Segmented(TARGETS, 'whole image', columns=2)
        self.column.addWidget(self.target)
        self.sliders = {}
        for group, items in ADJUSTMENTS:
            self.heading(group)
            for action, title, low, high, step in items:
                slider = Range(title, low, high, step)
                slider.setValue(0)
                slider.changed.connect(lambda _: self.sync())
                self.column.addWidget(slider)
                self.sliders[action] = slider
        self.column.addStretch()
        row = QHBoxLayout()
        self.reset = QPushButton('Reset')
        self.reset.clicked.connect(self.clear)
        row.addWidget(self.reset)
        self.apply = self.button('Apply', self.run, 'sliders-horizontal', 'primary', lambda: self.values())
        row.addWidget(self.apply, 1)
        self.column.addLayout(row)

    def values(self):
        return {action: slider.value() for action, slider in self.sliders.items() if slider.value()}

    def clear(self):
        for slider in self.sliders.values():
            slider.setValue(0)
        self.sync()

    def run(self):
        values = self.values()
        if values:
            self.edits(*adjust_edits(values, self.target.value()))
            self.clear()

    def sync(self):
        super().sync()
        count = len(self.values())
        self.reset.setEnabled(bool(count))
        self.apply.setText(f'Apply {count or ""} adjustment{"" if count == 1 else "s"}'.replace('  ', ' '))


class LooksPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Looks', 'Complete color grades. Each one is a set of editable layers and filters.')
        self.strength = Segmented(STRENGTHS, 'moderate')
        self.column.addWidget(self.strength)
        grid = QGridLayout()
        grid.setSpacing(6)
        for index, (key, title, start, end) in enumerate(LOOKS):
            button = self.button(title, lambda _=False, key=key, title=title: self.edits(
                [dict(action='look', choice=key, quote=title, strength=self.strength.value())], f'Look: {title}'))
            button.setIcon(swatch(start, end))
            button.setIconSize(QSize(18, 18))
            button.setStyleSheet('text-align: left;')
            button.setMinimumWidth(10)
            grid.addWidget(button, index // 2, index % 2)
        self.column.addLayout(grid)

        self.heading('BLACK & WHITE')
        row = QHBoxLayout()
        for style in ('neutral', 'high contrast', 'infrared'):
            button = self.button(style.capitalize(), lambda _=False, style=style: self.edits(
                [dict(action='black_and_white', choice=style, quote=f'black and white {style}')],
                f'Black & white ({style})'))
            button.setMinimumWidth(10)
            row.addWidget(button)
        self.column.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label('Toned', 'muted'))
        self.tint = ColorButton('#a3845c')
        row.addWidget(self.tint)
        row.addWidget(self.button('Apply toned', lambda: self.edits(
            [dict(action='black_and_white', color=self.tint.color, quote='toned black and white')],
            'Toned black & white')), 1)
        row.addWidget(self.button('Sepia', lambda: self.edits([dict(action='sepia', quote='sepia')], 'Sepia')))
        self.column.addLayout(row)

        self.heading('DUOTONE')
        row = QHBoxLayout()
        row.addWidget(label('Shadows', 'muted'))
        self.dark = ColorButton('#14213d')
        row.addWidget(self.dark)
        row.addWidget(label('Highlights', 'muted'))
        self.light = ColorButton('#fcd116')
        row.addWidget(self.light)
        row.addWidget(self.button('Apply', lambda: self.edits(
            [dict(action='duotone', color=f'{self.dark.color} and {self.light.color}', quote='duotone')],
            'Duotone')), 1)
        self.column.addLayout(row)
        self.column.addStretch()


class CropPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Crop & rotate', '')
        self.intro = self.column.itemAt(1).widget()
        self.heading('CROP TO A SHAPE')
        self.column.addWidget(label('Keep in frame', 'small'))
        self.keep = QComboBox()
        for key, title in KEEP:
            self.keep.addItem(title, key)
        self.keep.currentIndexChanged.connect(lambda _: self.sync())
        self.column.addWidget(self.keep)
        self.named = QLineEdit()
        self.named.setPlaceholderText('the red car')
        self.named.textChanged.connect(lambda _: self.sync())
        self.column.addWidget(self.named)
        grid = QGridLayout()
        grid.setSpacing(6)
        for index, aspect in enumerate(ASPECTS):
            wide, tall = map(int, aspect.split(':'))
            button = self.button(aspect, lambda _=False, aspect=aspect: self.edits(
                [crop_edit(aspect, self.keep.currentData(), self.named.text())], f'Crop to {aspect}'),
                ready=lambda: self.keep.currentData() != 'object' or self.named.text().strip())
            button.setIcon(shape_icon(wide, tall))
            button.setMinimumWidth(10)
            grid.addWidget(button, index // 4, index % 4)
        self.column.addLayout(grid)

        self.heading('ROTATE & FLIP')
        row = QHBoxLayout()
        for icon, tip, edit, title in (
                ('rotate-ccw', 'Rotate 90° left', dict(action='rotate', value=90, choice='counterclockwise',
                                                       quote='rotate 90 counterclockwise'), 'Rotate left'),
                ('rotate-cw', 'Rotate 90° right', dict(action='rotate', value=90, choice='clockwise',
                                                       quote='rotate 90 clockwise'), 'Rotate right'),
                ('flip-horizontal-2', 'Flip horizontally', dict(action='flip', choice='horizontal',
                                                                quote='flip horizontal'), 'Flip horizontally'),
                ('flip-vertical-2', 'Flip vertically', dict(action='flip', choice='vertical', quote='flip vertical'),
                 'Flip vertically')):
            button = self.button('', lambda _=False, edit=edit, title=title: self.edits([edit], title), icon)
            button.setToolTip(tip)
            row.addWidget(button)
        self.column.addLayout(row)
        self.angle = Range('Straighten (degrees)', -15, 15, 0.1)
        self.angle.setValue(0)
        self.angle.changed.connect(lambda _: self.sync())
        self.column.addWidget(self.angle)
        self.column.addWidget(self.button('Straighten (crops the empty corners)', self.straighten,
                                          ready=lambda: self.angle.value()))

        self.heading('RESIZE')
        row = QHBoxLayout()
        self.width_box, self.height_box = QLineEdit(), QLineEdit()
        for box, other in ((self.width_box, 'h'), (self.height_box, 'w')):
            box.setValidator(QIntValidator(1, 30000, box))
            box.textEdited.connect(lambda _=None, side=other: self.resized(side))
            row.addWidget(box, 1)
            if other == 'h':
                row.addWidget(label('×', 'muted'))
        self.lock = QCheckBox('Keep shape')
        self.lock.setChecked(True)
        self.lock.toggled.connect(lambda _: self.sync())
        row.addWidget(self.lock)
        self.column.addLayout(row)
        self.resize_button = self.button('Resize', self.resize_document,
                                         ready=lambda: self.width_box.text() and self.height_box.text())
        self.column.addWidget(self.resize_button)

        self.heading('BORDER')
        row = QHBoxLayout()
        self.border = QSpinBox()
        self.border.setRange(1, 2000)
        self.border.setValue(40)
        self.border.setSuffix(' px')
        row.addWidget(self.border)
        self.border_color = ColorButton('#ffffff')
        row.addWidget(self.border_color)
        row.addWidget(self.button('Add border', lambda: self.edits(
            [dict(action='canvas_border', value=self.border.value(), color=self.border_color.color,
                  quote=f'{self.border.value()}px border')], f'Add {self.border.value()}px border')), 1)
        self.column.addLayout(row)
        self.column.addStretch()

    def document_size(self):
        state = (self.studio.document or {}).get('state') or {}
        return state.get('width') or 0, state.get('height') or 0

    def resized(self, other):
        width, height = self.document_size()
        if self.lock.isChecked() and width and height:
            if other == 'h' and self.width_box.text():
                self.height_box.setText(str(round(int(self.width_box.text()) * height / width)))
            elif other == 'w' and self.height_box.text():
                self.width_box.setText(str(round(int(self.height_box.text()) * width / height)))
        self.sync()

    def straighten(self):
        angle = self.angle.value()
        way = 'clockwise' if angle > 0 else 'counterclockwise'
        self.edits([dict(action='straighten', value=abs(angle), choice=way,
                         quote=f'straighten {abs(angle)} degrees {way}')], f'Straighten {angle}°')
        self.angle.setValue(0)
        self.sync()

    def resize_document(self):
        width, height = self.width_box.text(), self.height_box.text()
        self.edits([dict(action='resize', quote=f'resize to {width}x{height}')], f'Resize to {width}×{height}')

    def sync(self):
        super().sync()
        width, height = self.document_size()
        self.intro.setText(f'Exact geometry, computed from the document ({width} × {height}).' if width
                           else 'Exact geometry, computed from the document.')
        self.named.setVisible(self.keep.currentData() == 'object')
        self.width_box.setPlaceholderText(str(width or ''))
        self.height_box.setPlaceholderText(str(height or ''))
        self.resize_button.setText('Resize' if self.lock.isChecked() else 'Resize (crops first so nothing stretches)')


class SelectPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Select & cut out',
                         'The planner finds what you name; PhotoCraft outlines it precisely and every result is '
                         'masked.')
        self.column.addWidget(label('Subject', 'small'))
        self.subject = QLineEdit()
        self.subject.setPlaceholderText('Empty for the main subject, or: the woman, the car…')
        self.column.addWidget(self.subject)

        self.heading('REMOVE BACKGROUND')
        row = QHBoxLayout()
        self.transparent = QCheckBox('Transparent')
        self.transparent.toggled.connect(lambda _: self.sync())
        row.addWidget(self.transparent)
        self.backdrop = ColorButton('#ffffff', 'Backdrop color')
        row.addWidget(self.backdrop)
        row.addStretch()
        row.addWidget(self.button('Cut out', lambda: self.edits(
            [dict(action='remove_background', target='main subject', object=self.subject.text().strip(),
                  color='' if self.transparent.isChecked() else self.backdrop.color, quote='remove the background')],
            'Remove background')))
        self.column.addLayout(row)

        self.heading('BLUR BACKGROUND')
        self.blur = Segmented(STRENGTHS, 'moderate')
        self.column.addWidget(self.blur)
        self.column.addWidget(self.button('Blur behind the subject', lambda: self.edits(
            [dict(action='blur_background', target='object' if self.subject.text().strip() else 'main subject',
                  object=self.subject.text().strip(), strength=self.blur.value(), quote='blur the background')],
            'Blur background')))

        self.heading('REMOVE AN OBJECT')
        row = QHBoxLayout()
        self.remove = QLineEdit()
        self.remove.setPlaceholderText('the trash can on the left')
        self.remove.textChanged.connect(lambda _: self.sync())
        row.addWidget(self.remove, 1)
        row.addWidget(self.button('Remove', lambda: self.edits(
            [dict(action='remove_object', target='object', object=self.remove.text().strip(),
                  quote=f'remove {self.remove.text().strip()}')], f'Remove {self.remove.text().strip()}'),
            ready=lambda: self.remove.text().strip()))
        self.column.addLayout(row)
        self.column.addWidget(label('Small things use content-aware fill; larger ones are rebuilt by AI on their own '
                                    'layer.', 'small', wrap=True))

        self.heading('RECOLOR AN OBJECT')
        row = QHBoxLayout()
        self.recolor = QLineEdit()
        self.recolor.setPlaceholderText('her shirt')
        self.recolor.textChanged.connect(lambda _: self.sync())
        row.addWidget(self.recolor, 1)
        self.recolor_color = ColorButton('#d62828', 'New color')
        row.addWidget(self.recolor_color)
        row.addWidget(self.button('Recolor', lambda: self.edits(
            [dict(action='recolor', target='object', object=self.recolor.text().strip(),
                  color=self.recolor_color.color, quote=f'make {self.recolor.text().strip()} {self.recolor_color.color}')],
            f'Recolor {self.recolor.text().strip()}'), ready=lambda: self.recolor.text().strip()))
        self.column.addLayout(row)

        self.heading('PAINT NEW CONTENT WITH AI')
        self.ai = QPlainTextEdit()
        self.ai.setFixedHeight(64)
        self.ai.setTabChangesFocus(True)
        self.ai.setPlaceholderText('Replace the sky with a stormy sky · add a small boat on the water')
        self.ai.textChanged.connect(self.sync)
        self.column.addWidget(self.ai)
        self.column.addWidget(self.button('Paint as a new layer', self.generate, 'wand-sparkles',
                                          ready=lambda: self.ai.toPlainText().strip()))
        self.column.addStretch()

    def generate(self):
        text = self.ai.toPlainText().strip()
        target = 'sky' if re.search(r'\bsky\b', text, re.IGNORECASE) else 'whole image'
        self.edits([dict(action='generate', target=target, quote=text)], f'AI: {text}')

    def sync(self):
        super().sync()
        self.backdrop.setVisible(not self.transparent.isChecked())


class TextPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Text', 'Measured placement: the title is fitted inside the margins and kept '
                                         'readable.')
        self.column.addWidget(label('Words', 'small'))
        self.words = QPlainTextEdit()
        self.words.setFixedHeight(64)
        self.words.setTabChangesFocus(True)
        self.words.setPlaceholderText('SUMMER 2026')
        self.words.textChanged.connect(self.sync)
        self.column.addWidget(self.words)
        self.column.addWidget(label('Font', 'small'))
        self.typeface = QComboBox()
        self.typeface.setMaxVisibleItems(18)
        self.column.addWidget(self.typeface)
        self.set_fonts([])
        self.text_size = Segmented(TEXT_SIZES, 'large', columns=3)
        self.text_size.changed.connect(lambda _: self.sync())
        self.column.addWidget(self.text_size)
        self.points = QSpinBox()
        self.points.setRange(4, 1296)
        self.points.setValue(48)
        self.points.setSuffix(' pt')
        self.column.addWidget(self.points)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label('Position', 'small'))
        grid = QGridLayout()
        grid.setSpacing(3)
        self.position = QButtonGroup(self)
        for index, place in enumerate(POSITIONS):
            cell = QPushButton()
            cell.setCheckable(True)
            cell.setFixedSize(28, 28)
            cell.setToolTip(place.capitalize())
            cell.setProperty('kind', 'tile')
            self.position.addButton(cell, index)
            grid.addWidget(cell, index // 3, index % 3)
        self.position.button(POSITIONS.index('bottom')).setChecked(True)
        left.addLayout(grid)
        left.addStretch()
        row.addLayout(left)
        options = QVBoxLayout()
        options.setSpacing(4)
        line = QHBoxLayout()
        self.auto = QCheckBox('Readable color')
        self.auto.setChecked(True)
        self.auto.toggled.connect(lambda _: self.sync())
        line.addWidget(self.auto)
        self.color = ColorButton('#ffffff', 'Text color')
        line.addWidget(self.color)
        line.addStretch()
        options.addLayout(line)
        self.styles = {}
        for name in TEXT_STYLES:
            self.styles[name] = QCheckBox(name.capitalize())
            options.addWidget(self.styles[name])
        row.addLayout(options, 1)
        self.column.addLayout(row)
        self.column.addWidget(self.button('Add text', self.add, 'type', 'primary',
                                          ready=lambda: self.words.toPlainText().strip()))

        self.selected = Box()
        selected = QVBoxLayout(self.selected)
        selected.setContentsMargins(0, 0, 0, 0)
        self.heading('EDIT SELECTED TEXT', selected)
        self.replacement = QLineEdit()
        self.replacement.textChanged.connect(lambda _: self.sync())
        selected.addWidget(self.replacement)
        selected.addWidget(self.button('Change words', self.change,
                                       ready=lambda: self.replacement.text().strip()))
        self.column.addWidget(self.selected)
        self.column.addStretch()

    def set_fonts(self, fonts):
        current = self.typeface.currentData()
        self.typeface.clear()
        self.typeface.addItem('Default (Inter)', '')
        for generic in ('serif', 'script', 'impact', 'mono'):
            self.typeface.addItem(f'Any {generic}', generic)
        for name in fonts:
            self.typeface.addItem(name, name)
        self.typeface.setCurrentIndex(max(self.typeface.findData(current), 0))

    def active_text(self):
        document = self.studio.document
        if document is None:
            return None
        state = document['state']
        return next((layer for layer, _ in flatten(state.get('layers'))
                     if layer.get('id') == state.get('activeLayer') and layer.get('kind') == 'Type'), None)

    def add(self):
        words = self.words.toPlainText().strip()
        styles = [name for name, box in self.styles.items() if box.isChecked()]
        edit = text_edit(words, POSITIONS[self.position.checkedId()], self.text_size.value(), self.points.value(),
                         '' if self.auto.isChecked() else self.color.color, self.typeface.currentData(), styles)
        self.edits([edit], f'Add “{words[:40]}”')

    def change(self):
        layer, words = self.active_text(), self.replacement.text().strip()
        if layer is not None:
            self.edits([dict(action='edit_text', object=layer['name'], text=words, quote='change the text')],
                       f'Change text to “{words[:30]}”')

    def sync(self):
        super().sync()
        self.points.setVisible(self.text_size.value() == 'points')
        self.color.setVisible(not self.auto.isChecked())
        layer = self.active_text()
        self.selected.setVisible(layer is not None)
        if layer is not None:
            self.replacement.setPlaceholderText(readable((layer.get('text') or {}).get('text')))


class FieldForm(QWidget):
    """Controls drawn from a PhotoCraft parameter specification; values() holds only what was changed."""

    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(8)
        self.changed = {}
        self.errors = set()

    def values(self):
        return dict(self.changed)

    def set(self, name, value):
        if value is None:
            self.changed.pop(name, None)
        else:
            self.changed[name] = value
        self.on_change()

    def build(self, fields, layers):
        AssistantPanel.clear(self.column)
        self.changed, self.errors = {}, set()
        visible = [field for field in fields if field['name'] not in ('path', 'file')]
        if not visible:
            self.column.addWidget(label('This command has no settings.', 'small'))
        for field in visible:
            self.column.addWidget(self.control(field, layers))

    def control(self, field, layers):
        name, kind = field['name'], field['type']
        title = field_title(name)
        holder = Box()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        note = field.get('note') or ''
        if kind == 'number' and field.get('min') is not None and field.get('max') is not None:
            low, high = field['min'], field['max']
            step = 1 if field.get('integer') else max((high - low) / 200, 0.01)
            slider = Range(title, low, high, step)
            default = field.get('default')
            slider.setValue(default if isinstance(default, (int, float)) and not isinstance(default, bool) else low)
            slider.changed.connect(lambda value: self.set(name, value))
            slider.setToolTip(note)
            column.addWidget(slider)
            return holder
        if kind != 'bool':
            column.addWidget(label(title + (f'  ·  {note}' if note else ''), 'small', wrap=True))
        if kind == 'number':
            box = QLineEdit()
            if field.get('default') is not None:
                box.setPlaceholderText(str(field['default']))

            def number(text):
                try:
                    self.set(name, float(text) if text.strip() else None)
                except ValueError:
                    self.set(name, None)

            box.textChanged.connect(number)
            column.addWidget(box)
        elif kind == 'choice':
            box = QComboBox()
            default = field.get('default')
            box.addItem(f'Default ({default})' if default not in (None, '') else 'Default', None)
            for option in field.get('options') or []:
                box.addItem(field_title(str(option)), option)
            box.currentIndexChanged.connect(lambda _: self.set(name, box.currentData()))
            column.addWidget(box)
        elif kind == 'bool':
            box = QCheckBox(title)
            box.setChecked(bool(field.get('default')))
            box.setToolTip(note)
            box.toggled.connect(lambda on: self.set(name, on))
            column.addWidget(box)
        elif kind == 'color':
            row = QHBoxLayout()
            default = field.get('default') if isinstance(field.get('default'), str) else '#ffffff'
            swatch_button = ColorButton(default if QColor(default).isValid() else '#ffffff')
            row.addWidget(swatch_button)
            reset = QPushButton('Default')
            reset.setProperty('kind', 'flat')
            reset.setVisible(False)
            row.addWidget(reset)
            row.addStretch()

            def chosen(color):
                self.set(name, color)
                reset.setVisible(True)

            def back():
                self.set(name, None)
                swatch_button.set_color(default if QColor(default).isValid() else '#ffffff')
                reset.setVisible(False)

            swatch_button.changed.connect(chosen)
            reset.clicked.connect(back)
            column.addLayout(row)
        elif kind == 'layer':
            box = QComboBox()
            box.addItem('Active layer', None)
            for layer, depth in flatten(layers):
                box.addItem('   ' * depth + readable(layer.get('name')), layer.get('id'))
            box.currentIndexChanged.connect(lambda _: self.set(name, box.currentData()))
            column.addWidget(box)
        elif kind == 'text':
            box = QLineEdit()
            box.textChanged.connect(lambda text: self.set(name, text or None))
            column.addWidget(box)
        else:
            box = QPlainTextEdit()
            box.setFixedHeight(54)
            box.setTabChangesFocus(True)
            box.setPlaceholderText('JSON value')
            error = label('', 'error')
            error.setVisible(False)

            def parse():
                text = box.toPlainText().strip()
                try:
                    value = json.loads(text) if text else None
                    self.errors.discard(name)
                    error.setVisible(False)
                    self.set(name, value)
                except ValueError:
                    self.errors.add(name)
                    self.set(name, None)
                    error.setText('Not valid JSON yet')
                    error.setVisible(True)

            box.textChanged.connect(parse)
            column.addWidget(box)
            column.addWidget(error)
        return holder


class CommandRunner(Box):
    """One engine command with its settings, applied to the document."""

    def __init__(self, panel, on_photo):
        super().__init__()
        self.panel, self.on_photo, self.command = panel, on_photo, None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(6)
        self.title = label('', 'heading', wrap=True)
        column.addWidget(self.title)
        self.ident = label('', 'small', selectable=True)
        column.addWidget(self.ident)
        self.reason = label('', 'small', wrap=True)
        column.addWidget(self.reason)
        self.form = FieldForm(lambda: panel.sync())
        column.addWidget(self.form)
        self.apply = panel.button('Apply', self.run, 'play', 'primary', ready=lambda: self.runnable())
        column.addWidget(self.apply)
        self.setVisible(False)

    def runnable(self):
        return self.command is not None and self.command.get('runnable') and not self.form.errors

    def show_command(self, command):
        self.command = command
        self.setVisible(command is not None)
        if command is None:
            return
        self.title.setText(plain(command['label']))
        self.ident.setText(command['id'])
        runnable = bool(command.get('runnable'))
        self.reason.setText(command.get('reason') or '')
        self.reason.setVisible(not runnable)
        self.form.setVisible(runnable)
        self.apply.setVisible(runnable)
        layers = ((self.panel.studio.document or {}).get('state') or {}).get('layers') or []
        self.form.build(command.get('fields') or [], layers)
        filtering = self.on_photo and command['id'].startswith('filter.')
        self.apply.setText(' Apply as a smart filter' if filtering else ' Apply')

    def run(self):
        command = self.command
        if not self.runnable():
            return
        steps = []
        if self.on_photo and command['id'].startswith('filter.'):
            steps.append(dict(command='studio.select_photo', params=dict(smart=True), label='Select the photo'))
        steps.append(dict(command=command['id'], params=self.form.values(), label=plain(command['label'])))
        self.panel.studio.commands(steps, plain(command['label']))


class FiltersPanel(Panel):
    def __init__(self, studio):
        super().__init__(studio, 'Filters', 'Applied to the photo as editable smart filters; toggle or delete them '
                                            'from the layer later.')
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        self.groups = []
        for group, ids in FILTER_GROUPS:
            heading = label(group, 'eyebrow')
            self.column.addSpacing(4)
            self.column.addWidget(heading)
            flow = Flow()
            buttons = []
            for ident in ids:
                chip = QPushButton(ident.split('.')[-1])
                chip.setProperty('kind', 'chip')
                chip.setCheckable(True)
                chip.setProperty('command', ident)
                chip.clicked.connect(lambda _=False, ident=ident: self.choose(ident))
                self.chips.addButton(chip)
                flow.addWidget(chip)
                buttons.append(chip)
            self.column.addLayout(flow)
            self.groups.append((heading, buttons))
        self.runner = CommandRunner(self, on_photo=True)
        self.column.addWidget(self.runner)
        self.column.addStretch()
        self.known = {}
        self.chosen = 'filter.blur.gaussianBlur'

    def set_commands(self, commands):
        self.known = {command['id']: command for command in commands}
        for heading, buttons in self.groups:
            for chip in buttons:
                command = self.known.get(chip.property('command'))
                chip.setVisible(command is not None)
                if command:
                    chip.setText(plain(command['label']).replace('&', '&&'))
            heading.setVisible(any(not chip.isHidden() for chip in buttons))
        self.choose(self.chosen if self.chosen in self.known else None)

    def choose(self, ident):
        self.chosen = ident or self.chosen
        for chip in self.chips.buttons():
            chip.setChecked(chip.property('command') == ident)
        self.runner.show_command(self.known.get(ident))
        self.sync()


class CommandsPanel(Panel):
    LIMIT = 80

    def __init__(self, studio):
        super().__init__(studio, 'All tools', '')
        self.intro = self.column.itemAt(1).widget()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Curves, mask, warp, text, liquify…')
        self.search.addAction(theme.icon('search', theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.filter(reset=True))
        self.column.addWidget(self.search)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.setStyleSheet(f'QListWidget {{ background: {theme.BG}; border: 1px solid {theme.LINE}; '
                                f'border-radius: 8px; }} QListWidget::item {{ padding: 5px 8px; }} '
                                f'QListWidget::item:selected {{ background: rgba(196, 244, 119, 0.12); '
                                f'color: {theme.LIME}; }}')
        self.list.currentItemChanged.connect(self.picked)
        self.column.addWidget(self.list)
        row = QHBoxLayout()
        self.count = label('', 'small')
        row.addWidget(self.count, 1)
        self.more = QPushButton('Show more')
        self.more.setProperty('kind', 'flat')
        self.more.clicked.connect(self.show_more)
        row.addWidget(self.more)
        self.column.addLayout(row)
        self.runner = CommandRunner(self, on_photo=False)
        self.column.addWidget(self.runner)
        self.column.addStretch()
        self.commands, self.limit = [], self.LIMIT
        self.timer = QTimer(self)  # typing in the search is filtered once it pauses
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.fill)

    def set_commands(self, commands, discovered):
        self.commands = commands
        runnable = sum(bool(command.get('runnable')) for command in commands)
        self.intro.setText(f'Every one of PhotoCraft’s {discovered} engine commands, with real controls. {runnable} '
                           'run here; the rest need the desktop app (files, preferences, plug-ins).')
        self.filter(reset=True)

    def matches(self):
        query = self.search.text().lower().strip()
        return [command for command in self.commands if not query or query in
                f'{command["id"]} {plain(command["label"])} {" ".join(command.get("menu") or [])}'.lower()]

    def filter(self, reset=False):
        if reset:
            self.limit = self.LIMIT
        self.timer.start()

    def show_more(self):
        self.limit += 100
        self.fill()

    def fill(self):
        matches = self.matches()
        self.list.blockSignals(True)
        self.list.clear()
        for command in matches[:self.limit]:
            where = ' › '.join(command.get('menu') or []) or command.get('category', '')
            item = QListWidgetItem(f'{plain(command["label"])}\n{where}{" · desktop" if not command.get("runnable") else ""}')
            item.setData(Qt.ItemDataRole.UserRole, command['id'])
            item.setToolTip(command['id'])
            self.list.addItem(item)
            if self.runner.command and command['id'] == self.runner.command['id']:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.count.setText(f'{len(matches)} match{"" if len(matches) == 1 else "es"}')
        self.more.setVisible(len(matches) > self.limit)

    def picked(self, item, _previous=None):
        if item is None:
            return
        ident = item.data(Qt.ItemDataRole.UserRole)
        self.runner.show_command(next((command for command in self.commands if command['id'] == ident), None))
        self.sync()


class PipelinesPanel(Panel):
    """Every pipeline the engine can run, the same ones the assistant chooses from: pick one, fill
    in its few choices and run it. Workflows run all of their procedures."""

    TARGETS = [('whole image', 'Whole image'), ('main subject', 'Subject'), ('background', 'Background'),
               ('object', 'Named thing')]

    def __init__(self, studio):
        super().__init__(studio, 'Pipelines', 'Professional procedures and whole jobs. The assistant picks these '
                                              'for you; here you choose one yourself.')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Product, real estate, skin, sky, frame…')
        self.search.addAction(theme.icon('search', theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.fill())
        self.column.addWidget(self.search)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(lambda _: self.fill())
        self.column.addWidget(self.category)
        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        self.list.setStyleSheet(f'QListWidget {{ background: {theme.BG}; border: 1px solid {theme.LINE}; '
                                f'border-radius: 8px; }} QListWidget::item {{ padding: 5px 8px; }} '
                                f'QListWidget::item:selected {{ background: rgba(196, 244, 119, 0.12); '
                                f'color: {theme.LIME}; }}')
        self.list.currentItemChanged.connect(self.picked)
        self.column.addWidget(self.list)
        self.count = label('', 'small')
        self.column.addWidget(self.count)

        self.detail = QWidget()
        form = QVBoxLayout(self.detail)
        form.setContentsMargins(0, 6, 0, 0)
        form.setSpacing(8)
        self.name = label('', 'heading')
        self.summary = label('', 'muted', wrap=True)
        self.parts = label('', 'small', wrap=True)
        form.addWidget(self.name)
        form.addWidget(self.summary)
        form.addWidget(self.parts)
        self.option_row = QWidget()
        row = QHBoxLayout(self.option_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label('Choice', 'muted'))
        self.option = QComboBox()
        row.addWidget(self.option, 1)
        form.addWidget(self.option_row)
        self.target = Segmented(self.TARGETS, 'whole image', columns=2)
        form.addWidget(self.target)
        self.thing = QLineEdit()
        self.thing.setPlaceholderText('What it applies to, e.g. the red mug (optional)')
        form.addWidget(self.thing)
        self.words = QLineEdit()
        self.words.setPlaceholderText('Exact words, for titles')
        form.addWidget(self.words)
        self.strength = Segmented(STRENGTHS, 'moderate')
        form.addWidget(self.strength)
        form.addWidget(self.button('Run pipeline', self.run, 'play', 'primary', ready=lambda: self.chosen is not None))
        self.column.addWidget(self.detail)
        self.column.addStretch()
        self.pipelines, self.categories, self.chosen = [], [], None
        self.detail.setVisible(False)

    def set_pipelines(self, pipelines, categories=()):
        self.pipelines = pipelines
        titles = dict(categories) or {item['category']: item['category_title'] for item in pipelines}
        present = [key for key in titles if any(item['category'] == key for item in pipelines)]
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(f'All {len(pipelines)} pipelines', '')
        for key in present:
            self.category.addItem(titles[key], key)
        self.category.blockSignals(False)
        self.fill()

    def fill(self):
        query = self.search.text().lower().strip()
        wanted = self.category.currentData() or ''
        shown = [item for item in self.pipelines if (not wanted or item['category'] == wanted) and (
            not query or query in f'{item["id"]} {item["title"]} {item["summary"]} {item["category_title"]}'.lower())]
        self.list.blockSignals(True)
        self.list.clear()
        for item in shown:
            kind = 'workflow' if item['kind'] == 'workflow' else item['category_title']
            entry = QListWidgetItem(f'{item["title"]}\n{kind}')
            entry.setData(Qt.ItemDataRole.UserRole, item['id'])
            entry.setToolTip(item['summary'])
            self.list.addItem(entry)
            if self.chosen and item['id'] == self.chosen['id']:
                self.list.setCurrentItem(entry)
        self.list.blockSignals(False)
        self.count.setText(f'{len(shown)} pipeline{"" if len(shown) == 1 else "s"}')

    def picked(self, entry, _previous=None):
        if entry is None:
            return
        ident = entry.data(Qt.ItemDataRole.UserRole)
        self.chosen = next((item for item in self.pipelines if item['id'] == ident), None)
        if self.chosen is None:
            return
        item = self.chosen
        self.name.setText(item['title'])
        self.summary.setText(item['summary'][:1].upper() + item['summary'][1:] + '.')
        lines = []
        if item['steps']:
            lines.append('Runs: ' + ' → '.join(step.replace('_', ' ') for step in item['steps']))
        if item['measures']:
            lines.append('Measures first: ' + ', '.join(item['measures']).replace('_', ' '))
        if item['ai']:
            lines.append('Needs the AI content model.')
        self.parts.setText('\n'.join(lines))
        self.parts.setVisible(bool(lines))
        self.option.clear()
        for option in item['options']:
            self.option.addItem(option)
        self.option_row.setVisible(bool(item['options']))
        self.words.setVisible('text =' in item['summary'] or 'title' in item['summary'])
        self.detail.setVisible(True)
        self.sync()

    def run(self):
        item = self.chosen
        if item is None:
            return
        target = self.target.value()
        thing = self.thing.text().strip()
        if target == 'object' and not thing:
            target = 'main subject'
        edit = dict(action=item['id'], quote=item['title'], strength=self.strength.value(), target=target,
                    object=thing, choice=self.option.currentText() if item['options'] else '',
                    text=self.words.text().strip() if not self.words.isHidden() else '')
        self.edits([edit], f'Pipeline: {item["title"]}')


def when(seconds):
    return time.strftime('%H:%M:%S', time.localtime(seconds or 0))

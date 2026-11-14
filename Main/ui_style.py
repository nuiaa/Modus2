"""Apple-style Kivy presentation primitives for Modus (light and dark).

Colours come from ``theme``; every widget reads them when it is built, so the
app rebuilds its screens after a theme switch. No network, storage or app state.
"""
import theme
from kivy.graphics import Color, Ellipse, InstructionGroup, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.utils import get_color_from_hex

# Legacy names (BG_DARK, CARD_BG, WHITE, ...) are injected and kept current by theme.
theme.register(globals())


def hex_color(value):
    return get_color_from_hex(theme.resolve(value))


def _with_alpha(value, alpha):
    rgba = list(hex_color(value))
    rgba[3] = alpha
    return rgba


def _is_filled(bg):
    resolved = theme.resolve(bg)
    return resolved in (theme.palette['accent'], theme.palette['red'], theme.palette['accent_pressed'])


class ModernButton(Button):
    """Borderless rounded control.

    Accent or red backgrounds are filled buttons with light text; any other
    background is a quiet grey or card-coloured control. ``border_hex`` is
    accepted for compatibility but no outline is drawn (Apple controls have none).
    """
    bg_hex = StringProperty('')
    border_hex = StringProperty('')
    radius_val = NumericProperty(12)

    def __init__(self, bg_hex=None, border_hex=None, radius_val=12, **kwargs):
        kwargs.setdefault('font_size', '15sp')
        kwargs.setdefault('bold', True)
        kwargs.setdefault('color', hex_color(ACCENT_LINE))
        kwargs.setdefault('disabled_color', hex_color(GRAY))
        kwargs.setdefault('padding', (dp(12), dp(6)))
        kwargs.setdefault('halign', 'center')
        kwargs.setdefault('valign', 'middle')
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_disabled_normal = ''
        self.background_disabled_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bg_hex = bg_hex or FILL
        self.border_hex = border_hex or ''
        self.radius_val = radius_val
        with self.canvas.before:
            self._bg_col = Color(*hex_color(self.bg_hex))
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_graphics, size=self._update_graphics,
                  radius_val=self._update_graphics, bg_hex=self._update_colors,
                  state=self._update_colors, disabled=self._update_colors)
        self._update_graphics()
        self._update_colors()

    def _update_graphics(self, *args):
        radius = min(dp(self.radius_val), self.height / 2, self.width / 2)
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [radius]
        if self.halign == 'center':
            self.text_size = (max(1, self.width - dp(16)), max(1, self.height - dp(8)))

    def _update_colors(self, *args):
        filled = _is_filled(self.bg_hex)
        if filled:
            self.color = hex_color(ON_ACCENT)
        color = hex_color(self.bg_hex)
        if self.disabled:
            color[3] *= 0.4
        elif self.state == 'down':
            color = hex_color(BLUE_DARK) if theme.resolve(self.bg_hex) == theme.palette['accent'] \
                else hex_color(theme.palette['fill_pressed'])
        self._bg_col.rgba = color


class ModernTextInput(TextInput):
    """Filled rounded field with an accent focus ring."""
    def __init__(self, **kwargs):
        kwargs.setdefault('font_size', '16sp')
        kwargs.setdefault('background_normal', '')
        kwargs.setdefault('background_active', '')
        kwargs.setdefault('background_color', (0, 0, 0, 0))
        kwargs.setdefault('foreground_color', hex_color(WHITE))
        kwargs.setdefault('disabled_foreground_color', hex_color(GRAY))
        kwargs.setdefault('hint_text_color', hex_color(GRAY))
        kwargs.setdefault('cursor_color', hex_color(BLUE))
        kwargs.setdefault('selection_color', _with_alpha(BLUE, 0.25))
        kwargs.setdefault('padding', (dp(14), dp(13), dp(14), dp(11)))
        self._radius = dp(kwargs.pop('radius_val', 12))
        super().__init__(**kwargs)
        # TextInput's kv rules end canvas.before with the text colour, so our
        # surface must be inserted *before* them or it would recolour the text.
        group = InstructionGroup()
        group.add(Color(*hex_color(FILL)))
        self._surface = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._radius])
        group.add(self._surface)
        self._focus_color = Color(0, 0, 0, 0)
        group.add(self._focus_color)
        self._focus_line = Line(width=1.4)
        group.add(self._focus_line)
        self.canvas.before.insert(0, group)
        # TextInput owns _update_graphics; overriding it hides the text and caret.
        self.bind(pos=self._update_surface_graphics, size=self._update_surface_graphics,
                  focus=self._update_focus)
        self._update_surface_graphics()

    def _update_surface_graphics(self, *args):
        radius = min(self._radius, self.height / 2)
        self._surface.pos = self.pos
        self._surface.size = self.size
        self._surface.radius = [radius]
        self._focus_line.rounded_rectangle = (self.x, self.y, self.width, self.height, radius)

    def _update_focus(self, *args):
        self._focus_color.rgba = hex_color(BLUE) if self.focus else (0, 0, 0, 0)


class Surface(BoxLayout):
    """Inset-grouped card: rounded, borderless, on the grouped background."""
    def __init__(self, bg_hex=None, border_hex=None, radius_val=14, **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('padding', dp(16))
        kwargs.setdefault('spacing', dp(10))
        super().__init__(**kwargs)
        self.radius_val = radius_val
        with self.canvas.before:
            Color(*hex_color(bg_hex or CARD_BG))
            self._surface = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_graphics, size=self._update_graphics)
        self._update_graphics()

    def _update_graphics(self, *args):
        self._surface.pos = self.pos
        self._surface.size = self.size
        self._surface.radius = [dp(self.radius_val)]


class Background(BoxLayout):
    """Full-screen layout painted with the grouped background colour."""
    def __init__(self, color=None, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*hex_color(color or BG_DARK))
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size


class ResponsiveLabel(Label):
    """Plain text that wraps at available width and grows to fit its content."""
    def __init__(self, min_height=0, **kwargs):
        kwargs.setdefault('font_size', '15sp')
        kwargs.setdefault('color', hex_color(WHITE))
        kwargs.setdefault('halign', 'left')
        kwargs.setdefault('valign', 'middle')
        kwargs.setdefault('size_hint_y', None)
        super().__init__(**kwargs)
        self._minimum_height = dp(min_height)
        self.bind(width=self._wrap, texture_size=self._fit)
        self._wrap()

    def _wrap(self, *args):
        self.text_size = (max(1, self.width), None)

    def _fit(self, *args):
        self.height = max(self._minimum_height, self.texture_size[1])


class Hairline(Widget):
    """Single-pixel separator, inset from the left like iOS table rows."""
    def __init__(self, inset=16, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', 1)
        super().__init__(**kwargs)
        self.inset = dp(inset)
        with self.canvas:
            Color(*hex_color(SEPARATOR))
            self._rect = Rectangle()
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *args):
        self._rect.pos = (self.x + self.inset, self.y)
        self._rect.size = (max(0, self.width - self.inset), max(1, self.height))


class Chevron(Widget):
    """Disclosure chevron drawn as two strokes; points right, or down when open."""
    open = BooleanProperty(False)

    def __init__(self, color=None, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(14), dp(14)))
        super().__init__(**kwargs)
        with self.canvas:
            Color(*hex_color(color or GRAY))
            self._line = Line(width=dp(1.3), cap='round', joint='round')
        self.bind(pos=self._draw, size=self._draw, open=self._draw)
        self._draw()

    def _draw(self, *args):
        cx, cy, r = self.center_x, self.center_y, dp(4)
        if self.open:
            self._line.points = [cx - r, cy + r / 2, cx, cy - r / 2, cx + r, cy + r / 2]
        else:
            self._line.points = [cx - r / 2, cy + r, cx + r / 2, cy, cx - r / 2, cy - r]


class Checkmark(Widget):
    """Accent checkmark drawn as strokes (no font glyph dependency)."""
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(18), dp(18)))
        super().__init__(**kwargs)
        with self.canvas:
            Color(*hex_color(BLUE))
            self._line = Line(width=dp(1.8), cap='round', joint='round')
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        x, y, w, h = self.x, self.y, self.width, self.height
        self._line.points = [x + w * 0.12, y + h * 0.5, x + w * 0.4, y + h * 0.2, x + w * 0.9, y + h * 0.82]


class SectionLabel(Label):
    """Uppercase caption placed above a grouped card."""
    def __init__(self, text='', **kwargs):
        kwargs.setdefault('font_size', '12.5sp')
        kwargs.setdefault('color', hex_color(GRAY_LIGHT))
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', dp(30))
        kwargs.setdefault('halign', 'left')
        kwargs.setdefault('valign', 'bottom')
        kwargs.setdefault('padding', (dp(16), dp(6)))
        super().__init__(text=text.upper(), **kwargs)
        self.bind(size=self.setter('text_size'))


class SectionHeading(BoxLayout):
    """Title with an optional secondary line."""
    def __init__(self, title, subtitle='', **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('spacing', dp(2))
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter('height'))
        self.title_label = ResponsiveLabel(text=title, font_size='17sp', bold=True)
        self.add_widget(self.title_label)
        self.subtitle_label = ResponsiveLabel(text=subtitle, font_size='13sp', color=hex_color(GRAY_LIGHT))
        if subtitle:
            self.add_widget(self.subtitle_label)


class StatusPill(Label):
    """Tinted badge, e.g. a +1.2% change. Pair colour with text or sign."""
    def __init__(self, text='', tone=None, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('height', dp(24))
        kwargs.setdefault('font_size', '13sp')
        kwargs.setdefault('bold', True)
        tone = tone or BLUE
        kwargs.setdefault('color', hex_color(tone))
        super().__init__(text=text, **kwargs)
        with self.canvas.before:
            Color(*_with_alpha(tone, 0.14))
            self._surface = RoundedRectangle(radius=[dp(6)])
        self.bind(texture_size=self._fit, pos=self._draw, size=self._draw)
        self._fit()

    def _fit(self, *args):
        self.width = self.texture_size[0] + dp(14)

    def _draw(self, *args):
        self._surface.pos = self.pos
        self._surface.size = self.size


class IconButton(ButtonBehavior, AnchorLayout):
    """Image button with a circular grey fill and pressed feedback."""
    def __init__(self, source, icon_size=22, filled=True, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(36), dp(36)))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._fill = Color(*(hex_color(FILL) if filled else (0, 0, 0, 0)))
            self._circle = Ellipse(pos=self.pos, size=self.size)
        self._base = list(self._fill.rgba)
        self.add_widget(Image(source=source, size_hint=(None, None), fit_mode='contain',
                              size=(dp(icon_size), dp(icon_size))))
        self.bind(pos=self._sync, size=self._sync, state=self._press)

    def _sync(self, *args):
        self._circle.pos = self.pos
        self._circle.size = self.size

    def _press(self, *args):
        self._fill.rgba = hex_color(theme.palette['fill_pressed']) if self.state == 'down' else self._base


class TextAction(Button):
    """Plain tinted text button, as used in iOS navigation bars."""
    def __init__(self, text, **kwargs):
        kwargs.setdefault('font_size', '16sp')
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('height', dp(36))
        super().__init__(text=text, **kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.color = hex_color(BLUE)
        self.bind(texture_size=lambda *_: setattr(self, 'width', self.texture_size[0] + dp(16)),
                  state=lambda *_: setattr(self, 'opacity', 0.45 if self.state == 'down' else 1))


class LargeTitleHeader(BoxLayout):
    """iOS large-title navigation header: actions row, big title, quiet subtitle."""
    def __init__(self, title, subtitle='', **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('padding', (dp(16), dp(4), dp(16), dp(4)))
        kwargs.setdefault('spacing', 0)
        super().__init__(**kwargs)
        self.actions = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40), spacing=dp(10))
        self.actions.add_widget(Widget())
        self.add_widget(self.actions)
        self.title_label = Label(text=title, font_size='32sp', bold=True, color=hex_color(WHITE),
                                 size_hint_y=None, height=dp(42), halign='left', valign='middle')
        self.title_label.bind(size=self.title_label.setter('text_size'))
        self.add_widget(self.title_label)
        self.subtitle_label = ResponsiveLabel(text=subtitle, font_size='13sp',
                                              color=hex_color(GRAY_LIGHT), min_height=20)
        self.add_widget(self.subtitle_label)
        self.bind(minimum_height=self.setter('height'))

    def add_action(self, widget):
        self.actions.add_widget(widget)
        return widget


class DashboardHeader(LargeTitleHeader):
    """Backward-compatible name for the large-title header."""
    def __init__(self, title='MODUS', subtitle='Piyasa terminali', **kwargs):
        kwargs.pop('height', None)
        super().__init__(title, subtitle, **kwargs)


class SegmentedControl(BoxLayout):
    """iOS segmented control. ``on_change(value)`` is called on selection."""
    def __init__(self, options, selected, on_change=None, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', dp(36))
        kwargs.setdefault('padding', dp(2))
        kwargs.setdefault('spacing', dp(2))
        super().__init__(**kwargs)
        self.on_change = on_change
        self.selected = selected
        with self.canvas.before:
            Color(*hex_color(FILL))
            self._track = RoundedRectangle(radius=[dp(9)])
        self.bind(pos=self._sync, size=self._sync)
        self.buttons = {}
        for value, label in options:
            button = ModernButton(text=label, font_size='14sp', radius_val=7,
                                  bg_hex=CARD_BG, color=hex_color(WHITE))
            button.bind(on_press=lambda _btn, v=value: self.select(v))
            self.buttons[value] = button
            self.add_widget(button)
        self._paint()

    def _sync(self, *args):
        self._track.pos = self.pos
        self._track.size = self.size

    def _paint(self):
        for value, button in self.buttons.items():
            active = value == self.selected
            button.bg_hex = theme.palette['segment'] if active else FILL
            button.bold = active
            button.color = hex_color(WHITE)

    def select(self, value):
        if value == self.selected:
            return
        self.selected = value
        self._paint()
        if self.on_change:
            self.on_change(value)


class Sheet(ModalView):
    """Bottom sheet with grabber, title and close button. Add content to ``body``."""
    def __init__(self, title, height=None, height_ratio=0.86, **kwargs):
        kwargs.setdefault('size_hint', (1, None))
        kwargs.setdefault('auto_dismiss', True)
        super().__init__(**kwargs)
        self.pos_hint = {'x': 0, 'y': 0}
        self.height = height or Window.height * height_ratio
        self.background = ''
        self.background_color = (0, 0, 0, 0)
        self.overlay_color = hex_color(theme.palette['scrim'])
        container = BoxLayout(orientation='vertical', padding=(dp(16), dp(6), dp(16), dp(18)),
                              spacing=dp(10))
        with container.canvas.before:
            Color(*hex_color(MODAL_BG))
            surface = RoundedRectangle(radius=[dp(16), dp(16), 0, 0])
            Color(*hex_color(theme.palette['label3']))
            grabber = RoundedRectangle(radius=[dp(2.5)])

        def sync(*_):
            surface.pos = container.pos
            surface.size = container.size
            grabber.size = (dp(36), dp(5))
            grabber.pos = (container.center_x - dp(18), container.top - dp(11))
        container.bind(pos=sync, size=sync)

        header = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(48), spacing=dp(8))
        self.title_label = Label(text=title, font_size='18sp', bold=True, color=hex_color(WHITE),
                                 halign='left', valign='middle')
        self.title_label.bind(size=self.title_label.setter('text_size'))
        header.add_widget(self.title_label)
        self.header = header
        close = ModernButton(text='×', font_size='20sp', bold=False, color=hex_color(GRAY_LIGHT),
                             bg_hex=FILL, radius_val=15, size_hint=(None, None), size=(dp(30), dp(30)))
        close.bind(on_press=lambda *_: self.dismiss())
        holder = AnchorLayout(size_hint_x=None, width=dp(30), anchor_y='center')
        holder.add_widget(close)
        header.add_widget(holder)
        container.add_widget(Widget(size_hint_y=None, height=dp(6)))
        container.add_widget(header)
        self.body = BoxLayout(orientation='vertical', spacing=dp(10))
        container.add_widget(self.body)
        self.add_widget(container)


class TabBar(BoxLayout):
    """Bottom tab bar with drawn icons. ``tabs`` = [(key, label, icon_kind)]."""
    def __init__(self, tabs, selected, on_select, **kwargs):
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', dp(58))
        super().__init__(**kwargs)
        self.on_select = on_select
        with self.canvas.before:
            Color(*hex_color(theme.palette['card'] if theme.name == 'light' else theme.palette['bg']))
            self._bg = Rectangle()
            Color(*hex_color(SEPARATOR))
            self._top = Rectangle()
        self.bind(pos=self._sync, size=self._sync)
        self.items = {}
        for key, label, kind in tabs:
            item = _TabItem(label, kind)
            item.bind(on_press=lambda _i, k=key: self.on_select(k))
            self.items[key] = item
            self.add_widget(item)
        self.select(selected)

    def _sync(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._top.pos = (self.x, self.top - 1)
        self._top.size = (self.width, 1)

    def select(self, key):
        for item_key, item in self.items.items():
            item.set_active(item_key == key)


class _TabItem(ButtonBehavior, BoxLayout):
    def __init__(self, label, kind, **kwargs):
        super().__init__(orientation='vertical', padding=(0, dp(7), 0, dp(5)), spacing=dp(2), **kwargs)
        self.kind = kind
        self.icon = Widget(size_hint_y=None, height=dp(26))
        with self.icon.canvas:
            self._icon_color = Color(*hex_color(GRAY))
            self._stroke = Line(width=dp(1.6), cap='round', joint='round')
            self._extra = Line(width=dp(1.6), cap='round', joint='round')
        self.add_widget(self.icon)
        self.caption = Label(text=label, font_size='11sp', size_hint_y=None, height=dp(14))
        self.add_widget(self.caption)
        self.bind(pos=self._draw, size=self._draw)
        self.icon.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        # Centre on the tab itself; the icon widget's own x lags behind layout.
        cx, cy = self.center_x, self.icon.center_y
        s = dp(10)
        if self.kind == 'chart':
            self._stroke.points = [cx - s, cy - s * 0.55, cx - s * 0.35, cy + s * 0.1,
                                   cx + s * 0.1, cy - s * 0.3, cx + s, cy + s * 0.7]
            self._extra.points = [cx - s, cy - s, cx + s, cy - s]
        else:  # chat bubble
            self._stroke.rounded_rectangle = (cx - s, cy - s * 0.55, 2 * s, s * 1.5, dp(6))
            self._extra.points = [cx - s * 0.45, cy - s * 0.55, cx - s * 0.7, cy - s * 1.05,
                                  cx - s * 0.05, cy - s * 0.55]

    def set_active(self, active):
        rgba = hex_color(BLUE if active else GRAY)
        self._icon_color.rgba = rgba
        self.caption.color = rgba
        self.caption.bold = active


class SendButton(ButtonBehavior, Widget):
    """Circular accent button with an upward arrow."""
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(40), dp(40)))
        super().__init__(**kwargs)
        with self.canvas:
            self._fill = Color(*hex_color(BLUE))
            self._circle = Ellipse()
            Color(*hex_color(ON_ACCENT))
            self._shaft = Line(width=dp(1.8), cap='round')
            self._head = Line(width=dp(1.8), cap='round', joint='round')
        self.bind(pos=self._draw, size=self._draw, state=self._paint, disabled=self._paint)
        self._draw()

    def _draw(self, *args):
        self._circle.pos = self.pos
        self._circle.size = self.size
        cx, cy, r = self.center_x, self.center_y, dp(8)
        self._shaft.points = [cx, cy - r, cx, cy + r]
        self._head.points = [cx - r * 0.75, cy + r * 0.2, cx, cy + r, cx + r * 0.75, cy + r * 0.2]

    def _paint(self, *args):
        if self.disabled:
            self._fill.rgba = hex_color(GRAY)
        else:
            self._fill.rgba = hex_color(BLUE_DARK if self.state == 'down' else BLUE)

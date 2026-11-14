"""Apple-style light/dark palettes with a persisted System / Light / Dark choice.

Widgets read the module-level legacy names (WHITE, CARD_BG, ...) when they are
built, so switching theme updates those names everywhere and the app rebuilds
its screens. ``resolve`` maps a colour from any palette (including the old
terminal palette kept in cached market data) onto the active palette.
"""
import json
import os

# Values are unique across both palettes so a stored colour maps back to one token.
LIGHT = {
    'bg': '#F2F2F7',          # systemGroupedBackground
    'card': '#FFFFFF',        # secondarySystemGroupedBackground
    'elevated': '#FAFAFC',    # sheets
    'fill': '#E9E9EE',        # tertiarySystemFill-like controls
    'bubble': '#E9E9EB',      # incoming chat bubble
    'segment': '#FFFFFD',     # selected segment
    'fill_pressed': '#DCDCE2',
    'separator': '#D1D1D6',
    'label': '#1D1D1F',
    'label2': '#6E6E73',
    'label3': '#A1A1A6',
    'accent': '#007AFF',
    'accent_pressed': '#0062CC',
    'accent_tint': '#E5F0FF',
    'on_accent': '#FEFEFE',
    'green': '#248A3D',
    'green_tint': '#E3F5E8',
    'red': '#D70015',
    'red_tint': '#FDE7E9',
    'orange': '#C93400',
    'purple': '#8944AB',
    'scrim': '#00000059',
}

DARK = {
    'bg': '#000000',
    'card': '#1C1C1E',
    'elevated': '#2C2C2E',
    'fill': '#3A3A3C',
    'bubble': '#262629',
    'segment': '#5A5A5E',
    'fill_pressed': '#48484A',
    'separator': '#38383A',
    'label': '#F5F5F7',
    'label2': '#98989F',
    'label3': '#636366',
    'accent': '#0A84FF',
    'accent_pressed': '#409CFF',
    'accent_tint': '#0A2A4D',
    'on_accent': '#FDFDFD',
    'green': '#30D158',
    'green_tint': '#0E3319',
    'red': '#FF453A',
    'red_tint': '#3D1412',
    'orange': '#FF9F0A',
    'purple': '#BF5AF2',
    'scrim': '#00000099',
}

# Names used throughout main.py / ui_style.py, mapped onto semantic tokens.
LEGACY = {
    'BG_DARK': 'bg', 'CARD_BG': 'card', 'CARD_BORDER': 'separator', 'ROW_LINE': 'separator',
    'MODAL_BG': 'elevated', 'USER_MSG_BG': 'accent', 'AI_MSG_BG': 'bubble',
    'WHITE': 'label', 'GRAY': 'label3', 'GRAY_LIGHT': 'label2',
    'BLUE': 'accent', 'BLUE_DARK': 'accent_pressed', 'GREEN': 'green', 'RED': 'red',
    'YELLOW': 'orange', 'CYAN': 'accent', 'PURPLE': 'purple', 'ACCENT_LINE': 'accent',
    'FILL': 'fill', 'SEPARATOR': 'separator', 'LABEL3': 'label3', 'ON_ACCENT': 'on_accent',
    'ACCENT_TINT': 'accent_tint',
}

# The previous dark terminal palette (still present in cached market data).
OLD_TERMINAL = {
    '#0B111B': 'bg', '#141E2B': 'card', '#293749': 'separator', '#223043': 'separator',
    '#173E48': 'accent', '#EDF3FA': 'label', '#94A5B9': 'label3', '#B8C6D8': 'label2',
    '#147D92': 'accent', '#106679': 'accent_pressed', '#57D4A0': 'green', '#FF8390': 'red',
    '#F2C36B': 'orange', '#67D5DF': 'accent', '#B3A2EB': 'purple',
    '#1E222D': 'fill', '#2A2E39': 'fill', '#181C26': 'fill', '#131722': 'elevated',
    '#3E4352': 'separator', '#1A365D': 'accent_tint', '#4D82FF': 'accent', '#2962FF': 'accent',
    '#2D4B73': 'accent', '#787B86': 'label3', '#00BCD4': 'accent', '#089981': 'green',
    '#FF9800': 'orange',
}

MODES = ('system', 'light', 'dark')
PREFS_FILE = 'ui_prefs.json'

mode = 'system'
name = 'light'
palette = dict(LIGHT)
_registered = []
_reverse = {}
for _source in (LIGHT, DARK):
    for _token, _value in _source.items():
        _reverse.setdefault(_value.upper(), _token)
for _value, _token in OLD_TERMINAL.items():
    _reverse.setdefault(_value.upper(), _token)


def legacy_values():
    return {legacy: palette[token] for legacy, token in LEGACY.items()}


def register(namespace):
    """Keep a module's legacy colour names in sync with the active palette."""
    if namespace not in _registered:
        _registered.append(namespace)
    namespace.update(legacy_values())


def resolve(value):
    """Map a colour from any known palette onto the active palette; pass others through."""
    if not isinstance(value, str):
        return value
    token = _reverse.get(value.upper())
    return palette[token] if token else value


def tone(token):
    return palette[token]


def system_prefers_dark():
    try:
        from kivy.utils import platform
        if platform != 'android':
            return False
        from jnius import autoclass
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        ui_mode = activity.getResources().getConfiguration().uiMode
        return (ui_mode & 0x30) == 0x20  # UI_MODE_NIGHT_MASK == UI_MODE_NIGHT_YES
    except Exception:
        return False


def load_mode(path=PREFS_FILE):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            value = json.load(handle).get('theme', 'system')
        return value if value in MODES else 'system'
    except (OSError, ValueError, AttributeError):
        return 'system'


def save_mode(value, path=PREFS_FILE):
    try:
        temporary = path + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump({'theme': value}, handle)
        os.replace(temporary, path)
    except OSError:
        pass


def apply(new_mode=None, dark=None):
    """Activate a mode ('system' | 'light' | 'dark') and update registered modules."""
    global mode, name
    if new_mode in MODES:
        mode = new_mode
    if dark is None:
        dark = system_prefers_dark() if mode == 'system' else mode == 'dark'
    name = 'dark' if dark else 'light'
    palette.clear()
    palette.update(DARK if dark else LIGHT)
    values = legacy_values()
    for namespace in _registered:
        namespace.update(values)
    return name


def style_system_bars():
    """Match Android status/navigation bars to the background (best effort)."""
    try:
        from kivy.utils import platform
        if platform != 'android':
            return
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        color_class = autoclass('android.graphics.Color')
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        background = color_class.parseColor(palette['bg'])
        light = name == 'light'

        @run_on_ui_thread
        def _style():
            window = activity.getWindow()
            window.setStatusBarColor(background)
            window.setNavigationBarColor(background)
            flags = 0x2000 | 0x10 if light else 0  # LIGHT_STATUS_BAR | LIGHT_NAVIGATION_BAR
            window.getDecorView().setSystemUiVisibility(flags)
        _style()
    except Exception:
        pass

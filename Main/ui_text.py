"""Kivy-side language support: fonts for non-Latin scripts and right-to-left Arabic.

Kivy's default SDL2 text provider draws glyphs left to right without Arabic
shaping. Arabic text is therefore reshaped (contextual letter forms) when a
core label receives it and reordered with the Unicode bidi algorithm line by
line at render time, after Kivy has wrapped the logical text. Lines that
contain Arabic are right-aligned.
"""
import os
import re

import i18n

_ARABIC = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

_WINDOWS_FONTS = ("C:/Windows/Fonts", "/mnt/c/Windows/Fonts")
_CJK_COMMON = (
    "/system/fonts/NotoSansCJK-Regular.ttc", "/system/fonts/NotoSansCJKsc-Regular.otf",
    "/system/fonts/NotoSansSC-Regular.otf", "/system/fonts/DroidSansFallbackFull.ttf",
    "/system/fonts/DroidSansFallback.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)
_WINDOWS_CJK = {"zh": (("msyh.ttc", "msyhbd.ttc"),), "ja": (("YuGothM.ttc", "YuGothB.ttc"), ("meiryo.ttc", "meiryob.ttc")),
                "ko": (("malgun.ttf", "malgunbd.ttf"),)}

_default_font = None
_patched = False


def font_files(code):
    """(regular, bold) font paths able to draw ``code``'s script, or None for the default."""
    if code == "ar":
        regular = os.path.join(FONT_DIR, "IBMPlexSansArabic-Regular.ttf")
        bold = os.path.join(FONT_DIR, "IBMPlexSansArabic-Bold.ttf")
        if os.path.exists(regular):
            return regular, bold if os.path.exists(bold) else regular
        return None
    if code in ("zh", "ja", "ko"):
        for folder in _WINDOWS_FONTS:
            for regular, bold in _WINDOWS_CJK[code]:
                path = os.path.join(folder, regular)
                if os.path.exists(path):
                    bold_path = os.path.join(folder, bold)
                    return path, bold_path if os.path.exists(bold_path) else path
        for path in _CJK_COMMON:
            if os.path.exists(path):
                return path, path
    return None


def apply_font(code):
    """Point Kivy's default font family at a font covering ``code``; returns the regular path."""
    global _default_font
    from kivy.core.text import DEFAULT_FONT, LabelBase
    if _default_font is None:
        _default_font = list(LabelBase._fonts.get(DEFAULT_FONT, ()))
    files = font_files(code)
    if files:
        LabelBase.register(DEFAULT_FONT, fn_regular=files[0], fn_bold=files[1],
                           fn_italic=files[0], fn_bolditalic=files[1])
        return files[0]
    if _default_font:
        regular, italic, bold, bolditalic = _default_font
        LabelBase.register(DEFAULT_FONT, fn_regular=regular, fn_italic=italic,
                           fn_bold=bold, fn_bolditalic=bolditalic)
    return None


def language_name_fonts():
    """Font per language code able to draw that language's own name in the picker."""
    from kivy.core.text import DEFAULT_FONT, LabelBase
    latin = (_default_font or LabelBase._fonts.get(DEFAULT_FONT) or [None])[0]
    fonts = {}
    for code, _name in i18n.LANGUAGES:
        files = font_files(code)
        fonts[code] = files[0] if files else latin
    return {code: path for code, path in fonts.items() if path}


def _shape(text):
    try:
        import arabic_reshaper
        return arabic_reshaper.reshape(text)
    except Exception:
        return text


def _visual(text):
    try:
        from bidi.algorithm import get_display
        return get_display(text)
    except Exception:
        return text


def install_rtl_support():
    """Patch Kivy core labels once; text without Arabic is unaffected."""
    global _patched
    if _patched:
        return
    from kivy.core.text import LabelBase
    from kivy.core.text.markup import MarkupLabel

    original_set_text = LabelBase._set_text

    def _set_text(self, text):
        if isinstance(text, str) and _ARABIC.search(text):
            text = _shape(text)
        original_set_text(self, text)
    LabelBase._set_text = _set_text
    LabelBase.text = property(LabelBase._get_text, _set_text, doc="Get/Set the text")

    def wrap(render_lines):
        def patched(self, lines, options, render_text, y, size):
            if not _ARABIC.search(self.text or ""):
                return render_lines(self, lines, options, render_text, y, size)

            def render_visual(text, x, line_y, *rest):
                return render_text(_visual(text) if _ARABIC.search(text) else text, x, line_y, *rest)
            if options.get("halign") in ("left", "auto"):
                options = dict(options, halign="right")
            return render_lines(self, lines, options, render_visual, y, size)
        return patched

    LabelBase.render_lines = wrap(LabelBase.render_lines)
    MarkupLabel.render_lines = wrap(MarkupLabel.render_lines)
    _patched = True


def activate(code):
    """Apply fonts and RTL handling for ``code`` before widgets are built."""
    i18n.set_language(code)
    apply_font(code)
    # Always on: Arabic can appear in any language (the language picker, AI replies);
    # text without Arabic letters is left untouched.
    install_rtl_support()

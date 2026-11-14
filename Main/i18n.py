"""Interface language: Turkish source strings looked up in per-language catalogs.

The source language is Turkish, so every catalog maps the Turkish text to its
translation. ``tr`` is for interface strings written in this codebase;
``trd`` is for data strings (indicator names, notes, values) that may be
assembled from several fragments, so it falls back to replacing known
fragments inside the text. Missing entries fall back to English, then to the
Turkish source. This module does not import Kivy, so the background service
can use it for notifications.
"""
import json
import locale
import os
import re

LANGUAGES = (
    ("tr", "Türkçe"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"),
    ("es", "Español"), ("ru", "Русский"), ("ar", "العربية"), ("zh", "中文"),
    ("ja", "日本語"), ("ko", "한국어"),
)
CODES = tuple(code for code, _ in LANGUAGES)
SOURCE = "tr"
FALLBACK = "en"
RTL = {"ar"}
# Language names given to the AI model so it answers in the interface language.
AI_LANGUAGE_NAMES = {
    "tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "ru": "Russian", "ar": "Arabic", "zh": "Simplified Chinese", "ja": "Japanese", "ko": "Korean",
}
PREFS_FILE = "language.json"
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

current = SOURCE
_catalogs = {}
_fragment_cache = {}
_keys = None


def source_keys():
    """Turkish source strings; locales/<code>.json lists translations in the same order."""
    global _keys
    if _keys is None:
        try:
            with open(os.path.join(LOCALE_DIR, "keys.json"), encoding="utf-8") as handle:
                _keys = [key for key in json.load(handle) if isinstance(key, str)]
        except (OSError, ValueError):
            _keys = []
    return _keys


def _load_catalog(code):
    if code == SOURCE:
        return {}
    if code not in _catalogs:
        try:
            with open(os.path.join(LOCALE_DIR, code + ".json"), encoding="utf-8") as handle:
                values = json.load(handle)
            _catalogs[code] = {key: value for key, value in zip(source_keys(), values)
                               if isinstance(value, str) and value}
        except (OSError, ValueError, TypeError):
            _catalogs[code] = {}
    return _catalogs[code]


def _lookup(text):
    if current == SOURCE:
        return text
    found = _load_catalog(current).get(text)
    if found is None:
        found = _load_catalog(FALLBACK).get(text)
    return text if found is None else found


def tr(text, **values):
    """Translate an interface string; ``values`` fill ``{name}`` placeholders."""
    translated = _lookup(str(text))
    if values:
        try:
            return translated.format(**values)
        except (KeyError, IndexError, ValueError):
            return str(text).format(**values)
    return translated


def _fragment_pattern(code):
    if code not in _fragment_cache:
        merged = dict(_load_catalog(FALLBACK))
        merged.update(_load_catalog(code))
        keys = sorted((key for key in merged if len(key.strip()) >= 3 and "{" not in key),
                      key=len, reverse=True)
        parts = []
        for key in keys:
            escaped = re.escape(key)
            if key[0].isalnum():
                escaped = r"(?<!\w)" + escaped
            if key[-1].isalnum():
                escaped += r"(?!\w)"
            parts.append(escaped)
        pattern = re.compile("|".join(parts)) if parts else None
        _fragment_cache[code] = (pattern, merged)
    return _fragment_cache[code]


def trd(text):
    """Translate a data string, replacing known fragments when there is no exact entry."""
    if text is None:
        return ""
    text = str(text)
    if current == SOURCE or not text:
        return text
    exact = _lookup(text)
    if exact is not text and exact != text:
        return exact
    pattern, merged = _fragment_pattern(current)
    if pattern is None:
        return text
    return pattern.sub(lambda match: merged.get(match.group(0), match.group(0)), text)


def is_rtl(code=None):
    return (code or current) in RTL


def ai_language_name(code=None):
    return AI_LANGUAGE_NAMES.get(code or current, "Turkish")


def system_language():
    """Two-letter device language if supported, else English."""
    code = None
    try:
        from jnius import autoclass  # Android
        code = autoclass("java.util.Locale").getDefault().getLanguage()
    except Exception:
        try:
            code = (locale.getlocale()[0] or os.environ.get("LANG") or "")
        except (ValueError, TypeError):
            code = os.environ.get("LANG") or ""
    code = str(code or "").replace("-", "_").split("_")[0].lower()
    aliases = {"turkish": "tr", "english": "en", "german": "de", "french": "fr", "spanish": "es",
               "russian": "ru", "arabic": "ar", "chinese": "zh", "japanese": "ja", "korean": "ko"}
    code = aliases.get(code, code)
    return code if code in CODES else FALLBACK


def load_language(path=PREFS_FILE):
    try:
        with open(path, encoding="utf-8") as handle:
            code = json.load(handle).get("language")
        if code in CODES:
            return code
    except (OSError, ValueError, AttributeError):
        pass
    return system_language()


def save_language(code, path=PREFS_FILE):
    if code not in CODES:
        return
    try:
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"language": code}, handle)
        os.replace(temporary, path)
    except OSError:
        pass


def set_language(code):
    global current
    current = code if code in CODES else FALLBACK
    return current


def language_name(code=None):
    return dict(LANGUAGES).get(code or current, code or current)

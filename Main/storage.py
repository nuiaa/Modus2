"""Where per-device files (settings, alarms, caches) live.

On Android, python-for-android runs the app from files/app, and that folder is
deleted and re-extracted whenever a new APK is installed over the old one.
Settings kept there (API key, alarms, theme, language) would be lost on every
update, so they are stored one level up in the app's private files directory,
next to the FRED database. On the desktop they stay in the working directory.
"""
import os
import shutil
import sys


def _on_android():
    return sys.platform == "android" or bool(os.environ.get("ANDROID_ARGUMENT"))


def data_dir():
    if _on_android():
        from fred_feed import default_database_path
        return os.path.dirname(os.path.abspath(default_database_path()))
    return os.getcwd()


def data_path(name):
    """Persistent path for ``name``; copies a file left in the working directory by older versions."""
    path = os.path.join(data_dir(), name)
    legacy = os.path.abspath(name)
    if legacy != os.path.abspath(path) and not os.path.exists(path) and os.path.exists(legacy):
        try:
            shutil.copy2(legacy, path)
        except OSError:
            pass
    return path

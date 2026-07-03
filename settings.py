# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
settings.py
-----------
Persisted user settings (QSettings) layered over the config.py defaults, plus
run-at-startup management.

config.py stays the single source of DEFAULTS. At launch, load_into_config()
applies any saved overrides onto the config module so the rest of the app keeps
reading config.X as before. The Settings dialog (settings_dialog.py) writes
changes back through save().
"""

import os
import sys

from PySide6.QtCore import QSettings

import config

ORG, APP = "TidalWidget", "TidalWidget"

# settings key -> (config attribute, python type)
FIELDS = {
    "accent": ("ACCENT", str),
    "auto_accent": ("AUTO_ACCENT", bool),
    "lyrics_offset": ("LYRICS_OFFSET", float),
    "background_opacity": ("BACKGROUND_OPACITY", float),
    "window_opacity": ("WINDOW_OPACITY", float),
    "always_on_top": ("ALWAYS_ON_TOP", bool),
    "start_expanded": ("START_EXPANDED", bool),
    "hide_fullscreen": ("HIDE_ON_FULLSCREEN", bool),
    "live_tray": ("LIVE_TRAY", bool),
    "fallback_any": ("FALLBACK_TO_ANY", bool),
    "volume_scope": ("VOLUME_SCOPE", str),
    "poll_ms": ("POLL_MS", int),
    "hotkeys_enabled": ("HOTKEYS_ENABLED", bool),
    "check_updates": ("CHECK_UPDATES", bool),
}


def _store():
    return QSettings(ORG, APP)


def _coerce(val, typ):
    if typ is bool:
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    if typ is int:
        return int(float(val))
    if typ is float:
        return float(val)
    return str(val)


def load_into_config():
    """Apply saved overrides onto the config module (defaults remain if unset)."""
    s = _store()
    for key, (attr, typ) in FIELDS.items():
        if s.contains(key):
            try:
                setattr(config, attr, _coerce(s.value(key), typ))
            except Exception:
                pass


def current():
    """Effective values (from config) as a plain dict."""
    return {key: getattr(config, attr) for key, (attr, _t) in FIELDS.items()}


def save(values: dict):
    """Persist the given values and apply them onto config immediately."""
    s = _store()
    for key, val in values.items():
        if key in FIELDS:
            attr, typ = FIELDS[key]
            v = _coerce(val, typ)
            setattr(config, attr, v)
            s.setValue(key, v)
    s.sync()


def set_placement(screen, corner):
    """Persist the last screen name + corner so the widget returns there."""
    s = _store()
    s.setValue("place_screen", screen)
    s.setValue("place_corner", corner)
    s.sync()


def get_placement():
    s = _store()
    return (s.value("place_screen", "", str), s.value("place_corner", "", str))


# ---- run at Windows startup (per-user HKCU Run key) -----------------------
_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "TidalNowPlaying"


def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'                       # the packaged .exe
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable    # windowless when run from source
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return f'"{exe}" "{main_py}"'


def is_run_at_startup():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_PATH) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except Exception:
        return False


def set_run_at_startup(enabled: bool):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_PATH, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, _RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False

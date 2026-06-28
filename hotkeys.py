# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
hotkeys.py
----------
Optional global (system-wide) hotkeys via pynput, so playback can be controlled
without focusing the widget. The pynput listener runs on its own thread; each
hotkey emits a Qt signal, which Qt delivers to the UI thread via a queued
connection. Inert if pynput isn't installed (available() == False).

Defaults:
  Ctrl+Alt+Space  play/pause
  Ctrl+Alt+Right  next
  Ctrl+Alt+Left   previous
  Ctrl+Alt+L      like (favorite) the current track
  Ctrl+Alt+H      show/hide the widget
"""

from PySide6.QtCore import QObject, Signal

try:
    from pynput import keyboard
except Exception:  # pragma: no cover - pynput optional
    keyboard = None


class HotkeyManager(QObject):
    play_pause = Signal()
    next_track = Signal()
    prev_track = Signal()
    like = Signal()
    show_hide = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None

    def available(self):
        return keyboard is not None

    def start(self):
        if keyboard is None or self._listener is not None:
            return
        mapping = {
            "<ctrl>+<alt>+<space>": lambda: self.play_pause.emit(),
            "<ctrl>+<alt>+<right>": lambda: self.next_track.emit(),
            "<ctrl>+<alt>+<left>": lambda: self.prev_track.emit(),
            "<ctrl>+<alt>+l": lambda: self.like.emit(),
            "<ctrl>+<alt>+h": lambda: self.show_hide.emit(),
        }
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
        except Exception:
            self._listener = None

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

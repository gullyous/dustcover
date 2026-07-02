# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
fullscreen_watch.py
-------------------
Detects when a fullscreen app (game, video player) owns the widget's monitor,
so the always-on-top widget can get out of the way ("game mode") and come back
when the app closes or leaves fullscreen.

Detection is a light 1.5s poll on the GUI thread using documented user32 calls
via ctypes: the foreground window counts as fullscreen when its rect covers its
ENTIRE monitor (maximized windows stop at the work area, so an exact
full-monitor cover implies borderless/exclusive fullscreen), it is not the
shell or our own window, and it sits on the same monitor as the widget.
"""

import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QObject, QTimer, Signal

_MONITOR_DEFAULTTONEAREST = 2
_SHELL_CLASSES = ("progman", "workerw")


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD),
                ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD)]


class FullscreenWatcher(QObject):
    """Polls the foreground window; emits fullscreen_changed(bool) on edges."""

    fullscreen_changed = Signal(bool)

    def __init__(self, own_hwnd, parent=None):
        """own_hwnd: zero-arg callable returning the widget's HWND (int)."""
        super().__init__(parent)
        self._own_hwnd = own_hwnd
        self._state = False
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._poll)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        try:
            fs = self._foreground_is_fullscreen()
        except Exception:
            fs = False   # any API hiccup counts as "not fullscreen" (fail open)
        if fs != self._state:
            self._state = fs
            self.fullscreen_changed.emit(fs)

    def _foreground_is_fullscreen(self):
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd or hwnd == u32.GetDesktopWindow():
            return False
        try:
            own = int(self._own_hwnd() or 0)
        except Exception:
            own = 0
        if own and hwnd == own:
            return False
        buf = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, buf, 64)
        if (buf.value or "").lower() in _SHELL_CLASSES:
            return False
        # A maximized window's rect extends PAST the work area by the invisible
        # resize border, so on a monitor with no taskbar (or auto-hide) it would
        # cover rcMonitor and misread as fullscreen. Real borderless/exclusive
        # fullscreen apps are not "zoomed", so excluding them is safe.
        if u32.IsZoomed(hwnd):
            return False

        rect = wt.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        mon = u32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        covers = (rect.left <= m.left and rect.top <= m.top and
                  rect.right >= m.right and rect.bottom >= m.bottom)
        if not covers:
            return False
        # Only yield when the fullscreen app is on the WIDGET's monitor, so a
        # widget parked on a second screen survives primary-monitor gaming.
        if own:
            own_mon = u32.MonitorFromWindow(own, _MONITOR_DEFAULTTONEAREST)
            if own_mon and own_mon != mon:
                return False
        return True

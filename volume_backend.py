# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
volume_backend.py
-----------------
Per-application volume control via the Windows Core Audio APIs (pycaw).

SMTC carries no volume, so this controls the audio-session volume of whichever
app is playing (exactly what the Windows Volume Mixer shows per app), with a
system-master fallback. The followed app is matched by executable name derived
from config.MATCH_APP ("tidal") plus a browser list (for the TIDAL web player).

The reported level is the EFFECTIVE (audible) volume: the app session scaled by
the system master. That keeps the widget's slider in step with keyboard volume
keys and the Windows mixer, which change the master, not the app session.
Setting the slider adjusts the app session relative to the master ceiling.

All COM work happens on a dedicated background thread with its own COM apartment,
so it never interferes with the WinRT (winsdk) worker. The whole feature degrades
gracefully: if pycaw/COM is unavailable, available() is False and the UI hides
the slider; every COM call is wrapped so a failure just yields "no control".

Qt contract:
  signal state_changed(float level, bool muted, str scope)
     level 0.0-1.0, or -1.0 when nothing controllable is found (UI hides slider);
     scope is a short label ("TIDAL" / a browser exe name / "System" / "").
  methods (call from the UI thread): set_volume(level), set_mute(bool),
     set_source(str), start(), stop().
"""

import queue
import threading

from PySide6.QtCore import QObject, Signal

import config

try:
    from ctypes import POINTER, cast
    import comtypes
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioEndpointVolume
    _OK = True
except Exception:  # pragma: no cover - optional dependency
    _OK = False

# Executable-name substrings for the TIDAL web player (browser sessions).
_BROWSERS = ("msedge", "chrome", "firefox", "brave", "opera", "vivaldi")


def available():
    return _OK


# ---- COM apartment (dedicated worker thread) -------------------------------
def _coinit():
    try:
        comtypes.CoInitializeEx(getattr(comtypes, "COINIT_MULTITHREADED", 0x0))
    except Exception:
        try:
            comtypes.CoInitialize()
        except Exception:
            pass


def _couninit():
    try:
        comtypes.CoUninitialize()
    except Exception:
        pass


# ---- session matching ------------------------------------------------------
def _app_names():
    names = []
    m = (str(getattr(config, "MATCH_APP", "tidal") or "")).lower()
    if m:
        names.append(m)
    if "tidal" not in names:
        names.append("tidal")
    return names


def _pick(source):
    """Return (scope_label, [ISimpleAudioVolume, ...]) for the followed app, or
    ("", []) if no app session is found (caller falls back to system master)."""
    src = (source or "").lower()
    sessions = AudioUtilities.GetAllSessions()

    def grab(name_list):
        out = []
        for s in sessions:
            try:
                proc = s.Process
                pn = (proc.name() or "").lower() if proc else ""
                if pn and any(n in pn for n in name_list):
                    out.append((pn, s.SimpleAudioVolume))
            except Exception:
                continue
        return out

    app = grab(_app_names())
    if app:
        return ("TIDAL", [v for _, v in app])

    # web player: prefer the browser named in the SMTC source, else any browser
    pref = [b for b in _BROWSERS if b in src]
    order = pref + [b for b in _BROWSERS if b not in pref]
    web = grab(order)
    if web:
        return (web[0][0], [v for _, v in web])
    return ("", [])


def _endpoint():
    spk = AudioUtilities.GetSpeakers()
    # Newer pycaw returns an AudioDevice wrapper with the endpoint-volume
    # interface as a property; older pycaw returns the raw IMMDevice.
    ev = getattr(spk, "EndpointVolume", None)
    if ev is not None:
        return ev
    dev = getattr(spk, "_dev", spk)
    iface = dev.Activate(IAudioEndpointVolume._iid_, 1, None)  # CLSCTX_INPROC_SERVER
    return cast(iface, POINTER(IAudioEndpointVolume))


def _get_state(source):
    scope, vols = _pick(source)
    if vols:
        v = vols[0]
        app_level = float(v.GetMasterVolume())
        app_mute = bool(v.GetMute())
        try:
            ep = _endpoint()
            if ep is not None:
                # What you HEAR is the app session scaled by the system master.
                # Reporting the product keeps the slider in step with keyboard
                # volume keys and the Windows mixer (which change the master).
                master = float(ep.GetMasterVolumeLevelScalar())
                return (app_level * master, app_mute or bool(ep.GetMute()), scope)
        except Exception:
            pass
        return (app_level, app_mute, scope)
    ep = _endpoint()
    if ep is not None:
        return (float(ep.GetMasterVolumeLevelScalar()), bool(ep.GetMute()), "System")
    return None


def _set_volume(source, level):
    scope, vols = _pick(source)
    if vols:
        target = level
        try:
            ep = _endpoint()
            if ep is not None:
                master = float(ep.GetMasterVolumeLevelScalar())
                if master < 0.01:
                    # Master is (near) zero: no audible target exists, and any
                    # write would silently pin the app session at 100%. Keep
                    # the user's stored per-app level until master comes back.
                    return
                # Invert the effective mapping: the slider asks for an audible
                # level, the app session is set relative to the master ceiling
                # (dragging to 80% with master at 50% pins the app at 100%).
                target = level / master
        except Exception:
            pass
        target = max(0.0, min(1.0, target))
        for v in vols:
            v.SetMasterVolume(target, None)
        return
    ep = _endpoint()
    if ep is not None:
        ep.SetMasterVolumeLevelScalar(level, None)


def _set_mute(source, muted):
    scope, vols = _pick(source)
    if vols:
        for v in vols:
            v.SetMute(1 if muted else 0, None)
        if not muted:
            # Unmuting the app is inaudible through a muted master; the click
            # means "I want sound", so lift a master mute too.
            try:
                ep = _endpoint()
                if ep is not None and ep.GetMute():
                    ep.SetMute(0, None)
            except Exception:
                pass
        return
    ep = _endpoint()
    if ep is not None:
        ep.SetMute(1 if muted else 0, None)


# ---- controller ------------------------------------------------------------
class VolumeController(QObject):
    state_changed = Signal(float, bool, str)   # level 0..1 (-1 = none), muted, scope

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()
        self._stop = False
        self._source = ""
        self._poll_s = 1.0   # snappy enough to follow keyboard volume keys
        self._thread = None

    def available(self):
        return _OK

    # ---- UI-thread API ----
    def set_source(self, source):
        self._source = source or ""   # plain attribute write is atomic enough

    def set_volume(self, level):
        self._q.put(("set", max(0.0, min(1.0, float(level)))))

    def set_mute(self, muted):
        self._q.put(("mute", bool(muted)))

    def start(self):
        if not _OK or (self._thread and self._thread.is_alive()):
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        self._q.put("__stop__")
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.5)

    # ---- worker thread ----
    def _emit(self):
        # Nothing playing -> report "no control" without enumerating sessions.
        if not self._source:
            self.state_changed.emit(-1.0, False, "")
            return
        try:
            st = _get_state(self._source)
        except Exception:
            st = None
        if st is None:
            self.state_changed.emit(-1.0, False, "")
        else:
            level, muted, scope = st
            self.state_changed.emit(float(level), bool(muted), scope or "")

    def _run(self):
        _coinit()
        try:
            self._emit()
            while not self._stop:
                try:
                    cmd = self._q.get(timeout=self._poll_s)
                except queue.Empty:
                    self._emit()           # periodic refresh
                    continue
                changed = False
                while cmd != "__stop__":
                    try:
                        if cmd[0] == "set":
                            _set_volume(self._source, cmd[1])
                        elif cmd[0] == "mute":
                            _set_mute(self._source, cmd[1])
                        changed = True
                    except Exception:
                        pass
                    try:
                        cmd = self._q.get_nowait()
                    except queue.Empty:
                        break
                if self._stop:
                    break
                if changed:
                    self._emit()
        finally:
            _couninit()

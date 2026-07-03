# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
volume_backend.py
-----------------
Per-application volume control via the Windows Core Audio APIs (pycaw).

SMTC carries no volume, so this controls a volume level and reports it back for
the slider. Two scopes, chosen by config.VOLUME_SCOPE:

  "system" (default): the slider IS the Windows system volume (the endpoint
      master). Dragging it moves the same level your keyboard volume keys and
      the taskbar speaker do, so everything stays in lock-step.
  "app": the per-app session volume of whichever app is playing (what the
      Windows Volume Mixer shows per app), with a system-master fallback. The
      reported level is the EFFECTIVE (audible) value, the app session scaled by
      the master, so it still follows the master; setting it adjusts the app
      session relative to the master ceiling. The followed app is matched by
      executable name from config.MATCH_APP ("tidal") plus a browser list (for
      the TIDAL web player).

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
import time

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


def _scope():
    """'system' (control the Windows master) or 'app' (per-app session)."""
    s = (str(getattr(config, "VOLUME_SCOPE", "system") or "system")).lower()
    return "app" if s == "app" else "system"


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


# ---- COM object cache -------------------------------------------------------
# _pick() enumerates every audio session (plus a process lookup each) and
# _endpoint() activates a device interface; doing that per slider tick made
# dragging lag by seconds. Cache the COM POINTERS for a short TTL: reads on a
# cached pointer still return live values, the TTL only bounds how long a
# stale session list (app closed, device swapped) can linger. Any COM error
# clears the cache so the next call re-enumerates.
_CACHE_TTL = 2.0


def _cached(cache, source, mode):
    if (cache.get("source") != source or cache.get("mode") != mode
            or "vols" not in cache
            or time.monotonic() - cache.get("t", 0.0) > _CACHE_TTL):
        # In "system" mode we control the endpoint master only, so skip the
        # (expensive) per-app session enumeration entirely.
        if mode == "system":
            label, vols = "System", []
        else:
            label, vols = _pick(source)
        try:
            ep = _endpoint()
        except Exception:
            ep = None
        cache.clear()
        cache.update(source=source, mode=mode, label=label, vols=vols, ep=ep,
                     t=time.monotonic())
    return cache


def _get_state(source, cache):
    mode = _scope()
    def read():
        c = _cached(cache, source, mode)
        vols, ep, label = c["vols"], c["ep"], c["label"]
        if vols:   # app mode with a live session
            v = vols[0]
            app_level = float(v.GetMasterVolume())
            app_mute = bool(v.GetMute())
            if ep is not None:
                # What you HEAR is the app session scaled by the system master.
                # Reporting the product keeps the slider in step with keyboard
                # volume keys and the Windows mixer (which change the master).
                master = float(ep.GetMasterVolumeLevelScalar())
                return (app_level * master, app_mute or bool(ep.GetMute()), label)
            return (app_level, app_mute, label)
        if ep is not None:   # system mode, or app mode with no session found
            return (float(ep.GetMasterVolumeLevelScalar()), bool(ep.GetMute()),
                    "System")
        return None
    try:
        return read()
    except Exception:
        cache.clear()   # stale COM pointer (app exited / device changed)
        return read()   # one fresh retry; a second failure raises to caller


def _ramp_steps(cur, target, gentle):
    """The write sequence for a volume move: a short glide for a large jump
    (so slamming the slider isn't an abrupt loudness step), else one write."""
    if not gentle or abs(target - cur) <= 0.10:
        return [target]
    return [cur + (target - cur) * f for f in (0.25, 0.5, 0.75, 1.0)]


def _set_volume(source, level, cache, gentle=False):
    mode = _scope()
    def write():
        c = _cached(cache, source, mode)
        vols, ep = c["vols"], c["ep"]
        if vols:
            target = level
            cur = float(vols[0].GetMasterVolume())
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
            target = max(0.0, min(1.0, target))
            steps = _ramp_steps(cur, target, gentle)
            for s in steps:
                for v in vols:
                    v.SetMasterVolume(s, None)
                if len(steps) > 1:
                    time.sleep(0.02)
            return
        if ep is not None:
            cur = float(ep.GetMasterVolumeLevelScalar())
            steps = _ramp_steps(cur, max(0.0, min(1.0, level)), gentle)
            for s in steps:
                ep.SetMasterVolumeLevelScalar(s, None)
                if len(steps) > 1:
                    time.sleep(0.02)
    try:
        write()
    except Exception:
        cache.clear()
        write()


def _set_mute(source, muted, cache):
    mode = _scope()
    def write():
        c = _cached(cache, source, mode)
        vols, ep = c["vols"], c["ep"]
        if vols:
            for v in vols:
                v.SetMute(1 if muted else 0, None)
            if not muted and ep is not None and ep.GetMute():
                # Unmuting the app is inaudible through a muted master; the
                # click means "I want sound", so lift a master mute too.
                ep.SetMute(0, None)
            return
        if ep is not None:
            ep.SetMute(1 if muted else 0, None)
    try:
        write()
    except Exception:
        cache.clear()
        write()


def _coalesce(cmds):
    """The surviving operations from a drained backlog: only the LAST "set" and
    the LAST "mute" matter, executed in their original relative order (a mute
    clicked before a slam must still land before the volume moves)."""
    last_set = last_mute = None
    set_idx = mute_idx = -1
    for i, c in enumerate(cmds):
        if c[0] == "set":
            last_set, set_idx = c[1], i
        elif c[0] == "mute":
            last_mute, mute_idx = c[1], i
    ops = []
    for idx, kind, val in sorted([(set_idx, "set", last_set),
                                  (mute_idx, "mute", last_mute)]):
        if idx >= 0:
            ops.append((kind, val))
    return ops


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
            st = _get_state(self._source, self._cache)
        except Exception:
            st = None
        if st is None:
            self.state_changed.emit(-1.0, False, "")
        else:
            level, muted, scope = st
            self.state_changed.emit(float(level), bool(muted), scope or "")

    def _run(self):
        _coinit()
        self._cache = {}   # COM pointer cache, owned by this thread
        last_set_ts = 0.0  # when the previous volume set executed (glide gate)
        try:
            self._emit()
            while not self._stop:
                try:
                    cmd = self._q.get(timeout=self._poll_s)
                except queue.Empty:
                    self._emit()           # periodic refresh
                    continue
                # Coalesce the whole backlog: during a drag dozens of "set"s
                # queue up, and only the LATEST value matters. Executing each
                # one (a full session enumeration apiece before the cache) is
                # what made the slider lag by seconds.
                cmds = [cmd]
                while True:
                    try:
                        cmds.append(self._q.get_nowait())
                    except queue.Empty:
                        break
                if "__stop__" in cmds or self._stop:
                    break
                # Glide only for an ISOLATED click/slam. Queue emptiness alone
                # cannot tell: the UI throttle paces a drag to one send per
                # 40ms, so the queue looks empty mid-drag too. A real drag has
                # a recent previous set; a click stands alone in time.
                gentle = (self._q.empty()
                          and time.monotonic() - last_set_ts > 0.3)
                for kind, val in _coalesce(cmds):
                    if kind == "set":
                        try:
                            _set_volume(self._source, val, self._cache, gentle)
                        except Exception:
                            pass
                        last_set_ts = time.monotonic()
                    else:
                        try:
                            _set_mute(self._source, val, self._cache)
                        except Exception:
                            pass   # a failed set must never eat a mute click
                self._emit()
        finally:
            _couninit()

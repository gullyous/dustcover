# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
media_backend.py
----------------
The data layer. Reads "now playing" from the Windows System Media Transport
Controls (SMTC) and sends transport commands back. Works with the TIDAL
desktop app (and any other app that integrates with SMTC) - no API keys,
no OAuth, no login.

This file is intentionally the *complete* hard part of the project: the
asyncio <-> Qt threading model and the WinRT calls are the easy things to
get subtly wrong, so they're done for you. The fun UI work lives in widget.py.

Quick check (no GUI needed):
    python media_backend.py
...prints whatever TIDAL (or your fallback app) is currently playing.
"""

import asyncio
import datetime
import queue
import time

from PySide6.QtCore import QThread, Signal

import config

# --- winsdk / winrt import shim -------------------------------------------
# "winsdk" is one package that bundles every namespace. Microsoft's newer
# PyWinRT ships split "winrt-Windows.*" packages with identical class names.
# Accept either so the project keeps working as the ecosystem shifts.
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winsdk.windows.media import MediaPlaybackAutoRepeatMode
    from winsdk.windows.storage.streams import DataReader, Buffer, InputStreamOptions
except ImportError:  # pragma: no cover - fallback path
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.media import MediaPlaybackAutoRepeatMode
    from winrt.windows.storage.streams import DataReader, Buffer, InputStreamOptions

PLAYING = PlaybackStatus.PLAYING


# --- low-level WinRT helpers (all async, all run on the worker loop) -------

async def _read_thumbnail(thumb_ref):
    """Turn an SMTC thumbnail reference into raw image bytes (or None)."""
    if thumb_ref is None:
        return None
    try:
        stream = await thumb_ref.open_read_async()
        size = int(stream.size)
        if size <= 0:
            return None
        size = min(size, 8_000_000)  # album art is tiny; guard anyway
        buf = Buffer(size)
        await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
        reader = DataReader.from_buffer(buf)
        count = int(buf.length) or size
        # winsdk/winrt project DataReader.read_bytes as an in-place fill: you
        # pass a pre-sized writable buffer and it writes into it (returns None).
        # Some builds return the bytes instead, so accept both.
        out = bytearray(count)
        res = reader.read_bytes(out)
        return bytes(res) if res is not None else bytes(out)
    except Exception:
        return None


def _pick_session(mgr):
    """Choose which media session to display.

    Prefer a session whose app id contains config.MATCH_APP (e.g. "tidal"),
    preferring one that is actively playing. Fall back to the system's
    current session if allowed.
    """
    target = (config.MATCH_APP or "").lower()
    matches = []
    try:
        sessions = mgr.get_sessions()
        for i in range(sessions.size):
            s = sessions.get_at(i)
            try:
                sid = (s.source_app_user_model_id or "").lower()
            except Exception:
                sid = ""
            if target and target in sid:
                matches.append(s)
    except Exception:
        matches = []

    # Prefer a matching session that's actually playing.
    for s in matches:
        try:
            if s.get_playback_info().playback_status == PLAYING:
                return s
        except Exception:
            pass
    if matches:
        return matches[0]

    if config.FALLBACK_TO_ANY:
        try:
            return mgr.get_current_session()
        except Exception:
            return None
    return None


_MAX_STAMP_AGE = 24 * 3600.0   # a timeline stamp older than this is garbage


def _live_position(raw, last_updated, playing, rate, duration, state):
    """Best-effort live playback position in seconds.

    Some apps (TIDAL among them) stamp the SMTC timeline only on track change
    and seek, so the reported `position` freezes while the song plays. While
    playing, advance the stamped position by the wall-clock time since the
    stamp (times the playback rate). While paused, hold the last value we
    computed: for those apps the stamp does not move on pause either, so time
    spent paused must never be counted as playback.

    `state` is a mutable dict owned by the worker thread (single-threaded).
    Well-behaved apps that re-stamp continuously get a near-zero correction,
    and their re-stamp on pause resets the state so the raw value is used.
    """
    if raw is None:
        raw = 0.0
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        stamp_age = (now - last_updated).total_seconds()
    except Exception:
        stamp_age = None
    if stamp_age is None or stamp_age < -5.0 or stamp_age > _MAX_STAMP_AGE:
        # No usable stamp THIS poll: report raw untouched but keep the
        # bookkeeping. A transient WinRT hiccup must not wipe paused_accum/
        # held; the epoch check below invalidates state when a genuinely new
        # stamp appears.
        return max(0.0, raw)

    # A new stamp (seek, track change, or a well-behaved app's regular update)
    # starts a fresh epoch: no accumulated pause time, nothing held.
    epoch = (round(raw, 3), last_updated)
    if state.get("epoch") != epoch:
        state["epoch"] = epoch
        # First observed while paused: everything since the stamp is
        # unobserved, so count it as paused. Resume then advances from the
        # raw position we were showing, instead of leaping to stamp age
        # (which pinned the bar at track end after launch-while-paused).
        state["paused_accum"] = 0.0 if playing else stamp_age
        state["paused_since"] = None
        state["held"] = None

    if playing:
        if state.get("paused_since") is not None:
            state["paused_accum"] += time.monotonic() - state["paused_since"]
            state["paused_since"] = None
        eff = max(0.0, stamp_age - state.get("paused_accum", 0.0))
        pos = raw + eff * (rate or 1.0)
        state["held"] = pos
    else:
        if state.get("paused_since") is None:
            state["paused_since"] = time.monotonic()
        pos = state.get("held")
        if pos is None:
            pos = raw   # paused since before we started watching
    if duration and duration > 0:
        pos = min(pos, duration)
    return max(0.0, pos)


def _source_state(pos_state, source):
    """Per-source bookkeeping for _live_position, so bouncing between apps
    (FALLBACK_TO_ANY) doesn't discard one app's pause state. Bounded."""
    st = pos_state.get(source)
    if st is None:
        if len(pos_state) >= 6:
            pos_state.pop(next(iter(pos_state)), None)
        st = pos_state[source] = {}
    return st


async def _snapshot(mgr, last_key, pos_state):
    """Build a dict describing the current track. Cheap to call repeatedly.

    Only re-reads (relatively expensive) album art when the track changes.
    """
    session = _pick_session(mgr)
    if session is None:
        return {"available": False}

    info = {"available": True}
    try:
        props = await session.try_get_media_properties_async()
        info["title"] = props.title or ""
        info["artist"] = props.artist or ""
        info["album"] = props.album_title or ""
    except Exception:
        return {"available": False}

    try:
        pi = session.get_playback_info()
    except Exception:
        pi = None
    info["playing"] = bool(pi is not None and pi.playback_status == PLAYING)

    try:
        tl = session.get_timeline_properties()
        raw_pos = max(0.0, tl.position.total_seconds()) if tl.position else 0.0
        info["duration"] = max(0.0, tl.end_time.total_seconds()) if tl.end_time else 0.0
        last_updated = getattr(tl, "last_updated_time", None)
    except Exception:
        raw_pos, last_updated = 0.0, None
        info["duration"] = 0.0

    try:
        info["source"] = session.source_app_user_model_id or ""
    except Exception:
        info["source"] = ""

    # transport capabilities + shuffle/repeat state (drives the adaptive UI)
    try:
        if pi is None:
            raise RuntimeError("playback info unavailable")
        c = pi.controls
        info["can_playpause"] = bool(c.is_play_enabled or c.is_pause_enabled
                                     or c.is_play_pause_toggle_enabled)
        info["can_next"] = bool(c.is_next_enabled)
        info["can_prev"] = bool(c.is_previous_enabled)
        info["can_seek"] = bool(c.is_playback_position_enabled)
        info["can_shuffle"] = bool(c.is_shuffle_enabled)
        info["can_repeat"] = bool(c.is_repeat_enabled)
        sh = pi.is_shuffle_active
        info["shuffle"] = bool(sh) if sh is not None else False
        rm = pi.auto_repeat_mode
        info["repeat"] = int(rm) if rm is not None else 0  # 0 none, 1 track, 2 list
        rate = pi.playback_rate
        info["rate"] = float(rate) if rate else 1.0
    except Exception:
        # Be conservative on failure: keep basic transport, but do NOT claim
        # seek/shuffle/repeat we couldn't confirm (avoids showing dead controls).
        info["can_playpause"] = info["can_next"] = info["can_prev"] = True
        info["can_seek"] = info["can_shuffle"] = info["can_repeat"] = False
        info["shuffle"], info["repeat"], info["rate"] = False, 0, 1.0

    # Position last: TIDAL freezes the reported position (stamping the timeline
    # only on seek/track change), so derive the live value from the stamp.
    info["position"] = _live_position(raw_pos, last_updated, info["playing"],
                                      info.get("rate", 1.0), info["duration"],
                                      _source_state(pos_state, info["source"]))

    key = (info["title"], info["artist"], info["album"])
    info["_key"] = key
    if key != last_key:
        info["art"] = await _read_thumbnail(getattr(props, "thumbnail", None))
        info["art_changed"] = True
    else:
        info["art_changed"] = False
    return info


# repeat cycle order: None -> List (all) -> Track (one) -> None
_REPEAT_ORDER = [0, 2, 1]


async def _do_command(mgr, cmd):
    s = _pick_session(mgr)
    if s is None:
        return
    # a command is either a string ("next") or a ("name", value) tuple ("seek", 42.0)
    name = cmd[0] if isinstance(cmd, tuple) else cmd
    arg = cmd[1] if isinstance(cmd, tuple) else None
    try:
        if name == "playpause":
            # Prefer the discrete play/pause command for the current state.
            # TIDAL (and some other apps) ignore try_toggle_play_pause when
            # paused, so toggling by hand is more reliable. Fall back to the
            # toggle if the discrete call is unavailable.
            try:
                playing = s.get_playback_info().playback_status == PLAYING
                if playing:
                    await s.try_pause_async()
                else:
                    await s.try_play_async()
            except Exception:
                await s.try_toggle_play_pause_async()
        elif name == "next":
            await s.try_skip_next_async()
        elif name == "prev":
            await s.try_skip_previous_async()
        elif name == "seek":
            # SMTC positions are in 100-nanosecond ticks
            await s.try_change_playback_position_async(int(max(0.0, arg) * 10_000_000))
        elif name == "shuffle":
            cur = s.get_playback_info().is_shuffle_active
            await s.try_change_shuffle_active_async(not bool(cur))
        elif name == "repeat":
            cur = s.get_playback_info().auto_repeat_mode
            cur = int(cur) if cur is not None else 0
            idx = _REPEAT_ORDER.index(cur) if cur in _REPEAT_ORDER else 0
            nxt = _REPEAT_ORDER[(idx + 1) % len(_REPEAT_ORDER)]
            await s.try_change_auto_repeat_mode_async(MediaPlaybackAutoRepeatMode(nxt))
    except Exception:
        pass


# --- Qt worker -------------------------------------------------------------

class MediaWorker(QThread):
    """Polls SMTC on its own thread/event loop and emits `updated(dict)`.

    All WinRT access happens on this one thread (its own asyncio loop), which
    keeps the apartment-bound WinRT objects happy. The UI thread talks to it
    only through Qt signals (in) and a thread-safe queue (out).
    """

    updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmds = queue.Queue()
        self._stop = False

    # called from the UI thread - just enqueue, never touch WinRT here
    def play_pause(self):
        self._cmds.put("playpause")

    def next_track(self):
        self._cmds.put("next")

    def prev_track(self):
        self._cmds.put("prev")

    def seek(self, seconds):
        self._cmds.put(("seek", float(seconds)))

    def toggle_shuffle(self):
        self._cmds.put("shuffle")

    def cycle_repeat(self):
        self._cmds.put("repeat")

    def stop(self):
        self._stop = True
        self._cmds.put("__stop__")  # wake the blocking get() immediately

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        poll_s = max(0.05, config.POLL_MS / 1000.0)
        try:
            try:
                mgr = loop.run_until_complete(MediaManager.request_async())
            except Exception:
                self.updated.emit({"available": False,
                                   "error": "Could not access Windows media controls."})
                return

            last_key = None
            pos_state = {}   # _live_position bookkeeping (worker thread only)

            def refresh():
                nonlocal last_key
                try:
                    info = loop.run_until_complete(_snapshot(mgr, last_key, pos_state))
                    if info.get("available"):
                        last_key = info.get("_key", last_key)
                    self.updated.emit(info)
                except Exception:
                    pass

            refresh()  # initial paint
            # Block until a command arrives or the poll interval elapses, rather
            # than waking ~10x/sec. A queued command wakes us immediately.
            while not self._stop:
                try:
                    cmd = self._cmds.get(timeout=poll_s)
                except queue.Empty:
                    refresh()
                    continue
                ran = False
                while cmd != "__stop__":
                    loop.run_until_complete(_do_command(mgr, cmd))
                    ran = True
                    try:
                        cmd = self._cmds.get_nowait()
                    except queue.Empty:
                        break
                if self._stop:
                    break
                if ran:
                    refresh()
        finally:
            loop.close()


# --- standalone sanity check ----------------------------------------------

if __name__ == "__main__":
    async def _selftest():
        mgr = await MediaManager.request_async()
        info = await _snapshot(mgr, None, {})
        if not info.get("available"):
            print("No media session found. Open TIDAL and press play, then retry.")
            return
        print(f"  title : {info['title']}")
        print(f"  artist: {info['artist']}")
        print(f"  album : {info['album']}")
        print(f"  state : {'playing' if info['playing'] else 'paused'}")
        print(f"  pos   : {info['position']:.1f} / {info['duration']:.1f} s")
        print(f"  source: {info['source']}")
        print(f"  art   : {len(info['art']) if info.get('art') else 0} bytes")

    asyncio.run(_selftest())

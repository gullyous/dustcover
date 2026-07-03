# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
discord_backend.py
------------------
Optional Discord Rich Presence: shows "Listening to <title>" by <artist> on your
Discord profile, with the album cover and a live-ticking progress bar, exactly
like Spotify's native integration.

The widget already owns the authoritative live playback state (SMTC gives
title/artist/play-state, and media_backend derives the true position that TIDAL
itself freezes), so it is the right place to feed Discord.

All Discord IPC runs on a dedicated daemon thread with its own event loop (the
sync pypresence client needs a ProactorEventLoop, which a fresh worker thread
gets by default on Windows), mirroring volume_backend's model. The whole feature
is inert if pypresence is missing, no client id is configured, or the toggle is
off, and every call is guarded so a Discord outage never touches the UI.

Needs a one-time Discord Application ID (config.DISCORD_CLIENT_ID). Discord
rate-limits presence updates to about one per 15s, so updates are debounced.
"""

import queue
import threading
import time

from PySide6.QtCore import QObject

import config

try:
    from pypresence import Presence, ActivityType
    _OK = True
except Exception:  # pragma: no cover - optional dependency
    _OK = False

_MIN_INTERVAL = 15.0   # Discord presence rate limit (seconds between updates)
_FALLBACK_IMAGE = "tidal"   # art-asset key uploaded to the Discord app (optional)


def available():
    return _OK


class DiscordPresence(QObject):
    """Feeds Discord Rich Presence from the now-playing stream. UI-thread API:
    set_enabled(bool), on_update(info), set_cover(title, artist, url), stop()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()
        self._thread = None
        self._stop = False
        self._enabled = False
        self._cover = {}     # (title, artist) -> cover URL

    # ---- UI-thread API ----
    def set_enabled(self, on):
        on = bool(on) and _OK and bool(_client_id())
        if on and not self._enabled:
            self._enabled = True
            self._start()
        elif not on and self._enabled:
            self._enabled = False
            self._q.put(("clear", None))

    def on_update(self, info):
        if not self._enabled:
            return
        if not info or not info.get("available") or not info.get("title"):
            self._q.put(("clear", None))
            return
        key = (info.get("title", ""), info.get("artist", ""))
        payload = {
            "title": info.get("title", ""),
            "artist": info.get("artist", ""),
            "album": info.get("album", ""),
            "playing": bool(info.get("playing")),
            "position": float(info.get("position") or 0.0),
            "duration": float(info.get("duration") or 0.0),
            "cover": self._cover.get(key),
        }
        self._q.put(("update", payload))

    def set_cover(self, title, artist, url):
        if url:
            self._cover[(title, artist)] = url
            if len(self._cover) > 16:
                self._cover.pop(next(iter(self._cover)), None)

    def stop(self):
        self._stop = True
        self._q.put(("__stop__", None))
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)

    # ---- worker thread ----
    def _start(self):
        if not _OK or (self._thread and self._thread.is_alive()):
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        rpc = None
        connected = False
        last_push = 0.0
        last_sig = None
        pending = None
        last_payload = None   # re-sent after a reconnect so presence reappears
        next_retry = 0.0
        while not self._stop:
            # Drain the queue (coalesce to the latest update); block briefly so
            # we still wake to push a pending change or retry a connection.
            try:
                kind, payload = self._q.get(timeout=1.0)
            except queue.Empty:
                kind, payload = None, None
            while kind is not None:
                if kind == "__stop__":
                    self._stop = True
                    break
                if kind == "clear":
                    pending = "clear"
                elif kind == "update":
                    pending = payload
                try:
                    kind, payload = self._q.get_nowait()
                except queue.Empty:
                    break
            if self._stop:
                break

            if rpc is None:
                rpc = self._make_client()
                if rpc is None:
                    time.sleep(2.0)
                    continue
            if not connected:
                now = time.monotonic()
                if now < next_retry:
                    continue
                try:
                    rpc.connect()
                    connected = True
                    last_sig = None          # force a fresh push after (re)connect
                    if pending is None and last_payload is not None:
                        pending = last_payload   # restore presence Discord lost
                except Exception:
                    next_retry = now + 5.0   # Discord not running: back off
                    continue

            if pending is None:
                continue
            # Debounce: honor Discord's rate limit, but always let "clear" through.
            now = time.monotonic()
            sig = self._signature(pending)
            if pending != "clear" and sig == last_sig:
                pending = None
                continue
            if pending != "clear" and now - last_push < _MIN_INTERVAL:
                continue  # hold the pending update until the interval elapses
            try:
                if pending == "clear":
                    rpc.clear()
                    last_payload = None
                else:
                    rpc.update(**self._activity(pending))
                    last_payload = pending
                last_push = now
                last_sig = sig
                pending = None
            except Exception:
                connected = False        # pipe closed: reconnect next loop
                next_retry = now + 3.0
        # shutdown
        try:
            if rpc is not None and connected:
                rpc.clear()
                rpc.close()
        except Exception:
            pass

    def _make_client(self):
        cid = _client_id()
        if not cid:
            return None
        try:
            return Presence(cid)
        except Exception:
            return None

    @staticmethod
    def _signature(payload):
        if payload == "clear":
            return "clear"
        # Ignore sub-second position so we don't churn; Discord derives the bar
        # from the timestamps we send, it does not need per-tick updates.
        return (payload["title"], payload["artist"], payload["playing"],
                int(payload["position"]) // 5, int(payload["duration"]),
                payload.get("cover"))

    @staticmethod
    def _activity(p):
        # Discord requires details/state to be at least 2 chars.
        details = (p["title"] or "Unknown")[:128]
        state = (p["artist"] or "Unknown")[:128]
        act = {
            "activity_type": ActivityType.LISTENING,
            "details": details.ljust(2),
            "state": state.ljust(2),
            "large_image": p.get("cover") or _FALLBACK_IMAGE,
            "large_text": (p["album"] or "TIDAL")[:128],
        }
        if p["playing"] and p["duration"] > 0:
            start = time.time() - max(0.0, p["position"])
            act["start"] = int(start)
            act["end"] = int(start + p["duration"])
        return act


def _client_id():
    return str(getattr(config, "DISCORD_CLIENT_ID", "") or "").strip()

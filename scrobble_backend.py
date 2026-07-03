# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
scrobble_backend.py
-------------------
Optional scrobbling to ListenBrainz (https://listenbrainz.org): submits your
plays to an open, private, self-hostable listening history. Off by default;
needs only a user token (Settings). Uses the Python standard library only.

The widget already sees every play with a correct position/duration (it derives
the true position that TIDAL freezes), so it can apply the standard scrobble
rule honestly: a track counts once it has actually PLAYED for at least half its
length or 4 minutes, whichever comes first, counting play time only (never time
spent paused). A "playing now" update is sent on each track change.

Privacy: by default only TIDAL plays are submitted (not a browser tab or another
app that SMTC happens to surface). All network calls run on a daemon thread; the
token is never logged.
"""

import json
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Signal

import config

_API = "https://api.listenbrainz.org/1/submit-listens"
_VALIDATE = "https://api.listenbrainz.org/1/validate-token"
_CTX = ssl.create_default_context()
_MIN_PLAYED = 4 * 60.0    # 4 minutes is "enough" regardless of length
_MIN_TRACK = 30.0         # ignore very short blips (stings, skips)


def _post(url, token, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "User-Agent": f"TidalNowPlaying/{getattr(config, 'APP_VERSION', '0')}",
    })
    with urllib.request.urlopen(req, timeout=10, context=_CTX) as r:
        return r.status


def validate_token(token):
    """Return (ok, message). Used by the Settings 'Verify' button."""
    token = (token or "").strip()
    if not token:
        return (False, "No token")
    req = urllib.request.Request(_VALIDATE, headers={
        "Authorization": f"Token {token}",
        "User-Agent": f"TidalNowPlaying/{getattr(config, 'APP_VERSION', '0')}"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=_CTX) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        if body.get("valid"):
            return (True, body.get("user_name") or "valid")
        return (False, body.get("message") or "invalid token")
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}")
    except Exception:
        return (False, "could not reach ListenBrainz")


def _listen(title, artist, album, listened_at=None):
    track = {"track_name": title, "artist_name": artist}
    if album:
        track["release_name"] = album
    m = {"track_metadata": track}
    if listened_at is not None:
        m["listened_at"] = int(listened_at)
    return m


class PlayTracker:
    """Pure play-time accounting: decides when to send a 'now playing' update
    and when a track has genuinely played enough to scrobble. Time is injected
    so it is deterministic and testable; the worker feeds it a real clock.

    update(info, now, match_app) returns a list of events, each a
    ("now_playing" | "scrobble", (title, artist, album)) tuple."""

    def __init__(self):
        self._reset(None)

    def _reset(self, key):
        self._key = key          # (title, artist, album, source, duration)
        self._played = 0.0       # accumulated PLAY seconds (never counts pauses)
        self._last = None        # monotonic anchor while playing
        self._scrobbled = False

    def update(self, info, now, match_app):
        events = []
        if not info or not info.get("available") or not info.get("title"):
            self._reset(None)
            return events
        source = info.get("source", "") or ""
        if match_app and match_app.lower() not in source.lower():
            self._reset(None)   # only the followed app (TIDAL) by default
            return events
        key = (info.get("title", ""), info.get("artist", ""),
               info.get("album", ""), source, float(info.get("duration") or 0.0))
        if key[:2] != (self._key[:2] if self._key else None):
            self._reset(key)
            events.append(("now_playing", (key[0], key[1], key[2])))
        playing = bool(info.get("playing"))
        if self._last is not None:
            self._played += max(0.0, now - self._last)
        self._last = now if playing else None
        if self._key and not self._scrobbled:
            dur = self._key[4]
            thr = min(_MIN_PLAYED, dur / 2.0) if dur > 0 else _MIN_PLAYED
            if dur >= _MIN_TRACK and self._played >= thr:
                self._scrobbled = True
                events.append(("scrobble", (self._key[0], self._key[1], self._key[2])))
        return events


class Scrobbler(QObject):
    """Tracks play time from the now-playing stream and submits listens.
    UI-thread API: set_enabled(bool), set_token(str), on_update(info), stop()."""

    scrobbled = Signal(str, str)   # (title, artist) once a listen is submitted

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()
        self._thread = None
        self._stop = False
        self._enabled = False

    # ---- UI-thread API ----
    def set_enabled(self, on):
        self._enabled = bool(on)
        if self._enabled:
            self._start()   # start once; the loop idles (submits nothing) when off

    def set_token(self, token):
        pass  # read live from config in the worker

    def on_update(self, info):
        if not self._enabled:
            return
        self._q.put(dict(info) if info else {"available": False})

    def stop(self):
        self._stop = True
        self._q.put("__stop__")
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)

    # ---- worker thread ----
    def _start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        tracker = PlayTracker()
        last_info = None
        while not self._stop:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                item = last_info    # tick with the last known state (accrues time)
            if item == "__stop__":
                break
            if not self._enabled:
                # Disabled: accrue nothing, submit nothing, and keep the tracker
                # fresh so a later re-enable never scrobbles stale play time.
                last_info = None
                tracker = PlayTracker()
                continue
            if isinstance(item, dict):
                last_info = item
            token = str(getattr(config, "LISTENBRAINZ_TOKEN", "") or "").strip()
            events = tracker.update(item, time.monotonic(),
                                    getattr(config, "MATCH_APP", "") or "")
            if not token:
                continue
            for kind, (title, artist, album) in events:
                if kind == "now_playing":
                    self._submit(token, "playing_now",
                                 _listen(title, artist, album))
                elif kind == "scrobble":
                    if self._submit(token, "single",
                                    _listen(title, artist, album, time.time())):
                        self.scrobbled.emit(title, artist)

    def _submit(self, token, listen_type, listen):
        try:
            _post(_API, token, {"listen_type": listen_type, "payload": [listen]})
            return True
        except Exception:
            return False

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
lyrics_backend.py
-----------------
Time-synced lyrics from LRCLIB (https://lrclib.net), a free, keyless lyrics API.

SMTC carries no lyrics, so we look them up by title/artist (+ album/duration for
an exact match) and parse the LRC timestamps. The widget then highlights the
active line using the playback clock it already interpolates.

All network calls run on a background thread and report back via a Qt signal, so
the UI never blocks. Uses ONLY the Python standard library (urllib). Nothing is
sent anywhere except the track's title/artist/album/duration to LRCLIB.
"""

import json
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import config

_GET = "https://lrclib.net/api/get"
_SEARCH = "https://lrclib.net/api/search"
_UA = (f"TidalNowPlaying/{getattr(config, 'APP_VERSION', '0')} "
       f"(+https://github.com/gullyous/Tidal-Widget)")
_CTX = ssl.create_default_context()
_TIMEOUT = 8

_TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_lrc(text):
    """Parse LRC text into a sorted list of (seconds, line). Blank lines kept
    (they create natural gaps); pure-metadata lines are skipped."""
    out = []
    for raw in (text or "").splitlines():
        tags = _TS.findall(raw)
        if not tags:
            continue
        body = _TS.sub("", raw).strip()
        for mm, ss in tags:
            out.append((int(mm) * 60 + float(ss), body))
    out.sort(key=lambda x: x[0])
    return out


class LyricsFetcher(QObject):
    # title, artist, lines  (lines = [(seconds, text), ...]; [] means none found)
    lyrics_ready = Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}

    def fetch(self, title, artist, album="", duration=0):
        if not title:
            return
        threading.Thread(target=self._worker,
                         args=(title, artist, album, duration), daemon=True).start()

    def _worker(self, title, artist, album, duration):
        key = (title, artist)
        if key in self._cache:
            self.lyrics_ready.emit(title, artist, self._cache[key])
            return
        lines = []
        try:
            lines = self._lookup(title, artist, album, duration)
        except Exception:
            lines = []
        if len(self._cache) >= 64:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = lines
        self.lyrics_ready.emit(title, artist, lines)

    def _lookup(self, title, artist, album, duration):
        data = None
        # 1) exact get (best match) when we have enough metadata
        params = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(round(duration))
        try:
            data = _get_json(_GET + "?" + urllib.parse.urlencode(params))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            data = None
        except (urllib.error.URLError, socket.timeout):
            return []
        # 2) fallback: search by title/artist, take the first synced hit
        if not data or not data.get("syncedLyrics"):
            try:
                res = _get_json(_SEARCH + "?" + urllib.parse.urlencode(
                    {"track_name": title, "artist_name": artist}))
            except Exception:
                res = None
            for item in (res or []):
                if isinstance(item, dict) and item.get("syncedLyrics"):
                    data = item
                    break
        if data and data.get("syncedLyrics"):
            return parse_lrc(data["syncedLyrics"])
        return []

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
lyrics_backend.py
-----------------
Time-synced lyrics from LRCLIB (https://lrclib.net), a free, keyless lyrics API.

SMTC carries no lyrics, so we look them up by title/artist (+ album/duration for
an exact match) and parse the LRC timestamps. The widget then highlights the
active line using the playback clock it already interpolates. When a track has
no time-synced lyrics, we fall back to plain (unsynced) lyrics so it still shows
something the user can scroll through.

All network calls run on a background thread and report back via a Qt signal, so
the UI never blocks. Uses ONLY the Python standard library (urllib). Nothing is
sent anywhere except the track's title/artist/album/duration to LRCLIB.
"""

import json
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import config

_GET = "https://lrclib.net/api/get"
_SEARCH = "https://lrclib.net/api/search"
_UA = (f"Dustcover/{getattr(config, 'APP_VERSION', '0')} "
       f"(+https://github.com/gullyous/dustcover)")
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


def parse_plain(text):
    """Parse plain (unsynced) lyrics into a list of (None, line). The None time
    marks the block as unsynced so the view shows it statically. Leading/trailing
    blank lines are trimmed; returns [] if there is no real content."""
    lines = [(None, raw.strip()) for raw in (text or "").splitlines()]
    while lines and not lines[0][1]:
        lines.pop(0)
    while lines and not lines[-1][1]:
        lines.pop()
    if not any(txt for _t, txt in lines):
        return []
    return lines


_MISSING = object()   # cache sentinel: distinguishes a miss from a cached []


class LyricsFetcher(QObject):
    # title, artist, lines.  lines = [(seconds, text), ...] for synced lyrics,
    # [(None, text), ...] for plain (unsynced) lyrics, or [] when none were found.
    lyrics_ready = Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}
        self._cache_lock = threading.Lock()   # workers run on background threads

    def fetch(self, title, artist, album="", duration=0):
        if not title:
            return
        threading.Thread(target=self._worker,
                         args=(title, artist, album, duration), daemon=True).start()

    def _worker(self, title, artist, album, duration):
        # Key on album + rounded duration too: two recordings that share a
        # title/artist (studio vs live, a remaster, a cover) have different
        # lyrics and timings, so keying on (title, artist) alone served the
        # wrong ones. pop+reinsert keeps the cache least-recently-used.
        key = (title, artist, album, int(round(duration or 0)))
        with self._cache_lock:
            cached = self._cache.pop(key, _MISSING)
            if cached is not _MISSING:
                self._cache[key] = cached      # touch: most-recently-used
        if cached is not _MISSING:
            self.lyrics_ready.emit(title, artist, cached)
            return
        try:
            lines = self._lookup(title, artist, album, duration)
        except Exception:
            # Transient fetch failure (offline, timeout, HTTP 5xx): report "none"
            # for now but do NOT cache it, so returning to this track retries the
            # lookup instead of being stuck lyric-less until the app restarts.
            self.lyrics_ready.emit(title, artist, [])
            return
        # A genuine result (synced, plain, or truly none): cache and report it.
        with self._cache_lock:
            if len(self._cache) >= 64:
                self._cache.pop(next(iter(self._cache)), None)   # evict least-recent
            self._cache[key] = lines
        self.lyrics_ready.emit(title, artist, lines)

    def _lookup(self, title, artist, album, duration):
        # Network errors (URLError/timeout) and unexpected HTTP errors propagate
        # to _worker, which treats them as a transient failure and does NOT cache
        # the miss. Only a 404 ("no match") counts as a genuine absence here.
        # 1) exact get (best match) when we have enough metadata
        exact = None
        params = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(round(duration))
        try:
            exact = _get_json(_GET + "?" + urllib.parse.urlencode(params))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            exact = None
        if exact and exact.get("syncedLyrics"):
            synced = parse_lrc(exact["syncedLyrics"])
            if synced:  # a present-but-timeless LRC parses to []; fall through then
                return synced

        # 2) fallback: search by title/artist for a usable time-synced hit. Keep
        #    the first plain (unsynced) hit as a backup so tracks that only have
        #    plain lyrics still show something.
        search_plain = None
        try:
            res = _get_json(_SEARCH + "?" + urllib.parse.urlencode(
                {"track_name": title, "artist_name": artist}))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            res = None
        for item in (res or []):
            if not isinstance(item, dict):
                continue
            if item.get("syncedLyrics"):
                synced = parse_lrc(item["syncedLyrics"])
                if synced:
                    return synced
            if search_plain is None and item.get("plainLyrics"):
                search_plain = item["plainLyrics"]

        # 3) plain fallback: prefer the exact (higher-confidence) match's plain
        #    lyrics over a looser search hit's, so unsynced tracks still show
        #    lyrics and from the best-matched record when possible.
        for text in ((exact.get("plainLyrics") if exact else None), search_plain):
            if text:
                plain = parse_plain(text)
                if plain:
                    return plain
        return []

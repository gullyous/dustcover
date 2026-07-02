# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
tidal_likes.py
--------------
Optional TIDAL "favorite / add to my collection" support for the heart button.

SMTC (the data source for now-playing) has no favorite command, so liking a
track is a write to the user's TIDAL account through the unofficial `tidalapi`.
Auth is a one-time OAuth device login; the token is stored in
%APPDATA%\\TidalWidget\\tidal_token.json and refreshed automatically.

All network calls run on background threads and report back via Qt signals, so
the UI never blocks. If `tidalapi` is not installed the object stays inert
(available() == False) and the heart simply reports that signing in is needed.

Matching: SMTC gives a title/artist string, not a TIDAL track id, so we search
the catalog and accept a result only when title AND artist match. A wrong match
is reported as "nomatch" rather than guessed.
"""

import json
import os
import re
import ssl
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

try:
    import tidalapi
except Exception:  # pragma: no cover - tidalapi optional
    tidalapi = None

_MISSING = object()   # cache sentinel: distinguishes a miss from a cached None


def _token_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "TidalWidget")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "tidal_token.json")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _quality_label(t):
    """Human label for the best quality a TIDAL track is available in."""
    if getattr(t, "is_hi_res_lossless", False):
        base = "MAX"
    elif getattr(t, "is_lossless", False):
        base = "Lossless"
    else:
        aq = (getattr(t, "audio_quality", "") or "").upper()
        base = {"HIGH": "High", "LOW": "Low"}.get(aq, aq.title() or "Standard")
    if getattr(t, "is_dolby_atmos", False):
        base += "  ·  Atmos"
    return base


class TidalLiker(QObject):
    """Favorites bridge. Signals are emitted from worker threads; Qt delivers
    them to the UI thread via queued connections."""

    login_link = Signal(str)              # device-login URL to open for the user
    login_state = Signal(bool, str)       # (logged_in, human message)
    like_result = Signal(bool, str, str)  # (success, action, track label)
    #   action in {"added", "removed", "nomatch", "error", "login"}
    quality_result = Signal(str, str, str)  # (title, artist, quality label or "")
    favorite_state = Signal(str, str, bool)  # (title, artist, is in collection?)
    radio_result = Signal(str, str, str)     # (title, artist, mix id or "")
    cover_ready = Signal(str, str, bytes)    # (title, artist, full-res cover bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None
        self._lock = threading.Lock()
        self._qcache = {}
        self._track_cache = {}    # (title, artist) -> resolved Track or None
        self._cover_cache = {}    # album id str -> full-res cover bytes
        self._cache_lock = threading.Lock()   # guards _track_cache/_cover_cache
        self._fav_ids = None      # set of favorited track-id strings (lazy, bulk)
        self._fav_complete = True  # False if the bulk fav fetch hit its page cap
        self._user_fav = {}       # id str -> bool: this session's own like/unlike
        self._fav_lock = threading.Lock()
        if tidalapi is not None:
            self._try_load_token()

    # ---- state -------------------------------------------------------------
    def available(self):
        return tidalapi is not None

    def logged_in(self):
        try:
            return self._session is not None and self._session.check_login()
        except Exception:
            return False

    def signed_in(self):
        """Cheap, non-network check: whether a TIDAL session is loaded."""
        return self._session is not None

    # ---- auth --------------------------------------------------------------
    def _try_load_token(self):
        try:
            with open(_token_path()) as f:
                tok = json.load(f)
            s = tidalapi.Session()
            s.load_oauth_session(tok["token_type"], tok["access_token"],
                                 tok.get("refresh_token"))
            if s.check_login():
                self._session = s
                self._save_token(s)   # persist the access token if it was refreshed
        except Exception:
            self._session = None

    def start_login(self):
        if tidalapi is None:
            self.login_state.emit(False, "tidalapi is not installed")
            return
        threading.Thread(target=self._login_worker, daemon=True).start()

    def _login_worker(self):
        try:
            s = tidalapi.Session()
            login, future = s.login_oauth()
            self.login_link.emit("https://" + login.verification_uri_complete)
            future.result()  # blocks until the user authorizes or the code expires
            if s.check_login():
                self._session = s
                self._save_token(s)
                self._invalidate_caches()   # this is a fresh session's collection
                self.login_state.emit(True, "Signed in to TIDAL")
            else:
                self.login_state.emit(False, "TIDAL sign-in was not completed")
        except Exception:
            self.login_state.emit(False, "TIDAL sign-in failed or timed out")

    def _save_token(self, s):
        try:
            with open(_token_path(), "w") as f:
                json.dump({
                    "token_type": s.token_type,
                    "access_token": s.access_token,
                    "refresh_token": s.refresh_token,
                    "expiry_time": str(s.expiry_time),
                }, f)
        except Exception:
            pass

    # ---- like / unlike -----------------------------------------------------
    def toggle(self, title, artist, album="", currently_liked=False):
        """Add the track to favorites, or remove it if currently_liked."""
        if not title:
            return
        threading.Thread(
            target=self._toggle_worker,
            args=(title, artist, album, currently_liked), daemon=True).start()

    def _toggle_worker(self, title, artist, album, currently_liked):
        if self._session is None:
            self.like_result.emit(False, "login", "")
            return
        label = f"{title}  ·  {artist}"
        try:
            tid = self._match(title, artist)   # network search, runs lock-free
            if tid is None:
                self.like_result.emit(False, "nomatch", label)
                return
            with self._lock:                   # serialize only the write
                if currently_liked:
                    self._session.user.favorites.remove_track(tid)
                else:
                    self._session.user.favorites.add_track(tid)
            # This session's own action is authoritative for that track, even if
            # the bulk fav set is still loading, stale, or truncated.
            self._user_fav[str(tid)] = not currently_liked
            if self._fav_ids is not None:      # keep the cached set in sync too
                if currently_liked:
                    self._fav_ids.discard(str(tid))
                else:
                    self._fav_ids.add(str(tid))
            self.like_result.emit(True, "removed" if currently_liked else "added", label)
            self._save_token(self._session)    # token may have refreshed
        except Exception:
            self.like_result.emit(False, "error", label)

    def _match_track(self, title, artist):
        # Cache the catalog search so the quality badge, the heart state, and a
        # like all reuse one network lookup per (title, artist) instead of three.
        # The lock guards the dict from concurrent quality/favorite/toggle workers.
        key = (title, artist)
        with self._cache_lock:
            cached = self._track_cache.pop(key, _MISSING)
            if cached is not _MISSING:
                self._track_cache[key] = cached      # touch: most-recently-used
        if cached is not _MISSING:
            return cached
        t = self._search_track(title, artist)        # network: outside the lock
        with self._cache_lock:
            if len(self._track_cache) >= 256:
                self._track_cache.pop(next(iter(self._track_cache)), None)
            self._track_cache[key] = t
        return t

    def _search_track(self, title, artist):
        nt, na = _norm(title), _norm(artist)
        if not nt:
            return None
        res = self._session.search(f"{title} {artist}", models=[tidalapi.media.Track])
        tracks = res.get("tracks") if isinstance(res, dict) else []
        for t in (tracks or [])[:10]:
            ct = _norm(t.name)
            cands = [_norm(a.name) for a in (t.artists or [])] or [_norm(t.artist.name)]
            title_ok = ct == nt or nt in ct or ct in nt
            artist_ok = any(na == a or na in a or a in na for a in cands if a)
            if title_ok and artist_ok:
                return t
        return None

    def _match(self, title, artist):
        t = self._match_track(title, artist)
        return t.id if t is not None else None

    def _invalidate_caches(self):
        """Drop per-session caches (call on a login transition)."""
        self._fav_ids = None
        self._fav_complete = True
        self._user_fav = {}
        with self._cache_lock:
            self._track_cache.clear()
            self._cover_cache.clear()
        self._qcache.clear()

    # ---- favorite state (is the current track already in the collection?) ---
    def favorite_state_request(self, title, artist):
        if not title:
            return
        threading.Thread(target=self._favorite_worker,
                         args=(title, artist), daemon=True).start()

    def _favorite_worker(self, title, artist):
        if self._session is None:
            self.favorite_state.emit(title, artist, False)
            return
        try:
            ids = self._fav_ids
            if ids is None:
                ids = self._load_fav_ids()
            t = self._match_track(title, artist)   # reuses the cached catalog search
            if t is None:
                is_fav = False
            else:
                tid = str(t.id)
                if tid in self._user_fav:          # our own toggle wins, always
                    is_fav = self._user_fav[tid]
                elif tid in ids:
                    is_fav = True
                elif not self._fav_complete:
                    return   # bulk set truncated: unknown, don't assert "not liked"
                else:
                    is_fav = False
        except Exception:
            return   # a tidalapi hiccup leaves the heart as-is; never regress
        self.favorite_state.emit(title, artist, bool(is_fav))

    def _load_fav_ids(self):
        """Fetch the user's favorite track ids once (paged) into a set.

        tidalapi has no cheap 'is this favorited?' check, so we page the whole
        favorites list a single time and keep the id set in memory (updated on
        every like/unlike). Bounded so a huge collection can't page forever.
        """
        with self._fav_lock:
            if self._fav_ids is not None:
                return self._fav_ids
            ids = set()
            complete = True
            favs = self._session.user.favorites
            page, offset, max_pages = 50, 0, 200
            for _ in range(max_pages):
                chunk = favs.tracks(limit=page, offset=offset)
                if not chunk:
                    break
                for t in chunk:
                    try:
                        ids.add(str(t.id))
                    except Exception:
                        pass
                if len(chunk) < page:
                    break
                offset += page
            else:
                complete = False   # hit the page cap without reaching the end
            self._fav_complete = complete
            self._fav_ids = ids
            return ids

    # ---- track radio ("more like this") --------------------------------------
    def radio(self, title, artist):
        if not title:
            return
        threading.Thread(target=self._radio_worker,
                         args=(title, artist), daemon=True).start()

    def _radio_worker(self, title, artist):
        mix_id = ""
        if self._session is not None:
            try:
                t = self._match_track(title, artist)
                if t is not None:
                    mix = t.get_radio_mix()
                    mix_id = str(getattr(mix, "id", "") or "")
            except Exception:
                mix_id = ""   # no mix for this track / transient API failure
        self.radio_result.emit(title, artist, mix_id)

    # ---- full-res cover art ---------------------------------------------------
    def fetch_cover(self, title, artist):
        if not title:
            return
        threading.Thread(target=self._cover_worker,
                         args=(title, artist), daemon=True).start()

    def _cover_worker(self, title, artist):
        # SMTC only hands the widget a small thumbnail; TIDAL hosts the same
        # cover up to 1280px. Fetch it once per album and let the widget swap
        # it in. Silent no-op on any failure (the thumbnail stays).
        if self._session is None:
            return
        try:
            t = self._match_track(title, artist)
            album = getattr(t, "album", None) if t is not None else None
            if album is None:
                return
            if not getattr(album, "cover", None):
                album = self._session.album(album.id)   # stub without cover UUID
            key = str(getattr(album, "id", "") or "")
            with self._cache_lock:
                data = self._cover_cache.get(key)
            if data is None:
                url = album.image(1280)
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(url, timeout=15, context=ctx) as r:
                    data = r.read(8 * 1024 * 1024)
                if not data:
                    return
                with self._cache_lock:
                    if len(self._cover_cache) >= 8:
                        self._cover_cache.pop(next(iter(self._cover_cache)), None)
                    self._cover_cache[key] = data
            self.cover_ready.emit(title, artist, data)
        except Exception:
            return

    # ---- quality (best quality the track is available in) ------------------
    def quality(self, title, artist):
        if not title:
            return
        threading.Thread(target=self._quality_worker,
                         args=(title, artist), daemon=True).start()

    def _quality_worker(self, title, artist):
        if self._session is None:
            self.quality_result.emit(title, artist, "")
            return
        key = (title, artist)
        if key in self._qcache:
            self.quality_result.emit(title, artist, self._qcache[key])
            return
        label = ""
        try:
            t = self._match_track(title, artist)   # network search, runs lock-free
            if t is not None:
                label = _quality_label(t)
        except Exception:
            label = ""
        if len(self._qcache) >= 256:        # bound the cache (drop oldest)
            self._qcache.pop(next(iter(self._qcache)))
        self._qcache[key] = label
        self.quality_result.emit(title, artist, label)

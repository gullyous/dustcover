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
import threading

from PySide6.QtCore import QObject, Signal

try:
    import tidalapi
except Exception:  # pragma: no cover - tidalapi optional
    tidalapi = None


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None
        self._lock = threading.Lock()
        self._qcache = {}
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
            self.like_result.emit(True, "removed" if currently_liked else "added", label)
            self._save_token(self._session)    # token may have refreshed
        except Exception:
            self.like_result.emit(False, "error", label)

    def _match_track(self, title, artist):
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

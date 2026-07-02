# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
widget.py  -- the TIDAL now-playing widget UI.
==============================================
Polished "dark glass" desktop card that shows what's playing on TIDAL with
transport controls and a compact <-> expanded toggle.

Contract main.py depends on (kept stable):
  signals:  playpause_clicked, next_clicked, prev_clicked, quit_requested
  slot:     on_update(info: dict)   # info keys below

info dict from media_backend._snapshot():
  available (bool), playing (bool), title, artist, album, source (str),
  position (float secs), duration (float secs),
  art (bytes|None), art_changed (bool)

Design:
  * Frameless, translucent, always-on-top draggable card with a drop shadow.
  * Album-art ambience: a blurred, darkened copy of the cover is painted as the
    card background (cheap blur = a tiny downscaled cover upscaled smoothly),
    clipped to the rounded rect, with a dark gradient overlay for readability.
  * COMPACT (small cover | text | transport) <-> EXPANDED (big cover, text,
    progress, transport). Toggle via the corner chevron, double-click, or the
    right-click menu. The window resizes and stays anchored in its corner.
  * Non-seekable progress line in expanded mode (config.ACCENT fill), smoothly
    interpolated between backend polls.
"""

import os
import re
import subprocess
import time
import webbrowser

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPainterPath, QPen, QLinearGradient,
    QAction, QGuiApplication, QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame, QStackedWidget, QSizePolicy, QSlider,
    QHBoxLayout, QVBoxLayout, QMenu, QSystemTrayIcon, QGraphicsDropShadowEffect,
    QFileDialog,
)

import config
import icons
import settings

# --- geometry --------------------------------------------------------------
MARGIN = 18          # transparent padding so the drop shadow has room
RADIUS = 18          # card corner radius
COMPACT_CARD = (360, 104)
EXPANDED_CARD = (360, 404)
TOGGLE_D = 22        # corner expand/collapse button diameter
CORNER_GAP = 6       # visible gap from the screen edges when locked into a corner

# --- palette ---------------------------------------------------------------
INK = "#ffffff"
SUBTLE = "#a9a9b4"
ON_ACCENT = "#06222a"   # icon color that reads on the cyan accent button
LIKE_COLOR = "#ff4d6d"  # filled-heart color when a track is liked

# Explains why a TIDAL sign-in exists at all: the now-playing display reads from
# Windows (no account needed); sign-in only powers TIDAL-account actions.
SIGNIN_HINT = ("Sign in to like tracks and show quality info from your TIDAL "
               "account. The now-playing display works without signing in.")

# TIDAL's web player. Opened as a standalone browser "app window" so its DRM
# (Widevine) works; a browser-played session also shows up in this widget via
# the Windows media controls.
WEB_PLAYER_URL = "https://listen.tidal.com"


def _fmt_time(secs: float) -> str:
    if not secs or secs < 0:
        return "--:--"
    secs = int(secs)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _rounded_cover(src: QPixmap, size: int, radius: int) -> QPixmap:
    """Center-crop `src` to a square `size` with rounded corners."""
    target = QPixmap(size, size)
    target.fill(Qt.transparent)
    p = QPainter(target)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    p.drawPixmap(0, 0, scaled, x, y, size, size)
    p.end()
    return target


def _dim_pixmap(pm: QPixmap) -> QPixmap:
    """Return a darkened copy of a (rounded) cover, to read 'paused' at a glance.
    SourceAtop keeps the transparent rounded corners transparent."""
    out = QPixmap(pm)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
    p.fillRect(out.rect(), QColor(0, 0, 0, 120))
    p.end()
    return out


class ElidedLabel(QLabel):
    """A QLabel that elides its text with '...' to whatever width it's given."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setFullText(self, text: str):
        self._full = text or ""
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(0, self.width())))


class ProgressLine(QWidget):
    """Progress bar that can be clicked or dragged to seek (when seekable)."""

    seek_requested = Signal(float)  # fraction 0..1
    BAR_H = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self._seekable = False
        self._dragging = False
        self.accent = config.ACCENT
        self.accent2 = None   # optional second color: duotone gradient fill
        self.setFixedHeight(14)

    def set_seekable(self, ok: bool):
        if ok != self._seekable:
            self._seekable = ok
            self.setCursor(Qt.PointingHandCursor if ok else Qt.ArrowCursor)
            self.update()

    def set_fraction(self, frac: float):
        if self._dragging:
            return  # don't fight the user's scrub
        frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
        if abs(frac - self._frac) > 0.0005:
            self._frac = frac
            self.update()

    def _frac_at(self, x):
        return min(1.0, max(0.0, x / max(1, self.width())))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        cy = self.height() / 2
        track = QRectF(0, cy - self.BAR_H / 2, w, self.BAR_H)
        rad = self.BAR_H / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(track, rad, rad)
        fx = w * self._frac
        if self._frac > 0:
            fill = QRectF(track)
            fill.setWidth(max(self.BAR_H, fx))
            if self.accent2:
                # duotone: gradient spans the FULL track, so the visible fill
                # reveals more of the second color as the song progresses
                grad = QLinearGradient(track.topLeft(), track.topRight())
                grad.setColorAt(0.0, QColor(self.accent))
                grad.setColorAt(1.0, QColor(self.accent2))
                p.setBrush(grad)
            else:
                p.setBrush(QColor(self.accent))
            p.drawRoundedRect(fill, rad, rad)
        if self._seekable:
            kr = 5
            p.setBrush(QColor(self.accent))
            p.drawEllipse(QPointF(min(max(kr, fx), w - kr), cy), kr, kr)
        p.end()

    def mousePressEvent(self, e):
        if self._seekable and e.button() == Qt.LeftButton:
            self._dragging = True
            self._frac = self._frac_at(e.position().x())
            self.update()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._frac = self._frac_at(e.position().x())
            self.update()
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._dragging and e.button() == Qt.LeftButton:
            self._dragging = False
            self.seek_requested.emit(self._frac)
            e.accept()


class LyricsView(QWidget):
    """Synced (karaoke) or plain lyrics.

    Synced lyrics: the active line is centred and accented, neighbours fade with
    distance; click a line to seek to it, scroll to nudge the sync offset when a
    track's timings drift, and middle-click to reset that nudge. Plain (unsynced)
    lyrics have no timestamps, so they show as a static block you scroll
    through."""

    seek_requested = Signal(float)   # absolute seconds
    offset_changed = Signal(float)   # sync offset (s); the widget persists it
    LINE_H = 34
    STEP = 0.1        # seconds per scroll notch when nudging the sync offset
    MAX_OFFSET = 5.0  # clamp for the sync nudge

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = []      # [(seconds_or_None, text)]; None time = plain line
        self._synced = False  # True once the lines carry timestamps (karaoke)
        self._active = -1
        self._msg = ""
        self._scroll = 0.0    # px scroll position for plain (unsynced) lyrics
        self._last_sec = None  # last playback position seen (re-highlight on nudge)
        self._last_mono = None  # monotonic stamp of _last_sec, for extrapolation
        self._advancing = False  # playback running -> extrapolate + animate wipe
        self._offset = float(getattr(config, "LYRICS_OFFSET", 0.0) or 0.0)
        self.accent = config.ACCENT
        # smooth karaoke wipe: repaint ~20fps, but only while synced lyrics are
        # visible AND playing (same spirit as the widget's gated progress timer)
        self._anim = QTimer(self)
        self._anim.setInterval(50)
        self._anim.timeout.connect(self.update)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip("Scroll to nudge lyric sync • middle-click to reset")

    def set_lines(self, lines):
        self._lines = list(lines or [])
        self._synced = any(t is not None for t, _txt in self._lines)
        self._active = -1
        self._scroll = 0.0
        self._msg = "" if self._lines else "No lyrics for this track"
        self.setCursor(Qt.PointingHandCursor if self._synced else Qt.ArrowCursor)
        self._update_anim()
        self.update()

    def set_loading(self):
        self._lines = []
        self._synced = False
        self._active = -1
        self._msg = "Finding lyrics..."
        self._update_anim()
        self.update()

    def has_lyrics(self):
        return bool(self._lines)

    def set_playing(self, playing):
        """Playback state, so the wipe extrapolates between 200ms ticks."""
        playing = bool(playing)
        if playing == self._advancing:
            return
        # re-anchor so a pause doesn't freeze mid-extrapolation drift
        self._last_sec = self._now_eff() - self._offset
        self._last_mono = time.monotonic()
        self._advancing = playing
        self._update_anim()
        self.update()

    def _update_anim(self):
        if self._synced and self._advancing and self.isVisible() and self._lines:
            if not self._anim.isActive():
                self._anim.start()
        elif self._anim.isActive():
            self._anim.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_anim()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_anim()

    def _now_eff(self):
        """Current effective lyric time: last known position, extrapolated while
        playing, plus the user's sync offset."""
        base = self._last_sec if self._last_sec is not None else 0.0
        if self._advancing and self._last_mono is not None:
            base += time.monotonic() - self._last_mono
        return base + self._offset

    def set_position(self, sec):
        self._last_sec = sec
        self._last_mono = time.monotonic()
        if not self._synced:
            return
        eff = sec + self._offset
        a = -1
        for i, (t, _txt) in enumerate(self._lines):
            if t is not None and t <= eff + 0.15:
                a = i
            else:
                break
        if a != self._active:
            self._active = a
            self.update()

    def _max_scroll(self):
        content = len(self._lines) * self.LINE_H
        return max(0.0, content - self.height() + self.LINE_H)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._synced:  # keep plain-lyrics scroll in range if the view grows
            self._scroll = min(self._scroll, self._max_scroll())

    def wheelEvent(self, e):
        if not self._lines:
            return
        dy = e.angleDelta().y()
        if dy == 0:
            return
        if self._synced:
            step = self.STEP if dy > 0 else -self.STEP
            self._offset = max(-self.MAX_OFFSET,
                               min(self.MAX_OFFSET, round(self._offset + step, 2)))
            self.offset_changed.emit(self._offset)
            if self._last_sec is not None:
                self.set_position(self._last_sec)
            self.update()
        else:
            self._scroll = max(0.0, min(self._max_scroll(),
                                        self._scroll - (dy / 120.0) * self.LINE_H * 2))
            self.update()
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            if self._synced and self._offset:
                self._offset = 0.0
                self.offset_changed.emit(0.0)
                if self._last_sec is not None:
                    self.set_position(self._last_sec)
                self.update()
            return
        if e.button() != Qt.LeftButton or not self._synced:
            return
        act = self._active if self._active >= 0 else 0
        idx = act + round((e.position().y() - self.height() / 2) / self.LINE_H)
        if 0 <= idx < len(self._lines):
            t = self._lines[idx][0]
            if t is not None:
                self.seek_requested.emit(max(0.0, t - self._offset))

    def contextMenuEvent(self, e):
        if not self._lines:
            e.ignore()   # let the window's management menu show through
            return
        # Snapshot: menu.exec runs a nested event loop, so a track change can
        # mutate _lines/_active while the menu is open.
        lines = list(self._lines)
        active = self._active
        menu = QMenu(self)
        act_all = menu.addAction("Copy all lyrics")
        act_line = None
        if self._synced and 0 <= active < len(lines):
            act_line = menu.addAction("Copy current line")
        chosen = menu.exec(e.globalPos())
        if chosen is None:
            return
        cb = QGuiApplication.clipboard()
        if chosen is act_all:
            cb.setText("\n".join(txt for _t, txt in lines))
        elif act_line is not None and chosen is act_line and 0 <= active < len(lines):
            cb.setText(lines[active][1])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if not self._lines:
            p.setPen(QColor(SUBTLE))
            f = p.font(); f.setPointSize(10); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._msg)
            p.end()
            return
        if self._synced:
            self._paint_synced(p, w, h)
        else:
            self._paint_plain(p, w, h)
        if self._synced:
            f = p.font(); f.setPointSize(9); f.setBold(False); p.setFont(f)
            box = QRectF(0, 4, w - 8, 16)
            if abs(self._offset) >= 0.05:
                p.setPen(QColor(self.accent))
                p.drawText(box, Qt.AlignRight | Qt.AlignTop, f"sync {self._offset:+.1f}s")
            else:
                # dim, always-present signifier so the scroll-to-nudge gesture
                # is discoverable; the offset badge replaces it once nudged.
                hint = QColor(SUBTLE); hint.setAlpha(120); p.setPen(hint)
                p.drawText(box, Qt.AlignRight | Qt.AlignTop, "scroll to sync")
        p.end()

    WIPE_MAX = 8.0   # cap the wipe duration so instrumental gaps hold at full
    DOTS_LEAD = 5.0  # countdown dots appear this many seconds before a line
    DOTS_GAP = 6.0   # ...but only for gaps at least this long

    def _wipe_frac(self, eff):
        """0..1 fill of the active line, interpolated to the next line's time."""
        act = self._active
        if act < 0:
            return 0.0
        t0 = self._lines[act][0]
        t1 = None
        if act + 1 < len(self._lines):
            t1 = self._lines[act + 1][0]
        dur = (t1 - t0) if t1 is not None else 5.0
        dur = max(0.5, min(dur, self.WIPE_MAX))
        frac = (eff - t0) / dur
        return 0.0 if frac < 0 else 1.0 if frac > 1 else frac

    def _paint_synced(self, p, w, h):
        cy = h / 2
        eff = self._now_eff()
        act = self._active if self._active >= 0 else 0
        for i, (_t, txt) in enumerate(self._lines):
            y = cy + (i - act) * self.LINE_H
            if y < -self.LINE_H or y > h + self.LINE_H:
                continue
            f = p.font()
            if i == self._active:
                f.setPointSize(15)
                f.setBold(True)
            else:
                col = QColor(255, 255, 255)
                col.setAlpha(max(110, 225 - abs(i - act) * 32))
                p.setPen(col)
                f.setPointSize(12)
                f.setBold(False)
            p.setFont(f)
            fm = QFontMetrics(f)
            line = fm.elidedText(txt, Qt.ElideRight, w - 24)
            rect = QRectF(12, y - self.LINE_H / 2, w - 24, self.LINE_H)
            if i != self._active:
                p.drawText(rect, Qt.AlignCenter, line)
                continue
            # active line: white base, then an accent "karaoke wipe" clipped to
            # the sung fraction (interpolated between this and the next line)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(rect, Qt.AlignCenter, line)
            frac = self._wipe_frac(eff)
            if frac > 0:
                textw = fm.horizontalAdvance(line)
                left = 12 + (w - 24 - textw) / 2
                p.save()
                p.setClipRect(QRectF(left, rect.top(), textw * frac, self.LINE_H))
                p.setPen(QColor(self.accent))
                p.drawText(rect, Qt.AlignCenter, line)
                p.restore()
        self._paint_countdown(p, w, cy, eff)

    def _paint_countdown(self, p, w, cy, eff):
        """Three draining dots during long instrumental gaps, so you know when
        the next line lands (visible only in the last DOTS_LEAD seconds)."""
        act = self._active
        nxt = act + 1 if act >= 0 else 0
        if nxt >= len(self._lines):
            return
        # only during a real gap: intro (no active line), a blank timed line,
        # or a long stretch between the active line and the next one
        gap_start = self._lines[act][0] if act >= 0 else 0.0
        t_next = self._lines[nxt][0]
        if t_next is None or t_next - gap_start < self.DOTS_GAP:
            return
        if act >= 0 and self._lines[act][1] and t_next - gap_start < 12.0:
            return   # a sung line followed by a shortish gap: no dots
        remaining = t_next - eff
        if not (0.0 < remaining <= self.DOTS_LEAD):
            return
        lit = min(3, max(1, int(remaining / self.DOTS_LEAD * 3) + 1))
        r = 4.0
        gap = 18.0
        x0 = w / 2 - gap
        y = cy - self.LINE_H * 1.6
        p.setPen(Qt.NoPen)
        for i in range(3):
            c = QColor(self.accent) if i < lit else QColor(255, 255, 255, 60)
            p.setBrush(c)
            p.drawEllipse(QPointF(x0 + i * gap, y), r, r)

    def _paint_plain(self, p, w, h):
        f = p.font(); f.setPointSize(12); f.setBold(False); p.setFont(f)
        p.setPen(QColor(235, 235, 240))
        fm = QFontMetrics(f)
        top = 12 - self._scroll
        for i, (_t, txt) in enumerate(self._lines):
            y = top + i * self.LINE_H
            if y < -self.LINE_H or y > h + self.LINE_H:
                continue
            line = fm.elidedText(txt, Qt.ElideRight, w - 24)
            p.drawText(QRectF(12, y, w - 24, self.LINE_H),
                       Qt.AlignCenter, line)


class Card(QFrame):
    """The visible card. Paints the ambient album-art background itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ambient = None  # tiny pixmap, upscaled smoothly for a cheap blur
        self._layer = None    # cached opaque composite (base + ambient + overlay)
        self._layer_key = None

    def set_ambient(self, src: QPixmap | None):
        if src is None:
            self._ambient = None
        else:
            self._ambient = src.scaled(
                36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self._layer = None    # invalidate the cached composite
        self.update()

    def _build_layer(self, rect, dpr):
        # The OPAQUE background composite (base + ambient + dark overlay). Built
        # once and cached; blitting it at BACKGROUND_OPACITY gives the panel a
        # uniform alpha (the desktop shows through evenly).
        layer = QPixmap(max(1, round(self.width() * dpr)),
                        max(1, round(self.height() * dpr)))
        layer.setDevicePixelRatio(dpr)
        layer.fill(QColor("#0c0c10"))
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._ambient is not None:
            lp.drawPixmap(rect, self._ambient, QRectF(self._ambient.rect()))
        overlay = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        overlay.setColorAt(0.0, QColor(8, 8, 12, 165))
        overlay.setColorAt(1.0, QColor(8, 8, 12, 220))
        lp.fillRect(rect, overlay)
        lp.end()
        return layer

    def paintEvent(self, _):
        bg = getattr(config, "BACKGROUND_OPACITY", 1.0)
        bg = 0.0 if bg < 0 else 1.0 if bg > 1 else bg

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)

        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), round(dpr * 100), id(self._ambient))
        if self._layer is None or self._layer_key != key:
            self._layer = self._build_layer(rect, dpr)
            self._layer_key = key

        p.setClipPath(path)
        p.setOpacity(bg)
        p.drawPixmap(0, 0, self._layer)
        p.setOpacity(1.0)

        # crisp hairline border (drawn at full opacity for a defined edge)
        p.setClipping(False)
        pen = QPen(QColor(255, 255, 255, 36))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        p.end()


class NowPlayingWidget(QWidget):
    playpause_clicked = Signal()
    next_clicked = Signal()
    prev_clicked = Signal()
    quit_requested = Signal()
    like_clicked = Signal(str, str, str, bool)  # title, artist, album, currently_liked
    signin_requested = Signal()
    seek_clicked = Signal(float)     # absolute position in seconds
    shuffle_clicked = Signal()
    repeat_clicked = Signal()
    settings_requested = Signal()
    quality_requested = Signal(str, str)   # title, artist (request "available in" quality)
    favorite_requested = Signal(str, str)  # title, artist (request real liked state)
    cover_requested = Signal(str, str)     # title, artist (request full-res cover)
    radio_requested = Signal(str, str)     # title, artist (request track-radio mix)
    check_updates_requested = Signal()     # tray "Check for updates..." (loud check)
    volume_changed = Signal(float)         # 0.0-1.0, from the volume slider
    mute_toggled = Signal(bool)            # desired mute state
    lyrics_requested = Signal(str, str, str, float)  # title, artist, album, duration

    def __init__(self, parent=None):
        super().__init__(parent)
        flags = Qt.FramelessWindowHint | Qt.Tool
        if config.ALWAYS_ON_TOP:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        wo = getattr(config, "WINDOW_OPACITY", 1.0)
        self.setWindowOpacity(min(1.0, max(0.2, wo)))

        self._drag = None
        self._moved = False            # did the current drag actually move the window?
        self._cover_src = None         # full-res cover QPixmap (or None)
        self._expanded = bool(config.START_EXPANDED)
        self._corner = "br"            # which screen corner the widget locks to

        # current track + like state (for the heart button)
        self._cur_title = ""
        self._cur_artist = ""
        self._cur_album = ""
        self._liked = False
        self._heart_user_owned = False  # user explicitly toggled the current track
        self._logged_in = False   # signed in to TIDAL (for likes/quality)
        self._muted = False         # current app/system mute (from volume backend)
        self._vol_updating = False  # guard: ignore slider signals during programmatic set
        self._accent_dyn = None     # accent tinted from album art (auto-accent)
        self._accent2_dyn = None    # second sampled color (duotone gradient)
        self._auto_hidden = False   # hidden by game mode, not by the user
        self._cover_hires = False   # full-res TIDAL cover applied for this track
        self._cover_bytes = None    # raw bytes of that cover (for "Save cover art")
        self._tray_icon_state = None  # throttle for the live tray icon
        self._lyrics_mode = False   # lyrics panel showing in the expanded view
        self._shuffle = False
        self._repeat = 0   # 0 none, 1 track, 2 list

        # progress interpolation state
        self._pos = 0.0
        self._dur = 0.0
        self._playing = False
        self._anchor = time.monotonic()

        self._build_ui()
        self._apply_style()
        self._build_tray()

        self._set_mode(self._expanded, anchor=False)
        self._restore_placement()
        self._move_to_corner()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick_progress)
        # started on demand by _update_timer() (only while playing + expanded + visible)

        # Debounce disk writes while the user scrolls the lyrics sync nudge.
        # (_pending_offset is set for real in _on_lyrics_offset before each save.)
        self._pending_offset = 0.0
        self._offset_save = QTimer(self)
        self._offset_save.setSingleShot(True)
        self._offset_save.setInterval(500)
        self._offset_save.timeout.connect(self._save_lyrics_offset)

        self._set_tooltips()

    # ---- UI construction ---------------------------------------------------
    def _build_ui(self):
        self.card = Card(self)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_compact())   # index 0
        self.stack.addWidget(self._build_expanded())  # index 1

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self.stack)

        # single floating expand/collapse button, top-right of the card
        self.toggle_btn = self._round_btn(
            icons.expand_icon(SUBTLE), self.toggle_mode, TOGGLE_D)
        self.toggle_btn.setParent(self.card)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.addWidget(self.card)

        # keep play/pause buttons in sync as one group
        self._play_buttons = [self.c_play, self.e_play]

    def _build_compact(self) -> QWidget:
        page = QWidget()

        self.c_cover = QLabel()
        self.c_cover.setFixedSize(64, 64)

        self.c_title = ElidedLabel("Nothing playing")
        self.c_title.setObjectName("title")
        self.c_artist = ElidedLabel("Open TIDAL and press play")
        self.c_artist.setObjectName("artist")

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        text.addWidget(self.c_title)
        text.addWidget(self.c_artist)
        text.addStretch(1)

        self.c_like = self._round_btn(icons.heart_icon(SUBTLE, filled=False),
                                      self._on_heart, 28)
        self.c_prev = self._round_btn(icons.prev_icon(INK), self.prev_clicked.emit, 30)
        self.c_play = self._round_btn(icons.play_icon(ON_ACCENT),
                                      self.playpause_clicked.emit, 36, accent=True)
        self.c_next = self._round_btn(icons.next_icon(INK), self.next_clicked.emit, 30)

        self.c_lyrics_btn = self._round_btn(icons.lyrics_icon(SUBTLE),
                                            self._open_lyrics, 32)
        self.c_lyrics_btn.hide()   # signifier; shown while a track plays
        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addWidget(self.c_lyrics_btn)
        btns.addWidget(self.c_like)
        btns.addWidget(self.c_prev)
        btns.addWidget(self.c_play)
        btns.addWidget(self.c_next)

        # tiny volume slider under the compact controls, for a quick adjust
        self.c_vol = QSlider(Qt.Horizontal)
        self.c_vol.setRange(0, 100)
        self.c_vol.setFixedHeight(14)
        self.c_vol.setCursor(Qt.PointingHandCursor)
        self.c_vol.valueChanged.connect(self._on_vol_changed)
        self.c_vol.hide()   # shown only when a controllable session is found

        controls = QVBoxLayout()
        controls.setSpacing(4)
        controls.addStretch(1)              # keep the buttons below the corner chevron
        controls.addLayout(btns)
        controls.addWidget(self.c_vol)
        controls.addSpacing(2)

        row = QHBoxLayout(page)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(12)
        row.addWidget(self.c_cover)
        row.addLayout(text, 1)
        row.addLayout(controls)
        return page

    def _build_expanded(self) -> QWidget:
        page = QWidget()

        self.e_cover = QLabel()
        self.e_cover.setFixedSize(150, 150)
        cover_row = QHBoxLayout()
        cover_row.addStretch(1)
        cover_row.addWidget(self.e_cover)
        cover_row.addStretch(1)

        self.e_title = ElidedLabel("Nothing playing")
        self.e_title.setObjectName("title_big")
        self.e_title.setAlignment(Qt.AlignCenter)
        self.e_artist = ElidedLabel("Open TIDAL and press play")
        self.e_artist.setObjectName("artist")
        self.e_artist.setAlignment(Qt.AlignCenter)

        self.e_quality = QLabel("")
        self.e_quality.setObjectName("quality")
        self.e_quality.hide()
        quality_row = QHBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        quality_row.addStretch(1)
        quality_row.addWidget(self.e_quality)
        quality_row.addStretch(1)

        self.progress = ProgressLine()
        self.progress.seek_requested.connect(self._on_seek)
        self.e_pos = QLabel("--:--")
        self.e_pos.setObjectName("time")
        self.e_dur = QLabel("--:--")
        self.e_dur.setObjectName("time")
        self.e_lyrics = LyricsView()
        self.e_lyrics.seek_requested.connect(self.seek_clicked)
        self.e_lyrics.offset_changed.connect(self._on_lyrics_offset)
        self.e_lyrics.hide()
        self.e_lyrics_btn = self._round_btn(icons.lyrics_icon(SUBTLE),
                                            self._toggle_lyrics, 30)
        self.e_lyrics_btn.hide()   # shown when the current track has lyrics

        times = QHBoxLayout()
        times.setContentsMargins(0, 0, 0, 0)
        times.addWidget(self.e_pos)
        times.addStretch(1)
        times.addWidget(self.e_lyrics_btn)
        times.addStretch(1)
        times.addWidget(self.e_dur)

        self.e_like = self._round_btn(icons.heart_icon(SUBTLE, filled=False),
                                      self._on_heart, 34)
        self.e_shuffle = self._round_btn(icons.shuffle_icon(SUBTLE),
                                         self.shuffle_clicked.emit, 30)
        self.e_prev = self._round_btn(icons.prev_icon(INK), self.prev_clicked.emit, 38)
        self.e_play = self._round_btn(icons.play_icon(ON_ACCENT),
                                      self.playpause_clicked.emit, 46, accent=True)
        self.e_next = self._round_btn(icons.next_icon(INK), self.next_clicked.emit, 38)
        self.e_repeat = self._round_btn(icons.repeat_icon(SUBTLE),
                                        self.repeat_clicked.emit, 30)
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addStretch(1)
        controls.addWidget(self.e_like)
        controls.addWidget(self.e_shuffle)
        controls.addWidget(self.e_prev)
        controls.addWidget(self.e_play)
        controls.addWidget(self.e_next)
        controls.addWidget(self.e_repeat)
        controls.addStretch(1)
        # shuffle/repeat appear only when the current source supports them
        self.e_shuffle.hide()
        self.e_repeat.hide()

        # volume (per-app via Core Audio); the row is shown only when a
        # controllable audio session is found (see on_volume_state).
        self.e_mute = self._round_btn(icons.volume_icon(INK), self._on_mute, 28)
        self.e_vol = QSlider(Qt.Horizontal)
        self.e_vol.setRange(0, 100)
        self.e_vol.setFixedHeight(18)
        self.e_vol.setCursor(Qt.PointingHandCursor)
        self.e_vol.valueChanged.connect(self._on_vol_changed)
        self.e_vol_box = QWidget()
        vol_row = QHBoxLayout(self.e_vol_box)
        vol_row.setContentsMargins(6, 0, 6, 0)
        vol_row.setSpacing(8)
        vol_row.addWidget(self.e_mute)
        vol_row.addWidget(self.e_vol, 1)
        self.e_vol_box.hide()

        col = QVBoxLayout(page)
        col.setContentsMargins(20, 20, 20, 18)
        col.setSpacing(8)
        col.addLayout(cover_row)
        col.addSpacing(10)
        col.addWidget(self.e_title)
        col.addWidget(self.e_artist)
        col.addLayout(quality_row)
        col.addWidget(self.e_lyrics, 100)   # fills the cover area when in lyrics mode
        col.addStretch(1)
        col.addWidget(self.progress)
        col.addLayout(times)
        col.addSpacing(2)
        col.addLayout(controls)
        col.addSpacing(6)
        col.addWidget(self.e_vol_box)
        return page

    def _round_btn(self, icon, on_click, diameter, accent=False):
        b = QPushButton()
        b.setIcon(icon)
        b.setIconSize(QSize(int(diameter * 0.5), int(diameter * 0.5)))
        b.setFixedSize(diameter, diameter)
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("accent", accent)
        b.clicked.connect(lambda: on_click())
        return b

    def _set_tooltips(self):
        hk = config.HOTKEYS_ENABLED
        tips = [
            (("c_like", "e_like"), "Like" + (" (Ctrl+Alt+L)" if hk else "")),
            (("c_prev", "e_prev"), "Previous" + (" (Ctrl+Alt+Left)" if hk else "")),
            (("c_play", "e_play"), "Play / Pause" + (" (Ctrl+Alt+Space)" if hk else "")),
            (("c_next", "e_next"), "Next" + (" (Ctrl+Alt+Right)" if hk else "")),
            (("e_shuffle",), "Shuffle"),
            (("e_repeat",), "Repeat"),
            (("toggle_btn",), "Expand / collapse (double-click the card)"),
        ]
        for names, tip in tips:
            for n in names:
                b = getattr(self, n, None)
                if b is not None:
                    b.setToolTip(tip)
                    b.setAccessibleName(tip.split(" (")[0])

    # ---- volume ------------------------------------------------------------
    def _on_vol_changed(self, value):
        if self._vol_updating:
            return
        self.volume_changed.emit(value / 100.0)

    def _on_mute(self):
        self.mute_toggled.emit(not self._muted)

    def on_volume_state(self, level, muted, scope):
        # level < 0 or empty scope -> nothing controllable; hide the controls.
        if level < 0 or not scope:
            self.e_vol_box.hide()
            self.c_vol.hide()
            return
        self.e_vol_box.show()
        self.c_vol.show()
        self._muted = bool(muted)
        self.e_mute.setIcon(icons.volume_icon(INK, muted=self._muted))
        self.e_mute.setToolTip(("Unmute " if self._muted else "Mute ") + scope)
        self.e_vol.setToolTip(f"Volume: {scope}")
        self.c_vol.setToolTip(f"Volume: {scope}")
        if self.e_vol.isSliderDown() or self.c_vol.isSliderDown():
            # Never yank a handle the user is holding: above the master ceiling
            # the read-back is lower than the request, and a mid-drag setValue
            # would fight every mouse move. The next poll settles it on release.
            return
        self._vol_updating = True
        v = int(round(max(0.0, min(1.0, level)) * 100))
        self.e_vol.setValue(v)
        self.c_vol.setValue(v)
        self._vol_updating = False

    # ---- accent (fixed, or auto-tinted from album art) ---------------------
    def _effective_accent(self):
        if config.AUTO_ACCENT and self._accent_dyn:
            return self._accent_dyn
        return config.ACCENT

    def _effective_accent2(self):
        """Second duotone color: sampled from the art when available, otherwise
        a lightened variant of the primary so the gradient is always subtle."""
        if config.AUTO_ACCENT and self._accent2_dyn:
            return self._accent2_dyn
        return QColor(self._effective_accent()).lighter(135).name()

    def _on_accent_color(self, hexcolor):
        c = QColor(hexcolor)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        return "#0a0a0a" if lum > 140 else "#ffffff"

    def _effective_on_accent(self):
        return self._on_accent_color(self._effective_accent())

    @staticmethod
    def _boost(color):
        """Push a sampled color into legible-accent territory."""
        h, s, v, _a = color.getHsv()
        return QColor.fromHsv(h, min(255, max(s, 150)),
                              min(255, max(v, 175))).name()

    def _compute_accents(self, pm):
        """Pick up to two vivid accents from the album art: the strongest color,
        plus the strongest one at least 60 degrees of hue away (duotone).
        Returns (primary_or_None, secondary_or_None)."""
        try:
            img = pm.toImage().scaled(24, 24, Qt.IgnoreAspectRatio,
                                      Qt.SmoothTransformation)
            # best-scoring candidate per 30-degree hue bucket
            bins = {}   # bucket -> (score, QColor, hue)
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixelColor(x, y)
                    h, s, v, _a = c.getHsv()
                    if h < 0 or v < 60 or v > 245:
                        continue
                    score = (s / 255.0) * (v / 255.0)
                    b = h // 30
                    if b not in bins or score > bins[b][0]:
                        bins[b] = (score, c, h)
            ranked = sorted(bins.values(), key=lambda t: -t[0])
            ranked = [r for r in ranked if r[0] >= 0.12]
            if not ranked:
                return None, None
            primary = ranked[0]
            secondary = None
            for cand in ranked[1:]:
                d = abs(cand[2] - primary[2])
                if min(d, 360 - d) >= 60:
                    secondary = cand
                    break
            return (self._boost(primary[1]),
                    self._boost(secondary[1]) if secondary else None)
        except Exception:
            return None, None

    def _apply_accent(self):
        """Push the effective accent through every accent-colored element."""
        acc = self._effective_accent()
        self.progress.accent = acc
        self.progress.accent2 = self._effective_accent2()
        self.progress.update()
        self.e_lyrics.accent = acc
        self.e_lyrics.update()
        if self._lyrics_mode:
            self.e_lyrics_btn.setIcon(icons.lyrics_icon(acc))
        self._apply_style()
        self._set_play_icon(self._playing)
        self._refresh_shuffle_repeat()
        self._refresh_tray_icon()   # ring color follows the accent

    def _apply_style(self):
        acc = self._effective_accent()
        acc2 = self._effective_accent2()
        grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                f"stop:0 {acc}, stop:1 {acc2})")
        self.setStyleSheet(f"""
            QLabel#title      {{ color:{INK}; font-size:13px; font-weight:600; }}
            QLabel#title_big  {{ color:{INK}; font-size:16px; font-weight:700; }}
            QLabel#artist     {{ color:{SUBTLE}; font-size:11px; }}
            QLabel#time       {{ color:{SUBTLE}; font-size:10px; }}
            QLabel#quality    {{ color:{acc}; border:1px solid {acc};
                                  border-radius:8px; padding:1px 8px;
                                  font-size:10px; font-weight:700; }}
            QLabel            {{ background:transparent; }}
            QPushButton {{ border:none; background:rgba(255,255,255,0.10); }}
            QPushButton:hover   {{ background:rgba(255,255,255,0.20); }}
            QPushButton:pressed {{ background:rgba(255,255,255,0.32); }}
            QPushButton[accent="true"]         {{ background:{grad}; }}
            QPushButton[accent="true"]:hover   {{ background:{grad}; }}
            QPushButton[accent="true"]:pressed {{ background:{grad}; }}
            QPushButton:disabled {{ background:rgba(255,255,255,0.04); }}
            QPushButton[accent="true"]:disabled {{ background:rgba(255,255,255,0.10); }}
            QSlider::groove:horizontal {{ height:4px; background:rgba(255,255,255,0.18);
                                          border-radius:2px; }}
            QSlider::sub-page:horizontal {{ background:{grad}; border-radius:2px; }}
            QSlider::add-page:horizontal {{ background:rgba(255,255,255,0.18);
                                            border-radius:2px; }}
            QSlider::handle:horizontal {{ width:12px; height:12px; margin:-4px 0;
                                          border-radius:6px; background:#ffffff; }}
        """)
        # round each button to a circle via its fixed size
        for b in self.findChildren(QPushButton):
            b.setStyleSheet(f"border-radius:{b.width() // 2}px;")

    def apply_settings(self):
        """Re-apply settings live after the preferences dialog saves them."""
        self.setWindowOpacity(min(1.0, max(0.2, getattr(config, "WINDOW_OPACITY", 1.0))))
        flags = Qt.FramelessWindowHint | Qt.Tool
        if config.ALWAYS_ON_TOP:
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)          # note: this hides the window
        if config.AUTO_ACCENT and self._cover_src:
            self._accent_dyn, self._accent2_dyn = \
                self._compute_accents(self._cover_src)
        else:
            self._accent_dyn = self._accent2_dyn = None
        self._apply_accent()                # picks up the new / auto accent color
        self._refresh_heart()
        self.card.update()
        self.progress.update()
        self._tray_icon_state = None   # LIVE_TRAY may have been toggled
        self._refresh_tray_icon()
        if was_visible:
            self._show_widget()
            self._snap_to_corner()

    # ---- system tray -------------------------------------------------------
    def _build_tray(self):
        self.tray = None
        self._tray_menu = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.tray_icon(config.ACCENT), self)
        self.tray.setToolTip("Tidal Now Playing")

        menu = QMenu()
        menu.setToolTipsVisible(True)
        self._tray_menu = menu  # keep a reference so it isn't garbage-collected

        self.act_track = QAction("Nothing playing", self)
        self.act_track.setEnabled(False)
        menu.addAction(self.act_track)
        menu.addSeparator()

        self.act_play = QAction(icons.play_icon(INK), "Play", self)
        self.act_play.triggered.connect(lambda: self.playpause_clicked.emit())
        menu.addAction(self.act_play)
        act_next = QAction(icons.next_icon(INK), "Next", self)
        act_next.triggered.connect(lambda: self.next_clicked.emit())
        menu.addAction(act_next)
        act_prev = QAction(icons.prev_icon(INK), "Previous", self)
        act_prev.triggered.connect(lambda: self.prev_clicked.emit())
        menu.addAction(act_prev)
        menu.addSeparator()

        self.act_like = QAction(icons.heart_icon(SUBTLE, filled=False),
                                "Like current track", self)
        self.act_like.triggered.connect(self._on_heart)
        menu.addAction(self.act_like)
        self.act_signin = QAction("Sign in to TIDAL", self)
        self.act_signin.setToolTip(SIGNIN_HINT)
        self.act_signin.triggered.connect(lambda: self.signin_requested.emit())
        menu.addAction(self.act_signin)
        act_open = QAction("Open TIDAL", self)
        act_open.triggered.connect(self._open_tidal)
        menu.addAction(act_open)
        act_web = QAction("TIDAL web player", self)
        act_web.triggered.connect(self._open_web_player)
        menu.addAction(act_web)
        self.act_radio = QAction("Track radio (more like this)", self)
        self.act_radio.setToolTip("Open a TIDAL mix seeded from the playing track")
        self.act_radio.triggered.connect(self._on_radio_clicked)
        menu.addAction(self.act_radio)
        act_copy = QAction("Copy now playing", self)
        act_copy.triggered.connect(self._copy_now_playing)
        menu.addAction(act_copy)
        self.act_save_cover = QAction("Save cover art...", self)
        self.act_save_cover.triggered.connect(self._save_cover)
        menu.addAction(self.act_save_cover)
        menu.addSeparator()

        act_check_updates = QAction("Check for updates...", self)
        act_check_updates.triggered.connect(lambda: self.check_updates_requested.emit())
        menu.addAction(act_check_updates)
        menu.addSeparator()

        self.act_visibility = QAction("Hide widget", self)
        self.act_visibility.triggered.connect(self._toggle_visibility)
        menu.addAction(self.act_visibility)
        self.act_mode = QAction("Expand", self)
        self.act_mode.triggered.connect(self.toggle_mode)
        menu.addAction(self.act_mode)
        menu.addSeparator()

        act_settings = QAction("Settings...", self)
        act_settings.triggered.connect(lambda: self.settings_requested.emit())
        menu.addAction(act_settings)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(lambda: self.quit_requested.emit())
        menu.addAction(act_quit)

        menu.aboutToShow.connect(self._refresh_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _refresh_tray_menu(self):
        if not self.tray:
            return
        self.act_signin.setVisible(not self._logged_in)
        self.act_radio.setEnabled(self._logged_in and bool(self._cur_title))
        self.act_save_cover.setEnabled(self._cover_src is not None)
        self.act_visibility.setText("Hide widget" if self.isVisible() else "Show widget")
        self.act_mode.setText("Compact" if self._expanded else "Expand")
        self.act_play.setText("Pause" if self._playing else "Play")
        self.act_play.setIcon(icons.pause_icon(INK) if self._playing
                              else icons.play_icon(INK))

    def _tray_activated(self, reason):
        # left-click toggles the widget; right-click opens the context menu
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self):
        if self.isVisible():
            self._hide_widget()
        else:
            self._show_widget()

    def _hide_widget(self):
        self._auto_hidden = False   # a manual hide overrides game mode
        self.hide()

    def _show_widget(self):
        self._auto_hidden = False   # showing means it's no longer auto-hidden
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_tray(self, title, artist, available):
        if not self.tray:
            return
        if available:
            self.act_track.setText(f"{title}  ·  {artist}")
            self.tray.setToolTip(f"{title}\n{artist}")
        else:
            self.act_track.setText("Nothing playing")
            self.tray.setToolTip("Tidal Now Playing")

    def _refresh_tray_icon(self):
        """Live tray icon: cover + accent progress ring, throttled so the icon
        is only re-rendered when something visible about it changed."""
        if not getattr(self, "tray", None):
            return
        live = (getattr(config, "LIVE_TRAY", True)
                and self._cover_src is not None and self._dur > 0)
        if not live:
            if self._tray_icon_state is not None:
                self._tray_icon_state = None
                self.tray.setIcon(icons.tray_icon(self._effective_accent()))
            return
        frac = min(1.0, max(0.0, self._pos / self._dur))
        state = (id(self._cover_src), self._playing,
                 int(frac * 24), self._effective_accent())
        if state == self._tray_icon_state:
            return
        self._tray_icon_state = state
        self.tray.setIcon(icons.live_tray_icon(
            self._cover_src, self._playing, frac, self._effective_accent()))

    # ---- game mode (auto-hide while a fullscreen app runs) -------------------
    def on_fullscreen(self, fullscreen):
        if not getattr(config, "HIDE_ON_FULLSCREEN", True):
            return
        if fullscreen and self.isVisible():
            self._auto_hidden = True
            self.hide()
        elif not fullscreen and self._auto_hidden:
            self._auto_hidden = False
            self._show_widget()

    # ---- track radio ---------------------------------------------------------
    def _on_radio_clicked(self):
        if self._cur_title and self._logged_in:
            self.radio_requested.emit(self._cur_title, self._cur_artist)

    def on_radio(self, title, artist, mix_id):
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        if mix_id:
            self._open_web_player(f"{WEB_PLAYER_URL}/mix/{mix_id}")

    # ---- likes / TIDAL -----------------------------------------------------
    def _on_heart(self):
        if self._cur_title:
            self.like_clicked.emit(self._cur_title, self._cur_artist,
                                   self._cur_album, self._liked)

    def _refresh_heart(self):
        ic = icons.heart_icon(LIKE_COLOR if self._liked else SUBTLE, 64, self._liked)
        for b in (self.c_like, self.e_like):
            b.setIcon(ic)

    def _tray_msg(self, text, title="Tidal Now Playing"):
        # Desktop balloon notifications were intrusive; intentionally a no-op.
        # Feedback comes from the widget itself (heart fill, menu state).
        return

    def on_like_result(self, ok, action, label):
        if action == "login":
            self._tray_msg("Sign in to TIDAL first (tray icon menu).", "TIDAL")
            return
        if not ok:
            if action == "nomatch":
                self._tray_msg("Couldn't find this track on TIDAL.", "TIDAL")
            else:
                self._tray_msg("Couldn't update your TIDAL collection.", "TIDAL")
            return
        if action == "added":
            self._liked = True
            self._heart_user_owned = True
            self._tray_msg("Added to your collection:\n" + label, "TIDAL")
        elif action == "removed":
            self._liked = False
            self._heart_user_owned = True
            self._tray_msg("Removed from your collection:\n" + label, "TIDAL")
        self._refresh_heart()

    def on_favorite_state(self, title, artist, is_fav):
        # Ground-truth liked state from TIDAL, so the heart shows reality (not
        # just optimistic add) and clicking it toggles in the right direction.
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        if self._heart_user_owned:
            return  # user's own like/unlike wins over an in-flight ground truth
        self._liked = bool(is_fav)
        self._refresh_heart()

    def on_login_link(self, url):
        try:
            webbrowser.open(url)
        except Exception:
            pass
        self._tray_msg("Opening TIDAL sign-in in your browser...", "TIDAL")

    def on_login_state(self, ok, msg):
        self._logged_in = bool(ok)
        if self.tray:
            self.act_signin.setVisible(not self._logged_in)
        # Sign-in can complete while a track is already playing; re-resolve its
        # quality badge and heart now instead of waiting for the next track.
        if self._logged_in and self._cur_title:
            self.quality_requested.emit(self._cur_title, self._cur_artist)
            self.favorite_requested.emit(self._cur_title, self._cur_artist)
            self.cover_requested.emit(self._cur_title, self._cur_artist)

    def on_quality(self, title, artist, label):
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        if label:
            self.e_quality.setText(label)
            self.e_quality.setToolTip(f"Available in {label} on TIDAL")
            self.e_quality.show()
        else:
            self.e_quality.hide()

    # ---- lyrics ------------------------------------------------------------
    def on_lyrics(self, title, artist, lines):
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        self.e_lyrics.set_lines(lines)
        tip = "Show lyrics" if lines else "No lyrics for this track"
        for b in (self.c_lyrics_btn, self.e_lyrics_btn):
            b.show()
            b.setEnabled(bool(lines))   # dimmed signifier when none; won't expand
            b.setToolTip(tip)
        if not lines and self._lyrics_mode:
            self._set_lyrics_mode(False)

    def _on_lyrics_offset(self, val):
        # Remember the nudged sync offset, but coalesce rapid scrolls into one
        # write (the timer restarts on each notch and only saves once it settles).
        self._pending_offset = float(val)
        self._offset_save.start()

    def _save_lyrics_offset(self):
        try:
            settings.save({"lyrics_offset": self._pending_offset})
        except Exception:
            pass

    def _toggle_lyrics(self):
        self._set_lyrics_mode(not self._lyrics_mode)

    def _set_lyrics_mode(self, on):
        self._lyrics_mode = on
        self.e_cover.setVisible(not on)
        self.e_quality.setVisible(not on and bool(self.e_quality.text()))
        self.e_lyrics.setVisible(on)
        self.e_lyrics_btn.setIcon(
            icons.lyrics_icon(self._effective_accent() if on else SUBTLE))
        if on:
            self.e_lyrics.set_position(self._pos)

    def _open_lyrics(self):
        # From the compact bar: expand and open the lyrics panel.
        if not self.e_lyrics.has_lyrics():
            return
        if not self._expanded:
            self._set_mode(True)
        self._set_lyrics_mode(True)

    def _open_tidal(self):
        for opener in (lambda: webbrowser.open("tidal://"),
                       lambda: os.startfile("tidal://")):
            try:
                opener()
                break
            except Exception:
                continue
        self._tray_msg("Opening TIDAL. Change playlists or streaming quality "
                       "in the TIDAL app.", "TIDAL")

    def _copy_now_playing(self):
        if self._cur_title:
            text = f"{self._cur_artist} - {self._cur_title}".strip(" -")
            QGuiApplication.clipboard().setText(text)

    def _open_web_player(self, url=None):
        # Open TIDAL's web player as a chromeless browser "app window": it acts
        # like a dedicated popup, plays fine (the browser has the Widevine DRM a
        # Qt web view lacks), and its media session shows up in this widget.
        if not isinstance(url, str) or not url:
            url = WEB_PLAYER_URL   # also swallows QAction.triggered's bool arg
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for exe in candidates:
            if exe and os.path.exists(exe):
                try:
                    subprocess.Popen([exe, f"--app={url}",
                                      "--window-size=480,800"])
                    return
                except Exception:
                    pass
        # Fallback: the default browser (a normal tab).
        try:
            webbrowser.open(url)
        except Exception:
            try:
                os.startfile(url)
            except Exception:
                pass

    # ---- mode toggle -------------------------------------------------------
    def toggle_mode(self):
        self._set_mode(not self._expanded)

    def _set_mode(self, expanded: bool, anchor: bool = True):
        self._expanded = expanded
        card_w, card_h = EXPANDED_CARD if expanded else COMPACT_CARD
        new_w, new_h = card_w + 2 * MARGIN, card_h + 2 * MARGIN

        self.stack.setCurrentIndex(1 if expanded else 0)
        self.setFixedSize(new_w, new_h)
        self._update_timer()

        # place the floating toggle button in the card's top-right corner
        self.toggle_btn.setIcon(
            icons.collapse_icon(SUBTLE) if expanded else icons.expand_icon(SUBTLE))
        self.toggle_btn.move(card_w - 8 - TOGGLE_D, 8)
        self.toggle_btn.raise_()

        # keep the widget locked to its current corner after resizing
        if anchor:
            self._snap_to_corner()

        self._refresh_covers()

    # ---- data update -------------------------------------------------------
    def on_update(self, info: dict):
        if not info.get("available"):
            self._cover_src = None
            self.card.set_ambient(None)
            self.c_cover.clear()
            self.e_cover.clear()
            self.c_title.setFullText("Nothing playing")
            self.e_title.setFullText("Nothing playing")
            msg = info.get("error", "Open TIDAL and press play")
            self.c_artist.setFullText(msg)
            self.e_artist.setFullText(msg)
            self._playing = False
            self._update_timer()
            self._set_play_icon(False)
            self._pos = self._dur = 0.0
            self.progress.set_fraction(0.0)
            self.e_pos.setText("--:--")
            self.e_dur.setText("--:--")
            self._cur_title = self._cur_artist = self._cur_album = ""
            self._liked = False
            self._refresh_heart()
            self.progress.set_seekable(False)
            self.e_shuffle.hide()
            self.e_repeat.hide()
            self.e_quality.hide()
            self.e_lyrics.set_lines([])
            self.c_lyrics_btn.hide()
            self.e_lyrics_btn.hide()
            if self._lyrics_mode:
                self._set_lyrics_mode(False)
            self.e_lyrics.set_playing(False)
            self._update_tray(None, None, available=False)
            self._refresh_tray_icon()   # falls back to the brand mark
            return

        title = info.get("title") or "Unknown title"
        artist = info.get("artist") or "Unknown artist"
        track_changed = (title != self._cur_title or artist != self._cur_artist)
        if track_changed:
            self._liked = False        # a new track starts unliked in the UI
            self._heart_user_owned = False   # ground-truth may set the heart again
            self._cover_hires = False  # SMTC thumbnail owns the art again
            self._cover_bytes = None
            self.e_quality.hide()      # clear the quality badge until it resolves
            for b in (self.c_lyrics_btn, self.e_lyrics_btn):
                b.show()
                b.setEnabled(False)   # signifier while we check / if none
                b.setToolTip("Finding lyrics...")
            self.e_lyrics.set_loading()
        self._cur_title, self._cur_artist = title, artist
        self._cur_album = info.get("album") or ""
        self._refresh_heart()
        if track_changed:
            self.quality_requested.emit(title, artist)
            self.lyrics_requested.emit(title, artist, self._cur_album,
                                       float(info.get("duration") or 0))
            if self._logged_in:
                self.favorite_requested.emit(title, artist)
                self.cover_requested.emit(title, artist)
        self.c_title.setFullText(title)
        self.e_title.setFullText(title)
        self.c_artist.setFullText(artist)
        self.e_artist.setFullText(artist)

        prev_playing = self._playing
        self._playing = bool(info.get("playing"))
        self._set_play_icon(self._playing)
        self._update_timer()
        self.e_lyrics.set_playing(self._playing)   # karaoke wipe extrapolation
        self._update_tray(title, artist, available=True)
        self._apply_caps(info)

        self._pos = float(info.get("position") or 0.0)
        self._dur = float(info.get("duration") or 0.0)
        self._anchor = time.monotonic()
        self._update_progress(self._pos)

        if info.get("art_changed"):
            if self._cover_hires:
                # The backend keys art on (title, artist, album): new art with
                # the hires flag still set means the ALBUM changed under the
                # same title/artist (single vs album cut), so the old full-res
                # cover is stale. Otherwise the flag blocks SMTC-thumbnail
                # downgrades between track changes (it is reset on track change).
                self._cover_hires = False
                self._cover_bytes = None
                if self._logged_in and not track_changed:
                    self.cover_requested.emit(title, artist)
            art = info.get("art")
            if art:
                pm = QPixmap()
                pm.loadFromData(art)
                self._cover_src = pm if not pm.isNull() else None
            else:
                self._cover_src = None
            self._apply_cover()
        elif self._playing != prev_playing and self._cover_src is not None:
            self._refresh_covers()   # play/pause flipped: apply or lift the dim
        self._refresh_tray_icon()

    def _apply_cover(self):
        """Push self._cover_src through ambience, covers, accents, and tray."""
        self.card.set_ambient(self._cover_src)
        self._refresh_covers()
        if config.AUTO_ACCENT and self._cover_src:
            self._accent_dyn, self._accent2_dyn = \
                self._compute_accents(self._cover_src)
        else:
            self._accent_dyn = self._accent2_dyn = None
        self._apply_accent()

    def on_cover_hires(self, title, artist, data):
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        pm = QPixmap()
        pm.loadFromData(data)
        if pm.isNull():
            return
        if self._cover_src is not None and pm.width() <= self._cover_src.width():
            return  # not actually an upgrade
        self._cover_src = pm
        self._cover_bytes = bytes(data)
        self._cover_hires = True
        self._apply_cover()

    def _save_cover(self):
        # Snapshot first: the modal dialog runs a nested event loop, so the
        # track (and with it _cover_src/_cover_bytes) can change while it's open.
        pm = self._cover_src
        data = self._cover_bytes
        if pm is None:
            return
        base = f"{self._cur_artist} - {self._cur_album or self._cur_title}".strip(" -")
        base = re.sub(r'[<>:"/\\|?*]', "_", base) or "cover"
        path, _f = QFileDialog.getSaveFileName(
            self, "Save cover art", base + ".jpg", "Images (*.jpg *.png)")
        if not path:
            return
        try:
            if data and path.lower().endswith(".jpg"):
                with open(path, "wb") as f:
                    f.write(data)   # original full-res bytes
            else:
                pm.save(path)
        except Exception:
            pass

    def _set_play_icon(self, playing: bool):
        oa = self._effective_on_accent()
        icon = icons.pause_icon(oa) if playing else icons.play_icon(oa)
        for b in self._play_buttons:
            b.setIcon(icon)

    # ---- transport capabilities + shuffle/repeat ---------------------------
    def _apply_caps(self, info):
        self.progress.set_seekable(bool(info.get("can_seek")))
        for b in (self.c_prev, self.e_prev):
            b.setEnabled(bool(info.get("can_prev", True)))
        for b in (self.c_next, self.e_next):
            b.setEnabled(bool(info.get("can_next", True)))
        for b in self._play_buttons:
            b.setEnabled(bool(info.get("can_playpause", True)))
        self.e_shuffle.setVisible(bool(info.get("can_shuffle")))
        self.e_repeat.setVisible(bool(info.get("can_repeat")))
        self._shuffle = bool(info.get("shuffle"))
        self._repeat = int(info.get("repeat", 0))
        self._refresh_shuffle_repeat()

    def _refresh_shuffle_repeat(self):
        acc = self._effective_accent()
        self.e_shuffle.setIcon(
            icons.shuffle_icon(acc if self._shuffle else SUBTLE))
        if self._repeat == 1:
            self.e_repeat.setIcon(icons.repeat_icon(acc, one=True))
        elif self._repeat == 2:
            self.e_repeat.setIcon(icons.repeat_icon(acc))
        else:
            self.e_repeat.setIcon(icons.repeat_icon(SUBTLE))

    def _on_seek(self, frac):
        if self._dur > 0:
            secs = frac * self._dur
            self._pos = secs
            self._anchor = time.monotonic()
            self._update_progress(secs)
            self.seek_clicked.emit(secs)

    def _refresh_covers(self):
        if self._cover_src is None:
            self.c_cover.clear()
            self.e_cover.clear()
            return
        c = _rounded_cover(self._cover_src, 64, 12)
        e = _rounded_cover(self._cover_src, 150, 16)
        if not self._playing:                 # dim the art while paused
            c, e = _dim_pixmap(c), _dim_pixmap(e)
        self.c_cover.setPixmap(c)
        self.e_cover.setPixmap(e)

    # ---- progress ----------------------------------------------------------
    def _tick_progress(self):
        if not self._expanded:
            return
        if self._playing and self._dur > 0:
            est = min(self._pos + (time.monotonic() - self._anchor), self._dur)
            self._update_progress(est)
            if self._lyrics_mode:
                self.e_lyrics.set_position(est)

    def _update_timer(self):
        # The 200ms progress timer only does visible work when playing AND
        # expanded AND on screen; keep it stopped otherwise (saves idle CPU).
        if not hasattr(self, "_timer"):
            return
        if self._playing and self._expanded and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_timer()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_timer()

    def _update_progress(self, pos: float):
        if self._dur > 0:
            self.progress.set_fraction(pos / self._dur)
            self.e_pos.setText(_fmt_time(pos))
            self.e_dur.setText(_fmt_time(self._dur))
        else:
            self.progress.set_fraction(0.0)
            self.e_pos.setText("--:--")
            self.e_dur.setText("--:--")

    # ---- positioning / corner locking --------------------------------------
    def _current_screen(self):
        scr = QGuiApplication.screenAt(self.frameGeometry().center())
        return scr or QGuiApplication.primaryScreen()

    def _corner_pos(self, corner):
        geo = self._current_screen().availableGeometry()
        w, h = self.width(), self.height()
        # The window carries MARGIN px of transparent padding for the drop
        # shadow. Offset by it so the VISIBLE card hugs the corner, leaving only
        # CORNER_GAP; the transparent margin spills harmlessly off-screen.
        off = MARGIN - CORNER_GAP
        x = geo.left() - off if corner[1] == "l" else geo.right() - w + off
        y = geo.top() - off if corner[0] == "t" else geo.bottom() - h + off
        return int(x), int(y)

    def _snap_to_corner(self, corner=None):
        if corner:
            self._corner = corner
        x, y = self._corner_pos(self._corner)
        self.move(x, y)

    def _nearest_corner(self):
        geo = self._current_screen().availableGeometry()
        c = self.frameGeometry().center()
        h = "l" if c.x() < geo.center().x() else "r"
        v = "t" if c.y() < geo.center().y() else "b"
        return v + h

    def _move_to_corner(self):
        self._snap_to_corner(self._corner)

    def _restore_placement(self):
        # Return to the last monitor + corner across runs.
        try:
            scr_name, corner = settings.get_placement()
            if corner in ("tl", "tr", "bl", "br"):
                self._corner = corner
            if scr_name:
                for scr in QGuiApplication.screens():
                    if scr.name() == scr_name:
                        c = scr.availableGeometry().center()
                        self.move(c.x(), c.y())   # land on that monitor first
                        break
        except Exception:
            pass

    # ---- window drag + double-click + context menu -------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_gpos = e.globalPosition().toPoint()
            self._drag = self._press_gpos - self.frameGeometry().topLeft()
            self._moved = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            gp = e.globalPosition().toPoint()
            if not self._moved:
                # Ignore tiny jitter so an ordinary click (or double-click)
                # doesn't nudge the window and rewrite the saved placement.
                if (gp - self._press_gpos).manhattanLength() < \
                        QGuiApplication.styleHints().startDragDistance():
                    return
                self._moved = True
            self.move(gp - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        moved = self._moved
        self._drag = None
        self._moved = False
        if moved:
            self._snap_to_corner(self._nearest_corner())
            try:
                settings.set_placement(self._current_screen().name(), self._corner)
            except Exception:
                pass

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle_mode()
            e.accept()

    def contextMenuEvent(self, e):
        # The widget already shows transport + like as on-screen buttons, so the
        # right-click menu carries only the management actions (no transport, to
        # avoid duplicating the buttons). The tray icon keeps the FULL menu for
        # when the widget is hidden.
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        act_open = QAction("Open TIDAL", self)
        act_open.triggered.connect(self._open_tidal)
        menu.addAction(act_open)
        act_web = QAction("TIDAL web player", self)
        act_web.triggered.connect(self._open_web_player)
        menu.addAction(act_web)
        act_radio = QAction("Track radio (more like this)", self)
        act_radio.setEnabled(self._logged_in and bool(self._cur_title))
        act_radio.triggered.connect(self._on_radio_clicked)
        menu.addAction(act_radio)
        act_copy = QAction("Copy now playing", self)
        act_copy.triggered.connect(self._copy_now_playing)
        menu.addAction(act_copy)
        act_cover = QAction("Save cover art...", self)
        act_cover.setEnabled(self._cover_src is not None)
        act_cover.triggered.connect(self._save_cover)
        menu.addAction(act_cover)
        if not self._logged_in:
            act_signin = QAction("Sign in to TIDAL", self)
            act_signin.setToolTip(SIGNIN_HINT)
            act_signin.triggered.connect(lambda: self.signin_requested.emit())
            menu.addAction(act_signin)
        act_updates = QAction("Check for updates...", self)
        act_updates.triggered.connect(lambda: self.check_updates_requested.emit())
        menu.addAction(act_updates)
        menu.addSeparator()
        act_mode = QAction("Compact" if self._expanded else "Expand", self)
        act_mode.triggered.connect(self.toggle_mode)
        menu.addAction(act_mode)
        if self.tray:
            act_hide = QAction("Hide widget", self)
            act_hide.triggered.connect(self._hide_widget)
            menu.addAction(act_hide)
        menu.addSeparator()
        act_settings = QAction("Settings...", self)
        act_settings.triggered.connect(lambda: self.settings_requested.emit())
        menu.addAction(act_settings)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(lambda: self.quit_requested.emit())
        menu.addAction(act_quit)
        menu.exec(e.globalPos())

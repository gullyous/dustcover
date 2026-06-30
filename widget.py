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
import subprocess
import time
import webbrowser

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPainterPath, QPen, QLinearGradient,
    QAction, QGuiApplication,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame, QStackedWidget, QSizePolicy, QSlider,
    QHBoxLayout, QVBoxLayout, QMenu, QSystemTrayIcon, QGraphicsDropShadowEffect,
)

import config
import icons

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


class Card(QFrame):
    """The visible card. Paints the ambient album-art background itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ambient = None  # tiny pixmap, upscaled smoothly for a cheap blur

    def set_ambient(self, src: QPixmap | None):
        if src is None:
            self._ambient = None
        else:
            self._ambient = src.scaled(
                36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.update()

    def paintEvent(self, _):
        bg = getattr(config, "BACKGROUND_OPACITY", 1.0)
        bg = 0.0 if bg < 0 else 1.0 if bg > 1 else bg

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)

        # Build the OPAQUE background composite (base + ambient + dark overlay)
        # on a separate layer, then blit it once at BACKGROUND_OPACITY. Doing it
        # in one blit gives the panel a uniform alpha (so the desktop shows
        # through evenly) instead of compounding each layer's alpha. The child
        # widgets (text, cover, buttons) paint on top and stay fully opaque.
        dpr = self.devicePixelRatioF()
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

        p.setClipPath(path)
        p.setOpacity(bg)
        p.drawPixmap(0, 0, layer)
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
    check_updates_requested = Signal()     # tray "Check for updates..." (loud check)
    volume_changed = Signal(float)         # 0.0-1.0, from the volume slider
    mute_toggled = Signal(bool)            # desired mute state

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
        self._cover_src = None         # full-res cover QPixmap (or None)
        self._expanded = bool(config.START_EXPANDED)
        self._corner = "br"            # which screen corner the widget locks to

        # current track + like state (for the heart button)
        self._cur_title = ""
        self._cur_artist = ""
        self._cur_album = ""
        self._liked = False
        self._logged_in = False   # signed in to TIDAL (for likes/quality)
        self._muted = False         # current app/system mute (from volume backend)
        self._vol_updating = False  # guard: ignore slider signals during programmatic set
        self._accent_dyn = None     # accent tinted from album art (auto-accent)
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
        self._move_to_corner()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick_progress)
        # started on demand by _update_timer() (only while playing + expanded + visible)

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

        btns = QHBoxLayout()
        btns.setSpacing(6)
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
        times = QHBoxLayout()
        times.setContentsMargins(0, 0, 0, 0)
        times.addWidget(self.e_pos)
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

    def _on_accent_color(self, hexcolor):
        c = QColor(hexcolor)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        return "#0a0a0a" if lum > 140 else "#ffffff"

    def _effective_on_accent(self):
        return self._on_accent_color(self._effective_accent())

    def _compute_accent(self, pm):
        """Pick a vivid accent from the album art, or None if too monochrome."""
        try:
            img = pm.toImage().scaled(24, 24, Qt.IgnoreAspectRatio,
                                      Qt.SmoothTransformation)
            best, best_score = None, -1.0
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixelColor(x, y)
                    h, s, v, _a = c.getHsv()
                    if h < 0 or v < 60 or v > 245:
                        continue
                    score = (s / 255.0) * (v / 255.0)
                    if score > best_score:
                        best_score, best = score, c
            if best is None or best_score < 0.12:
                return None
            h, s, v, _a = best.getHsv()
            return QColor.fromHsv(h, min(255, max(s, 150)),
                                  min(255, max(v, 175))).name()
        except Exception:
            return None

    def _apply_accent(self):
        """Push the effective accent through every accent-colored element."""
        self.progress.accent = self._effective_accent()
        self.progress.update()
        self._apply_style()
        self._set_play_icon(self._playing)
        self._refresh_shuffle_repeat()

    def _apply_style(self):
        acc = self._effective_accent()
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
            QPushButton[accent="true"]         {{ background:{acc}; }}
            QPushButton[accent="true"]:hover   {{ background:{acc}; }}
            QPushButton[accent="true"]:pressed {{ background:{acc}; }}
            QSlider::groove:horizontal {{ height:4px; background:rgba(255,255,255,0.18);
                                          border-radius:2px; }}
            QSlider::sub-page:horizontal {{ background:{acc}; border-radius:2px; }}
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
        self._accent_dyn = (self._compute_accent(self._cover_src)
                            if (config.AUTO_ACCENT and self._cover_src) else None)
        self._apply_accent()                # picks up the new / auto accent color
        self._refresh_heart()
        self.card.update()
        self.progress.update()
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
            self.hide()
        else:
            self._show_widget()

    def _show_widget(self):
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
            self._tray_msg("Added to your collection:\n" + label, "TIDAL")
        elif action == "removed":
            self._liked = False
            self._tray_msg("Removed from your collection:\n" + label, "TIDAL")
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

    def on_quality(self, title, artist, label):
        if (title, artist) != (self._cur_title, self._cur_artist):
            return  # stale result for a track that already changed
        if label:
            self.e_quality.setText(label)
            self.e_quality.setToolTip(f"Available in {label} on TIDAL")
            self.e_quality.show()
        else:
            self.e_quality.hide()

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

    def _open_web_player(self):
        # Open TIDAL's web player as a chromeless browser "app window": it acts
        # like a dedicated popup, plays fine (the browser has the Widevine DRM a
        # Qt web view lacks), and its media session shows up in this widget.
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
                    subprocess.Popen([exe, f"--app={WEB_PLAYER_URL}",
                                      "--window-size=480,800"])
                    return
                except Exception:
                    pass
        # Fallback: the default browser (a normal tab).
        try:
            webbrowser.open(WEB_PLAYER_URL)
        except Exception:
            try:
                os.startfile(WEB_PLAYER_URL)
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
            self._update_tray(None, None, available=False)
            return

        title = info.get("title") or "Unknown title"
        artist = info.get("artist") or "Unknown artist"
        track_changed = (title != self._cur_title or artist != self._cur_artist)
        if track_changed:
            self._liked = False        # a new track starts unliked in the UI
            self.e_quality.hide()      # clear the quality badge until it resolves
        self._cur_title, self._cur_artist = title, artist
        self._cur_album = info.get("album") or ""
        self._refresh_heart()
        if track_changed:
            self.quality_requested.emit(title, artist)
        self.c_title.setFullText(title)
        self.e_title.setFullText(title)
        self.c_artist.setFullText(artist)
        self.e_artist.setFullText(artist)

        self._playing = bool(info.get("playing"))
        self._set_play_icon(self._playing)
        self._update_timer()
        self._update_tray(title, artist, available=True)
        self._apply_caps(info)

        self._pos = float(info.get("position") or 0.0)
        self._dur = float(info.get("duration") or 0.0)
        self._anchor = time.monotonic()
        self._update_progress(self._pos)

        if info.get("art_changed"):
            art = info.get("art")
            if art:
                pm = QPixmap()
                pm.loadFromData(art)
                self._cover_src = pm if not pm.isNull() else None
            else:
                self._cover_src = None
            self.card.set_ambient(self._cover_src)
            self._refresh_covers()
            self._accent_dyn = (self._compute_accent(self._cover_src)
                                if (config.AUTO_ACCENT and self._cover_src) else None)
            self._apply_accent()

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
        self.c_cover.setPixmap(_rounded_cover(self._cover_src, 64, 12))
        self.e_cover.setPixmap(_rounded_cover(self._cover_src, 150, 16))

    # ---- progress ----------------------------------------------------------
    def _tick_progress(self):
        if not self._expanded:
            return
        if self._playing and self._dur > 0:
            est = self._pos + (time.monotonic() - self._anchor)
            self._update_progress(min(est, self._dur))

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

    # ---- window drag + double-click + context menu -------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        was_dragging = self._drag is not None
        self._drag = None
        if was_dragging:
            self._snap_to_corner(self._nearest_corner())

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
            act_hide.triggered.connect(self.hide)
            menu.addAction(act_hide)
        menu.addSeparator()
        act_settings = QAction("Settings...", self)
        act_settings.triggered.connect(lambda: self.settings_requested.emit())
        menu.addAction(act_settings)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(lambda: self.quit_requested.emit())
        menu.addAction(act_quit)
        menu.exec(e.globalPos())

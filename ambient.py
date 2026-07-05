# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
ambient.py
----------
Fullscreen "now playing" ambient mode: turns a monitor into an Apple-TV-style
player screen with a big blurred-cover wash, large album art, title/artist/
album, the karaoke LyricsView at room scale, and a full set of controls: a
seekable progress bar, previous/play/next, shuffle and repeat, the heart (with
the right-click add-to-playlist menu), a quality badge, and volume with mute.
The controls and the mouse cursor melt away after a few idle seconds and wake
on any mouse move, so the calm "put on an album and sit back" view is still
the default.

Reuses the widget's own pieces (the cheap cover blur, _rounded_cover,
ElidedLabel, ProgressLine, LyricsView with a scale factor, make_round_btn) fed
by the same now-playing/lyrics/position stream, so it stays in lock-step with
the card and needs no new dependencies. Every action routes back through the
widget's existing signals (wired in NowPlayingWidget.toggle_ambient); this
file holds no backend logic. Esc/F11, the close button, or a background
double-click exit; a single background click only wakes the controls. Space
toggles play/pause and Left/Right seek by ten seconds when seeking is allowed.
"""

from PySide6.QtCore import Qt, QEvent, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider)

import config
import icons
from widget import (LyricsView, ProgressLine, ElidedLabel, _ClickToSetStyle,
                    _rounded_cover, _dim_pixmap, _fmt_time, _on_accent_color,
                    make_round_btn, INK, SUBTLE, LIKE_COLOR)

CHROME_IDLE_MS = 3000   # controls + cursor auto-hide after this much stillness


class AmbientWindow(QWidget):
    """Frameless fullscreen now-playing screen. Fed by the widget via the
    set_* methods (track / progress / lines / position / accent / playing /
    capabilities / shuffle-repeat / liked / quality / volume); its buttons,
    slider and progress bar are wired back to the widget's signals in
    NowPlayingWidget.toggle_ambient, so all control flows through the widget."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(None)   # top-level (no parent), so it can go fullscreen
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._cover = None       # full-res QPixmap
        self._playing = False
        self._pos = 0.0
        self._dur = 0.0
        self._accent = config.ACCENT
        self._seekable = False
        self._liked = False
        self._chrome_visible = True
        self._slider_style = _ClickToSetStyle()  # keep a reference (Qt doesn't own it)

        self.art = QLabel(alignment=Qt.AlignCenter)
        self.title = ElidedLabel("")
        self.title.setObjectName("a_title")
        self.title.setAlignment(Qt.AlignCenter)
        self.artist = ElidedLabel("")
        self.artist.setObjectName("a_artist")
        self.artist.setAlignment(Qt.AlignCenter)
        self.album = ElidedLabel("")
        self.album.setObjectName("a_album")
        self.album.setAlignment(Qt.AlignCenter)
        self.album.hide()        # subtle third line, only when the album is known
        self.quality = QLabel("")
        self.quality.setObjectName("a_quality")
        self.quality.hide()      # accent-bordered badge, only once quality resolves
        self.progress = ProgressLine()
        self.pos_lbl = QLabel("--:--"); self.pos_lbl.setObjectName("a_time")
        self.dur_lbl = QLabel("--:--"); self.dur_lbl.setObjectName("a_time")
        self.lyrics = LyricsView()
        self.lyrics.set_scale(2.0)

        quality_row = QHBoxLayout()
        quality_row.addStretch(1)
        quality_row.addWidget(self.quality)
        quality_row.addStretch(1)

        times = QHBoxLayout()
        times.addWidget(self.pos_lbl)
        times.addStretch(1)
        times.addWidget(self.dur_lbl)

        # ---- control cluster (the auto-hiding chrome) ----
        self.btn_heart = make_round_btn(icons.heart_icon(SUBTLE, 64, False), None, 44)
        self.btn_shuffle = make_round_btn(icons.shuffle_icon(SUBTLE), None, 44)
        self.btn_prev = make_round_btn(icons.prev_icon(INK), None, 54)
        self.btn_play = make_round_btn(icons.play_icon(INK), None, 72, accent=True)
        self.btn_next = make_round_btn(icons.next_icon(INK), None, 54)
        self.btn_repeat = make_round_btn(icons.repeat_icon(SUBTLE), None, 44)
        self.btn_shuffle.hide()   # shown only when the source supports them
        self.btn_repeat.hide()

        self.btn_mute = make_round_btn(icons.volume_icon(INK), None, 32)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedSize(240, 18)
        self.vol.setCursor(Qt.PointingHandCursor)
        self.vol.setStyle(self._slider_style)   # groove click = go there
        self.vol_box = QWidget()
        vol_row = QHBoxLayout(self.vol_box)
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(8)
        vol_row.addWidget(self.btn_mute)
        vol_row.addWidget(self.vol)
        self.vol_box.hide()   # shown only when a controllable session is found

        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_heart)
        buttons.addWidget(self.btn_shuffle)
        buttons.addWidget(self.btn_prev)
        buttons.addWidget(self.btn_play)
        buttons.addWidget(self.btn_next)
        buttons.addWidget(self.btn_repeat)
        buttons.addStretch(1)

        self.chrome = QWidget()
        chrome_col = QVBoxLayout(self.chrome)
        chrome_col.setContentsMargins(0, 0, 0, 0)
        chrome_col.setSpacing(10)
        chrome_col.addLayout(buttons)
        chrome_col.addWidget(self.vol_box, 0, Qt.AlignHCenter)
        sp = self.chrome.sizePolicy()
        sp.setRetainSizeWhenHidden(True)   # no reflow when the chrome melts away
        self.chrome.setSizePolicy(sp)

        # floating close button, top-right; part of the auto-hiding chrome
        self.btn_close = make_round_btn(icons.close_icon(SUBTLE), self.close, 40)
        self.btn_close.setParent(self)

        col = QVBoxLayout(self)
        col.setContentsMargins(80, 60, 80, 50)
        col.setSpacing(14)
        col.addStretch(2)
        col.addWidget(self.art, 0, Qt.AlignCenter)
        col.addSpacing(14)
        col.addWidget(self.title)
        col.addWidget(self.artist)
        col.addWidget(self.album)
        col.addLayout(quality_row)
        col.addSpacing(10)
        col.addWidget(self.lyrics, 5)
        col.addSpacing(6)
        col.addWidget(self.progress)
        col.addLayout(times)
        col.addSpacing(6)
        col.addWidget(self.chrome)
        col.addStretch(1)

        tips = [(self.btn_heart, "Like  •  right-click to add to a playlist"),
                (self.btn_shuffle, "Shuffle"), (self.btn_prev, "Previous"),
                (self.btn_play, "Play / Pause"), (self.btn_next, "Next"),
                (self.btn_repeat, "Repeat"), (self.btn_close, "Close (Esc)")]
        for b, tip in tips:
            b.setToolTip(tip)
            b.setAccessibleName(tip.split("  •")[0])

        self._apply_style()

        # Apple-TV-style chrome: hide the controls + cursor after a few idle
        # seconds; any mouse move (on the window or a child) wakes them.
        self._chrome_timer = QTimer(self)
        self._chrome_timer.setSingleShot(True)
        self._chrome_timer.setInterval(CHROME_IDLE_MS)
        self._chrome_timer.timeout.connect(self._hide_chrome)
        self.setMouseTracking(True)
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
            w.installEventFilter(self)
        # keep the keyboard on the window (Space / arrows), not on a button
        for w in self.findChildren(QPushButton) + [self.vol]:
            w.setFocusPolicy(Qt.NoFocus)

    def _apply_style(self):
        """Window stylesheet in the card's visual language, rebuilt whenever
        the accent changes (quality badge border, accent button, slider fill)."""
        acc = self._accent
        self.setStyleSheet(f"""
            QLabel#a_title   {{ color:{INK}; font-size:34px; font-weight:800; }}
            QLabel#a_artist  {{ color:{SUBTLE}; font-size:20px; }}
            QLabel#a_album   {{ color:{SUBTLE}; font-size:15px; }}
            QLabel#a_time    {{ color:{SUBTLE}; font-size:14px; }}
            QLabel#a_quality {{ color:{acc}; border:1px solid {acc};
                                border-radius:9px; padding:2px 10px;
                                font-size:12px; font-weight:700; }}
            QLabel           {{ background:transparent; }}
            QPushButton {{ border:none; background:rgba(255,255,255,0.10); }}
            QPushButton:hover   {{ background:rgba(255,255,255,0.20); }}
            QPushButton:pressed {{ background:rgba(255,255,255,0.32); }}
            QPushButton[accent="true"]         {{ background:{acc}; }}
            QPushButton[accent="true"]:hover   {{ background:{acc}; }}
            QPushButton[accent="true"]:pressed {{ background:{acc}; }}
            QPushButton:disabled {{ background:rgba(255,255,255,0.04); }}
            QPushButton[accent="true"]:disabled {{ background:rgba(255,255,255,0.10); }}
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

    # ---- feed (called from the widget) ----
    def set_accent(self, accent):
        self._accent = accent or config.ACCENT
        self.progress.accent = self._accent
        self.lyrics.accent = self._accent
        self._apply_style()      # badge border, accent button, slider fill
        self._set_play_icon()    # keep the glyph legible on the new accent
        self.update()

    def set_track(self, cover, title, artist, album=""):
        self._cover = cover
        self.title.setFullText(title or "")
        self.artist.setFullText(artist or "")
        self.album.setFullText(album or "")
        self.album.setVisible(bool(album))
        self._refresh_art()
        self.update()   # repaint the ambient wash

    def set_progress(self, pos, dur, playing):
        self._pos, self._dur, self._playing = pos, dur, bool(playing)
        if dur > 0:
            self.progress.set_fraction(pos / dur)
            self.pos_lbl.setText(_fmt_time(pos))
            self.dur_lbl.setText(_fmt_time(dur))
        else:
            self.progress.set_fraction(0.0)
            self.pos_lbl.setText("--:--")
            self.dur_lbl.setText("--:--")

    def set_lines(self, lines):
        self.lyrics.set_lines(lines)
        if not self._chrome_visible:
            self.lyrics.setCursor(Qt.BlankCursor)  # stay hidden mid-idle

    def set_loading(self):
        self.lyrics.set_loading()

    def set_position(self, sec):
        self.lyrics.set_position(sec)

    def set_playing(self, playing):
        playing = bool(playing)
        changed = playing != self._playing
        self._playing = playing
        self.lyrics.set_playing(playing)
        self._set_play_icon()
        if changed:
            self._refresh_art()   # only the play/pause dim alters the art, so
            #                       skip the per-poll full-size cover rebuild

    def set_capabilities(self, can_seek, can_prev, can_next, can_play=True):
        """Transport capabilities from the backend (via the widget)."""
        self._seekable = bool(can_seek)
        self.progress.set_seekable(self._seekable)
        if not self._chrome_visible:
            self.progress.setCursor(Qt.BlankCursor)  # stay hidden mid-idle
        self.btn_prev.setEnabled(bool(can_prev))
        self.btn_next.setEnabled(bool(can_next))
        self.btn_play.setEnabled(bool(can_play))

    def set_shuffle_repeat(self, shuffle, repeat, can_shuffle, can_repeat):
        """Same semantics as the card: hidden when unsupported, accent-colored
        when active, and the repeat-one glyph for repeat == 1."""
        self.btn_shuffle.setVisible(bool(can_shuffle))
        self.btn_repeat.setVisible(bool(can_repeat))
        acc = self._accent
        self.btn_shuffle.setIcon(icons.shuffle_icon(acc if shuffle else SUBTLE))
        if repeat == 1:
            self.btn_repeat.setIcon(icons.repeat_icon(acc, one=True))
        elif repeat == 2:
            self.btn_repeat.setIcon(icons.repeat_icon(acc))
        else:
            self.btn_repeat.setIcon(icons.repeat_icon(SUBTLE))

    def set_liked(self, liked):
        self._liked = bool(liked)
        self.btn_heart.setIcon(icons.heart_icon(
            LIKE_COLOR if self._liked else SUBTLE, 64, self._liked))

    def set_quality(self, label):
        if label:
            self.quality.setText(label)
            self.quality.setToolTip(f"Available in {label} on TIDAL")
            self.quality.show()
        else:
            self.quality.clear()
            self.quality.hide()

    def set_volume_state(self, level, muted, scope):
        # level < 0 or empty scope -> nothing controllable; hide the row.
        # (The widget guards its volume_changed echo while it pushes here.)
        if level < 0 or not scope:
            self.vol_box.hide()
            return
        self.vol_box.show()
        self.btn_mute.setIcon(icons.volume_icon(INK, muted=bool(muted)))
        self.btn_mute.setToolTip(("Unmute " if muted else "Mute ") + scope)
        self.vol.setToolTip(f"Volume: {scope}")
        if not self.vol.isSliderDown():   # never yank a handle the user holds
            self.vol.setValue(int(round(max(0.0, min(1.0, level)) * 100)))

    def show_on(self, screen):
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._wake_chrome()

    # ---- auto-hiding chrome ----
    def _wake_chrome(self):
        if not self._chrome_visible:
            self._chrome_visible = True
            self.chrome.show()
            self.btn_close.show()
            self.unsetCursor()
            self.lyrics.setCursor(Qt.PointingHandCursor if self.lyrics._synced
                                  else Qt.ArrowCursor)
            self.progress.setCursor(Qt.PointingHandCursor if self._seekable
                                    else Qt.ArrowCursor)
        self._chrome_timer.start()

    def _hide_chrome(self):
        if not self._chrome_visible:
            return
        if self.vol.isSliderDown() or self.progress._dragging:
            self._chrome_timer.start()   # mid-drag: try again once released
            return
        self._chrome_visible = False
        self.chrome.hide()
        self.btn_close.hide()
        # blank the cursor everywhere it could rest (children set their own)
        for w in (self, self.lyrics, self.progress):
            w.setCursor(Qt.BlankCursor)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseMove:
            self._wake_chrome()
        return super().eventFilter(obj, ev)

    def mouseMoveEvent(self, e):
        self._wake_chrome()
        super().mouseMoveEvent(e)

    # ---- internals ----
    def _art_size(self):
        h = self.height() or 1000
        return max(160, int(h * 0.30))

    def _refresh_art(self):
        if self._cover is None or self._cover.isNull():
            self.art.clear()
            return
        s = self._art_size()
        pm = _rounded_cover(self._cover, s, int(s * 0.06))
        if not self._playing:
            pm = _dim_pixmap(pm)
        self.art.setPixmap(pm)

    def _set_play_icon(self):
        oa = _on_accent_color(self._accent)
        self.btn_play.setIcon(icons.pause_icon(oa) if self._playing
                              else icons.play_icon(oa))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_art()
        self.btn_close.move(self.width() - self.btn_close.width() - 24, 24)
        self.btn_close.raise_()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#08080c"))
        if self._cover is not None and not self._cover.isNull():
            # cheap blur: tiny downscale drawn back up, then a dark gradient
            small = self._cover.scaled(42, 42, Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation)
            p.setOpacity(0.55)
            # cover the screen, center-cropped
            scaled = small.scaled(w, h, Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
            x = (scaled.width() - w) // 2
            y = (scaled.height() - h) // 2
            p.drawPixmap(0, 0, scaled, x, y, w, h)
            p.setOpacity(1.0)
        grad = QLinearGradient(QPointF(0, 0), QPointF(0, h))
        grad.setColorAt(0.0, QColor(0, 0, 0, 150))
        grad.setColorAt(0.5, QColor(0, 0, 0, 90))
        grad.setColorAt(1.0, QColor(0, 0, 0, 190))
        p.fillRect(self.rect(), grad)
        p.end()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
        elif k == Qt.Key_Space:
            self.btn_play.click()   # routes through the widget's signal wiring
        elif k in (Qt.Key_Left, Qt.Key_Right) and self._seekable and self._dur > 0:
            step = -10.0 if k == Qt.Key_Left else 10.0
            secs = max(0.0, min(self._dur, self._pos + step))
            # same path as a progress-bar scrub: the widget owns the seek math
            self.progress.seek_requested.emit(secs / self._dur)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # a click used to close from anywhere; with controls on screen, a
        # single background click now just wakes (or keeps) the chrome
        if e.button() == Qt.LeftButton:
            self._wake_chrome()
            e.accept()

    def mouseDoubleClickEvent(self, e):
        # Close only on the empty backdrop. A double-click that lands on any
        # content (art, title/artist/album, quality, lyrics, progress, times or
        # a control) hits a child widget and must never exit the player.
        if e.button() == Qt.LeftButton and self.childAt(e.position().toPoint()) is None:
            self.close()

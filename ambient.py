# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
ambient.py
----------
Fullscreen "now playing" ambient mode: turns a monitor into an Apple-TV-style
screen with a big blurred-cover wash, large album art, title/artist, a progress
bar, and the karaoke LyricsView at room scale. A calm "put on an album and sit
back" view.

Reuses the widget's own pieces (the cheap cover blur, _rounded_cover,
ElidedLabel, ProgressLine, LyricsView with a scale factor) fed by the same
now-playing/lyrics/position stream, so it stays in lock-step with the card and
needs no new dependencies. Esc or a click exits.
"""

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPixmap, QLinearGradient, QGuiApplication
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

import config
from widget import (LyricsView, ProgressLine, ElidedLabel, _rounded_cover,
                    _dim_pixmap, _fmt_time, INK, SUBTLE)


class AmbientWindow(QWidget):
    """Frameless fullscreen now-playing screen. Fed via set_track / set_progress
    / set_lines / set_position / set_accent by the widget."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(None)   # top-level (no parent), so it can go fullscreen
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(
            f"QLabel#a_title {{ color:{INK}; font-size:34px; font-weight:800; }}"
            f"QLabel#a_artist {{ color:{SUBTLE}; font-size:20px; }}"
            f"QLabel#a_time {{ color:{SUBTLE}; font-size:14px; }}"
            "QLabel { background:transparent; }")
        self._cover = None       # full-res QPixmap
        self._playing = False
        self._pos = 0.0
        self._dur = 0.0

        self.art = QLabel(alignment=Qt.AlignCenter)
        self.title = ElidedLabel("")
        self.title.setObjectName("a_title")
        self.title.setAlignment(Qt.AlignCenter)
        self.artist = ElidedLabel("")
        self.artist.setObjectName("a_artist")
        self.artist.setAlignment(Qt.AlignCenter)
        self.progress = ProgressLine()
        self.pos_lbl = QLabel("--:--"); self.pos_lbl.setObjectName("a_time")
        self.dur_lbl = QLabel("--:--"); self.dur_lbl.setObjectName("a_time")
        self.lyrics = LyricsView()
        self.lyrics.set_scale(2.0)

        from PySide6.QtWidgets import QHBoxLayout
        times = QHBoxLayout()
        times.addWidget(self.pos_lbl)
        times.addStretch(1)
        times.addWidget(self.dur_lbl)

        col = QVBoxLayout(self)
        col.setContentsMargins(80, 60, 80, 60)
        col.setSpacing(14)
        col.addStretch(2)
        col.addWidget(self.art, 0, Qt.AlignCenter)
        col.addSpacing(14)
        col.addWidget(self.title)
        col.addWidget(self.artist)
        col.addSpacing(10)
        col.addWidget(self.lyrics, 5)
        col.addSpacing(6)
        col.addWidget(self.progress)
        col.addLayout(times)
        col.addStretch(1)

    # ---- feed (called from the widget) ----
    def set_accent(self, accent):
        self.progress.accent = accent
        self.lyrics.accent = accent
        self.update()

    def set_track(self, cover, title, artist):
        self._cover = cover
        self.title.setFullText(title or "")
        self.artist.setFullText(artist or "")
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

    def set_loading(self):
        self.lyrics.set_loading()

    def set_position(self, sec):
        self.lyrics.set_position(sec)

    def set_playing(self, playing):
        self._playing = bool(playing)
        self.lyrics.set_playing(playing)
        self._refresh_art()

    def show_on(self, screen):
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh_art()

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
        if e.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # a click anywhere that isn't on the lyrics (which seeks) closes it
        if not self.lyrics.geometry().contains(e.position().toPoint()):
            self.close()

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

import time

from PySide6.QtCore import Qt, QSize, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPainterPath, QPen, QLinearGradient,
    QAction, QGuiApplication,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame, QStackedWidget, QSizePolicy,
    QHBoxLayout, QVBoxLayout, QMenu, QGraphicsDropShadowEffect,
)

import config
import icons

# --- geometry --------------------------------------------------------------
MARGIN = 18          # transparent padding so the drop shadow has room
RADIUS = 18          # card corner radius
COMPACT_CARD = (360, 92)
EXPANDED_CARD = (360, 330)
TOGGLE_D = 22        # corner expand/collapse button diameter

# --- palette ---------------------------------------------------------------
INK = "#ffffff"
SUBTLE = "#a9a9b4"
ON_ACCENT = "#06222a"   # icon color that reads on the cyan accent button


def _fmt_time(secs: float) -> str:
    if not secs or secs < 0:
        return "--:--"
    secs = int(secs)
    return f"{secs // 60}:{secs % 60:02d}"


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
    """A thin, non-seekable progress bar painted with the accent color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self.setFixedHeight(4)

    def set_fraction(self, frac: float):
        frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
        if abs(frac - self._frac) > 0.0005:
            self._frac = frac
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(r, rad, rad)
        if self._frac > 0:
            fill = QRectF(r)
            fill.setWidth(max(r.height(), r.width() * self._frac))
            p.setBrush(QColor(config.ACCENT))
            p.drawRoundedRect(fill, rad, rad)
        p.end()


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

        # progress interpolation state
        self._pos = 0.0
        self._dur = 0.0
        self._playing = False
        self._anchor = time.monotonic()

        self._build_ui()
        self._apply_style()

        self._set_mode(self._expanded, anchor=False)
        self._move_to_corner()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start()

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

        self.c_prev = self._round_btn(icons.prev_icon(INK), self.prev_clicked.emit, 30)
        self.c_play = self._round_btn(icons.play_icon(ON_ACCENT),
                                      self.playpause_clicked.emit, 36, accent=True)
        self.c_next = self._round_btn(icons.next_icon(INK), self.next_clicked.emit, 30)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(self.c_prev)
        controls.addWidget(self.c_play)
        controls.addWidget(self.c_next)

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

        self.progress = ProgressLine()
        self.e_pos = QLabel("--:--")
        self.e_pos.setObjectName("time")
        self.e_dur = QLabel("--:--")
        self.e_dur.setObjectName("time")
        times = QHBoxLayout()
        times.setContentsMargins(0, 0, 0, 0)
        times.addWidget(self.e_pos)
        times.addStretch(1)
        times.addWidget(self.e_dur)

        self.e_prev = self._round_btn(icons.prev_icon(INK), self.prev_clicked.emit, 38)
        self.e_play = self._round_btn(icons.play_icon(ON_ACCENT),
                                      self.playpause_clicked.emit, 46, accent=True)
        self.e_next = self._round_btn(icons.next_icon(INK), self.next_clicked.emit, 38)
        controls = QHBoxLayout()
        controls.setSpacing(16)
        controls.addStretch(1)
        controls.addWidget(self.e_prev)
        controls.addWidget(self.e_play)
        controls.addWidget(self.e_next)
        controls.addStretch(1)

        col = QVBoxLayout(page)
        col.setContentsMargins(20, 20, 20, 18)
        col.setSpacing(8)
        col.addLayout(cover_row)
        col.addSpacing(2)
        col.addWidget(self.e_title)
        col.addWidget(self.e_artist)
        col.addStretch(1)
        col.addWidget(self.progress)
        col.addLayout(times)
        col.addSpacing(2)
        col.addLayout(controls)
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

    def _apply_style(self):
        self.setStyleSheet(f"""
            QLabel#title      {{ color:{INK}; font-size:13px; font-weight:600; }}
            QLabel#title_big  {{ color:{INK}; font-size:16px; font-weight:700; }}
            QLabel#artist     {{ color:{SUBTLE}; font-size:11px; }}
            QLabel#time       {{ color:{SUBTLE}; font-size:10px; }}
            QLabel            {{ background:transparent; }}
            QPushButton {{ border:none; background:rgba(255,255,255,0.10); }}
            QPushButton:hover   {{ background:rgba(255,255,255,0.20); }}
            QPushButton:pressed {{ background:rgba(255,255,255,0.32); }}
            QPushButton[accent="true"]         {{ background:{config.ACCENT}; }}
            QPushButton[accent="true"]:hover   {{ background:{config.ACCENT}; }}
            QPushButton[accent="true"]:pressed {{ background:{config.ACCENT}; }}
        """)
        # round each button to a circle via its fixed size
        for b in self.findChildren(QPushButton):
            b.setStyleSheet(f"border-radius:{b.width() // 2}px;")

    # ---- mode toggle -------------------------------------------------------
    def toggle_mode(self):
        self._set_mode(not self._expanded)

    def _set_mode(self, expanded: bool, anchor: bool = True):
        self._expanded = expanded
        card_w, card_h = EXPANDED_CARD if expanded else COMPACT_CARD
        new_w, new_h = card_w + 2 * MARGIN, card_h + 2 * MARGIN

        bottom_right = self.frameGeometry().bottomRight()
        self.stack.setCurrentIndex(1 if expanded else 0)
        self.setFixedSize(new_w, new_h)

        # place the floating toggle button in the card's top-right corner
        self.toggle_btn.setIcon(
            icons.collapse_icon(SUBTLE) if expanded else icons.expand_icon(SUBTLE))
        self.toggle_btn.move(card_w - 8 - TOGGLE_D, 8)
        self.toggle_btn.raise_()

        if anchor:
            new_x = bottom_right.x() - new_w
            new_y = bottom_right.y() - new_h
            self._move_clamped(new_x, new_y)

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
            self._set_play_icon(False)
            self._pos = self._dur = 0.0
            self.progress.set_fraction(0.0)
            self.e_pos.setText("--:--")
            self.e_dur.setText("--:--")
            return

        title = info.get("title") or "Unknown title"
        artist = info.get("artist") or "Unknown artist"
        self.c_title.setFullText(title)
        self.e_title.setFullText(title)
        self.c_artist.setFullText(artist)
        self.e_artist.setFullText(artist)

        self._playing = bool(info.get("playing"))
        self._set_play_icon(self._playing)

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

    def _set_play_icon(self, playing: bool):
        icon = icons.pause_icon(ON_ACCENT) if playing else icons.play_icon(ON_ACCENT)
        for b in self._play_buttons:
            b.setIcon(icon)

    def _refresh_covers(self):
        if self._cover_src is None:
            self.c_cover.clear()
            self.e_cover.clear()
            return
        self.c_cover.setPixmap(_rounded_cover(self._cover_src, 64, 12))
        self.e_cover.setPixmap(_rounded_cover(self._cover_src, 150, 16))

    # ---- progress ----------------------------------------------------------
    def _tick_progress(self):
        if self._playing and self._dur > 0:
            est = self._pos + (time.monotonic() - self._anchor)
            self._update_progress(min(est, self._dur))

    def _update_progress(self, pos: float):
        if self._dur > 0:
            self.progress.set_fraction(pos / self._dur)
            self.e_pos.setText(_fmt_time(pos))
            self.e_dur.setText(_fmt_time(self._dur))
        else:
            self.progress.set_fraction(0.0)
            self.e_pos.setText("--:--")
            self.e_dur.setText("--:--")

    # ---- positioning -------------------------------------------------------
    def _move_to_corner(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 24,
                  geo.bottom() - self.height() - 24)

    def _move_clamped(self, x: int, y: int):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x = max(geo.left(), min(x, geo.right() - self.width()))
        y = max(geo.top(), min(y, geo.bottom() - self.height()))
        self.move(x, y)

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
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle_mode()
            e.accept()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        toggle_act = QAction("Compact" if self._expanded else "Expand", self)
        toggle_act.triggered.connect(self.toggle_mode)
        menu.addAction(toggle_act)
        menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_act)
        menu.exec(e.globalPos())

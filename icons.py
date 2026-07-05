# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
icons.py
--------
Crisp transport icons drawn with QPainter, so we don't depend on icon fonts
or shipping image assets. Each function returns a QIcon at the requested size
and color. Used by widget.py for the play/pause/next/prev/close/toggle buttons.

app_icon() draws the app/brand mark ("E" — three linked nodes with a live pulse
ring on the centre node) used for the tray + window icon. The same mark is what
make_icon.py bakes into icon.ico / icon.png for the packaged .exe.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPainterPath, QPen, QIcon, QLinearGradient,
)


def _canvas(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    return pm, p


def _tri_right(p, color, x0, x1, ymid, half):
    path = QPainterPath()
    path.moveTo(x0, ymid - half)
    path.lineTo(x0, ymid + half)
    path.lineTo(x1, ymid)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def play_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    _tri_right(p, color, size * 0.32, size * 0.74, size * 0.5, size * 0.26)
    p.end()
    return QIcon(pm)


def pause_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    w = size * 0.14
    gap = size * 0.10
    top, h = size * 0.26, size * 0.48
    cx = size / 2
    p.drawRoundedRect(QRectF(cx - gap / 2 - w, top, w, h), 2, 2)
    p.drawRoundedRect(QRectF(cx + gap / 2, top, w, h), 2, 2)
    p.end()
    return QIcon(pm)


def next_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    _tri_right(p, color, size * 0.26, size * 0.60, size * 0.5, size * 0.22)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(size * 0.62, size * 0.28, size * 0.10, size * 0.44), 2, 2)
    p.end()
    return QIcon(pm)


def prev_icon(color="#ffffff", size=64):
    # draw next_icon mirrored
    pm, p = _canvas(size)
    p.translate(size, 0)
    p.scale(-1, 1)
    _tri_right(p, color, size * 0.26, size * 0.60, size * 0.5, size * 0.22)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(size * 0.62, size * 0.28, size * 0.10, size * 0.44), 2, 2)
    p.end()
    return QIcon(pm)


def volume_icon(color="#ffffff", size=64, muted=False):
    pm, p = _canvas(size)
    c = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    bx, by = size * 0.18, size * 0.39
    bw, bh = size * 0.14, size * 0.22
    p.drawRect(QRectF(bx, by, bw, bh))                 # speaker body
    cone = QPainterPath()                              # speaker cone
    cone.moveTo(bx + bw, by)
    cone.lineTo(bx + bw + size * 0.17, by - size * 0.13)
    cone.lineTo(bx + bw + size * 0.17, by + bh + size * 0.13)
    cone.lineTo(bx + bw, by + bh)
    cone.closeSubpath()
    p.drawPath(cone)
    if muted:
        pen = QPen(c)
        pen.setWidthF(size * 0.07)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(size * 0.62, size * 0.36), QPointF(size * 0.84, size * 0.64))
        p.drawLine(QPointF(size * 0.84, size * 0.36), QPointF(size * 0.62, size * 0.64))
    else:
        pen = QPen(c)
        pen.setWidthF(size * 0.06)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(size * 0.50, size * 0.32, size * 0.20, size * 0.36), -55 * 16, 110 * 16)
        p.drawArc(QRectF(size * 0.50, size * 0.22, size * 0.34, size * 0.56), -55 * 16, 110 * 16)
    p.end()
    return QIcon(pm)


def lyrics_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    x = size * 0.24
    for y, w in ((0.30, 0.46), (0.46, 0.34), (0.62, 0.50)):
        p.drawRoundedRect(QRectF(x, size * y, size * w, size * 0.085),
                          size * 0.04, size * 0.04)
    p.end()
    return QIcon(pm)


def close_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.09)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    m = size * 0.34
    p.drawLine(QPointF(m, m), QPointF(size - m, size - m))
    p.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    p.end()
    return QIcon(pm)


def _chevron(color, size, up):
    pm, p = _canvas(size)
    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.09)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    a, b, c = size * 0.30, size * 0.50, size * 0.70
    if up:
        p.drawLine(QPointF(a, c), QPointF(b, a))
        p.drawLine(QPointF(b, a), QPointF(c, c))
    else:
        p.drawLine(QPointF(a, a), QPointF(b, c))
        p.drawLine(QPointF(b, c), QPointF(c, a))
    p.end()
    return QIcon(pm)


def expand_icon(color="#ffffff", size=64):
    return _chevron(color, size, up=True)


def collapse_icon(color="#ffffff", size=64):
    return _chevron(color, size, up=False)


def heart_icon(color="#ffffff", size=64, filled=True):
    """Heart for the 'like / add to collection' button (filled or outline)."""
    pm, p = _canvas(size)
    s = size
    path = QPainterPath()
    path.moveTo(0.50 * s, 0.32 * s)
    path.cubicTo(0.50 * s, 0.22 * s, 0.34 * s, 0.13 * s, 0.20 * s, 0.20 * s)
    path.cubicTo(0.04 * s, 0.29 * s, 0.06 * s, 0.52 * s, 0.50 * s, 0.82 * s)
    path.cubicTo(0.94 * s, 0.52 * s, 0.96 * s, 0.29 * s, 0.80 * s, 0.20 * s)
    path.cubicTo(0.66 * s, 0.13 * s, 0.50 * s, 0.22 * s, 0.50 * s, 0.32 * s)
    path.closeSubpath()
    if filled:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(path)
    else:
        pen = QPen(QColor(color))
        pen.setWidthF(size * 0.085)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# App / brand mark: a vinyl record (outer edge, label ring, spindle) on a
# dark-glass tile. The tile stands in for the smoked "dust cover" you watch the
# spinning record through, which is what the app is named for. Single source of
# truth, shared by the tray/window icon (app_icon) and the .exe (make_icon.py).
# ---------------------------------------------------------------------------

def _draw_record(p, cx, cy, r, accent, detail=True):
    """Paint a vinyl-record mark centred at (cx, cy) with outer radius r, in the
    accent colour: a thick outer edge, an inner label ring and a spindle dot,
    with a faint groove ring added when `detail` (larger sizes only)."""
    p.setRenderHint(QPainter.Antialiasing, True)
    c = QPointF(cx, cy)
    ac = QColor(accent)

    pen = QPen(ac)                       # outer disc edge
    pen.setWidthF(max(1.4, r * 0.15))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(c, r, r)

    if detail:                           # fine grooves clustered near the rim
        g = QColor(accent)
        g.setAlphaF(0.45)
        gpen = QPen(g)
        gpen.setWidthF(max(1.0, r * 0.05))
        p.setPen(gpen)
        p.drawEllipse(c, r * 0.82, r * 0.82)
        p.drawEllipse(c, r * 0.70, r * 0.70)

    p.setPen(Qt.NoPen)                   # solid label disc
    p.setBrush(ac)
    p.drawEllipse(c, r * 0.33, r * 0.33)

    p.setBrush(ac.darker(320))           # spindle hole in the label
    p.drawEllipse(c, max(1.0, r * 0.09), max(1.0, r * 0.09))


def draw_app_icon(p, size, accent="#39d6e0"):
    """Paint the app mark onto an already-open QPainter `p`, filling `size`x`size`
    (transparent outside the rounded tile). Geometry matches the exported PNGs."""
    p.setRenderHint(QPainter.Antialiasing, True)

    # --- dark-glass tile ---
    inset = size * 0.055
    t = size - inset * 2.0
    x0 = inset
    y0 = inset
    rad = t * 0.24

    path = QPainterPath()
    path.addRoundedRect(QRectF(x0, y0, t, t), rad, rad)
    grad = QLinearGradient(QPointF(x0 + t * 0.18, y0), QPointF(x0, y0 + t))
    grad.setColorAt(0.0, QColor("#20202a"))
    grad.setColorAt(1.0, QColor("#0a0a0d"))
    p.fillPath(path, grad)

    if size >= 40:
        pen = QPen(QColor(255, 255, 255, 16))
        pen.setWidthF(max(1.0, size * 0.004))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x0, y0, t, t), rad, rad)

    # --- record mark, centred in the tile (the tile is the dust cover) ---
    small = size <= 32
    cx = x0 + t / 2.0
    cy = y0 + t / 2.0
    r = t * (0.40 if small else 0.33)
    _draw_record(p, cx, cy, r, accent, detail=size >= 44)


def _arrow_corner(p, x, y, dx, dy, size):
    """Two short strokes forming an arrowhead at (x,y) opening toward (dx,dy)."""
    a = size * 0.16
    p.drawLine(QPointF(x, y), QPointF(x - dx * a, y))
    p.drawLine(QPointF(x, y), QPointF(x, y - dy * a))


def shuffle_icon(color="#ffffff", size=64):
    pm, p = _canvas(size)
    s = size
    pen = QPen(QColor(color))
    pen.setWidthF(s * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p1 = QPainterPath()
    p1.moveTo(0.16 * s, 0.32 * s)
    p1.lineTo(0.36 * s, 0.32 * s)
    p1.lineTo(0.80 * s, 0.68 * s)
    p.drawPath(p1)
    _arrow_corner(p, 0.80 * s, 0.68 * s, 1, 1, s)
    p2 = QPainterPath()
    p2.moveTo(0.16 * s, 0.68 * s)
    p2.lineTo(0.36 * s, 0.68 * s)
    p2.lineTo(0.80 * s, 0.32 * s)
    p.drawPath(p2)
    _arrow_corner(p, 0.80 * s, 0.32 * s, 1, -1, s)
    p.end()
    return QIcon(pm)


def repeat_icon(color="#ffffff", size=64, one=False):
    pm, p = _canvas(size)
    s = size
    pen = QPen(QColor(color))
    pen.setWidthF(s * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    r = QRectF(0.20 * s, 0.26 * s, 0.60 * s, 0.48 * s)
    p.drawRoundedRect(r, 0.16 * s, 0.16 * s)
    # arrowheads: top edge pointing right, bottom edge pointing left (classic loop)
    _arrow_corner(p, 0.66 * s, 0.26 * s, 1, -1, s)
    _arrow_corner(p, 0.34 * s, 0.74 * s, -1, 1, s)
    if one:
        f = p.font()
        f.setPixelSize(int(s * 0.30))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignCenter, "1")
    p.end()
    return QIcon(pm)


def app_icon(accent="#39d6e0", size=64):
    """Multi-resolution QIcon for the window / .exe icon. `size` is kept for
    backwards-compatibility but the icon carries every standard size so it stays
    crisp in the taskbar, alt-tab and Explorer."""
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        draw_app_icon(p, s, accent)
        p.end()
        icon.addPixmap(pm)
    return icon


def _draw_mark(p, size, accent, fill=0.92):
    """Paint just the record mark (no tile) scaled to fill the canvas, so it reads
    as large as possible in the system tray on a dark taskbar."""
    _draw_record(p, size / 2.0, size / 2.0, fill * size * 0.46, accent,
                 detail=size >= 40)


def tray_icon(accent="#39d6e0", size=64):
    """Multi-resolution QIcon for the system tray: the mark fills the icon (no
    dark tile) so it doesn't look tiny against the dark taskbar."""
    icon = QIcon()
    for s in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        _draw_mark(p, s, accent)
        p.end()
        icon.addPixmap(pm)
    return icon


def live_tray_icon(cover, playing, frac, accent="#39d6e0"):
    """Tray icon showing the current album art with an accent progress ring.
    `cover` is the full-res cover QPixmap; `frac` is track progress 0..1.
    The cover is dimmed while paused so play state reads even at 16px."""
    icon = QIcon()
    frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    for s in (16, 20, 24, 32, 48):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        ring_w = max(1.5, s * 0.09)
        inset = ring_w + max(1.0, s * 0.05)
        d = s - 2 * inset
        # rounded cover, center-cropped
        path = QPainterPath()
        path.addRoundedRect(QRectF(inset, inset, d, d), d * 0.22, d * 0.22)
        p.save()
        p.setClipPath(path)
        scaled = cover.scaled(int(d), int(d), Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
        p.drawPixmap(int(inset) - (scaled.width() - int(d)) // 2,
                     int(inset) - (scaled.height() - int(d)) // 2, scaled)
        if not playing:
            p.fillRect(QRectF(inset, inset, d, d), QColor(0, 0, 0, 130))
        p.restore()
        # progress ring: faint track + accent arc, clockwise from 12 o'clock
        arc_rect = QRectF(ring_w / 2, ring_w / 2, s - ring_w, s - ring_w)
        pen = QPen(QColor(255, 255, 255, 50))
        pen.setWidthF(ring_w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(arc_rect, 0, 360 * 16)
        if frac > 0:
            pen.setColor(QColor(accent))
            p.setPen(pen)
            p.drawArc(arc_rect, 90 * 16, -int(frac * 360 * 16))
        p.end()
        icon.addPixmap(pm)
    return icon

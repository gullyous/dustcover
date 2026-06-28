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
# App / brand mark — "E": three linked nodes with a live pulse ring on the
# centre node, on a dark-glass tile. Single source of truth, shared by the
# tray/window icon (app_icon, below) and the packaged .exe icon (make_icon.py).
# ---------------------------------------------------------------------------

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

    # --- mark (100x100 design space, scaled into the tile) ---
    small = size <= 32
    ms = t * (0.84 if small else 0.64)
    mx0 = x0 + (t - ms) / 2.0
    my0 = y0 + (t - ms) / 2.0
    sc = ms / 100.0

    def MX(v):
        return mx0 + v * sc

    def MY(v):
        return my0 + v * sc

    ac = QColor(accent)

    # pulse ring on the centre node (only legible at larger sizes)
    if size >= 48:
        ring = QColor(accent)
        ring.setAlphaF(0.5)
        pen = QPen(ring)
        pen.setWidthF(3 * sc)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(MX(50), MY(42)), 14 * sc, 14 * sc)

    # connectors
    pen = QPen(ac)
    pen.setWidthF((7 if small else 6) * sc)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(MX(28), MY(42)), QPointF(MX(72), MY(42)))
    p.drawLine(QPointF(MX(50), MY(42)), QPointF(MX(50), MY(66)))

    # nodes
    p.setPen(Qt.NoPen)
    p.setBrush(ac)
    n_r = (7.5 if small else 7) * sc
    for vx, vy in ((28, 42), (72, 42), (50, 66)):
        p.drawEllipse(QPointF(MX(vx), MY(vy)), n_r, n_r)
    c_r = (10 if small else 9) * sc
    p.drawEllipse(QPointF(MX(50), MY(42)), c_r, c_r)


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
    """Paint just the brand mark (no tile) scaled to fill the canvas, so it reads
    as large as possible in the system tray on a dark taskbar."""
    p.setRenderHint(QPainter.Antialiasing, True)
    # mark bounding box in the 100x100 design space is ~58 wide, centred at (50,53)
    sc = fill * size / 58.0

    def MX(v):
        return size / 2 + (v - 50) * sc

    def MY(v):
        return size / 2 + (v - 53) * sc

    ac = QColor(accent)
    pen = QPen(ac)
    pen.setWidthF(max(1.2, 6.5 * sc))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(MX(28), MY(42)), QPointF(MX(72), MY(42)))
    p.drawLine(QPointF(MX(50), MY(42)), QPointF(MX(50), MY(66)))
    p.setPen(Qt.NoPen)
    p.setBrush(ac)
    for vx, vy in ((28, 42), (72, 42), (50, 66)):
        p.drawEllipse(QPointF(MX(vx), MY(vy)), 7.5 * sc, 7.5 * sc)
    p.drawEllipse(QPointF(MX(50), MY(42)), 10 * sc, 10 * sc)


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

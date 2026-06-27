"""
icons.py
--------
Crisp transport icons drawn with QPainter, so we don't depend on icon fonts
or shipping image assets. Each function returns a QIcon at the requested size
and color. Used by widget.py for the play/pause/next/prev/close/toggle buttons.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QPen, QIcon


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

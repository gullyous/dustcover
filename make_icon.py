"""Generate icon.ico for the packaged app (a dark-glass tile with an accent
play glyph). Run once; PyInstaller embeds the result into the .exe."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPainter, QColor, QPainterPath, QLinearGradient

import config

app = QApplication(sys.argv)


def render(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    r = QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
    rad = size * 0.22

    # dark glass tile
    path = QPainterPath()
    path.addRoundedRect(r, rad, rad)
    grad = QLinearGradient(r.topLeft(), r.bottomLeft())
    grad.setColorAt(0.0, QColor("#16161c"))
    grad.setColorAt(1.0, QColor("#0a0a0d"))
    p.fillPath(path, grad)

    # accent ring
    pen = p.pen()
    pen.setColor(QColor(config.ACCENT))
    pen.setWidthF(size * 0.035)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r, rad, rad)

    # play triangle in accent
    tri = QPainterPath()
    cx, cy = size * 0.5, size * 0.5
    h = size * 0.30
    tri.moveTo(QPointF(cx - h * 0.45, cy - h * 0.55))
    tri.lineTo(QPointF(cx - h * 0.45, cy + h * 0.55))
    tri.lineTo(QPointF(cx + h * 0.62, cy))
    tri.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(config.ACCENT))
    p.drawPath(tri)
    p.end()
    return img


img = render(256)
ok_ico = img.save("icon.ico")
ok_png = img.save("icon.png")
print("icon.ico:", ok_ico)
print("icon.png:", ok_png)

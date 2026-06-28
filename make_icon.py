# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""Generate icon.ico + icon.png for the packaged app.

Draws the brand mark "E" (three linked nodes with a live pulse ring on the
centre node, on a dark-glass tile) at every standard size and writes a proper
MULTI-resolution icon.ico (16/24/32/48/64/128/256) so the .exe stays crisp in
the taskbar, alt-tab and Explorer. Also writes a 256px icon.png.

The mark itself lives in icons.draw_app_icon() so this file and the runtime
tray/window icon never drift. Run once; PyInstaller embeds icon.ico via the
.spec (icon=['icon.ico']).
"""
import sys
import struct

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPainter

import config
import icons

app = QApplication(sys.argv)

SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    icons.draw_app_icon(p, size, config.ACCENT)
    p.end()
    return img


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_ico(entries):
    """entries: list of (size, png_bytes) -> bytes of a multi-image .ico."""
    count = len(entries)
    out = struct.pack("<HHH", 0, 1, count)          # ICONDIR
    offset = 6 + count * 16
    for size, data in entries:
        w = 0 if size >= 256 else size              # 0 == 256 in the ICO spec
        out += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in entries:
        out += data
    return out


def main():
    entries = [(s, png_bytes(render(s))) for s in SIZES]

    with open("icon.ico", "wb") as f:
        f.write(build_ico(entries))

    render(256).save("icon.png")
    print("icon.ico: %d sizes (%s)" % (len(SIZES), ", ".join(map(str, SIZES))))
    print("icon.png: 256")


if __name__ == "__main__":
    main()

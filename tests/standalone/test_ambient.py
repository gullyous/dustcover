import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QMouseEvent, QKeyEvent
from PySide6.QtCore import Qt, QEvent, QPointF
app = QApplication(sys.argv)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

from ambient import AmbientWindow
from widget import NowPlayingWidget

pm = QPixmap(200, 200); pm.fill(QColor("#334455"))

def dbl(x=10, y=10):
    return QMouseEvent(QEvent.MouseButtonDblClick, QPointF(x, y),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
def keyev(k):
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)

# ---- Fix: set_playing rebuilds the (expensive) art ONLY on a real state change,
#          not on every 500ms poll -------------------------------------------
a = AmbientWindow()
a.set_track(pm, "S", "A", "Al")
calls = []
a._refresh_art = lambda: calls.append(1)
a._playing = True
a.set_playing(True)                       # unchanged
check("set_playing same-state does NOT rebuild art", calls == [])
a.set_playing(False)                      # changed -> one rebuild
check("set_playing on change rebuilds art once", calls == [1])
a.set_playing(False)                      # unchanged again
check("set_playing same-state (2) no extra rebuild", calls == [1])

# ---- Fix: double-click closes ONLY on the empty backdrop, never on content --
b = AmbientWindow()
closed = []
b.close = lambda: closed.append(1)        # spy (also dodges WA_DeleteOnClose)
b.childAt = lambda p: b.art               # click landed on the album art
b.mouseDoubleClickEvent(dbl())
check("double-click on content does NOT close the player", closed == [])
b.childAt = lambda p: None                # click landed on bare backdrop
b.mouseDoubleClickEvent(dbl())
check("double-click on the backdrop closes the player", closed == [1])

# ---- Fix: when playback goes unavailable, the ambient window is cleared,
#          not left showing the last track's art/text/lyrics ------------------
w = NowPlayingWidget()
amb = AmbientWindow()
w._ambient = amb
amb.set_track(pm, "Song", "Artist", "Album")
amb.set_lines([(0.0, "line one"), (5.0, "line two")])
check("precondition: ambient is showing a track",
      amb._cover is not None and amb.title._full == "Song" and amb.lyrics._lines)
w.on_update({"available": False})
check("unavailable clears the ambient cover art", amb._cover is None)
check("unavailable clears ambient title/artist/album",
      amb.title._full == "" and amb.artist._full == "" and amb.album._full == "")
check("unavailable clears the ambient lyrics", amb.lyrics._lines == [])

# ---- Fix: the card parks behind the player and returns instantly on close,
#          and the game-mode watcher stays out of it while the player is open -
w.show()
check("precondition: card visible", w.isVisible())
w._hidden_for_ambient = True
w.hide()
w._on_ambient_closed()
check("closing the player restores the card immediately",
      w.isVisible() and not w._hidden_for_ambient)
check("closing the player clears the ambient reference", w._ambient is None)

import config as _cfg
_cfg.HIDE_ON_FULLSCREEN = True
w._ambient = amb
w._ambient_open = lambda: True            # simulate the player being open
w.show(); w._auto_hidden = False
w.on_fullscreen(True)
check("watcher does NOT hide the card while the player is open",
      w.isVisible() and not w._auto_hidden)

# ---- baseline behaviours (locked in): keyboard seek math, Space, volume row --
c = AmbientWindow()
seeks = []
c.progress.seek_requested.connect(lambda f: seeks.append(round(f, 4)))
c._pos, c._dur, c._seekable = 30.0, 200.0, True
c.keyPressEvent(keyev(Qt.Key_Right)); c.keyPressEvent(keyev(Qt.Key_Left))
check("Right/Left seek by +/-10s as a fraction", seeks == [0.2, 0.1])
seeks.clear(); c._pos = 195.0
c.keyPressEvent(keyev(Qt.Key_Right))
check("seek clamps at the end (<= 1.0)", seeks == [1.0])
seeks.clear(); c._pos = 3.0
c.keyPressEvent(keyev(Qt.Key_Left))
check("seek clamps at the start (>= 0.0)", seeks == [0.0])
seeks.clear(); c._seekable = False
c.keyPressEvent(keyev(Qt.Key_Right))
check("arrows do nothing when the track is not seekable", seeks == [])
clicks = []
c.btn_play.clicked.connect(lambda: clicks.append(1))
c.keyPressEvent(keyev(Qt.Key_Space))
check("Space triggers play/pause", clicks == [1])
c.set_volume_state(0.5, False, "TIDAL")
check("volume row shown when a session is controllable", not c.vol_box.isHidden())
c.set_volume_state(-1, False, "")
check("volume row hidden when nothing is controllable", c.vol_box.isHidden())

print("\nAmbient:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

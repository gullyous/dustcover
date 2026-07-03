import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter
from PySide6.QtCore import QBuffer
app = QApplication(sys.argv)
import config
from widget import NowPlayingWidget

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# 1) apply_settings with AUTO_ACCENT + cover: the review's HIGH bug
w = NowPlayingWidget()
duo = QPixmap(24, 24); duo.fill(QColor(200, 40, 40))
p = QPainter(duo); p.fillRect(0, 0, 12, 24, QColor(40, 90, 200)); p.end()
w._cover_src = duo
config.AUTO_ACCENT = True
try:
    w.apply_settings()
    check("apply_settings with auto-accent + cover", True)
except AttributeError as e:
    check(f"apply_settings with auto-accent + cover ({e})", False)
check("apply_settings refreshes both accents",
      w._accent_dyn is not None and w._accent2_dyn is not None)
config.AUTO_ACCENT = False
w.apply_settings()
check("apply_settings clears accents when off",
      w._accent_dyn is None and w._accent2_dyn is None)

# 2) album change under same title/artist resets the hires gate
w2 = NowPlayingWidget()
w2._cur_title, w2._cur_artist = "Song", "Artist"
w2._logged_in = True
reqs = []
w2.cover_requested.connect(lambda t, a: reqs.append((t, a)))
big = QPixmap(400, 400); big.fill(QColor(9, 9, 9))
buf = QBuffer(); buf.open(QBuffer.ReadWrite); big.save(buf, "PNG")
w2.on_cover_hires("Song", "Artist", bytes(buf.data()))
check("hires applied", w2._cover_hires)
# same title/artist, art_changed fires (album changed)
w2.on_update({"available": True, "title": "Song", "artist": "Artist",
              "album": "Other Album", "playing": True, "position": 1,
              "duration": 100, "art_changed": True, "art": None})
check("album change resets hires gate", not w2._cover_hires)
check("album change re-requests cover", ("Song", "Artist") in reqs)

# 3) show/hide own the game-mode flag
config.HIDE_ON_FULLSCREEN = True
w3 = NowPlayingWidget()
w3.show()
w3.on_fullscreen(True)          # auto-hidden
check("auto hidden", w3._auto_hidden and not w3.isVisible())
w3._show_widget()               # CLI --cmd show
check("cmd show clears flag", not w3._auto_hidden and w3.isVisible())
w3._hide_widget()               # CLI --cmd hide
check("cmd hide keeps flag cleared", not w3._auto_hidden)
w3.on_fullscreen(False)         # game exits: must NOT re-show
check("explicit hide survives game exit", not w3.isVisible())

# 4) sign-in mid-track requests the cover too
w4 = NowPlayingWidget()
w4._cur_title, w4._cur_artist = "Now", "Playing"
creq = []
w4.cover_requested.connect(lambda t, a: creq.append((t, a)))
w4.on_login_state(True, "")
check("sign-in requests full-res cover", creq == [("Now", "Playing")])

print("\nV140Fixes:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

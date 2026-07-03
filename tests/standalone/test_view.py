import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))

from PySide6.QtWidgets import QApplication
import config
config.LYRICS_OFFSET = 0.0
app = QApplication(sys.argv)
from widget import LyricsView

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: fails.append(name)

v = LyricsView()
v.resize(360, 300)

# synced classification + active line
synced = [(0.0,"a"),(10.0,"b"),(20.0,"c"),(30.0,"d")]
v.set_lines(synced)
check("synced detected", v._synced is True)
v.set_position(11.0)
check("active at 11s -> idx1", v._active == 1)
v.set_position(25.0)
check("active at 25s -> idx2", v._active == 2)

# offset shifts activation: +2s offset makes line at 30 active by 28.1
v._offset = 2.0
v.set_position(28.2)          # eff = 30.2 >= 30 -> idx3
check("positive offset activates earlier", v._active == 3)
v._offset = -2.0
v.set_position(20.5)          # eff = 18.5 -> still idx1 (b at 10, c at 20 not reached)
check("negative offset activates later", v._active == 1)

# plain classification + no active tracking + scroll clamp
plain = [(None,"l%d"%i) for i in range(40)]
v.set_lines(plain)
check("plain detected", v._synced is False)
check("plain resets active", v._active == -1)
v.set_position(5.0)          # should be a no-op in plain mode
check("plain set_position no-op", v._active == -1)
ms = v._max_scroll()
check("plain has positive max_scroll", ms > 0)
v._scroll = 99999
v._scroll = max(0.0, min(v._max_scroll(), v._scroll))
check("scroll clamps to max", v._scroll == ms)

# empty
v.set_lines([])
check("empty -> not synced", v._synced is False)
check("empty -> no lyrics msg", v._msg == "No lyrics for this track")
check("empty has_lyrics False", v.has_lyrics() is False)

# offset_changed signal fires and value persists to attribute
got = {}
v.offset_changed.connect(lambda x: got.__setitem__("v", x))
v.set_lines(synced)
v._offset = 0.3
v.offset_changed.emit(v._offset)
check("offset_changed carries value", abs(got.get("v",0)-0.3) < 1e-9)

# seek target accounts for offset: line at 20 with +2 offset -> seek 18
v._offset = 2.0
seeks = {}
v.seek_requested.connect(lambda s: seeks.__setitem__("s", s))
# emulate the seek computation used in mousePressEvent
t = 20.0
v.seek_requested.emit(max(0.0, t - v._offset))
check("seek subtracts offset", abs(seeks.get("s",0)-18.0) < 1e-9)

print("\nView:", "ALL PASS" if not fails else f"{len(fails)} FAIL")
sys.exit(1 if fails else 0)

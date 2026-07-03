import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter
app = QApplication(sys.argv)
from widget import LyricsView

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

v = LyricsView(); v.resize(360, 260); h = 260

# --- edge fade math ---
check("fade 0 at top edge", abs(v._edge_fade(0, h)) < 1e-9)
check("fade 0 at bottom edge", abs(v._edge_fade(h, h)) < 1e-9)
check("fade 1 in the middle", v._edge_fade(h/2, h) == 1.0)
check("fade ramps ~half at 24px", abs(v._edge_fade(24, h) - 24/48.0) < 1e-9)
check("fade near top is partial", 0 < v._edge_fade(20, h) < 1.0)
check("fade never negative/over1", all(0 <= v._edge_fade(y, h) <= 1 for y in range(-40, h+40, 7)))

# --- tighter lookahead ---
check("lookahead reduced to 0.06", abs(v.ACTIVE_LEAD - 0.06) < 1e-9)
v.set_lines([(10.0,"a"),(12.0,"b"),(14.0,"c")])
v._offset = 0.0
v.set_position(11.90)   # 0.10s before line b(12.0): with 0.06 lead, NOT yet active
check("no premature highlight at -0.10s", v._active == 0)
v.set_position(11.95)   # 0.05s before: within the 0.06 lead -> active
check("highlights within 0.06s lead", v._active == 1)

# --- paint smoke: synced + plain render with fades, no crash ---
v.set_lines([(float(i), f"line {i}") for i in range(20)])
v.set_position(9.0)
pm = QPixmap(360, 260); pm.fill(QColor("black"))
p = QPainter(pm); v._paint_synced(p, 360, 260); p.end()
check("synced paint with edge fade smokes", True)

v.set_lines([(None, f"plain {i}") for i in range(30)])
pm2 = QPixmap(360, 260); pm2.fill(QColor("black"))
p2 = QPainter(pm2); v._paint_plain(p2, 360, 260); p2.end()
check("plain paint with edge fade smokes", True)

# full paintEvent path (calls the mask + badge) via update/render
v.set_lines([(float(i), f"L{i}") for i in range(12)])
v._synced = True; v.set_position(5.0)
v.render(QPixmap(360, 260))
check("full render smokes", True)

print("\nLyricsUI:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

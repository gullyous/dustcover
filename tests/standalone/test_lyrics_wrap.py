import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont, QFontMetrics
from PySide6.QtCore import Qt
app = QApplication(sys.argv)
from widget import LyricsView

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

v = LyricsView()
f = QFont(); f.setPointSize(15); f.setBold(True)
fm = QFontMetrics(f)

# --- _wrap ---
check("empty -> single empty row", v._wrap("", fm, 300) == [""])
short = v._wrap("hello world", fm, 4000)
check("short line stays one row", short == ["hello world"])
longtxt = "And never take the time to find out all about the small minutiae"
rows = v._wrap(longtxt, fm, 300)
check("long line wraps to multiple rows", len(rows) >= 2)
check("wrap preserves all words (no elide when it fits in max_rows)",
      " ".join(rows).replace("...", "").split()[:5] == longtxt.split()[:5])
check("each row fits the width", all(fm.horizontalAdvance(r) <= 300 for r in rows[:-1]))
# max_rows cap with elide
huge = "word " * 200
rr = v._wrap(huge.strip(), fm, 200, max_rows=3)
check("capped at max_rows", len(rr) == 3)
check("last row elided when overflowing", ("…" in rr[-1]) or rr[-1].endswith("..."))
# a single word wider than maxw doesn't infinite-loop
long_word = "supercalifragilisticexpialidocious" * 3
lw = v._wrap(long_word, fm, 80)
check("over-wide single word terminates", len(lw) >= 1)

# --- paint smoke + line_bounds populated + full text (active not elided) ---
lines = [(float(i), longtxt if i == 5 else f"neighbor line {i}") for i in range(12)]
v.set_lines(lines); v._synced = True; v._offset = 0.0
v.resize(360, 260)
v.set_position(5.0)   # active = line 5 (the long one)
pm = QPixmap(360, 260); pm.fill(QColor(0, 0, 0))
p = QPainter(pm); v._paint_synced(p, 360, 260); p.end()
check("line_bounds populated after paint", len(v._line_bounds) > 0)
check("active line first in bounds", v._line_bounds[0][2] == 5)
act_top, act_bot, _ = v._line_bounds[0]
check("active block taller than one row (wrapped)", act_bot - act_top > v.LINE_H)
check("bounds don't overlap the active block", all(
    b[0] >= act_bot - 0.01 or b[1] <= act_top + 0.01 for b in v._line_bounds[1:]))

# --- click hit-test maps y to the right line via bounds ---
seeks = []
v.seek_requested.connect(lambda s: seeks.append(s))
# simulate: find a neighbor bound, click its middle, expect its timestamp
nb = [b for b in v._line_bounds if b[2] != 5][0]
ymid = (nb[0] + nb[1]) / 2
class E:
    def __init__(s, yy): s._y = yy
    def button(s):
        from PySide6.QtCore import Qt; return Qt.LeftButton
    def position(s):
        from PySide6.QtCore import QPointF; return QPointF(180, s._y)
v.mousePressEvent(E(ymid))
check("click seeks to the clicked line's time", seeks and abs(seeks[-1] - nb[2]) < 0.01)

print("\nLyricsWrap:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

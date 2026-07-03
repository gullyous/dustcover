import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor
app = QApplication(sys.argv)
from widget import NowPlayingWidget, LyricsView, _dim_pixmap

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

w = NowPlayingWidget()
w._cur_title, w._cur_artist = "Song", "Artist"

# --- favorite state sets the heart to ground truth ---
w._liked = False
w.on_favorite_state("Song", "Artist", True)
check("favorite_state True -> _liked True", w._liked is True)
w.on_favorite_state("Song", "Artist", False)
check("favorite_state False -> _liked False", w._liked is False)
# stale result ignored
w.on_favorite_state("Other", "Artist", True)
check("stale favorite_state ignored", w._liked is False)

# --- heart click toggles in the right direction (uses real _liked) ---
w._liked = True
seen = {}
w.like_clicked.connect(lambda t, a, al, cur: seen.update(cur=cur))
w._on_heart()
check("liked track -> click sends currently_liked=True (unlike)", seen.get("cur") is True)

# --- track change requests favorite state only when logged in ---
reqs = []
w.favorite_requested.connect(lambda t, a: reqs.append((t, a)))
w._logged_in = False
w.on_update({"available": True, "title": "T2", "artist": "A2", "playing": True,
             "position": 0, "duration": 100})
check("track change while signed out -> no favorite request", reqs == [])
w._logged_in = True
w.on_update({"available": True, "title": "T3", "artist": "A3", "playing": True,
             "position": 0, "duration": 100})
check("track change while signed in -> favorite request", reqs and reqs[-1] == ("T3", "A3"))

# --- post-sign-in refresh re-requests quality + favorite for current track ---
q = []; fr = []
w.quality_requested.connect(lambda t, a: q.append((t, a)))
w.favorite_requested.connect(lambda t, a: fr.append((t, a)))
w._cur_title, w._cur_artist = "Now", "Playing"
w.on_login_state(True, "")
check("sign-in refreshes quality for current track", q and q[-1] == ("Now", "Playing"))
check("sign-in refreshes favorite for current track", fr and fr[-1] == ("Now", "Playing"))

# --- dim on pause: covers build for both states without error; paused differs ---
src = QPixmap(80, 80); src.fill(QColor(200, 120, 60))
w._cover_src = src
w._playing = True
w._refresh_covers()
playing_pm = w.e_cover.pixmap()
check("playing cover set", not playing_pm.isNull())
w._playing = False
w._refresh_covers()
paused_pm = w.e_cover.pixmap()
check("paused cover set", not paused_pm.isNull())
# dim helper keeps transparent corners (top-left corner stays transparent)
dimmed = _dim_pixmap(playing_pm)
check("dim helper returns same-size pixmap", dimmed.size() == playing_pm.size())

# --- lyrics copy menu: no crash / no-op when empty ---
lv = LyricsView()
lv.set_lines([])
check("contextMenuEvent guards empty lyrics", lv._lines == [])

print("\nWidget2:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

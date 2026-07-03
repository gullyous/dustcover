import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import tidal_likes as tl
from widget import NowPlayingWidget

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

class FA:
    def __init__(s, n): s.name = n
class FT:
    def __init__(s, i, n, a): s.id = i; s.name = n; s.artists = [FA(a)]
class FF:
    def __init__(s, ids): s._t = [FT(i, f"t{i}", "x") for i in ids]; s.added = []; s.removed = []
    def tracks(s, limit=50, offset=0): return s._t[offset:offset + limit]
    def add_track(s, t): s.added.append(t)
    def remove_track(s, t): s.removed.append(t)
class FU:
    def __init__(s, f): s.favorites = f
class FS:
    def __init__(s, f, m): s.user = FU(f); s._m = m; s.searches = 0
    def search(s, q, models=None): s.searches += 1; return {"tracks": s._m.get(q, [])}

m = {"Song Artist": [FT(2, "Song", "Artist")], "New Artist": [FT(5, "New", "Artist")]}

# user override wins over the bulk set (unlike a set member -> False)
lk = tl.TidalLiker(); lk._session = FS(FF([1, 2, 3]), m)
got = []; lk.favorite_state.connect(lambda t, a, f: got.append(f))
lk._toggle_worker("Song", "Artist", "", True)   # unlike track 2
lk._favorite_worker("Song", "Artist")
check("user unlike overrides bulk set -> False", got[-1] is False)

# completeness guard: incomplete set + unknown track -> NO emit (heart unchanged)
lk2 = tl.TidalLiker(); lk2._session = FS(FF([]), m)
lk2._fav_ids = set(); lk2._fav_complete = False
g2 = []; lk2.favorite_state.connect(lambda t, a, f: g2.append(f))
lk2._favorite_worker("Song", "Artist")
check("incomplete set + unknown -> no emit", g2 == [])
lk2._fav_complete = True
lk2._favorite_worker("Song", "Artist")
check("complete set + unknown -> emits False", g2 == [False])

# _load_fav_ids marks a fully-paged collection complete
lk3 = tl.TidalLiker(); lk3._session = FS(FF([1, 2]), m)
ids = lk3._load_fav_ids()
check("small collection -> complete", lk3._fav_complete is True and ids == {"1", "2"})

# widget heart-ownership guard
w = NowPlayingWidget(); w._cur_title, w._cur_artist = "S", "A"; w._logged_in = True
w.on_like_result(True, "added", "x")
check("like sets owned + liked", w._liked is True and w._heart_user_owned is True)
w.on_favorite_state("S", "A", False)      # stale ground truth
check("owned heart ignores in-flight ground truth", w._liked is True)
w.on_update({"available": True, "title": "S2", "artist": "A2", "playing": True,
             "position": 0, "duration": 10})
check("track change clears ownership", w._heart_user_owned is False)
w.on_favorite_state("S2", "A2", True)
check("after reset, ground truth applies", w._liked is True)

print("\nFixes:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

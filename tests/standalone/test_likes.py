import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import tidal_likes as tl

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

class FArtist:
    def __init__(s, name): s.name = name
class FTrack:
    def __init__(s, i, name, artist):
        s.id = i; s.name = name; s.artists = [FArtist(artist)]
class FFav:
    def __init__(s, ids):
        s._t = [FTrack(i, f"t{i}", "x") for i in ids]
        s.added = []; s.removed = []; s.calls = 0; s.raise_on_tracks = False
    def tracks(s, limit=50, offset=0):
        s.calls += 1
        if s.raise_on_tracks: raise RuntimeError("api down")
        return s._t[offset:offset + limit]
    def add_track(s, tid): s.added.append(tid)
    def remove_track(s, tid): s.removed.append(tid)
class FUser:
    def __init__(s, favs): s.favorites = favs
class FSession:
    def __init__(s, favs, smap):
        s.user = FUser(favs); s._smap = smap; s.searches = 0
    def search(s, q, models=None):
        s.searches += 1
        return {"tracks": s._smap.get(q, [])}

smap = {"Song Artist": [FTrack(2, "Song", "Artist")],
        "Other Artist": [FTrack(99, "Other", "Artist")],
        "New Artist": [FTrack(5, "New", "Artist")]}

liker = tl.TidalLiker()
favs = FFav([1, 2, 3])
liker._session = FSession(favs, smap)
got = []
liker.favorite_state.connect(lambda t, a, f: got.append((t, a, f)))

liker._favorite_worker("Song", "Artist")
check("favorited track -> True", got and got[-1] == ("Song", "Artist", True))
liker._favorite_worker("Other", "Artist")
check("non-favorited -> False", got[-1] == ("Other", "Artist", False))
check("fav ids loaded once as set", liker._fav_ids == {"1", "2", "3"})

before = liker._session.searches
liker._favorite_worker("Song", "Artist")
check("catalog match cached (no re-search)", liker._session.searches == before)

fav_calls_before = favs.calls
liker._favorite_worker("Other", "Artist")
check("fav ids not re-paged", favs.calls == fav_calls_before)

# toggle add updates the cached fav set
liker._toggle_worker("New", "Artist", "", False)
check("toggle add updates fav set", "5" in liker._fav_ids and favs.added == [5])
# a subsequent favorite check reflects it
liker._favorite_worker("New", "Artist")
check("newly-liked reads as favorited", got[-1] == ("New", "Artist", True))
# toggle remove updates the cached fav set
liker._toggle_worker("Song", "Artist", "", True)
check("toggle remove updates fav set", "2" not in liker._fav_ids and favs.removed == [2])

# signed out -> emits False
liker2 = tl.TidalLiker(); liker2._session = None
g2 = []
liker2.favorite_state.connect(lambda t, a, f: g2.append((t, a, f)))
liker2._favorite_worker("Song", "Artist")
check("signed out -> emits False", g2 == [("Song", "Artist", False)])

# tidalapi error -> degrade: no emit, no crash
liker3 = tl.TidalLiker()
favs3 = FFav([1]); favs3.raise_on_tracks = True
liker3._session = FSession(favs3, smap)
g3 = []
liker3.favorite_state.connect(lambda t, a, f: g3.append(1))
liker3._favorite_worker("Song", "Artist")
check("api error degrades (no emit)", g3 == [])

# invalidate_caches clears everything
liker._invalidate_caches()
check("invalidate clears caches", liker._fav_ids is None and liker._track_cache == {})

print("\nLikes:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

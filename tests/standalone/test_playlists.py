import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import tidal_likes as tl

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

class FA:
    def __init__(s, n): s.name = n
class FT:
    def __init__(s, i, n, a): s.id = i; s.name = n; s.artists = [FA(a)]
class FPlaylist:
    def __init__(s, i, name): s.id = i; s.name = name; s.added = []
    def add(s, ids): s.added.extend(ids); return [1]
class FReadonly:   # a followed playlist we DON'T own -> no .add
    def __init__(s, i, name): s.id = i; s.name = name
class FUser:
    def __init__(s, pls): s._pls = pls; s.created = []
    def playlists(s): return s._pls
    def create_playlist(s, title, desc, parent_id="root"):
        p = FPlaylist("new99", title); s.created.append(p); return p
class FSession:
    def __init__(s, pls, smap):
        s.user = FUser(pls); s._m = smap
        s.token_type=s.access_token=s.refresh_token=s.expiry_time="x"
    def search(s, q, models=None): return {"tracks": s._m.get(q, [])}

smap = {"Song Artist": [FT(7, "Song", "Artist")]}
mine = FPlaylist("p1", "Chill"); ro = FReadonly("p2", "Someone Else's")
lk = tl.TidalLiker(); lk._session = FSession([mine, ro], smap)

# list: only OWN (editable) playlists surface
got = []
lk.playlists_ready.connect(lambda pls: got.append(pls))
lk._playlists_worker()
check("lists only editable playlists", got and got[-1] == [("p1", "Chill")])

# add to an existing playlist
res = []
lk.playlist_result.connect(lambda ok, name: res.append((ok, name)))
lk._add_to_playlist_worker("Song", "Artist", "p1")
check("add succeeds", res and res[-1] == (True, "Chill"))
check("track id added to playlist", mine.added == ["7"])

# nomatch -> failure, playlist untouched
lk._add_to_playlist_worker("Nope", "Nobody", "p1")
check("no catalog match -> failure", res[-1][0] is False)

# unknown playlist id -> failure
lk._add_to_playlist_worker("Song", "Artist", "zzz")
check("unknown playlist -> failure", res[-1][0] is False)

# create-with-track
lk._create_playlist_worker("Song", "Artist", "Fresh Mix")
check("create playlist succeeds", res[-1] == (True, "Fresh Mix"))
check("created playlist got the track", lk._session.user.created[-1].added == ["7"])
check("new playlist appended to cache", any(n == "Fresh Mix" for _p, _i, n in lk._playlists))

# signed out
lk2 = tl.TidalLiker(); lk2._session = None
g2 = []
lk2.playlists_ready.connect(lambda pls: g2.append(pls))
lk2._playlists_worker()
check("signed out -> empty list", g2 == [[]])
r2 = []
lk2.playlist_result.connect(lambda ok, name: r2.append(ok))
lk2._add_to_playlist_worker("Song", "Artist", "p1")
check("signed out add -> failure", r2 == [False])

# invalidate clears the playlist cache
lk._invalidate_caches()
check("invalidate clears playlist cache", lk._playlists is None)

print("\nPlaylists:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

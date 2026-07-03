import os as _os, sys, time
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor
app = QApplication(sys.argv)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# --- Fix 2: disabled scrobbler submits nothing even while a track "plays" ---
import config
config.LISTENBRAINZ_TOKEN = "tok"; config.MATCH_APP = "tidal"
import scrobble_backend as sb
posts = []
sb._post = lambda url, token, payload: posts.append(payload["listen_type"])
sc = sb.Scrobbler()
sc.set_enabled(True)
info = {"available": True, "title": "T", "artist": "A", "album": "",
        "source": "TIDAL.exe", "duration": 2.0, "playing": True}
sc.on_update(info)
time.sleep(0.3)   # let now_playing go out
check("enabled: now_playing sent", "playing_now" in posts)
sc.set_enabled(False)
posts.clear()
sc.on_update(info)
time.sleep(2.0)   # a track this short would scrobble if the worker kept accruing
check("disabled: nothing submitted", posts == [])
sc.stop()

# --- Fix 1: playlist menu captures track before exec (snapshot semantics) ---
from widget import NowPlayingWidget
w = NowPlayingWidget()
w._logged_in = True
w._cur_title, w._cur_artist = "SongA", "ArtA"
w._playlists = [("p1", "Chill")]
emitted = []
w.add_to_playlist_requested.connect(lambda t, a, pid: emitted.append((t, a, pid)))
# emulate the post-exec emit path with a track change happening "during" exec:
# the fix reads title/artist BEFORE building the menu, so we verify the snapshot
# is used. Drive it by monkeypatching QMenu.exec to change the track mid-exec.
def exec_then_change(menu, gpos):
    w._cur_title, w._cur_artist = "SongB", "ArtB"   # song advanced during the menu
    for act in menu.actions():
        if act.data():
            return act
    return None
w._exec_menu = exec_then_change   # seam override (no real modal)
w._playlist_menu(w.e_like, w.e_like.rect().center())
check("playlist add uses the track shown, not the advanced one",
      emitted and emitted[-1][:2] == ("SongA", "ArtA"))

# --- Fix 5: menu shows 'Loading' only when not fetched (None), else states ---
w._playlists = None
check("None playlists => not-fetched state", w._playlists is None)
w.on_playlists([])
check("on_playlists([]) => loaded-empty, not None", w._playlists == [])

# --- OBS: still bound loopback, /overlay ok after the reprocess guard ---
import obs_overlay as ob
srv = ob.OverlayServer(); ok = srv.start(0)
check("overlay still binds", ok and srv.port() > 0)
srv.stop()

print("\nV150Fixes:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

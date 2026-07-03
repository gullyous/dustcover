import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QPainter
app = QApplication(sys.argv)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# ---------- karaoke wipe ----------
from widget import LyricsView
v = LyricsView(); v.resize(360, 300)
v.set_lines([(10.0, "a"), (14.0, "b"), (30.0, "c")])
v._active = 0
v._last_sec = 12.0; v._last_mono = None; v._advancing = False; v._offset = 0.0
check("wipe mid-line = 0.5", abs(v._wipe_frac(12.0) - 0.5) < 1e-6)
check("wipe before line = 0", v._wipe_frac(9.0) == 0.0)
check("wipe past line = 1", v._wipe_frac(14.5) == 1.0)
v._active = 1   # line b..c is a 16s gap; wipe capped at WIPE_MAX (8s)
check("wipe capped at WIPE_MAX", abs(v._wipe_frac(18.0) - 0.5) < 1e-6)
v._active = 2   # last line: 5s default duration
check("last line uses 5s default", abs(v._wipe_frac(32.5) - 0.5) < 1e-6)

# extrapolation between ticks
v.set_position(20.0)
v._advancing = True
v._last_mono = time.monotonic() - 1.0   # pretend a second has passed
check("now_eff extrapolates while playing", abs(v._now_eff() - 21.0) < 0.1)
v._advancing = False
v._last_mono = time.monotonic() - 1.0
v._last_sec = 20.0
check("now_eff frozen while paused", abs(v._now_eff() - 20.0) < 1e-6)

# anim timer gating: needs synced + advancing + visible
v.show()
v.set_playing(True)
check("anim runs when synced+playing+visible", v._anim.isActive())
v.set_playing(False)
check("anim stops on pause", not v._anim.isActive())
v.set_playing(True); v.hide()
check("anim stops when hidden", not v._anim.isActive())

# paint smoke (wipe + dots paths execute without error)
v.show(); v.set_position(11.0)
pm = QPixmap(360, 300); pm.fill(QColor("black"))
p = QPainter(pm); v._paint_synced(p, 360, 300); p.end()
check("synced paint with wipe smokes", True)

# ---------- duotone ----------
from widget import NowPlayingWidget
w = NowPlayingWidget()
duo = QPixmap(24, 24); duo.fill(QColor(200, 40, 40))
pnt = QPainter(duo); pnt.fillRect(0, 0, 12, 24, QColor(40, 90, 200)); pnt.end()
c1, c2 = w._compute_accents(duo)
check("duotone picks two colors", c1 is not None and c2 is not None and c1 != c2)
h1 = QColor(c1).getHsv()[0]; h2 = QColor(c2).getHsv()[0]
d = abs(h1 - h2); d = min(d, 360 - d)
check("duotone hues >= 60 deg apart", d >= 60)
mono = QPixmap(24, 24); mono.fill(QColor(200, 60, 60))
m1, m2 = w._compute_accents(mono)
check("monochrome art -> one color, no second", m1 is not None and m2 is None)
grey = QPixmap(24, 24); grey.fill(QColor(30, 30, 30))
g1, g2 = w._compute_accents(grey)
check("grey art -> no accents", g1 is None and g2 is None)
w._accent2_dyn = None
import config
config.AUTO_ACCENT = False
check("accent2 falls back to lighter primary",
      w._effective_accent2() == QColor(w._effective_accent()).lighter(135).name())

# ---------- live tray icon ----------
import icons
cov = QPixmap(64, 64); cov.fill(QColor(120, 60, 200))
ic = icons.live_tray_icon(cov, True, 0.5, "#39d6e0")
check("live tray icon builds", not ic.isNull() and len(ic.availableSizes()) >= 4)
ic2 = icons.live_tray_icon(cov, False, 1.7, "#39d6e0")   # frac clamps
check("live tray icon clamps frac / paused", not ic2.isNull())

# throttle: same state -> no re-render
class FakeTray:
    def __init__(s): s.count = 0
    def setIcon(s, *_a): s.count += 1
w.tray = FakeTray()
w._cover_src = cov; w._dur = 100.0; w._pos = 10.0; w._playing = True
w._tray_icon_state = None
w._refresh_tray_icon(); w._refresh_tray_icon()
check("tray icon throttled on identical state", w.tray.count == 1)
w._pos = 90.0
w._refresh_tray_icon()
check("tray icon re-renders on progress", w.tray.count == 2)
config.LIVE_TRAY = False
w._refresh_tray_icon()
check("LIVE_TRAY off -> falls back once", w.tray.count == 3)
w._refresh_tray_icon()
check("fallback not repeated", w.tray.count == 3)
config.LIVE_TRAY = True

# ---------- game mode ----------
config.HIDE_ON_FULLSCREEN = True
w2 = NowPlayingWidget()
w2.show()
w2.on_fullscreen(True)
check("fullscreen hides widget", not w2.isVisible() and w2._auto_hidden)
w2.on_fullscreen(False)
check("fullscreen end restores widget", w2.isVisible() and not w2._auto_hidden)
w2.hide(); w2._auto_hidden = False       # manual hide
w2.on_fullscreen(True); w2.on_fullscreen(False)
check("manual hide not overridden by game mode", not w2.isVisible())
config.HIDE_ON_FULLSCREEN = False
w2.show(); w2.on_fullscreen(True)
check("setting off -> no auto-hide", w2.isVisible())
config.HIDE_ON_FULLSCREEN = True

# watcher constructs and polls without crashing (offscreen: fail-open False)
from fullscreen_watch import FullscreenWatcher
fw = FullscreenWatcher(lambda: 0)
fw._poll()
check("fullscreen watcher polls safely", True)

# ---------- full-res cover ----------
w3 = NowPlayingWidget()
w3._cur_title, w3._cur_artist = "S", "A"
small = QPixmap(64, 64); small.fill(QColor(10, 10, 10))
w3._cover_src = small
big = QPixmap(400, 400); big.fill(QColor(200, 100, 50))
import io
from PySide6.QtCore import QBuffer
buf = QBuffer(); buf.open(QBuffer.ReadWrite); big.save(buf, "PNG")
data = bytes(buf.data())
w3.on_cover_hires("Other", "A", data)
check("stale hi-res ignored", w3._cover_src.width() == 64)
w3.on_cover_hires("S", "A", data)
check("hi-res applied", w3._cover_src.width() == 400 and w3._cover_hires)
tiny = QPixmap(32, 32); tiny.fill(QColor(1, 2, 3))
buf2 = QBuffer(); buf2.open(QBuffer.ReadWrite); tiny.save(buf2, "PNG")
w3.on_cover_hires("S", "A", bytes(buf2.data()))
check("downgrade ignored", w3._cover_src.width() == 400)

# ---------- radio + cover workers ----------
import tidal_likes as tl
class FMix:  id = "mix123"
class FA2:
    def __init__(s, n): s.name = n
class FT2:
    def __init__(s):
        s.id = 7; s.name = "Song"; s.artists = [FA2("Artist")]
    def get_radio_mix(s): return FMix()
class FS2:
    def search(s, q, models=None): return {"tracks": [FT2()]}
lk = tl.TidalLiker(); lk._session = FS2()
got = []
lk.radio_result.connect(lambda t, a, m: got.append(m))
lk._radio_worker("Song", "Artist")
check("radio worker emits mix id", got == ["mix123"])
lk2 = tl.TidalLiker(); lk2._session = None
g2 = []
lk2.radio_result.connect(lambda t, a, m: g2.append(m))
lk2._radio_worker("Song", "Artist")
check("radio without session -> empty id", g2 == [""])

# ---------- CLI verb parsing + round trip ----------
import main as mainmod
# hermetic: never touch a REAL running widget's command pipe
mainmod.CMD_SERVER_NAME = "TidalWidgetTest-cmd"
check("cli verb parsed", mainmod._cli_verb(["x", "--cmd", "next"]) == "next")
check("cli verb invalid -> ''", mainmod._cli_verb(["x", "--cmd", "bogus"]) == "")
check("cli no cmd -> None", mainmod._cli_verb(["x"]) is None)
check("cli dangling cmd -> ''", mainmod._cli_verb(["x", "--cmd"]) == "")
check("forward with no server -> False", mainmod._forward_cmd("next") is False)
from PySide6.QtNetwork import QLocalServer
QLocalServer.removeServer(mainmod.CMD_SERVER_NAME)
srv = QLocalServer(); srv.listen(mainmod.CMD_SERVER_NAME)
received = []
conns = []
def on_conn():
    c = srv.nextPendingConnection()
    conns.append(c)
    def read():
        if c.bytesAvailable():
            received.append(bytes(c.readAll()).decode().strip())
    c.readyRead.connect(read)
    read()
srv.newConnection.connect(on_conn)
ok = mainmod._forward_cmd("playpause")
for _ in range(50):
    app.processEvents()
    if received: break
    time.sleep(0.02)
check("cli round-trip delivers verb", ok and received == ["playpause"])
srv.close()

print("\nV140:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

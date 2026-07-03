import sys, time
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
import volume_backend as vb
import config
config.VOLUME_SCOPE = "app"   # these suites exercise per-app behavior

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

class FakeVol:
    def __init__(s, level=0.8, mute=False):
        s.level = level; s.mute = mute; s.writes = []
    def GetMasterVolume(s): return s.level
    def GetMute(s): return s.mute
    def SetMasterVolume(s, v, ctx): s.level = v; s.writes.append(v)
    def SetMute(s, m, ctx): s.mute = bool(m)

class FakeEp:
    def __init__(s, level=0.5, mute=False): s.level = level; s.mute = mute
    def GetMasterVolumeLevelScalar(s): return s.level
    def GetMute(s): return s.mute
    def SetMasterVolumeLevelScalar(s, v, ctx): s.level = v
    def SetMute(s, m, ctx): s.mute = bool(m)

picks = {"n": 0}
def wire(app_vols, ep, scope="TIDAL"):
    def _pick(src):
        picks["n"] += 1
        return (scope if app_vols else "", list(app_vols))
    vb._pick = _pick
    vb._endpoint = lambda: ep

app = FakeVol(0.8); ep = FakeEp(0.5)
wire([app], ep)
cache = {}

# effective read + follow (as before, now via cache)
lvl, mute, scope = vb._get_state("tidal", cache)
check("effective = app*master", abs(lvl - 0.4) < 1e-9)
ep.level = 0.25
lvl, _m, _s = vb._get_state("tidal", cache)
check("master change follows through cached pointer", abs(lvl - 0.2) < 1e-9)
ep.level = 0.5

# cache: repeated calls do NOT re-enumerate within the TTL
n0 = picks["n"]
for _ in range(5):
    vb._get_state("tidal", cache)
    vb._set_volume("tidal", 0.3, cache)
check("no re-enumeration within TTL", picks["n"] == n0)
cache["t"] -= 10   # age the cache past the TTL
vb._get_state("tidal", cache)
check("re-enumerates after TTL", picks["n"] == n0 + 1)

# set inverts master scaling; ceiling pins
vb._set_volume("tidal", 0.2, cache)
check("set inverts master scaling", abs(app.level - 0.4) < 1e-9)
vb._set_volume("tidal", 0.9, cache)
check("ceiling pins app at 1.0", app.level == 1.0)

# zero master leaves the session untouched
ep.level = 0.0; app.level = 0.35; cache.clear()
vb._set_volume("tidal", 0.5, cache)
check("zero master leaves app session untouched", app.level == 0.35)
ep.level = 0.5; cache.clear()

# gentle ramp: big jump writes intermediate steps, ends exactly on target
app.level = 0.2; app.writes = []
t0 = time.monotonic()
vb._set_volume("tidal", 0.5, cache, gentle=True)   # target app = 1.0, big delta
dt = time.monotonic() - t0
check("gentle ramp uses multiple steps", len(app.writes) == 4)
check("ramp ends exactly on target", abs(app.writes[-1] - 1.0) < 1e-9)
check("ramp is monotonic", app.writes == sorted(app.writes))
check("ramp stays brief (<0.3s)", dt < 0.3)
# small nudge is a single write even when gentle
app.level = 0.96; app.writes = []
vb._set_volume("tidal", 0.5, cache, gentle=True)    # target 1.0, delta 0.04
check("small gentle nudge = one write", len(app.writes) == 1)
# non-gentle is always one write
app.level = 0.2; app.writes = []
vb._set_volume("tidal", 0.5, cache, gentle=False)
check("drag set = one write", len(app.writes) == 1)

# stale COM pointer: first call raises -> cache cleared -> fresh retry works
class Dying(FakeVol):
    def __init__(s): super().__init__(0.5); s.dead = True
    def GetMasterVolume(s):
        if s.dead: raise OSError("COM gone")
        return s.level
dying = Dying()
fresh = FakeVol(0.6)
holder = {"vols": [dying]}
def _pick2(src):
    picks["n"] += 1
    return ("TIDAL", holder["vols"])
vb._pick = _pick2
cache2 = {}
try:
    vb._get_state("tidal", cache2)   # both attempts hit the dying session
    check("dead session raises to caller", False)
except OSError:
    check("dead session raises to caller", True)   # _emit catches this per poll
# swap to fresh session and confirm recovery on the NEXT call
holder["vols"] = [fresh]
lvl, _m, _s = vb._get_state("tidal", cache2)
check("recovers after session swap", abs(lvl - 0.6 * 0.5) < 1e-9)

# mute matrix (via cache)
app.mute = True; ep.mute = True
wire([app], ep); cache.clear()
vb._set_mute("tidal", False, cache)
check("unmute lifts app + master mute", app.mute is False and ep.mute is False)
vb._set_mute("tidal", True, cache)
check("mute is app-only", app.mute is True and ep.mute is False)
app.mute = False

# system fallback
wire([], FakeEp(0.33)); cacheF = {}
lvl, mute, scope = vb._get_state("x", cacheF)
check("fallback reports master", abs(lvl - 0.33) < 1e-9 and scope == "System")

print("\nVolume:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

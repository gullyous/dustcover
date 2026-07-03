import sys
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
import volume_backend as vb
import config

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# --- fakes ---
class FakeVol:   # a TIDAL app session that must be IGNORED in system mode
    def __init__(s): s.level = 0.8; s.mute = False; s.set = []
    def GetMasterVolume(s): return s.level
    def GetMute(s): return s.mute
    def SetMasterVolume(s, v, ctx): s.level = v; s.set.append(v)
    def SetMute(s, m, ctx): s.mute = bool(m)

class FakeEp:
    def __init__(s, level=0.6, mute=False):
        s.level = level; s.mute = mute; s.set = []; s.muted_set = []
    def GetMasterVolumeLevelScalar(s): return s.level
    def GetMute(s): return s.mute
    def SetMasterVolumeLevelScalar(s, v, ctx): s.level = v; s.set.append(v)
    def SetMute(s, m, ctx): s.mute = bool(m); s.muted_set.append(bool(m))

app = FakeVol(); ep = FakeEp(0.6)
pick_calls = {"n": 0}
def _pick(src):
    pick_calls["n"] += 1
    return ("TIDAL", [app])
vb._pick = _pick
vb._endpoint = lambda: ep

# ---- system scope ----
config.VOLUME_SCOPE = "system"
cache = {}

# reads the endpoint master directly, labelled System, ignoring the app session
lvl, mute, scope = vb._get_state("tidal", cache)
check("system: reads endpoint master", abs(lvl - 0.6) < 1e-9)
check("system: labelled System", scope == "System")

# and it never enumerated app sessions (the lag source)
check("system: no session enumeration", pick_calls["n"] == 0)

# set moves the ENDPOINT master 1:1 (what keyboard keys move), not the app
vb._set_volume("tidal", 0.3, cache)
check("system: set moves endpoint master to exactly the value", abs(ep.level - 0.3) < 1e-9)
check("system: app session left untouched", app.set == [])

# gentle ramp on a big jump still lands exactly on target, endpoint only
ep.set = []; ep.level = 0.1
vb._set_volume("tidal", 0.9, cache, gentle=True)
check("system: gentle ramp multi-step", len(ep.set) == 4)
check("system: ramp ends on target", abs(ep.set[-1] - 0.9) < 1e-9)

# mute is the system mute
ep.muted_set = []
vb._set_mute("tidal", True, cache)
check("system: mute sets endpoint mute", ep.mute is True and ep.muted_set == [True])
check("system: mute does not touch app", app.mute is False)
ep.mute = False

# ---- switching to app scope re-enumerates (cache keyed on mode) ----
config.VOLUME_SCOPE = "app"
pick_calls["n"] = 0
lvl, mute, scope = vb._get_state("tidal", cache)
check("switch to app re-enumerates sessions", pick_calls["n"] == 1)
check("app mode reports effective app*master", abs(lvl - app.level * ep.level) < 1e-9)
check("app mode label is TIDAL", scope == "TIDAL")

# ---- back to system: cache invalidates again ----
config.VOLUME_SCOPE = "system"
lvl, _m, scope = vb._get_state("tidal", cache)
check("switch back to system reads master", abs(lvl - ep.level) < 1e-9 and scope == "System")

# _scope() normalizes junk to system
config.VOLUME_SCOPE = "APP"
check("_scope case-insensitive app", vb._scope() == "app")
config.VOLUME_SCOPE = "nonsense"
check("_scope junk -> system", vb._scope() == "system")
config.VOLUME_SCOPE = "system"

print("\nVolumeSystem:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

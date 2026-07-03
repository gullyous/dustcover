import os, sys, time, datetime
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from media_backend import _live_position

UTC = datetime.timezone.utc
def ago(sec):
    return datetime.datetime.now(UTC) - datetime.timedelta(seconds=sec)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

TOL = 0.3

# TIDAL case: stale stamp while playing -> advance by stamp age
st = {}
p = _live_position(0.017, ago(98.2), True, 1.0, 175.5, st)
check("stale stamp advances (TIDAL case)", abs(p - 98.2) < TOL)

# well-behaved app: fresh stamp -> near-raw
st2 = {}
p = _live_position(50.0, ago(0.2), True, 1.0, 300.0, st2)
check("fresh stamp ~ raw", abs(p - 50.2) < TOL)

# garbage stamp -> raw untouched
st3 = {}
check("ancient stamp -> raw", _live_position(42.0, ago(200000), True, 1.0, 300.0, st3) == 42.0)
check("None stamp -> raw", _live_position(42.0, None, True, 1.0, 300.0, {}) == 42.0)
check("future stamp -> raw", _live_position(42.0, ago(-30), True, 1.0, 300.0, {}) == 42.0)

# clamp to duration
check("clamped to duration", _live_position(0.0, ago(500), True, 1.0, 175.5, {}) == 175.5)

# rate scaling
p = _live_position(10.0, ago(10.0), True, 1.5, 300.0, {})
check("rate scales elapsed", abs(p - 25.0) < TOL * 1.5)

# pause holds the last played value (same epoch, no re-stamp)
st4 = {}
lu = ago(60.0)
p_playing = _live_position(0.0, lu, True, 1.0, 300.0, st4)
check("playing at ~60", abs(p_playing - 60.0) < TOL)
p_paused = _live_position(0.0, lu, False, 1.0, 300.0, st4)
check("pause holds value", abs(p_paused - p_playing) < TOL)
# simulate 5s of pause, then resume: pause time must not count
st4["paused_since"] = time.monotonic() - 5.0
p_resumed = _live_position(0.0, ago(65.0), True, 1.0, 300.0, st4)
# real-time consistent: play ~2s, pause 1s (real sleep), resume -> still ~2s
st5 = {}
lu5 = ago(2.0)
p_a = _live_position(0.0, lu5, True, 1.0, 300.0, st5)    # playing, ~2.0
_live_position(0.0, lu5, False, 1.0, 300.0, st5)         # paused now
time.sleep(1.0)                                          # 1s of real pause
p_b = _live_position(0.0, lu5, False, 1.0, 300.0, st5)
check("held value does not advance during pause", abs(p_b - p_a) < 0.2)
p2 = _live_position(0.0, lu5, True, 1.0, 300.0, st5)     # resume
check("resume excludes paused time", abs(p2 - p_a) < 0.4)

# well-behaved pause: app re-stamps at pause -> raw is trusted
st6 = {}
_live_position(0.0, ago(60.0), True, 1.0, 300.0, st6)
p3 = _live_position(60.0, ago(0.1), False, 1.0, 300.0, st6)   # new epoch: new stamp+raw
check("re-stamped pause -> raw", abs(p3 - 60.0) < TOL)

# paused since before we started watching -> raw
check("cold paused -> raw", _live_position(33.0, ago(500.0), False, 1.0, 300.0, {}) == 33.0)

# raw None -> treated as 0 (guard)
p4 = _live_position(None, ago(10.0), True, 1.0, 300.0, {})
check("raw None tolerated", abs(p4 - 10.0) < TOL)

print("\nPosition:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

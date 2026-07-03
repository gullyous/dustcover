import os, sys, time, datetime
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from media_backend import _live_position, _source_state

UTC = datetime.timezone.utc
def ago(sec):
    return datetime.datetime.now(UTC) - datetime.timedelta(seconds=sec)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# Review fix 1: transient unusable stamp must NOT wipe bookkeeping
st = {}
lu = ago(2.0)
p_play = _live_position(0.0, lu, True, 1.0, 300.0, st)      # ~2.0, held
_live_position(0.0, lu, False, 1.0, 300.0, st)              # paused
time.sleep(0.5)                                             # 0.5s real pause
bad = _live_position(0.0, None, False, 1.0, 300.0, st)      # transient hiccup
check("bad stamp returns raw", bad == 0.0)
check("bad stamp keeps held", st.get("held") is not None)
p_after = _live_position(0.0, lu, False, 1.0, 300.0, st)    # good poll, same stamp
check("held survives the hiccup", abs(p_after - p_play) < 0.2)
p_res = _live_position(0.0, lu, True, 1.0, 300.0, st)       # resume
check("resume after hiccup excludes pause", abs(p_res - p_play) < 0.4)

# Review fix 2: first observed while PAUSED -> unobserved time counts as paused
st2 = {}
lu2 = ago(600.0)   # TIDAL stamped 10 min ago; user paused at some point; we just launched
p_paused = _live_position(50.0, lu2, False, 1.0, 300.0, st2)
check("launch-while-paused shows raw", p_paused == 50.0)
p_resume = _live_position(50.0, lu2, True, 1.0, 300.0, st2)
check("resume advances from raw, not pinned at end", abs(p_resume - 50.0) < 0.5)
# and it keeps advancing normally afterwards (same stamp, playing)
time.sleep(0.6)
p_later = _live_position(50.0, lu2, True, 1.0, 300.0, st2)
check("keeps advancing after resume", 0.3 < (p_later - p_resume) < 1.2)

# first observed while PLAYING keeps the original (correct) behavior
st3 = {}
p = _live_position(0.017, ago(98.2), True, 1.0, 175.5, st3)
check("launch-while-playing still corrects", abs(p - 98.2) < 0.3)

# Review fix 3: per-source state isolation (A-B-A bounce)
pool = {}
a = _source_state(pool, "tidal")
b = _source_state(pool, "spotify")
check("distinct sources get distinct state", a is not b)
check("same source returns same state", _source_state(pool, "tidal") is a)
lua = ago(180.0)
_live_position(0.0, lua, True, 1.0, 400.0, _source_state(pool, "tidal"))   # ~180 held
_live_position(0.0, lua, False, 1.0, 400.0, _source_state(pool, "tidal"))  # paused
_live_position(30.0, ago(0.1), True, 1.0, 200.0, _source_state(pool, "spotify"))  # other app
p_back = _live_position(0.0, lua, False, 1.0, 400.0, _source_state(pool, "tidal"))
check("A-B-A bounce keeps A's held pause value", abs(p_back - 180.0) < 0.5)
# eviction bound
for i in range(10):
    _source_state(pool, f"app{i}")
check("state pool bounded", len(pool) <= 6)

print("\nPosition2:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

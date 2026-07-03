import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import volume_backend as vb

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# ---- _coalesce: survivors + original relative order ----
ops = vb._coalesce([("set", 0.1), ("set", 0.2), ("set", 0.3)])
check("keeps only last set", ops == [("set", 0.3)])
ops = vb._coalesce([("mute", True), ("set", 1.0)])
check("mute BEFORE set stays first", ops == [("mute", True), ("set", 1.0)])
ops = vb._coalesce([("set", 1.0), ("mute", True)])
check("set before mute stays first", ops == [("set", 1.0), ("mute", True)])
ops = vb._coalesce([("mute", True), ("set", 0.5), ("mute", False), ("set", 0.8)])
check("mixed: last of each, order by last position",
      ops == [("mute", False), ("set", 0.8)])

# ---- worker loop: gentle gating + mute survives failing set ----
calls = []
def fake_set(source, level, cache, gentle=False):
    calls.append(("set", level, gentle))
    if getattr(fake_set, "explode", False):
        raise OSError("device gone")
def fake_mute(source, muted, cache):
    calls.append(("mute", muted))
vb._set_volume = fake_set
vb._set_mute = fake_mute
vb._get_state = lambda s, c: (0.5, False, "TIDAL")

ctl = vb.VolumeController(); ctl._source = "tidal"
ctl.start()
time.sleep(0.2)

# isolated click -> gentle
ctl.set_volume(0.9)
time.sleep(0.15)
sets = [c for c in calls if c[0] == "set"]
check("isolated click is gentle", sets and sets[-1][2] is True)

# a second set arriving 50ms later (drag pacing) -> NOT gentle
ctl.set_volume(0.7)
time.sleep(0.15)
sets = [c for c in calls if c[0] == "set"]
check("drag-paced set is not gentle", sets[-1][2] is False)

# after settling >0.3s, the next single set is gentle again
time.sleep(0.4)
ctl.set_volume(0.2)
time.sleep(0.15)
sets = [c for c in calls if c[0] == "set"]
check("settled click is gentle again", sets[-1][2] is True)

# a failing set must not eat a mute queued in the same drain
fake_set.explode = True
calls.clear()
ctl._q.put(("mute", True)); ctl._q.put(("set", 1.0))   # mute first, then slam
time.sleep(0.15)
fake_set.explode = False
check("mute still executed when set fails",
      ("mute", True) in calls)
check("mute ran BEFORE the set (original order)",
      calls and calls[0] == ("mute", True))

ctl.stop()
print("\nVolumeWorker:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

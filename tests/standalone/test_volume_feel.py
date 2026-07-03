import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication, QStyle
app = QApplication(sys.argv)
from widget import NowPlayingWidget

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

w = NowPlayingWidget()

# click-to-position: the slider's style must answer LeftButton for absolute set
hint = w.e_vol.style().styleHint(QStyle.SH_Slider_AbsoluteSetButtons, None, w.e_vol)
from PySide6.QtCore import Qt
check("groove click jumps to position (expanded)",
      hint == int(Qt.MouseButton.LeftButton.value))
hint2 = w.c_vol.style().styleHint(QStyle.SH_Slider_AbsoluteSetButtons, None, w.c_vol)
check("groove click jumps to position (compact)",
      hint2 == int(Qt.MouseButton.LeftButton.value))

# throttle: a burst of 25 slider moves must emit far fewer sends,
# first one instantly, last value delivered by the trailing edge
sends = []
w.volume_changed.connect(lambda v: sends.append(v))
for i in range(25):
    w.e_vol.setValue(40 + i)          # 25 valueChanged in quick succession
check("leading edge fires instantly", len(sends) >= 1 and sends[0] == 0.40)
deadline = time.time() + 1.0
while time.time() < deadline and (not sends or sends[-1] != 0.64):
    app.processEvents(); time.sleep(0.01)
check("trailing edge delivers the final value", sends[-1] == 0.64)
check("burst was throttled (<6 sends for 25 moves)", len(sends) < 6)

# programmatic state updates do not feed back into sends
n = len(sends)
w.on_volume_state(0.3, False, "TIDAL")
app.processEvents()
check("state update does not re-emit", len(sends) == n)

# controller coalescing: 30 queued sets -> far fewer actual writes
import volume_backend as vb
import config
config.VOLUME_SCOPE = "app"   # these suites exercise per-app behavior
writes = []
class V:
    def GetMasterVolume(s): return 0.5
    def GetMute(s): return False
    def SetMasterVolume(s, v, ctx): writes.append(v)
    def SetMute(s, m, ctx): pass
class E:
    def GetMasterVolumeLevelScalar(s): return 1.0
    def GetMute(s): return False
vb._pick = lambda src: ("TIDAL", [V()])
vb._endpoint = lambda: E()
ctl = vb.VolumeController()
ctl._source = "tidal"
states = []
ctl.state_changed.connect(lambda l, m, s: states.append(l))
ctl.start()
for i in range(30):
    ctl.set_volume(i / 30.0)
deadline = time.time() + 2.0
while time.time() < deadline and 0.9666 not in [round(x, 4) for x in writes]:
    app.processEvents(); time.sleep(0.01)
ctl.stop()
final_ok = any(abs(x - 29/30.0) < 1e-6 for x in writes)
check("final value written", final_ok)
check(f"coalesced ({len(writes)} writes for 30 sets)", len(writes) <= 10)

print("\nVolumeFeel:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

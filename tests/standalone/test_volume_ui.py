import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from widget import NowPlayingWidget

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

w = NowPlayingWidget()
# normal state update moves the slider
w.on_volume_state(0.6, False, "TIDAL")
check("state update sets slider", w.e_vol.value() == 60)

# while the user holds the handle, a state emit must NOT move it
w.e_vol.setSliderDown(True)
w.on_volume_state(0.5, False, "TIDAL")
check("no yank while dragging (expanded)", w.e_vol.value() == 60)
w.e_vol.setSliderDown(False)

w.c_vol.setSliderDown(True)
w.on_volume_state(0.5, False, "TIDAL")
check("no yank while dragging (compact)", w.e_vol.value() == 60)
w.c_vol.setSliderDown(False)

# after release the next emit settles it
w.on_volume_state(0.5, False, "TIDAL")
check("settles after release", w.e_vol.value() == 50 and w.c_vol.value() == 50)

# mute state still refreshes even mid-drag
w.e_vol.setSliderDown(True)
w.on_volume_state(0.5, True, "TIDAL")
check("mute icon updates mid-drag", w._muted is True)
w.e_vol.setSliderDown(False)

print("\nVolumeUI:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

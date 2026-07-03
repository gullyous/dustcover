import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from PySide6.QtGui import QColor
app = QApplication(sys.argv)
import settings_dialog as sd

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

d = sd.SettingsDialog()
bb = d.findChild(QDialogButtonBox)
ok = bb.button(QDialogButtonBox.Ok)
check("OK is the accent button", ok.objectName() == "accent")
check("OK renamed to Save", ok.text() == "Save")
ss = d.styleSheet()
check("ghost buttons use palette (theme-adaptive)", "palette(button-text)" in ss and "palette(mid)" in ss)
check("accent fill present", d._accent in ss and "#accent" in ss)
check("no hardcoded white ghost text (light-mode safe)", "rgba(255,255,255" not in ss)

# restyle previews a newly picked accent
d._accent = "#ff6600"; d._style_accent_btn(); d._restyle()
check("Save previews new accent", "#ff6600" in d.styleSheet())
# on-accent text flips for a light accent
d._accent = "#f5f5f5"; d._style_accent_btn()
check("light accent -> dark swatch text", "#0a0a0a" in d.accent_btn.styleSheet())
d._accent = "#101010"; d._style_accent_btn()
check("dark accent -> light swatch text", "#ffffff" in d.accent_btn.styleSheet())

# values() still complete after the restyle work
for k in ("accent", "volume_scope", "discord_rpc", "hide_fullscreen"):
    check(f"values has {k}", k in d.values())

check("_lum sane", sd._lum(QColor("#ffffff")) > 200 and sd._lum(QColor("#000000")) < 5)

print("\nSettings:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

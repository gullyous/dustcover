import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import settings_dialog as sd

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

notes = sd._release_notes()
check("has v1.4.1", "v1.4.1" in notes)
check("has v1.4.0", "v1.4.0" in notes)
check("has v1.1.1", "v1.1.1" in notes)
check("has v1.0.0", "v1.0.0" in notes)
check("no Unreleased", "nreleased" not in notes)
check("no md artifacts", "**" not in notes and "##" not in notes)
check("no preamble", "Semantic Versioning" not in notes)
import config
check("newest first is the running version",
      notes.splitlines()[0].startswith(f"v{config.APP_VERSION}"))
sys._MEIPASS = r"C:\definitely\not\a\dir"
fb = sd._release_notes()
del sys._MEIPASS
check("fallback links to releases", "releases" in fb)
dlg = sd.SettingsDialog()
check("dialog constructs", dlg is not None)
print("\nNotes:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtCore import QPoint
app = QApplication(sys.argv)

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

def order_ok(seq, *items):
    """items appear in seq in the given relative order (all present)."""
    idx = [seq.index(x) for x in items if x in seq]
    return len(idx) == len(items) and idx == sorted(idx)

def no_dups(texts):
    real = [t for t in texts if t]           # ignore separators (empty text)
    return len(real) == len(set(real)), [t for t in set(real) if real.count(t) > 1]

# The offscreen platform has no system tray, and constructing a real
# QSystemTrayIcon there is flaky/blocking. Swap in a harmless fake so
# _build_tray() runs its full body and populates a real QMenu we can inspect.
class _FakeSignal:
    def connect(self, *a, **k): pass
class _FakeTray:
    def __init__(self, *a, **k): self.activated = _FakeSignal()
    @staticmethod
    def isSystemTrayAvailable(): return True
    def setToolTip(self, *a, **k): pass
    def setContextMenu(self, *a, **k): pass
    def setIcon(self, *a, **k): pass
    def setVisible(self, *a, **k): pass
    def show(self, *a, **k): pass

import config
config.START_EXPANDED = False               # start compact
import widget
widget.QSystemTrayIcon = _FakeTray          # before construction, so _build_tray uses it
from widget import NowPlayingWidget
w = NowPlayingWidget()
w._logged_in = True
w._cur_title, w._cur_artist = "Song", "Artist"

# ---- tray menu ----
tray = w._tray_menu
check("tray menu was built", tray is not None)
if tray is not None:
    tt = [a.text() for a in tray.actions()]
    ok, dups = no_dups(tt)
    check("tray: no duplicated actions", ok)
    if dups: print("   dups:", dups)
    # every advertised feature still reachable from the tray
    for want in ("Like current track", "Copy now playing", "Save cover art...",
                 "Track radio (more like this)", "Open TIDAL", "TIDAL web player",
                 "Compact mode", "Fullscreen now playing", "Sign in to TIDAL",
                 "Check for updates...", "Settings...", "Quit"):
        check(f"tray has '{want}'", want in tt)
    # grouped by intent: track -> navigation -> view -> housekeeping
    check("tray group order (track<nav<view<housekeeping)",
          order_ok(tt, "Like current track", "Open TIDAL", "Compact mode",
                   "Check for updates...", "Settings...", "Quit"))
    # 'Check for updates...' moved down next to Settings (housekeeping)
    check("tray: Check-for-updates sits just above Settings",
          "Settings..." in tt and "Check for updates..." in tt
          and 0 <= tt.index("Settings...") - tt.index("Check for updates...") <= 2)

# ---- Compact mode is a checkable item reflecting state, and stays in sync ----
am = w.act_mode                              # the tray's mode action
check("Compact mode is checkable", am.isCheckable())
check("compact by default => checked", am.isChecked() is True)
w._set_mode(True)                            # expand however triggered...
check("expanded => Compact mode unchecked", am.isChecked() is False)
w._set_mode(False)
check("compact again => Compact mode re-checked", am.isChecked() is True)
check("no stale flip-flop label", am.text() == "Compact mode")

# ---- right-click (context) menu ----
# Drive it through the _exec_menu seam (patching QMenu.exec doesn't intercept
# the real C++ modal in PySide6, it just hangs); the seam captures and returns.
cap = {}
def _spy(menu, gpos):
    cap["texts"] = [x.text() for x in menu.actions()]
    cap["checkable"] = {x.text(): x.isCheckable() for x in menu.actions() if x.text()}
    return None
w._exec_menu = _spy
w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(0, 0), QPoint(0, 0)))

ct = cap.get("texts", [])
check("context menu was captured", bool(ct))
ok, dups = no_dups(ct)
check("context: no duplicated actions", ok)
if dups: print("   dups:", dups)
# context menu is management-only: no transport buttons duplicated in it
for banned in ("Play", "Pause", "Next", "Previous"):
    check(f"context omits transport '{banned}'", banned not in ct)
# same intent grouping as the tray
check("context group order (track<nav<view<housekeeping)",
      order_ok(ct, "Copy now playing", "Open TIDAL", "Compact mode",
               "Check for updates...", "Settings...", "Quit"))
check("context: Compact mode is checkable too",
      cap.get("checkable", {}).get("Compact mode") is True)

print("\nMenu:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

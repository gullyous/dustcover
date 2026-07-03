import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
from PySide6.QtWidgets import QApplication
import settings
app = QApplication(sys.argv)
from widget import NowPlayingWidget

fails=[]
def check(n,c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# intercept settings.save so the test never writes real user settings
saved={}
_orig=settings.save
settings.save=lambda d: saved.update(d)

w = NowPlayingWidget()
w._cur_title, w._cur_artist = "Song", "Artist"

# synced lyrics arrive
w.on_lyrics("Song","Artist",[(0.0,"a"),(5.0,"b"),(10.0,"c")])
check("synced enables lyrics buttons", w.e_lyrics_btn.isEnabled() and w.c_lyrics_btn.isEnabled())
check("view is synced", w.e_lyrics._synced is True)

# open lyrics + tick position
w._set_mode(True)
w._set_lyrics_mode(True)
w._pos=6.0; w._playing=True
w.e_lyrics.set_position(6.0)
check("active line tracks position", w.e_lyrics._active == 1)

# nudge offset via the widget's persist slot (as wheelEvent would)
w._on_lyrics_offset(0.4)
w._save_lyrics_offset()
check("offset persisted through settings.save", abs(saved.get("lyrics_offset",0)-0.4)<1e-9)

# plain lyrics arrive for a different state
w.on_lyrics("Song","Artist",[(None,"p1"),(None,"p2"),(None,"p3")])
check("plain still enables button", w.e_lyrics_btn.isEnabled())
check("view is plain", w.e_lyrics._synced is False)

# no lyrics -> button dims, exits lyrics mode
w.on_lyrics("Song","Artist",[])
check("empty disables button", not w.e_lyrics_btn.isEnabled())
check("empty exits lyrics mode", w._lyrics_mode is False)

# stale result ignored
w.e_lyrics.set_lines([(0.0,"x")])
w.on_lyrics("Other","Artist",[(1.0,"stale")])
check("stale result ignored", w.e_lyrics._lines == [(0.0,"x")])

settings.save=_orig
print("\nIntegration:", "ALL PASS" if not fails else f"{len(fails)} FAIL")
sys.exit(1 if fails else 0)

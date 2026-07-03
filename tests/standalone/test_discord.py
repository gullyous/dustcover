import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import discord_backend as db
import config

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

check("pypresence available in venv", db.available())

# _activity mapping
p = {"title": "Song", "artist": "Artist", "album": "Alb", "playing": True,
     "position": 30.0, "duration": 200.0, "cover": "https://x/y.jpg"}
a = db.DiscordPresence._activity(p)
from pypresence import ActivityType
check("activity is LISTENING", a["activity_type"] == ActivityType.LISTENING)
check("details=title, state=artist", a["details"] == "Song" and a["state"] == "Artist")
check("cover url used as large_image", a["large_image"] == "https://x/y.jpg")
check("playing -> start/end timestamps present", "start" in a and "end" in a)
check("progress window matches duration", a["end"] - a["start"] == 200)

# paused -> no timestamps (bar doesn't advance)
pp = dict(p, playing=False)
a2 = db.DiscordPresence._activity(pp)
check("paused -> no timestamps", "start" not in a2 and "end" not in a2)

# no cover -> fallback asset key
a3 = db.DiscordPresence._activity(dict(p, cover=None))
check("no cover -> fallback image key", a3["large_image"] == db._FALLBACK_IMAGE)

# short details/state padded to >=2 chars (Discord requirement)
a4 = db.DiscordPresence._activity({"title": "x", "artist": "", "album": "",
    "playing": False, "position": 0, "duration": 0, "cover": None})
check("details padded to >=2", len(a4["details"]) >= 2 and len(a4["state"]) >= 2)

# _signature: same track/5s-bucket -> equal; position past a bucket -> different
s1 = db.DiscordPresence._signature(dict(p, position=30.0))
s2 = db.DiscordPresence._signature(dict(p, position=32.0))   # same 5s bucket
s3 = db.DiscordPresence._signature(dict(p, position=40.0))   # next bucket
check("signature ignores small position drift", s1 == s2)
check("signature changes across buckets", s1 != s3)
check("clear signature", db.DiscordPresence._signature("clear") == "clear")

# enable gating: no client id -> inert (never starts a thread)
config.DISCORD_CLIENT_ID = ""
d = db.DiscordPresence()
d.set_enabled(True)
check("no client id -> not enabled", d._enabled is False and d._thread is None)
# cover cache + on_update enqueue when enabled
config.DISCORD_CLIENT_ID = "123456789012345678"
d2 = db.DiscordPresence()
d2.set_cover("Song", "Artist", "https://c")
check("cover cached by key", d2._cover.get(("Song", "Artist")) == "https://c")
d2.stop()

print("\nDiscord:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

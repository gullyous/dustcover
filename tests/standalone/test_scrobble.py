import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
import scrobble_backend as sb

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

def info(title="T", artist="A", album="Al", source="TIDAL.exe", dur=200.0, playing=True, avail=True):
    return {"available": avail, "title": title, "artist": artist, "album": album,
            "source": source, "duration": dur, "playing": playing}

# now_playing on first sight of a track
tr = sb.PlayTracker()
ev = tr.update(info(), 0.0, "tidal")
check("first update -> now_playing", ("now_playing", ("T", "A", "Al")) in ev)
check("no premature scrobble", not any(e[0] == "scrobble" for e in ev))

# scrobbles once half the duration has PLAYED (dur=200 -> 100s)
tr = sb.PlayTracker()
tr.update(info(dur=200), 0.0, "tidal")
tr.update(info(dur=200), 50.0, "tidal")
ev = tr.update(info(dur=200), 100.0, "tidal")
check("scrobble at half duration", ("scrobble", ("T", "A", "Al")) in ev)
# does not scrobble twice
ev2 = tr.update(info(dur=200), 160.0, "tidal")
check("no double scrobble", not any(e[0] == "scrobble" for e in ev2))

# 4-minute cap for long tracks (dur=1000 -> 240s, not 500s)
tr = sb.PlayTracker()
tr.update(info(dur=1000), 0.0, "tidal")
ev = tr.update(info(dur=1000), 240.0, "tidal")
check("long track scrobbles at 4 min", any(e[0] == "scrobble" for e in ev))

# paused time is NOT counted
tr = sb.PlayTracker()
tr.update(info(dur=200, playing=True), 0.0, "tidal")   # playing from t=0
tr.update(info(dur=200, playing=False), 30.0, "tidal") # played 30s, now paused
tr.update(info(dur=200, playing=False), 200.0, "tidal")# 170s paused -> not counted
ev = tr.update(info(dur=200, playing=True), 205.0, "tidal")  # resume
check("pause not counted (no scrobble yet at ~30s played)",
      not any(e[0] == "scrobble" for e in ev))
ev = tr.update(info(dur=200, playing=True), 275.0, "tidal")  # +70 -> ~100s played
check("scrobbles after enough REAL play post-resume",
      any(e[0] == "scrobble" for e in ev))

# non-TIDAL source is ignored
tr = sb.PlayTracker()
ev = tr.update(info(source="chrome.exe"), 0.0, "tidal")
check("non-followed app ignored", ev == [])

# short track never scrobbles
tr = sb.PlayTracker()
tr.update(info(dur=20), 0.0, "tidal")
ev = tr.update(info(dur=20), 15.0, "tidal")
check("very short track not scrobbled", not any(e[0] == "scrobble" for e in ev))

# track change resets accounting + fresh now_playing
tr = sb.PlayTracker()
tr.update(info(title="One", dur=200), 0.0, "tidal")
tr.update(info(title="One", dur=200), 90.0, "tidal")
ev = tr.update(info(title="Two", dur=200), 95.0, "tidal")
check("track change -> new now_playing", ("now_playing", ("Two", "A", "Al")) in ev)
ev = tr.update(info(title="Two", dur=200), 150.0, "tidal")  # only 55s into Two
check("new track not scrobbled early", not any(e[0] == "scrobble" for e in ev))

# unavailable clears state
tr = sb.PlayTracker()
tr.update(info(), 0.0, "tidal")
ev = tr.update({"available": False}, 5.0, "tidal")
check("unavailable -> no events", ev == [])

# validate_token network path (mock urlopen)
import io, json
class R:
    def __init__(s, body): s._b = json.dumps(body).encode()
    def read(s): return s._b
    def __enter__(s): return s
    def __exit__(s, *a): return False
sb.urllib.request.urlopen = lambda *a, **k: R({"valid": True, "user_name": "me"})
ok, msg = sb.validate_token("tok")
check("validate_token ok", ok and msg == "me")
sb.urllib.request.urlopen = lambda *a, **k: R({"valid": False, "message": "bad"})
ok, msg = sb.validate_token("tok")
check("validate_token invalid", not ok)

print("\nScrobble:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

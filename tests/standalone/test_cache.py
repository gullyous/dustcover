import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
import lyrics_backend as lb
import urllib.error

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

def mk(fetcher, get_result=None, get_exc=None, search_result=None):
    calls = {"get": 0, "search": 0}
    def fake(url):
        if "/api/get" in url:
            calls["get"] += 1
            if get_exc: raise get_exc
            return get_result
        calls["search"] += 1
        return search_result
    lb._get_json = fake
    return calls

err404 = urllib.error.HTTPError("u", 404, "nf", None, None)

# key now includes album + rounded duration
f = lb.LyricsFetcher()
mk(f, get_result={"syncedLyrics": "[00:01.00]hi"})
f._worker("Song", "Art", "AlbumA", 200.4)
check("cache key = (title,artist,album,round(dur))",
      ("Song", "Art", "AlbumA", 200) in f._cache)

# same title/artist, different album -> separate entry, separate lookup
calls = mk(f, get_result={"syncedLyrics": "[00:02.00]live"})
f._worker("Song", "Art", "AlbumB", 250.0)
check("different album -> new lookup (no collision)",
      calls["get"] == 1 and ("Song", "Art", "AlbumB", 250) in f._cache)

# repeat same key -> served from cache, no new network
calls = mk(f, get_result={"syncedLyrics": "[00:09.00]SHOULD_NOT_USE"})
got = {}
f.lyrics_ready.connect(lambda t, a, l: got.__setitem__("l", l))
f._worker("Song", "Art", "AlbumA", 200.0)
check("cache hit -> no network", calls["get"] == 0)
check("cache hit -> original lyrics", got.get("l") == [(1.0, "hi")])

# LRU: hitting AlbumA moves it to most-recently-used (front is now AlbumB)
first_key = next(iter(f._cache))
check("LRU touch moved hit to newest (oldest is now the untouched one)",
      first_key == ("Song", "Art", "AlbumB", 250))

# genuine [] cached and served as a hit (not re-fetched)
f2 = lb.LyricsFetcher()
calls = mk(f2, get_exc=err404, search_result=[])
f2._worker("None", "Body", "", 0)
check("genuine none cached as []", f2._cache.get(("None", "Body", "", 0)) == [])
calls = mk(f2, get_result={"syncedLyrics": "[00:01.00]x"})
f2._worker("None", "Body", "", 0)
check("cached [] is a hit (no re-fetch)", calls["get"] == 0)

# transient failure not cached
f3 = lb.LyricsFetcher()
mk(f3, get_exc=urllib.error.URLError("down"))
f3._worker("Net", "Fail", "", 0)
check("transient failure not cached", ("Net", "Fail", "", 0) not in f3._cache)

print("\nCache:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

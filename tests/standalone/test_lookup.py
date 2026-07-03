import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import os as _os; sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
import lyrics_backend as lb
import urllib.error
fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)
def mk(f, get_result=None, get_exc=None, search_result=None):
    calls = {"get": 0, "search": 0}
    def fake(url):
        if "/api/get" in url:
            calls["get"] += 1
            if get_exc: raise get_exc
            return get_result
        calls["search"] += 1
        return search_result
    lb._get_json = fake; return calls
check("parse_lrc metadata-only -> []", lb.parse_lrc("[ar:X]\n[al:Y]") == [])
check("parse_plain None-times", lb.parse_plain("a\nb") == [(None, "a"), (None, "b")])
f = lb.LyricsFetcher(); err404 = urllib.error.HTTPError("u", 404, "nf", None, None)
mk(f, get_result={"syncedLyrics": "[00:01.00]hi"})
check("exact synced", f._lookup("t", "a", "", "") == [(1.0, "hi")])
mk(f, get_result={"syncedLyrics": "[ar:A]", "plainLyrics": "p"}, search_result=[])
check("metadata-only synced -> plain", f._lookup("t", "a", "", "") == [(None, "p")])
mk(f, get_result={"plainLyrics": "EXACT"}, search_result=[{"plainLyrics": "SEARCH"}])
check("exact plain preferred", f._lookup("t", "a", "", "") == [(None, "EXACT")])
c = mk(f, get_result={"syncedLyrics": "[00:01.00]hi"}, search_result=[{"syncedLyrics": "[00:09.00]n"}])
check("usable exact synced skips search", f._lookup("t", "a", "", "") == [(1.0, "hi")] and c["search"] == 0)
mk(f, get_exc=urllib.error.URLError("x"))
try:
    f._lookup("t", "a", "", ""); check("network raises", False)
except urllib.error.URLError: check("network raises", True)
print("\nLookup:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

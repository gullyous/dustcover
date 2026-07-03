import os as _os, sys, time
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QTcpSocket, QHostAddress
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import obs_overlay as ob

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

# pure helpers
st = ob.state_from_info({"available": True, "title": "T", "artist": "A",
    "album": "Al", "playing": True, "position": 5, "duration": 100}, "#39d6e0", None)
check("state maps fields", st["title"] == "T" and st["accent"] == "#39d6e0" and st["playing"])
check("unavailable -> minimal state", ob.state_from_info({"available": False}, "#fff")["available"] is False)
uri = ob.cover_data_uri(b"\xff\xd8jpeg")
check("cover data uri", uri and uri.startswith("data:image/jpeg;base64,"))
check("no cover -> None", ob.cover_data_uri(None) is None)

srv = ob.OverlayServer()
ok = srv.start(0)
port = srv.port()
check("server binds loopback", ok and port > 0)

def http_get(path, keep=False, timeout=2.0):
    s = QTcpSocket()
    s.connectToHost(QHostAddress("127.0.0.1"), port)
    if not s.waitForConnected(1000): return None, s
    s.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    s.flush()
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        app.processEvents()
        if s.waitForReadyRead(100):
            buf += bytes(s.readAll())
        if keep:
            if b"data:" in buf:
                break
        elif s.state() == QTcpSocket.SocketState.UnconnectedState:
            buf += bytes(s.readAll())   # non-keep-alive: server closed = done
            break
    return buf, s

buf, s = http_get("/overlay")
check("/overlay -> 200 html", buf and b"200 OK" in buf and b"<!doctype html>" in buf.lower())
check("overlay page is self-contained (no external src)", b"http://" not in buf.split(b"\r\n\r\n",1)[-1] or b"127.0.0.1" in buf)
s.close()

# feed a state, then subscribe to /events and expect the JSON pushed
srv.set_state(ob.state_from_info({"available": True, "title": "Live", "artist": "X",
    "album": "", "playing": True, "position": 1, "duration": 60}, "#39d6e0"))
buf, s = http_get("/events", keep=True)
check("/events -> event-stream", buf and b"text/event-stream" in buf)
check("/events pushes current state", buf and b'"title": "Live"' in buf)
# a new state broadcasts to the open SSE socket
srv.set_state(ob.state_from_info({"available": True, "title": "Next", "artist": "Y",
    "album": "", "playing": True, "position": 0, "duration": 60}, "#39d6e0"))
deadline = time.time() + 2.0
got = b""
while time.time() < deadline:
    app.processEvents()
    if s.waitForReadyRead(100): got += bytes(s.readAll())
    if b"Next" in got: break
check("SSE broadcasts new state", b'"title": "Next"' in got)
s.close()

buf, s = http_get("/nope")
check("unknown path -> 404", buf and b"404" in buf)
s.close()

srv.stop()
check("server stops cleanly", srv.port() >= 0)

print("\nOBS:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
obs_overlay.py
--------------
Optional localhost now-playing server + a drop-in OBS browser source. When
enabled, GET http://127.0.0.1:<port>/overlay is a self-contained dark-glass
lower-third (cover, title, artist, accent-colored progress) that matches the
widget; GET /events is a Server-Sent-Events feed the page subscribes to, pushed
from the same now-playing stream the widget uses.

Everything runs on the Qt event loop via QTcpServer (PySide6.QtNetwork, already
bundled) with no new dependency and no blocking. It binds to 127.0.0.1 only
(never a public interface). Off by default.
"""

import base64
import json

from PySide6.QtCore import QObject, QByteArray
from PySide6.QtNetwork import QHostAddress, QTcpServer


def _page(port):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>TIDAL Now Playing</title><style>
  html,body{{margin:0;background:transparent;font-family:'Segoe UI',system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;overflow:hidden}}
  #card{{position:fixed;left:24px;bottom:24px;display:flex;align-items:center;gap:16px;
    padding:14px 20px 14px 14px;border-radius:16px;background:rgba(16,16,20,0.82);
    box-shadow:0 10px 40px rgba(0,0,0,.45);color:#fff;max-width:560px;
    opacity:0;transition:opacity .4s}}
  #card.show{{opacity:1}}
  #art{{width:72px;height:72px;border-radius:12px;object-fit:cover;background:#222;flex:none}}
  #meta{{min-width:0;flex:1}}
  #title{{font-size:17px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  #artist{{font-size:13px;color:#b9b9c4;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  #bar{{height:4px;border-radius:2px;background:rgba(255,255,255,.18);margin-top:10px;overflow:hidden}}
  #fill{{height:100%;width:0;border-radius:2px;background:var(--accent,#39d6e0);transition:width .25s linear}}
</style></head><body>
<div id="card"><img id="art"><div id="meta">
  <div id="title"></div><div id="artist"></div><div id="bar"><div id="fill"></div></div>
</div></div>
<script>
let st=null, anchor=0, base=0;
function draw(){{
  if(!st||!st.duration){{document.getElementById('fill').style.width='0';return;}}
  let pos=base; if(st.playing) pos=base+(Date.now()-anchor)/1000;
  let f=Math.max(0,Math.min(1,pos/st.duration));
  document.getElementById('fill').style.width=(f*100)+'%';
}}
function apply(s){{
  st=s; base=s.position||0; anchor=Date.now();
  const card=document.getElementById('card');
  if(!s.available||!s.title){{card.classList.remove('show');return;}}
  card.classList.add('show');
  document.getElementById('title').textContent=s.title||'';
  document.getElementById('artist').textContent=s.artist||'';
  document.documentElement.style.setProperty('--accent',s.accent||'#39d6e0');
  const art=document.getElementById('art');
  if(s.cover){{art.src=s.cover;art.style.display='';}}else{{art.style.display='none';}}
  draw();
}}
setInterval(draw,250);
const es=new EventSource('/events');
es.onmessage=e=>{{try{{apply(JSON.parse(e.data));}}catch(_){{}}}};
</script></body></html>"""


class OverlayServer(QObject):
    """Serves /overlay + an SSE /events feed on 127.0.0.1. UI-thread API:
    start(port), stop(), set_state(dict). Runs entirely on the Qt loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._clients = []          # open SSE sockets
        self._state = {"available": False}
        self._port = 0

    def port(self):
        return self._port

    def start(self, port):
        self.stop()
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_connection)
        ok = self._server.listen(QHostAddress("127.0.0.1"), int(port))
        if not ok and int(port) != 0:
            ok = self._server.listen(QHostAddress("127.0.0.1"), 0)  # OS-picked
        self._port = self._server.serverPort() if ok else 0
        if not ok:
            self._server = None
        return ok

    def stop(self):
        for c in list(self._clients):
            try:
                c.close()
            except Exception:
                pass
        self._clients = []
        if self._server is not None:
            self._server.close()
            self._server = None

    def set_state(self, state):
        self._state = dict(state or {"available": False})
        self._broadcast()

    # ---- internals ----
    def _on_connection(self):
        while self._server and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.setProperty("_buf", QByteArray())
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _on_ready(self, sock):
        if sock.property("_handled"):
            return  # one request per connection; ignore any further bytes
        buf = sock.property("_buf")
        buf.append(sock.readAll())
        sock.setProperty("_buf", buf)
        data = bytes(buf)
        if b"\r\n\r\n" not in data:
            if len(data) > 16384:      # header flood: drop the connection
                sock.abort()
            return                     # otherwise wait for the full request head
        sock.setProperty("_handled", True)
        line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = line.split(" ")
        method = parts[0] if parts else ""
        path = parts[1].split("?")[0] if len(parts) > 1 else "/"
        if method != "GET":
            self._respond(sock, 405, "text/plain", b"method not allowed")
        elif path == "/overlay" or path == "/":
            self._respond(sock, 200, "text/html; charset=utf-8",
                          _page(self._port).encode("utf-8"))
        elif path == "/events":
            self._start_sse(sock)
        else:
            self._respond(sock, 404, "text/plain", b"not found")

    def _respond(self, sock, code, ctype, body, close=True):
        reason = {200: "OK", 404: "Not Found", 405: "Method Not Allowed"}.get(code, "OK")
        head = (f"HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n"
                f"Cache-Control: no-store\r\n\r\n").encode("latin-1")
        try:
            sock.write(head + body)
            sock.flush()
            if close:
                sock.disconnectFromHost()
        except Exception:
            pass

    def _start_sse(self, sock):
        head = ("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                "Cache-Control: no-store\r\nConnection: keep-alive\r\n\r\n")
        try:
            sock.write(head.encode("latin-1"))
            sock.flush()
        except Exception:
            return
        if sock not in self._clients:
            self._clients.append(sock)
        self._send(sock, self._state)

    def _send(self, sock, state):
        try:
            sock.write(("data: " + json.dumps(state) + "\n\n").encode("utf-8"))
            sock.flush()
        except Exception:
            self._drop(sock)

    def _broadcast(self):
        for c in list(self._clients):
            self._send(c, self._state)

    def _drop(self, sock):
        if sock in self._clients:
            self._clients.remove(sock)
        try:
            sock.deleteLater()
        except Exception:
            pass


def state_from_info(info, accent, cover_data_uri=None):
    """Build the overlay state dict from an on_update info dict."""
    if not info or not info.get("available"):
        return {"available": False}
    return {
        "available": True,
        "title": info.get("title", ""),
        "artist": info.get("artist", ""),
        "album": info.get("album", ""),
        "playing": bool(info.get("playing")),
        "position": float(info.get("position") or 0.0),
        "duration": float(info.get("duration") or 0.0),
        "accent": accent,
        "cover": cover_data_uri,
    }


def cover_data_uri(art_bytes):
    if not art_bytes:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(art_bytes).decode("ascii")

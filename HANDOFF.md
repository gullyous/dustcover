# 🎛️ TIDAL Now-Playing Widget — Build Handoff

A custom Windows desktop widget that shows what's playing on **TIDAL** (cover,
title, artist) with transport controls and a compact ↔ expanded toggle — the
same idea as the Windows media flyout in the reference screenshot, but ours,
styled in a Tidal "dark glass" look.

This folder is a **running start**, not an empty repo. The hard, easy-to-get-wrong
parts are already written and verified. The fun UI work is teed up with a clear
contract and TODOs.

---

## ▶️ Paste this into Claude Code to start

> Build the TIDAL now-playing desktop widget in this folder. Read `HANDOFF.md`
> first — the stack is locked and the data layer is done. `media_backend.py`
> (SMTC reader + transport, complete), `icons.py` (complete), `config.py`,
> `main.py`, `requirements.txt`, and `run*.bat` already exist and work.
>
> Your job is `widget.py`: turn the plain runnable baseline into the polished
> widget described in its header TODOs — Tidal dark-glass frameless card,
> album-art ambient background, **compact ↔ expanded toggle**, transport
> controls, non-seekable progress in expanded mode. Keep the signal/slot
> contract (`playpause_clicked`, `next_clicked`, `prev_clicked`,
> `quit_requested`, `on_update(info)`) stable so `main.py` keeps working.
>
> First run `python media_backend.py` with TIDAL playing to confirm the data
> layer, then iterate on the UI with `run-debug.bat`. Finish against the
> Acceptance Checklist in `HANDOFF.md`.

---

## ✅ Status: what's done vs. what's left

**Done (verified, leave alone unless improving):**
- `media_backend.py` — reads now-playing from Windows SMTC and sends
  play/pause/next/prev. Handles the asyncio↔Qt threading, album-art bytes,
  track-change detection, app filtering, and the winsdk/winrt import shim.
  Has a `python media_backend.py` self-test that prints the current track.
- `icons.py` — play / pause / next / prev / close / expand / collapse, drawn
  with QPainter (no asset files, no icon font).
- `main.py`, `config.py`, `requirements.txt`, `run.bat`, `run-debug.bat`.

**Left to build (the assignment):**
- `widget.py` — currently a plain but **runnable** baseline. Make it the real
  thing per the TODO block at the top of the file (and the checklist below).

---

## 🔒 Locked decisions (don't relitigate)

- **Platform:** Windows (the user is on Windows; SMTC is Windows-only).
- **Stack:** Python + **PySide6** (GUI) + **winsdk** (Windows Runtime / SMTC).
  Chosen because it's the fastest path to a polished widget and trivial to run.
- **Data source:** **System Media Transport Controls (SMTC)** — *not* the Tidal
  web API. See below.
- **Features in scope:** album art, play/pause, prev/next, **compact ↔ expanded
  toggle**, Tidal dark-glass styling, frameless always-on-top + draggable.
- **Out of scope (stretch goals):** seekable scrubbing, global hotkeys, lyrics.

---

## 💡 Why SMTC (the key insight)

The widget in the reference screenshot *is* the Windows SMTC flyout. Any app
that integrates with SMTC (Spotify, browsers, and **TIDAL's desktop app**)
publishes its now-playing metadata and accepts transport commands through it.

So instead of fighting the Tidal API (OAuth, rate limits, no real-time playback
position for the user's own session), we read the exact session Windows already
knows about. **No API keys, no login, works the moment TIDAL is playing.** A
known project, `tidal-rpc`, uses the same SMTC mechanism for Tidal, confirming
the desktop app reports to it.

---

## 🔬 Confirmed API (already implemented in media_backend.py)

```python
# winsdk projects WinRT to snake_case and async methods to awaitables.
mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
session = mgr.get_current_session()            # or iterate mgr.get_sessions()
props   = await session.try_get_media_properties_async()
#   props.title / props.artist / props.album_title / props.thumbnail
status  = session.get_playback_info().playback_status   # == ...PlaybackStatus.PLAYING
tl      = session.get_timeline_properties()             # tl.position / tl.end_time (timedelta)

# transport:
await session.try_toggle_play_pause_async()
await session.try_skip_next_async()
await session.try_skip_previous_async()

# album art: thumbnail -> stream -> Buffer -> DataReader -> bytes (see _read_thumbnail)
```

---

## ⚠️ Gotchas (already handled — keep handled)

- **asyncio + Qt:** all WinRT calls run on one worker thread with its own event
  loop. The UI talks to it via a Qt signal (out) and a `queue.Queue` (in).
  Don't call WinRT from the UI thread — enqueue a command instead.
- **Album art bytes:** read via `Buffer` + `DataReader.from_buffer`; wrap the
  result in `bytes(bytearray(...))` (works whether it returns bytes or list[int]).
- **Only reload art on track change** — compare `(title, artist, album)`.
- **winsdk vs winrt:** `media_backend.py` tries `winsdk.*` then falls back to
  the split `winrt.windows.*` packages — same class names either way.
- **App filtering:** prefer a session whose `source_app_user_model_id` contains
  `config.MATCH_APP` ("tidal"), preferring one that's playing; fall back to the
  current session if `config.FALLBACK_TO_ANY`.
- **Frameless window:** use `Qt.Tool` so it stays out of the taskbar (then close
  via the in-widget control / right-click Quit, since there's no taskbar entry).

---

## 🗂️ File map

| File | Role | State |
|------|------|-------|
| `config.py` | user-tweakable settings (match app, accent, poll, etc.) | done |
| `media_backend.py` | SMTC reader + transport, Qt worker thread, self-test | **done** |
| `icons.py` | QPainter-drawn transport/UI icons | done |
| `widget.py` | the widget UI — **your assignment** | baseline only |
| `main.py` | wires worker ↔ widget, runs the app | done |
| `requirements.txt` | PySide6 + winsdk | done |
| `run.bat` | one-click: venv + install + launch (no console) | done |
| `run-debug.bat` | same, console stays open, runs backend self-test first | done |

---

## 🚀 Run it (Windows)

1. Install Python 3.10+ (tick **Add Python to PATH**).
2. Open TIDAL and play a track.
3. Double-click **`run.bat`** (first run builds a venv + installs deps).
   - Troubleshooting? Use **`run-debug.bat`** to see logs + the backend self-test.

Move it by dragging anywhere on the card. Right-click → **Quit**.

---

## 🎯 Acceptance checklist (definition of done)

- [ ] `python media_backend.py` prints the current TIDAL track + art byte count.
- [ ] Widget launches frameless, always-on-top, draggable, no taskbar button.
- [ ] Shows live cover, title, artist; updates within ~0.5s of track changes.
- [ ] Play/pause button toggles TIDAL and reflects the real state; next/prev work.
- [ ] **Compact ↔ expanded** toggle works (button + double-click) and resizes.
- [ ] Tidal dark-glass styling with album-art ambient background; rounded card
      + drop shadow; `config.ACCENT` used for accents.
- [ ] Expanded mode shows a progress line from position/duration.
- [ ] Graceful "Nothing playing" state when TIDAL is closed/paused with no session.

---

## 🌟 Stretch goals (after the checklist)

Seekable progress (`try_change_playback_position_async`), global media hotkeys,
real Windows acrylic blur via `SetWindowCompositionAttribute`, accent color
sampled from the album art, lyrics panel, a tray icon + autostart, and a small
settings popover that edits `config.py`.

---

## 📚 Sources

- [winsdk — GlobalSystemMediaTransportControlsSessionManager usage](https://github.com/da-rth/yasb/pull/13)
- [Microsoft Learn — GlobalSystemMediaTransportControlsSessionManager](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager?view=winrt-26100)
- [Microsoft Learn — Integrate with System Media Transport Controls](https://learn.microsoft.com/en-us/windows/apps/develop/media-playback/integrate-with-systemmediatransportcontrols)
- [tidal-rpc — Tidal + SMTC, confirms desktop app reports to SMTC](https://github.com/Emiferpro/tidal-rpc)
- [pywinrt/python-winsdk — DataReader.read_bytes discussion](https://github.com/pywinrt/python-winsdk/issues/41)

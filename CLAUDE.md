# Tidal Desktop Widget — Project Facts (CLAUDE.md)

## What this is
**tidal-widget** — A Windows desktop "now-playing" widget for TIDAL. Shows cover art, title, artist, and transport controls in a frameless "dark glass" window. Reads playback from Windows **SMTC** (System Media Transport Controls — the same mechanism behind the volume-flyout). No API keys, no setup; works the moment TIDAL is playing. Optional TIDAL sign-in for heart (favorite) and quality-badge features.

Ships as a standalone `TidalNowPlaying.exe` (PyInstaller). Source is Python 3.10+.

## Repo
- **Local path:** `C:\dev\tidal-widget`
- **GitHub:** https://github.com/gullyous/Tidal-Widget
- **Active branch:** `main`

## Why C:\dev\, not the Desktop
ProtonDrive syncs the Desktop (`C:\Users\9i\Desktop`) and creates `… (# Name clash <date> <hash> #)` conflict files when it races git's writes inside `.git/`. These corrupt the git object store. This repo (and bull-operative) were moved to `C:\dev\` to stay outside the ProtonDrive sync boundary entirely. `C:\dev\` is a plain local directory — not synced.

## Source structure
| File | Purpose |
|---|---|
| `main.py` | Entry point |
| `widget.py` | Main UI — the "dark glass" floating window |
| `media_backend.py` | SMTC polling and playback state |
| `tidal_likes.py` | TIDAL OAuth + heart/quality-badge features |
| `config.py` | User preferences (JSON on disk) |
| `settings.py` / `settings_dialog.py` | Preferences dialog |
| `hotkeys.py` | Global hotkey registration |
| `icons.py` | Icon/image helpers |
| `updater.py` | In-app update checker (HTTPS, SHA-256 verified) |
| `build.bat` | PyInstaller build script |
| `TidalNowPlaying.spec` | PyInstaller spec |
| `run.bat` / `run-debug.bat` | Dev launch (creates venv, installs deps) |

## Key behaviors
- SMTC path needs no auth — works with TIDAL, Spotify, browsers, or anything using SMTC
- Heart/quality badge require one-time TIDAL sign-in (OAuth); can be skipped entirely
- Frameless, always-on-top, taskbar-excluded; drag to reposition, snaps to nearest screen corner on release
- Compact bar ↔ expanded card toggle via button, double-click, or tray menu
- Ships unsigned — first-run Windows SmartScreen warning is expected ("More info → Run anyway")
- Update checker can be disabled in preferences

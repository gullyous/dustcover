# TIDAL Now-Playing Widget

A polished "dark glass" desktop widget for Windows that shows what's currently
playing on **TIDAL** (cover art, title, artist) with transport controls, a
compact/expanded view, and a system-tray menu. It reads playback straight from
Windows, so there are no API keys, no login, and no configuration required to
get going.

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6)
![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)

<p align="center">
  <img src="assets/expanded.png" width="330" alt="Expanded view">
  <img src="assets/compact.png" width="330" alt="Compact view">
</p>

> **Disclaimer:** This is an unofficial, third-party tool. It is not affiliated
> with, endorsed by, or sponsored by TIDAL or Aspiro AB. "TIDAL" is a trademark
> of its respective owner and is used here only to describe compatibility.

## Features

- Live cover art, title, and artist, updating within about half a second of a track change
- Play / pause, next, and previous controls
- Compact bar and expanded card, toggled by button, double-click, or tray menu
- Blurred album-art ambient background for the signature "dark glass" look
- Configurable transparency and accent color
- Smooth progress bar in the expanded view
- System-tray icon with full controls and quit
- Frameless, always-on-top, draggable, and stays out of the taskbar
- Ships as a single standalone `.exe`, no Python needed to run it

## How it works

The widget reads the active session from the Windows **System Media Transport
Controls (SMTC)**, the same mechanism behind the volume-flyout media controls.
Any app that integrates with SMTC publishes its now-playing metadata and accepts
transport commands through it, including the TIDAL desktop app. That means no
OAuth, no API keys, and it works the moment TIDAL is playing. If TIDAL is not
running, it can optionally follow whatever else is playing (Spotify, a browser,
and so on).

## Requirements

- Windows 10 or 11
- The TIDAL desktop app (running and playing)
- Only to run from source or build it yourself: Python 3.10+ (the prebuilt `.exe` needs neither)

## Get it

### Option A: Download the .exe (easiest)

1. Download the latest `TidalNowPlaying.exe` from the
   [Releases](https://github.com/gullyous/tidal-widget/releases/latest) page.
2. Open TIDAL and play a track.
3. Double-click the `.exe`. The first launch takes a few seconds while it unpacks.

The app is unsigned, so Windows SmartScreen may show a warning the first time.
Click **More info -> Run anyway**, or build it yourself (below) if you prefer.

### Option B: Run from source

1. Install Python 3.10+ (tick **Add Python to PATH**).
2. Open TIDAL and play a track.
3. Double-click **`run.bat`** (it creates a virtual environment, installs
   dependencies, and launches). Use **`run-debug.bat`** to see logs and a
   backend self-test.

## Build your own .exe

Double-click **`build.bat`**, or run:

```bat
pip install -r requirements.txt pyinstaller
python make_icon.py
pyinstaller --noconfirm --onefile --windowed --name TidalNowPlaying --icon icon.ico --collect-all winsdk main.py
```

The result is `dist\TidalNowPlaying.exe`.

## Usage

- **Move it:** drag anywhere on the card.
- **Resize:** double-click the card, or use the chevron in the top-right corner, to switch between compact and expanded.
- **System tray:** left-click the tray icon to show or hide the widget; right-click for a menu with the current track, play/pause, next, previous, show/hide, expand/compact, and quit.
- **Quick menu:** right-click the card for expand/compact, hide to tray, and quit.

## Configuration

Edit `config.py` and relaunch (or rebuild the `.exe`).

| Setting | Default | What it does |
|---|---|---|
| `MATCH_APP` | `"tidal"` | Which app's session to follow (matched against the app id). |
| `FALLBACK_TO_ANY` | `True` | If TIDAL is not playing, follow any other player (Spotify, a browser, etc.). |
| `POLL_MS` | `500` | How often to refresh now-playing info, in milliseconds. |
| `ACCENT` | `"#39d6e0"` | Accent color for the play button and progress bar. |
| `START_EXPANDED` | `False` | Start in the larger expanded card. |
| `ALWAYS_ON_TOP` | `True` | Keep the widget above other windows. |
| `BACKGROUND_OPACITY` | `0.82` | Panel transparency (0.0 = clear, 1.0 = solid); text and controls stay opaque. |
| `WINDOW_OPACITY` | `1.0` | Fade the entire widget, text included. Lower for a fully ghosted look. |

## Project structure

| File | Role |
|---|---|
| `main.py` | Entry point; wires the backend worker to the widget. |
| `widget.py` | The UI: card, compact/expanded modes, tray icon, transparency. |
| `media_backend.py` | SMTC reader and transport commands, on a worker thread. |
| `icons.py` | Transport and app icons drawn at runtime with QPainter. |
| `config.py` | User settings (see above). |
| `make_icon.py` | Generates `icon.ico` for the packaged app. |
| `build.bat` | One-click build of the standalone `.exe`. |
| `run.bat` / `run-debug.bat` | Run from source (with or without a console). |
| `requirements.txt` | Python dependencies (PySide6, winsdk). |

## Troubleshooting

- **"Nothing playing":** open TIDAL and press play. SMTC only reports while a media session exists.
- **Can't find the window:** by design it has no taskbar button. Use the tray icon (left-click to show), or it sits in the bottom-right corner by default.
- **SmartScreen / antivirus warning:** expected for an unsigned PyInstaller binary. Use **More info -> Run anyway**, or build it yourself.
- **Need logs:** run `run-debug.bat`, or `python media_backend.py` to print the current track and album-art byte count.

## Tech and acknowledgements

- [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python), licensed under LGPLv3
- [winsdk](https://github.com/pywinrt/python-winsdk) (Python WinRT projection), licensed under MIT
- Icons are drawn at runtime with QPainter, so there are no image assets to ship

Because the packaged `.exe` bundles PySide6 (LGPLv3), the full source for this
project is published here so the Qt components remain replaceable, as LGPL
intends.

## Credits

Made by **[gullyous](https://github.com/gullyous)**.

## License

Released under the **MIT License**. See the [LICENSE](LICENSE) file for details.

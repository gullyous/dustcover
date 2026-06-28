# Changelog

All notable changes to this project are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **In-app updates.** The widget can check GitHub for new releases on startup
  and via a tray "Check for updates..." item. When one is found you can update
  with one click (Update now / Skip this version / Later); the download is over
  HTTPS and verified with a SHA-256 checksum before it runs, then the app swaps
  itself and restarts. Toggle "Check for updates on startup" in Settings; the
  About tab and README document exactly what data the check sends.
- Settings now has an **About** tab: version, links (repository, releases, report
  an issue), system info, a Licenses viewer (app license + third-party), and a
  **Check for updates** button.
- Right-clicking the widget opens a management menu (Settings, Open TIDAL, check
  for updates, sign in, hide, expand/compact, quit). Transport stays on the
  on-screen buttons; the tray icon keeps the full menu for when the widget is
  hidden.

### Changed
- "Sign in to TIDAL" now appears only when you are not signed in, with a tooltip
  explaining it powers the optional likes and quality badge (the now-playing
  display never needs it).
- Removed the desktop balloon notifications (e.g. "Opening TIDAL"); feedback is
  shown in the widget itself instead.
- The "Open TIDAL" action is no longer labelled "change quality"; opening TIDAL
  is useful for switching playlists too.
- Relicensed from MIT to the **GNU General Public License v3.0** (GPLv3), with
  SPDX headers across the source files. Versions up to and including 1.0.0 remain
  available under the MIT License.

### Fixed
- TIDAL login no longer silently expires: the OAuth token is re-saved after it
  refreshes, so favorites/quality keep working across launches.
- Clean shutdown: the SMTC worker thread is joined and its asyncio loop closed
  on exit (no "QThread destroyed while running" / leaked loop).
- Capability detection now fails closed: if controls can't be read, seek/
  shuffle/repeat are treated as unsupported instead of shown.
- Liking a track no longer blocks the quality lookup (the network search runs
  without holding the favorites lock).
- Track times over one hour now display as `H:MM:SS` instead of `62:00`.

## [1.0.0] - 2026-06-27

First release.

### Added
- Dark-glass TIDAL now-playing widget for Windows, reading from SMTC.
- Live cover art, title, and artist with track-change detection.
- Play / pause, next, and previous transport controls.
- Compact and expanded layouts, toggled by button, double-click, or tray menu.
- Blurred album-art ambient background with configurable transparency
  (`BACKGROUND_OPACITY`, `WINDOW_OPACITY`) and accent color.
- Smooth, interpolated progress bar in the expanded view.
- System-tray icon with controls, show/hide, and quit.
- Heart button to favorite the playing track to your TIDAL collection (optional,
  one-time OAuth sign-in via tidalapi; token stored locally in %APPDATA%).
- Custom multi-resolution app icon for the window, tray, and packaged `.exe`.
- Drag-to-reposition that locks the widget into the nearest screen corner on
  release (preserved across compact/expanded resizes and on multi-monitor).
- Seekable progress bar (drag to scrub) via SMTC.
- Shuffle and repeat toggles, capability-gated (shown only when the source supports them).
- Adaptive controls that grey out / hide actions the current source doesn't support.
- Preferences dialog with persisted settings (QSettings): accent, panel/window
  opacity, refresh interval, always-on-top, start-expanded, follow-other-apps.
- Run-at-Windows-startup toggle and optional global hotkeys (pynput).
- More reliable play/pause: discrete play/pause by state, since TIDAL ignores the
  SMTC toggle command when paused.
- Quality badge showing the best quality a track is available in on TIDAL
  (MAX / Hi-Res / Lossless / High / Atmos), with an "Open TIDAL" action.
- Standalone Windows `.exe` build via PyInstaller (`build.bat`).
- GitHub Actions workflow that builds and attaches the `.exe` to tagged releases.

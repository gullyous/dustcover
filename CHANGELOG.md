# Changelog

All notable changes to this project are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.4.1] - 2026-07-02

### Fixed
- **Track position now actually tracks.** TIDAL reports its timeline position
  to Windows only on seek and track change, so the progress bar and time label
  sat at 0:00 (and synced lyrics ran off the same frozen clock). The backend now
  derives the live position from the timestamp of TIDAL's last report, holds it
  while paused, and excludes paused time after resume. Apps that report
  continuously are unaffected.
- **In-app release notes are current again.** Settings > Updates was showing a
  hardcoded copy of the notes that had gone stale at v1.1.1; the pane now
  renders this changelog directly (bundled into the exe), so it always matches
  the version you're running.

## [1.4.0] - 2026-07-01

### Added
- **Karaoke wipe**: the active lyric line fills with the accent color in time
  with the vocal (interpolated between line timestamps), with smooth animation
  that runs only while lyrics are visible and playing.
- **Countdown dots**: during long instrumental breaks, three dots drain down so
  you know exactly when the next lyric lands.
- **Duotone accent**: with auto-accent on, two colors are sampled from the album
  art and the play button, progress bar, and volume slider carry the gradient.
- **Game mode**: the widget hides itself while a fullscreen app (game, video)
  owns its monitor and returns when it's gone. Off switch in Settings.
- **Live tray icon**: the tray shows the current album art with an accent
  progress ring, dimmed while paused. Off switch in Settings.
- **Full-res cover art**: when signed in, the small system thumbnail is silently
  upgraded to TIDAL's high-resolution cover; "Save cover art..." (tray and
  right-click menus) saves it to disk.
- **Track radio**: "Track radio (more like this)" opens a TIDAL mix seeded from
  the playing song in a standalone web-player window (needs sign-in).
- **Single instance + CLI verbs**: launching the exe again surfaces the running
  widget instead of starting a duplicate, and `--cmd playpause|next|prev|like|
  show|hide|toggle|expand` remote-controls it (Stream Deck / AutoHotkey ready).

## [1.3.0] - 2026-07-01

### Added
- **The heart reflects your actual TIDAL collection.** When signed in, a track
  already in your collection now shows a filled heart, and clicking it un-favorites
  correctly (before, the heart always started empty and could only ever add). Your
  own like/unlike stays authoritative even while the collection is still loading.
- **Copy lyrics**: right-click the lyrics panel for "Copy all lyrics" or "Copy
  current line".
- **Sync nudge is discoverable**: a dim "scroll to sync" signifier shows on synced
  lyrics until you nudge (then it becomes the offset badge).

### Changed
- The album art dims while playback is paused, so you can tell play state at a glance.

### Fixed
- Lyrics are cached per (title, artist, **album, and duration**), so two recordings
  that share a title/artist (a live version, a remaster, a cover) no longer show
  each other's lyrics or timings.
- Signing in while a track is already playing now refreshes that track's quality
  badge and heart immediately, instead of waiting for the next track.
- A plain click (or double-click) on the card no longer nudges the widget or
  rewrites its saved position; dragging now needs a small deliberate movement.

## [1.2.0] - 2026-07-01

### Added
- **Synced lyrics**: a karaoke-style panel in the expanded view (toggle by the
  times row). The active line is centered and accented and auto-scrolls with the
  song; click any line to seek to it. Lyrics come from LRCLIB (free, keyless);
  the toggle dims (disabled, with a "No lyrics for this track" tooltip) when a
  track has none, so it won't open an empty panel. The lyrics button is on both
  the compact bar and the expanded view; on compact it expands straight in.
- **Plain-lyrics fallback**: tracks with no time-synced LRC now show their plain
  (unsynced) lyrics as a scroll-through block instead of nothing, so the lyrics
  button lights up for many more tracks.
- **Sync nudge**: scroll on the lyrics panel to shift synced timings earlier or
  later when a track's LRC drifts (a small "sync +0.3s" badge shows the amount);
  middle-click resets it. The offset is remembered across runs (`LYRICS_OFFSET`).
- Optional **"Tint accent from album art"** (Settings -> Appearance): the play
  button, progress bar, quality badge and volume slider take a vivid color
  sampled from the current cover, with a contrast-aware icon. Off by default.
- Tooltips (showing the hotkey) and accessible names on the transport buttons;
  capability-disabled controls now render visibly inert instead of identical.
- Remembers the monitor + corner you left the widget on, and restores it on launch.
- "Copy now playing" (tray and right-click menus) copies "Artist - Title" to the clipboard.

### Changed
- The card's ambient background is cached and rebuilt only when the size or
  artwork changes (not on every repaint), for smoother dragging.

### Fixed
- A transient lyrics lookup failure (offline, timeout, or a server error) is no
  longer cached as "no lyrics", so a track isn't stuck lyric-less until restart;
  the lookup is retried the next time you land on that track.

## [1.1.1] - 2026-06-29

### Added
- A tiny volume slider under the compact controls, for quick volume changes
  without expanding the widget.

### Fixed
- The expand chevron no longer overlaps the next-track button in the compact bar
  (the bar is slightly taller to fit the volume slider below the controls).

## [1.1.0] - 2026-06-29

### Added
- **Volume slider** in the expanded card: controls the playing app's volume
  (TIDAL desktop, or your browser for the web player) via the Windows Core Audio
  APIs, with a system-volume fallback and a mute toggle. Hidden automatically
  when nothing controllable is found.
- **TIDAL web player** menu item (tray + right-click): opens listen.tidal.com as
  a standalone app window via Edge/Chrome, so the widget is usable without the
  TIDAL desktop app. A browser-played session shows up via Windows media controls.
- **In-app updates.** The widget can check GitHub for new releases on startup
  and via a tray "Check for updates..." item. When one is found you can update
  with one click (Update now / Skip this version / Later); the download is over
  HTTPS and verified with a SHA-256 checksum before it runs, then the app swaps
  itself and restarts. Toggle "Check for updates on startup" in Settings; the
  About tab and README document exactly what data the check sends.
- Settings has an **About** tab (version, links, system info, Licenses viewer)
  and a dedicated **Updates** tab with the update toggle, a manual "Check for
  updates now" button, and in-app release notes.
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
- **Performance:** the backend blocks on a queue instead of polling ~10x/sec,
  reads playback info once per poll, and the progress timer runs only when
  playing + expanded + visible. The build is now driven by the committed
  PyInstaller spec with unused Qt modules excluded.

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

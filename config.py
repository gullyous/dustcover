# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

# -------------------------------------------------------------------
# Tidal Now-Playing Widget - user settings
# Edit these values, then re-run the widget.
# -------------------------------------------------------------------

# Which media session to follow. Matched (case-insensitive) against the
# app's reported ID, so "tidal" follows the TIDAL desktop app.
MATCH_APP = "tidal"

# If TIDAL isn't running/playing, show whatever else is currently playing
# (Spotify, a browser, etc.) instead of an empty widget. Set False to only
# ever show TIDAL.
FALLBACK_TO_ANY = True

# How often (milliseconds) to refresh the now-playing info.
POLL_MS = 500

# Accent color used for the play button and progress bar.
ACCENT = "#39d6e0"

# Panel transparency (0.0 = invisible, 1.0 = solid). The card background and
# album-art ambience are painted at this opacity so the desktop shows through,
# while text, cover, and buttons stay fully opaque and readable ("dark glass").
BACKGROUND_OPACITY = 0.82

# Overall window opacity. This fades EVERYTHING uniformly, including text and
# buttons. Leave at 1.0 for the glass look above; lower it (e.g. 0.85) for a
# fully ghosted widget.
WINDOW_OPACITY = 1.0

# Start in the larger "expanded" card instead of the compact bar.
START_EXPANDED = False

# Keep the widget above other windows.
ALWAYS_ON_TOP = True

# Enable system-wide global hotkeys (needs the optional "pynput" package):
# Ctrl+Alt+Space play/pause, Ctrl+Alt+Left/Right prev/next, Ctrl+Alt+L like,
# Ctrl+Alt+H show/hide.
HOTKEYS_ENABLED = True

# App version, shown in Settings -> About.
APP_VERSION = "1.1.1"

# Check GitHub for a newer release on startup (silent), and enable the tray
# "Check for updates..." item. The check sends your app version and IP to
# GitHub over HTTPS at most once per launch. Turn off to make zero update
# network calls. (See README "Updates and privacy".)
CHECK_UPDATES = True

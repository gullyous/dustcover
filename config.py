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

# What the volume slider (and mute button) control:
#   "system" - the Windows system volume, exactly like your keyboard volume
#              keys and the taskbar speaker (they all move together).
#   "app"    - only the playing app's own volume (TIDAL, or your browser for
#              the web player), like the Windows Volume Mixer's per-app slider.
VOLUME_SCOPE = "system"

# Accent color used for the play button and progress bar.
ACCENT = "#39d6e0"

# When True, tint the accent (play button, progress, badge) from the current
# album art instead of using the fixed ACCENT above. Falls back to ACCENT when
# the art is too monochrome to pick a vivid color.
AUTO_ACCENT = False

# Fine-tune how far ahead (+) or behind (-) synced lyrics run, in seconds.
# Nudge it live by scrolling on the lyrics panel (middle-click to reset); the
# value is remembered across runs. Only affects time-synced (karaoke) lyrics.
LYRICS_OFFSET = 0.0

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

# Hide the widget automatically while a fullscreen app (game, video) owns the
# widget's monitor, and bring it back when the app closes or leaves fullscreen.
HIDE_ON_FULLSCREEN = True

# Live tray icon: show the current album art with an accent progress ring in
# the system tray instead of the static brand mark.
LIVE_TRAY = True

# Keep the widget above other windows.
ALWAYS_ON_TOP = True

# Enable system-wide global hotkeys (needs the optional "pynput" package):
# Ctrl+Alt+Space play/pause, Ctrl+Alt+Left/Right prev/next, Ctrl+Alt+L like,
# Ctrl+Alt+H show/hide.
HOTKEYS_ENABLED = True

# App version, shown in Settings -> About.
APP_VERSION = "1.6.1"

# Show what you're listening to on Discord ("Listening to TIDAL" with cover,
# title, artist and a live progress bar). Off by default. Needs a one-time
# Discord application id: create an app at https://discord.com/developers,
# copy its Application ID here (and optionally upload an art asset named
# "tidal" as the fallback icon). Without an id the feature stays inert.
DISCORD_RPC = False
DISCORD_CLIENT_ID = ""

# Submit your plays to ListenBrainz (an open, private listening history). Off by
# default. Paste a user token from https://listenbrainz.org/settings/ to enable.
SCROBBLE_LISTENBRAINZ = False
LISTENBRAINZ_TOKEN = ""

# Serve a now-playing overlay for OBS at http://127.0.0.1:<port>/overlay
# (localhost only). Off by default.
OBS_OVERLAY = False
OBS_OVERLAY_PORT = 8787

# Check GitHub for a newer release on startup (silent), and enable the tray
# "Check for updates..." item. The check sends your app version and IP to
# GitHub over HTTPS at most once per launch. Turn off to make zero update
# network calls. (See README "Updates and privacy".)
CHECK_UPDATES = True

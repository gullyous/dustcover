# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
main.py
-------
Entry point. Creates the Qt app, the SMTC worker, and the widget, then wires
them together. Run via run.bat (or `python main.py`).
"""

import sys
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import config
import icons
import settings
from fullscreen_watch import FullscreenWatcher
from hotkeys import HotkeyManager
from lyrics_backend import LyricsFetcher
from media_backend import MediaWorker
from settings_dialog import SettingsDialog
from tidal_likes import TidalLiker
from updater import Updater, maybe_run_helper, sweep_leftovers
from volume_backend import VolumeController
from widget import NowPlayingWidget

# ---- single instance + CLI verbs (Stream Deck / AutoHotkey friendly) --------
# `Dustcover.exe --cmd next` forwards a verb to the running widget over a
# local socket and exits. A bare second launch just surfaces the widget.
CMD_SERVER_NAME = "Dustcover-cmd"
CMD_VERBS = ("playpause", "next", "prev", "like", "show", "hide",
             "toggle", "expand")


def _cli_verb(argv):
    """The --cmd verb from argv, '' if malformed, None if not a cmd launch."""
    if "--cmd" not in argv:
        return None
    i = argv.index("--cmd")
    if i + 1 >= len(argv):
        return ""
    v = argv[i + 1].strip().lower()
    return v if v in CMD_VERBS else ""


def _forward_cmd(verb):
    """Send a verb to an already-running instance. True if one answered."""
    sock = QLocalSocket()
    sock.connectToServer(CMD_SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write((verb + "\n").encode("utf-8"))
    sock.flush()
    sock.disconnectFromServer()
    # On Windows the pipe write completes via the event loop, NOT waitFor*:
    # pump until the close handshake finishes so the verb actually lands
    # (disconnectFromServer holds the socket in ClosingState until flushed).
    deadline = time.time() + 1.0
    while (sock.state() != QLocalSocket.LocalSocketState.UnconnectedState
           and time.time() < deadline):
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return True


def main():
    # If we were re-launched as the self-update swap helper, do the swap and
    # exit BEFORE creating any Qt objects.
    if maybe_run_helper():
        return
    app = QApplication(sys.argv)

    # --cmd launches never start a second widget: forward the verb and exit.
    verb = _cli_verb(sys.argv)
    if verb is not None:
        if verb:
            _forward_cmd(verb)
        else:
            print("usage: --cmd " + "|".join(CMD_VERBS))
        return
    # Bare relaunch while an instance is running: surface it and exit.
    if _forward_cmd("show"):
        return
    QLocalServer.removeServer(CMD_SERVER_NAME)   # clear a stale pipe (crash)
    cmd_server = QLocalServer()
    if not cmd_server.listen(CMD_SERVER_NAME):
        # Not fatal: the widget runs fine, only --cmd control is unavailable.
        print(f"[cmd] could not listen on {CMD_SERVER_NAME}: "
              f"{cmd_server.errorString()}")

    settings.load_into_config()   # apply any saved overrides before building the UI
    app.setApplicationName("Dustcover")
    # Brand the running process: tray, taskbar and alt-tab all show the "E"
    # mark even before the app is packaged into a .exe. (The packaged build
    # also gets it from icon.ico via the PyInstaller .spec.)
    app.setWindowIcon(icons.app_icon(config.ACCENT))
    # The widget can be hidden to the system tray, so don't quit just because
    # no window is visible; quitting happens explicitly via the tray/menu.
    app.setQuitOnLastWindowClosed(False)

    widget = NowPlayingWidget()
    worker = MediaWorker()

    # backend -> UI
    worker.updated.connect(widget.on_update)
    # UI -> backend
    widget.playpause_clicked.connect(worker.play_pause)
    widget.next_clicked.connect(worker.next_track)
    widget.prev_clicked.connect(worker.prev_track)
    widget.seek_clicked.connect(worker.seek)
    widget.shuffle_clicked.connect(worker.toggle_shuffle)
    widget.repeat_clicked.connect(worker.cycle_repeat)
    # lifecycle
    widget.quit_requested.connect(app.quit)

    # optional TIDAL "favorite / add to collection" integration (heart button)
    liker = TidalLiker()
    widget.like_clicked.connect(liker.toggle)
    widget.signin_requested.connect(liker.start_login)
    liker.like_result.connect(widget.on_like_result)
    liker.login_link.connect(widget.on_login_link)
    liker.login_state.connect(widget.on_login_state)
    widget.quality_requested.connect(liker.quality)
    liker.quality_result.connect(widget.on_quality)
    widget.favorite_requested.connect(liker.favorite_state_request)
    liker.favorite_state.connect(widget.on_favorite_state)
    widget.cover_requested.connect(liker.fetch_cover)     # full-res album art
    liker.cover_ready.connect(widget.on_cover_hires)
    widget.radio_requested.connect(liker.radio)           # "more like this"
    liker.radio_result.connect(widget.on_radio)
    widget.playlists_requested.connect(liker.request_playlists)   # add-to-playlist
    liker.playlists_ready.connect(widget.on_playlists)
    widget.add_to_playlist_requested.connect(liker.add_to_playlist)
    widget.create_playlist_requested.connect(liker.create_playlist_with)
    liker.playlist_result.connect(widget.on_playlist_result)
    widget.on_login_state(liker.signed_in(), "")  # hide "Sign in" if already signed in

    # game mode: hide while a fullscreen app owns the widget's monitor
    fs_watch = FullscreenWatcher(lambda: int(widget.winId()))
    fs_watch.fullscreen_changed.connect(widget.on_fullscreen)
    fs_watch.start()

    # dispatch CLI verbs forwarded by later `--cmd` launches
    def _dispatch_cmd(v):
        actions = {
            "playpause": worker.play_pause,
            "next": worker.next_track,
            "prev": worker.prev_track,
            "like": widget._on_heart,
            "show": widget._show_widget,
            "hide": widget._hide_widget,   # owns the game-mode auto-hide flag
            "toggle": widget._toggle_visibility,
            "expand": widget.toggle_mode,
        }
        fn = actions.get(v)
        if fn:
            fn()

    def _on_cmd_connection():
        conn = cmd_server.nextPendingConnection()
        if conn is None:
            return
        def _read():
            data = bytes(conn.readAll()).decode("utf-8", "ignore")
            for v in data.split("\n"):
                v = v.strip().lower()
                if v:
                    _dispatch_cmd(v)
        conn.readyRead.connect(_read)
        conn.disconnected.connect(conn.deleteLater)   # don't accumulate sockets
        if conn.bytesAvailable():
            _read()   # data can land before the slot is connected
    cmd_server.newConnection.connect(_on_cmd_connection)

    # synced lyrics (LRCLIB, free / keyless)
    lyrics = LyricsFetcher()
    widget.lyrics_requested.connect(lyrics.fetch)
    lyrics.lyrics_ready.connect(widget.on_lyrics)

    # in-app auto-update (GitHub releases). Network work runs on a background
    # thread inside Updater; signals are delivered on the GUI thread.
    sweep_leftovers()  # clean any .new/.old/.upd-* from a prior update
    updater = Updater()

    def _on_update_available(rel):
        from update_dialog import UpdateDialog
        dlg = UpdateDialog(rel.get("name"), rel.get("tag_name"),
                           config.APP_VERSION, rel.get("body") or "", widget)

        def _progress(done, total):
            dlg.set_progress(done, total)

        def _done(status, msg):
            for sig, fn in ((updater.download_done, _done),
                            (updater.download_progress, _progress)):
                try:
                    sig.disconnect(fn)
                except (RuntimeError, TypeError):
                    pass
            if status == "relaunching":
                dlg.accept()   # unwind the modal loop before quitting
                app.quit()     # release the exe lock so the swap helper can run
            elif status == "source":
                dlg.accept()   # release page already opened in the browser
            else:
                dlg.show_error(msg)

        def _start():
            dlg.set_downloading()
            updater.download_progress.connect(_progress)
            updater.download_done.connect(_done)
            updater.download_async(rel)

        dlg.update_now.connect(_start)
        dlg.skip.connect(lambda: updater.skip_version(rel.get("tag_name")))
        dlg.exec()

    def _on_up_to_date(silent):
        if silent:
            return  # startup check stays quiet
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(widget, "No updates",
                               f"You're up to date (v{config.APP_VERSION}).")

    def _on_check_failed(msg, silent):
        if silent:
            return  # startup check stays quiet
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(widget, "Update check failed", msg)

    updater.update_available.connect(_on_update_available)
    updater.up_to_date.connect(_on_up_to_date)
    updater.check_failed.connect(_on_check_failed)
    # Tray/right-click "Check for updates..." runs a loud check.
    widget.check_updates_requested.connect(lambda: updater.check(silent=False))

    # per-app volume control (Windows Core Audio via pycaw, on its own COM
    # thread). Hidden automatically if pycaw is unavailable or nothing is found.
    volume = VolumeController()
    widget.volume_changed.connect(volume.set_volume)
    widget.mute_toggled.connect(volume.set_mute)
    volume.state_changed.connect(widget.on_volume_state)
    worker.updated.connect(
        lambda info: volume.set_source(info.get("source", "") if info.get("available") else ""))

    # optional Discord Rich Presence ("Listening to TIDAL")
    from discord_backend import DiscordPresence
    discord = DiscordPresence()
    worker.updated.connect(discord.on_update)
    liker.cover_url.connect(discord.set_cover)
    discord.set_enabled(getattr(config, "DISCORD_RPC", False))

    # optional ListenBrainz scrobbling
    from scrobble_backend import Scrobbler
    scrobbler = Scrobbler()
    worker.updated.connect(scrobbler.on_update)
    scrobbler.set_enabled(getattr(config, "SCROBBLE_LISTENBRAINZ", False))

    # optional OBS overlay server (localhost only)
    from obs_overlay import OverlayServer, state_from_info, cover_data_uri
    overlay = OverlayServer()
    _overlay_cover = {"uri": None}

    def _overlay_feed(info):
        if info.get("art_changed"):
            _overlay_cover["uri"] = cover_data_uri(info.get("art"))
        if not info.get("available"):
            _overlay_cover["uri"] = None
        overlay.set_state(state_from_info(info, widget._effective_accent(),
                                          _overlay_cover["uri"]))
    worker.updated.connect(_overlay_feed)
    if getattr(config, "OBS_OVERLAY", False):
        overlay.start(getattr(config, "OBS_OVERLAY_PORT", 8787))

    # global hotkeys (optional; needs pynput)
    hotkeys = HotkeyManager()
    hotkeys.play_pause.connect(worker.play_pause)
    hotkeys.next_track.connect(worker.next_track)
    hotkeys.prev_track.connect(worker.prev_track)
    hotkeys.like.connect(widget._on_heart)
    hotkeys.show_hide.connect(widget._toggle_visibility)
    if config.HOTKEYS_ENABLED and hotkeys.available():
        hotkeys.start()

    # clean shutdown: stop + join the worker thread (closing its asyncio loop)
    # and stop the hotkey listener before the app exits.
    def _cleanup():
        fs_watch.stop()
        cmd_server.close()
        updater.stop()
        volume.stop()
        discord.stop()
        scrobbler.stop()
        overlay.stop()
        worker.stop()
        worker.wait(2000)
        hotkeys.stop()
    app.aboutToQuit.connect(_cleanup)

    # settings dialog (from the tray menu)
    def open_settings():
        dlg = SettingsDialog(widget)
        dlg.check_updates_clicked.connect(lambda: updater.check(silent=False))
        if dlg.exec():
            v = dlg.values()
            settings.save({k: val for k, val in v.items() if k != "run_at_startup"})
            settings.set_run_at_startup(v["run_at_startup"])
            widget.apply_settings()
            discord.set_enabled(config.DISCORD_RPC)
            scrobbler.set_enabled(config.SCROBBLE_LISTENBRAINZ)
            if config.OBS_OVERLAY:
                if overlay.port() != config.OBS_OVERLAY_PORT:
                    overlay.start(config.OBS_OVERLAY_PORT)   # (re)bind on port change
            else:
                overlay.stop()
            if config.HOTKEYS_ENABLED and hotkeys.available():
                hotkeys.start()
            else:
                hotkeys.stop()
    widget.settings_requested.connect(open_settings)

    worker.start()
    widget.show()
    volume.start()

    # Silent startup check (only if enabled). A newer version pops the update
    # dialog; up-to-date/errors stay quiet (no loud handlers connected here).
    if config.CHECK_UPDATES:
        updater.check(silent=True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

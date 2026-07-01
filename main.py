# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
main.py
-------
Entry point. Creates the Qt app, the SMTC worker, and the widget, then wires
them together. Run via run.bat (or `python main.py`).
"""

import sys

from PySide6.QtWidgets import QApplication

import config
import icons
import settings
from hotkeys import HotkeyManager
from lyrics_backend import LyricsFetcher
from media_backend import MediaWorker
from settings_dialog import SettingsDialog
from tidal_likes import TidalLiker
from updater import Updater, maybe_run_helper, sweep_leftovers
from volume_backend import VolumeController
from widget import NowPlayingWidget


def main():
    # If we were re-launched as the self-update swap helper, do the swap and
    # exit BEFORE creating any Qt objects.
    if maybe_run_helper():
        return
    app = QApplication(sys.argv)
    settings.load_into_config()   # apply any saved overrides before building the UI
    app.setApplicationName("Tidal Now Playing")
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
    widget.on_login_state(liker.signed_in(), "")  # hide "Sign in" if already signed in

    # synced lyrics (LRCLIB, free / keyless)
    lyrics = LyricsFetcher()
    widget.lyrics_requested.connect(lyrics.fetch)
    lyrics.lyrics_ready.connect(widget.on_lyrics)

    # in-app auto-update (GitHub releases). Network work runs on a background
    # thread inside Updater; signals are delivered on the GUI thread.
    sweep_leftovers()  # clean any .new/.old/.upd-* from a prior update
    updater = Updater()

    def _on_update_available(rel):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        notes = (rel.get("body") or "").strip()
        if len(notes) > 1200:
            notes = notes[:1200] + "..."
        box = QMessageBox(widget)
        box.setWindowTitle("Update available")
        box.setIcon(QMessageBox.Information)
        box.setText(f"{rel.get('name') or rel.get('tag_name')} is available.\n"
                    f"You have v{config.APP_VERSION}.")
        if notes:
            box.setInformativeText(notes)
        b_now = box.addButton("Update now", QMessageBox.AcceptRole)
        b_skip = box.addButton("Skip this version", QMessageBox.DestructiveRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(b_now)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_skip:
            updater.skip_version(rel.get("tag_name"))
            return
        if clicked is not b_now:
            return
        # Download off the GUI thread so the widget never freezes; show a busy
        # dialog and act on the result delivered via download_done.
        progress = QProgressDialog("Downloading update...", "", 0, 0, widget)
        progress.setWindowTitle("Updating")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)

        def _done(status, msg):
            try:
                updater.download_done.disconnect(_done)
            except (RuntimeError, TypeError):
                pass
            progress.close()
            if status == "relaunching":
                app.quit()  # release the exe lock so the helper can swap it
            elif status == "source":
                pass  # release page already opened in the browser
            else:
                QMessageBox.warning(widget, "Update failed",
                                    msg or "The update could not be applied.")

        updater.download_done.connect(_done)
        progress.show()
        updater.download_async(rel)

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
        updater.stop()
        volume.stop()
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

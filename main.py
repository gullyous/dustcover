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
from media_backend import MediaWorker
from settings_dialog import SettingsDialog
from tidal_likes import TidalLiker
from widget import NowPlayingWidget


def main():
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
        worker.stop()
        worker.wait(2000)
        hotkeys.stop()
    app.aboutToQuit.connect(_cleanup)

    # settings dialog (from the tray menu)
    def open_settings():
        dlg = SettingsDialog(widget)
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

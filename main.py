"""
main.py
-------
Entry point. Creates the Qt app, the SMTC worker, and the widget, then wires
them together. Run via run.bat (or `python main.py`).
"""

import sys

from PySide6.QtWidgets import QApplication

from media_backend import MediaWorker
from widget import NowPlayingWidget


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tidal Now Playing")
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
    # lifecycle
    widget.quit_requested.connect(app.quit)
    app.aboutToQuit.connect(worker.stop)

    worker.start()
    widget.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

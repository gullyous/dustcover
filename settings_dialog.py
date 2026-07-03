# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
settings_dialog.py
------------------
The preferences dialog (tray -> "Settings...") with three tabs:
  * General  - Appearance / Behavior / Startup sections (collects values).
  * Updates  - the update toggle, a manual check, and release notes.
  * About    - version, links, system info, and licenses.

It only collects values; main.py applies and saves them so the live widget,
hotkeys, and startup entry all update together.
"""

import os
import platform
import re
import sys

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QTabWidget,
    QWidget, QCheckBox, QSlider, QPushButton, QLabel, QColorDialog,
    QDialogButtonBox, QSpinBox, QTextEdit,
)

import config
import settings

REPO = "https://github.com/gullyous/Tidal-Widget"

_LICENSES = f"""TIDAL Now-Playing Widget v{config.APP_VERSION}
Copyright (C) 2026 gullyous

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.

(Versions up to and including 1.0.0 were released under the MIT License.)

================================================================
Third-party components
================================================================

PySide6 (Qt for Python)
    License: LGPL v3
    https://www.qt.io/qt-for-python

winsdk (Python WinRT projection)
    License: MIT
    https://github.com/pywinrt/python-winsdk

tidalapi (unofficial TIDAL API client)
    License: LGPL v3
    https://github.com/tamland/python-tidal

pynput (global hotkeys)
    License: LGPL v3
    https://github.com/moses-palmer/pynput

pypresence (Discord Rich Presence)
    License: MIT
    https://github.com/qwertyquerty/pypresence

================================================================
This is an unofficial tool. It is not affiliated with, endorsed by, or
sponsored by TIDAL or Aspiro AB. "TIDAL" is a trademark of its respective owner.
"""


def _release_notes():
    """Release notes for the Updates tab, rendered from the bundled
    CHANGELOG.md so the in-app notes can never drift from the real history
    (they were previously a hand-maintained copy that went stale)."""
    base = (getattr(sys, "_MEIPASS", None)
            or os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "CHANGELOG.md"), encoding="utf-8") as f:
            md = f.read()
    except OSError:
        return ("Release notes could not be loaded.\n"
                f"They are always available at:\n{REPO}/releases")

    out, skipping, seen_release = [], False, False
    for line in md.splitlines():
        s = line.rstrip()
        m = re.match(r"^##\s*\[([^\]]+)\]\s*-?\s*(.*)$", s)
        if m:
            version, date = m.group(1), m.group(2).strip()
            skipping = version.lower() == "unreleased"
            if not skipping:
                if seen_release:
                    out.append("")
                out.append(f"v{version}" + (f"  ({date})" if date else ""))
                seen_release = True
            continue
        if skipping or not seen_release:
            continue   # preamble and the empty Unreleased section
        if s.startswith("### "):
            s = s[4:]
        s = s.replace("**", "").replace("`", "")
        if s or (out and out[-1]):     # collapse runs of blank lines
            out.append(s)
    return "\n".join(out).strip() or f"See {REPO}/releases"


class SettingsDialog(QDialog):
    check_updates_clicked = Signal()   # Updates tab "Check for updates" button
    _lb_checked = Signal(bool, str)    # ListenBrainz token-verify result (worker -> UI)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tidal Widget - Settings")
        self.setMinimumWidth(380)
        self.setStyleSheet(
            "QGroupBox { font-weight:600; margin-top:10px;"
            " border:1px solid #5a5a62; border-radius:6px; padding:10px 8px 8px 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left:10px; padding:0 4px; }")
        cur = settings.current()
        self._accent = str(cur["accent"])

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(cur), "General")
        tabs.addTab(self._build_integrations_tab(cur), "Integrations")
        tabs.addTab(self._build_updates_tab(cur), "Updates")
        tabs.addTab(self._build_about_tab(), "About")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        col = QVBoxLayout(self)
        col.addWidget(tabs)
        col.addWidget(bb)

    # ---- General tab -------------------------------------------------------
    def _build_general_tab(self, cur):
        self.accent_btn = QPushButton()
        self.accent_btn.setCursor(Qt.PointingHandCursor)
        self.accent_btn.clicked.connect(self._pick_accent)
        self._style_accent_btn()

        self.bg = QSlider(Qt.Horizontal)
        self.bg.setRange(30, 100)
        self.bg.setValue(int(round(float(cur["background_opacity"]) * 100)))

        self.win = QSlider(Qt.Horizontal)
        self.win.setRange(40, 100)
        self.win.setValue(int(round(float(cur["window_opacity"]) * 100)))

        self.auto_accent = QCheckBox("Tint accent from album art")
        self.auto_accent.setChecked(bool(cur.get("auto_accent", False)))

        appearance = QGroupBox("Appearance")
        af = QFormLayout(appearance)
        af.addRow("Accent color", self.accent_btn)
        af.addRow("Panel opacity", self.bg)
        af.addRow("Whole-widget opacity", self.win)
        af.addRow(self.auto_accent)

        self.aot = QCheckBox("Always on top")
        self.aot.setChecked(bool(cur["always_on_top"]))
        self.startexp = QCheckBox("Start in expanded view")
        self.startexp.setChecked(bool(cur["start_expanded"]))
        self.fallback = QCheckBox("Follow other apps when TIDAL isn't playing")
        self.fallback.setChecked(bool(cur["fallback_any"]))
        self.vol_system = QCheckBox("Volume slider controls the Windows system volume")
        self.vol_system.setToolTip(
            "On: the slider moves the system volume, in step with your keyboard "
            "volume keys.\nOff: it controls only the playing app's own volume "
            "(TIDAL / your browser).")
        self.vol_system.setChecked(
            str(cur.get("volume_scope", "system")).lower() != "app")
        self.hide_fs = QCheckBox("Hide while a fullscreen app is running (game mode)")
        self.hide_fs.setChecked(bool(cur.get("hide_fullscreen", True)))
        self.live_tray = QCheckBox("Live tray icon (album art + progress ring)")
        self.live_tray.setChecked(bool(cur.get("live_tray", True)))
        self.poll = QSpinBox()
        self.poll.setRange(200, 2000)
        self.poll.setSingleStep(100)
        self.poll.setSuffix(" ms")
        self.poll.setValue(int(cur["poll_ms"]))
        poll_row = QHBoxLayout()
        poll_row.addWidget(QLabel("Refresh interval"))
        poll_row.addStretch(1)
        poll_row.addWidget(self.poll)

        behavior = QGroupBox("Behavior")
        bl = QVBoxLayout(behavior)
        bl.addWidget(self.aot)
        bl.addWidget(self.startexp)
        bl.addWidget(self.fallback)
        bl.addWidget(self.vol_system)
        bl.addWidget(self.hide_fs)
        bl.addWidget(self.live_tray)
        bl.addLayout(poll_row)

        self.startup = QCheckBox("Start the widget when Windows starts")
        self.startup.setChecked(settings.is_run_at_startup())
        self.hotkeys = QCheckBox("Enable global hotkeys")
        self.hotkeys.setChecked(bool(cur["hotkeys_enabled"]))
        hk_hint = QLabel(
            "Ctrl+Alt+Space play/pause   |   Ctrl+Alt+Left/Right prev/next\n"
            "Ctrl+Alt+L like   |   Ctrl+Alt+H show/hide")
        hk_hint.setStyleSheet("color:#9a9aa3; font-size:11px;")

        startup = QGroupBox("Startup and shortcuts")
        sl = QVBoxLayout(startup)
        sl.addWidget(self.startup)
        sl.addWidget(self.hotkeys)
        sl.addWidget(hk_hint)

        note = QLabel("Refresh interval and 'start expanded' take effect on next launch.")
        note.setStyleSheet("color:#7d7d86; font-size:10px;")

        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(appearance)
        v.addWidget(behavior)
        v.addWidget(startup)
        v.addWidget(note)
        v.addStretch(1)
        return page

    # ---- Integrations tab --------------------------------------------------
    def _build_integrations_tab(self, cur):
        from PySide6.QtWidgets import QLineEdit

        # Discord Rich Presence
        self.discord_on = QCheckBox("Show what I'm listening to on Discord")
        self.discord_on.setChecked(bool(cur.get("discord_rpc", False)))
        self.discord_id = QLineEdit(str(cur.get("discord_client_id", "") or ""))
        self.discord_id.setPlaceholderText("Discord Application ID")
        d_hint = QLabel('Create an app at discord.com/developers, paste its '
                        'Application ID here. Needs the Discord desktop app running.')
        d_hint.setWordWrap(True); d_hint.setStyleSheet("color:#7d7d86; font-size:10px;")
        discord = QGroupBox("Discord Rich Presence")
        dl = QVBoxLayout(discord)
        dl.addWidget(self.discord_on)
        dl.addWidget(self.discord_id)
        dl.addWidget(d_hint)

        # ListenBrainz scrobbling
        self.lb_on = QCheckBox("Scrobble my plays to ListenBrainz")
        self.lb_on.setChecked(bool(cur.get("scrobble_listenbrainz", False)))
        self.lb_token = QLineEdit(str(cur.get("listenbrainz_token", "") or ""))
        self.lb_token.setEchoMode(QLineEdit.Password)
        self.lb_token.setPlaceholderText("ListenBrainz user token")
        verify = QPushButton("Verify token")
        verify.clicked.connect(self._verify_lb)
        self._lb_checked.connect(self._on_lb_checked)
        self._lb_status = QLabel("")
        self._lb_status.setStyleSheet("color:#9a9aa3; font-size:11px;")
        lb_row = QHBoxLayout(); lb_row.addWidget(verify, 0, Qt.AlignLeft)
        lb_row.addWidget(self._lb_status, 1)
        lb_hint = QLabel("Token from listenbrainz.org/settings. Only TIDAL plays "
                         "are submitted, and only after you've played enough of a track.")
        lb_hint.setWordWrap(True); lb_hint.setStyleSheet("color:#7d7d86; font-size:10px;")
        lbrainz = QGroupBox("ListenBrainz")
        ll = QVBoxLayout(lbrainz)
        ll.addWidget(self.lb_on)
        ll.addWidget(self.lb_token)
        ll.addLayout(lb_row)
        ll.addWidget(lb_hint)

        # OBS overlay
        self.obs_on = QCheckBox("Serve a now-playing overlay for OBS (localhost)")
        self.obs_on.setChecked(bool(cur.get("obs_overlay", False)))
        self.obs_port = QSpinBox(); self.obs_port.setRange(1024, 65535)
        self.obs_port.setValue(int(cur.get("obs_overlay_port", 8787)))
        obs_row = QHBoxLayout()
        obs_row.addWidget(QLabel("Port")); obs_row.addStretch(1)
        obs_row.addWidget(self.obs_port)
        obs_hint = QLabel("Add a Browser source in OBS pointing at "
                          "http://127.0.0.1:&lt;port&gt;/overlay. Bound to localhost only.")
        obs_hint.setWordWrap(True); obs_hint.setStyleSheet("color:#7d7d86; font-size:10px;")
        obs = QGroupBox("OBS overlay")
        ol = QVBoxLayout(obs)
        ol.addWidget(self.obs_on)
        ol.addLayout(obs_row)
        ol.addWidget(obs_hint)

        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(discord)
        v.addWidget(lbrainz)
        v.addWidget(obs)
        v.addStretch(1)
        return page

    def _verify_lb(self):
        import threading
        self._lb_status.setText("Checking...")
        self._lb_status.setStyleSheet("color:#9a9aa3; font-size:11px;")
        token = self.lb_token.text()

        def work():
            try:
                from scrobble_backend import validate_token
                ok, msg = validate_token(token)
            except Exception:
                ok, msg = False, "error"
            self._lb_checked.emit(ok, msg)   # queued back to the UI thread
        threading.Thread(target=work, daemon=True).start()

    def _on_lb_checked(self, ok, msg):
        self._lb_status.setText((f"Valid: {msg}" if ok else f"Invalid: {msg}"))
        self._lb_status.setStyleSheet(
            "color:%s; font-size:11px;" % ("#4fd07a" if ok else "#e06a6a"))

    # ---- Updates tab -------------------------------------------------------
    def _build_updates_tab(self, cur):
        page = QWidget()
        v = QVBoxLayout(page)

        self.check_updates = QCheckBox("Check for updates on startup")
        self.check_updates.setChecked(bool(cur.get("check_updates", True)))
        v.addWidget(self.check_updates)

        check_btn = QPushButton("Check for updates now")
        check_btn.clicked.connect(lambda: self.check_updates_clicked.emit())
        v.addWidget(check_btn, 0, Qt.AlignLeft)

        privacy = QLabel(
            "The check contacts GitHub over HTTPS and sends your app version and "
            "IP address. An update downloads over HTTPS, is verified with a "
            "SHA-256 checksum, and runs only after you confirm. Current builds "
            "are not code-signed, so Windows may warn about an unknown publisher.")
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color:#7d7d86; font-size:10px;")
        v.addWidget(privacy)

        notes_label = QLabel("Release notes")
        notes_label.setStyleSheet("font-weight:600; margin-top:8px;")
        v.addWidget(notes_label)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(_release_notes())
        v.addWidget(notes, 1)
        return page

    # ---- About tab --------------------------------------------------------
    def _build_about_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)

        title = QLabel(
            "<span style='font-size:15px; font-weight:700;'>TIDAL Now-Playing Widget</span>"
            f"&nbsp;&nbsp;<span style='color:#9a9aa3;'>v{config.APP_VERSION}</span>")
        desc = QLabel("A dark-glass desktop widget showing your current TIDAL track "
                      "with transport controls, seek, favorites, and a quality badge.")
        desc.setWordWrap(True)

        made = QLabel(f'Made by <a href="https://github.com/gullyous">gullyous</a>')
        made.setOpenExternalLinks(True)
        links = QLabel(
            f'<a href="{REPO}">Repository</a> &nbsp;&middot;&nbsp; '
            f'<a href="{REPO}/releases">Releases</a> &nbsp;&middot;&nbsp; '
            f'<a href="{REPO}/issues/new">Report an issue</a>')
        links.setOpenExternalLinks(True)
        links.setTextFormat(Qt.RichText)

        py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        sysinfo = QLabel(f"PySide6 {PYSIDE_VERSION}  |  Python {py}  |  "
                         f"{platform.system()} {platform.release()}")
        sysinfo.setStyleSheet("color:#7d7d86; font-size:10px;")

        disclaimer = QLabel(
            "Unofficial tool, not affiliated with, endorsed by, or sponsored by "
            "TIDAL or Aspiro AB. \"TIDAL\" is a trademark of its respective owner.")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet("color:#7d7d86; font-size:10px;")

        lic_btn = QPushButton("Licenses")
        lic_btn.clicked.connect(self._show_licenses)

        v.addWidget(title)
        v.addWidget(desc)
        v.addSpacing(6)
        v.addWidget(made)
        v.addWidget(links)
        v.addSpacing(8)
        v.addWidget(lic_btn, 0, Qt.AlignLeft)
        v.addStretch(1)
        v.addWidget(sysinfo)
        v.addWidget(disclaimer)
        return page

    def _show_licenses(self):
        d = QDialog(self)
        d.setWindowTitle("Licenses")
        d.resize(540, 480)
        lay = QVBoxLayout(d)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(_LICENSES)
        lay.addWidget(text)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.accept)
        bb.accepted.connect(d.accept)
        lay.addWidget(bb)
        d.exec()

    # ---- shared -----------------------------------------------------------
    def _pick_accent(self):
        c = QColorDialog.getColor(QColor(self._accent), self, "Accent color")
        if c.isValid():
            self._accent = c.name()
            self._style_accent_btn()

    def _style_accent_btn(self):
        self.accent_btn.setText(self._accent)
        self.accent_btn.setStyleSheet(
            f"background:{self._accent}; color:#06222a; padding:5px; font-weight:600;")

    def values(self):
        return {
            "accent": self._accent,
            "auto_accent": self.auto_accent.isChecked(),
            "background_opacity": self.bg.value() / 100.0,
            "window_opacity": self.win.value() / 100.0,
            "poll_ms": self.poll.value(),
            "always_on_top": self.aot.isChecked(),
            "start_expanded": self.startexp.isChecked(),
            "fallback_any": self.fallback.isChecked(),
            "volume_scope": "system" if self.vol_system.isChecked() else "app",
            "hide_fullscreen": self.hide_fs.isChecked(),
            "live_tray": self.live_tray.isChecked(),
            "hotkeys_enabled": self.hotkeys.isChecked(),
            "check_updates": self.check_updates.isChecked(),
            "discord_rpc": self.discord_on.isChecked(),
            "discord_client_id": self.discord_id.text().strip(),
            "scrobble_listenbrainz": self.lb_on.isChecked(),
            "listenbrainz_token": self.lb_token.text().strip(),
            "obs_overlay": self.obs_on.isChecked(),
            "obs_overlay_port": self.obs_port.value(),
            "run_at_startup": self.startup.isChecked(),
        }

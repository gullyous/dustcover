# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
update_dialog.py
----------------
The in-app "update available" dialog: a frameless dark-glass panel that matches
the widget instead of a stock message box. It renders the release notes cleanly,
uses on-brand buttons, and shows a real download progress bar (bytes / total)
in place of the old indeterminate spinner.

Signals:
  update_now()  skip()  later()   (later also fires on close/Esc)

Caller flow: connect the signals; on update_now start the download and call
set_downloading(); feed set_progress(done, total); on failure call show_error().
"""

import html
import re

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QColor, QPixmap, QPainter
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QProgressBar, QGraphicsDropShadowEffect,
)

import config
import icons

_INK = "#f4f4f7"
_SUBTLE = "#9a9aa6"
_PANEL = "#16161c"
_NOTES_BG = "#101014"


def notes_to_html(body, accent):
    """Render a release body (What's-new + changelog section) as tidy HTML."""
    out = []
    for raw in (body or "").splitlines():
        s = raw.rstrip()
        if not s.strip():
            out.append("<div style='height:6px'></div>")
            continue
        if s.strip() == "---":
            out.append(f"<hr style='border:none;border-top:1px solid #33333c;margin:8px 0'>")
            continue
        m = re.match(r"^#{1,6}\s*(.+)$", s)
        if m:
            out.append(f"<div style='color:{accent};font-weight:700;"
                       f"margin:10px 0 2px'>{html.escape(m.group(1))}</div>")
            continue
        if s.lstrip().startswith(("- ", "* ")):
            text = _inline(s.lstrip()[2:], accent)
            out.append(f"<div style='margin:2px 0 2px 2px;color:{_INK}'>"
                       f"<span style='color:{accent}'>&bull;</span>&nbsp;{text}</div>")
            continue
        if s.lower().startswith("what's new"):
            out.append(f"<div style='color:{_SUBTLE};font-size:12px;"
                       f"margin-bottom:4px'>{html.escape(s)}</div>")
            continue
        out.append(f"<div style='color:{_INK};margin:3px 0'>{_inline(s, accent)}</div>")
    return "".join(out)


def _inline(text, accent):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<span style='color:%s'>\1</span>" % accent, text)
    return text


class UpdateDialog(QDialog):
    update_now = Signal()
    skip = Signal()
    later = Signal()

    def __init__(self, new_name, new_tag, current_version, body, parent=None):
        super().__init__(parent)
        self._drag = None
        self._done = False
        accent = getattr(config, "ACCENT", "#39d6e0")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(460)

        card = QWidget(self)
        card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40); shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 200))
        card.setGraphicsEffect(shadow)

        # header: app mark + title + version line, close button top-right
        mark = QLabel()
        mark.setPixmap(icons.app_icon(accent).pixmap(44, 44))
        title = QLabel("Update available")
        title.setObjectName("title")
        ver = new_name or f"v{new_tag}"
        sub = QLabel(f"{ver} is ready  ·  you're on v{current_version}")
        sub.setObjectName("sub")
        head_text = QVBoxLayout(); head_text.setSpacing(1)
        head_text.addStretch(1); head_text.addWidget(title)
        head_text.addWidget(sub); head_text.addStretch(1)
        close = QPushButton("✕"); close.setObjectName("x")
        close.setFixedSize(26, 26); close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self._on_later)
        head = QHBoxLayout(); head.setSpacing(12)
        head.addWidget(mark); head.addLayout(head_text, 1)
        head.addWidget(close, 0, Qt.AlignTop)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setObjectName("notes")
        self.notes.setHtml(notes_to_html(body, accent))
        self.notes.setMinimumHeight(210)

        # download state (hidden until "Update now")
        self.bar = QProgressBar(); self.bar.setObjectName("bar")
        self.bar.setTextVisible(False); self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        self.status = QLabel(""); self.status.setObjectName("status")
        self.dl_box = QWidget()
        dl = QVBoxLayout(self.dl_box); dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(6)
        dl.addWidget(self.status); dl.addWidget(self.bar)
        self.dl_box.hide()

        # buttons
        self.b_skip = QPushButton("Skip this version"); self.b_skip.setObjectName("ghost")
        self.b_later = QPushButton("Later"); self.b_later.setObjectName("ghost")
        self.b_now = QPushButton("Update now"); self.b_now.setObjectName("accent")
        for b in (self.b_skip, self.b_later, self.b_now):
            b.setCursor(Qt.PointingHandCursor)
        self.b_skip.clicked.connect(self._on_skip)
        self.b_later.clicked.connect(self._on_later)
        self.b_now.clicked.connect(self._on_now)
        self.btns = QHBoxLayout(); self.btns.setSpacing(8)
        self.btns.addWidget(self.b_skip)
        self.btns.addStretch(1)
        self.btns.addWidget(self.b_later)
        self.btns.addWidget(self.b_now)

        cv = QVBoxLayout(card); cv.setContentsMargins(22, 20, 22, 18); cv.setSpacing(14)
        cv.addLayout(head)
        cv.addWidget(self.notes, 1)
        cv.addWidget(self.dl_box)
        cv.addLayout(self.btns)

        outer = QVBoxLayout(self); outer.setContentsMargins(18, 18, 18, 18)
        outer.addWidget(card)
        self.setStyleSheet(self._qss(accent))

    def _qss(self, accent):
        on = "#0a0a0a" if _lum(accent) > 140 else "#ffffff"
        return f"""
            QWidget#card {{ background:{_PANEL}; border-radius:16px;
                            border:1px solid rgba(255,255,255,0.06); }}
            QLabel#title {{ color:{_INK}; font-size:16px; font-weight:800; }}
            QLabel#sub   {{ color:{_SUBTLE}; font-size:11px; }}
            QLabel#status{{ color:{_SUBTLE}; font-size:11px; }}
            QTextBrowser#notes {{ background:{_NOTES_BG}; border:none;
                border-radius:12px; padding:12px; color:{_INK}; font-size:12px; }}
            QTextBrowser#notes QScrollBar:vertical {{ width:8px; background:transparent; }}
            QTextBrowser#notes QScrollBar::handle:vertical {{
                background:rgba(255,255,255,0.18); border-radius:4px; min-height:24px; }}
            QPushButton#accent {{ background:{accent}; color:{on}; border:none;
                border-radius:9px; padding:8px 18px; font-weight:700; }}
            QPushButton#accent:hover {{ background:{_lighten(accent)}; }}
            QPushButton#ghost {{ background:transparent; color:{_SUBTLE};
                border:none; border-radius:9px; padding:8px 12px; }}
            QPushButton#ghost:hover {{ color:{_INK}; background:rgba(255,255,255,0.08); }}
            QPushButton#x {{ background:transparent; color:{_SUBTLE}; border:none;
                border-radius:13px; font-size:13px; }}
            QPushButton#x:hover {{ background:rgba(255,255,255,0.10); color:{_INK}; }}
            QProgressBar#bar {{ background:rgba(255,255,255,0.12); border:none;
                border-radius:3px; }}
            QProgressBar#bar::chunk {{ background:{accent}; border-radius:3px; }}
        """

    # ---- state transitions ----
    def set_downloading(self):
        self.b_skip.hide(); self.b_later.hide(); self.b_now.hide()
        self.status.setText("Preparing download…")
        self.dl_box.show()

    def set_progress(self, done, total):
        if total > 0:
            frac = max(0.0, min(1.0, done / total))
            self.bar.setRange(0, 1000); self.bar.setValue(int(frac * 1000))
            self.status.setText(
                f"Downloading… {int(frac * 100)}%   "
                f"({_mb(done)} / {_mb(total)})")
        else:
            self.bar.setRange(0, 0)   # unknown size: indeterminate
            self.status.setText(f"Downloading… {_mb(done)}")

    def set_installing(self):
        self.bar.setRange(0, 0)
        self.status.setText("Verifying and installing…")

    def show_error(self, msg):
        self.dl_box.hide()
        self.status.setText("")
        err = QLabel(msg or "The update could not be applied.")
        err.setWordWrap(True); err.setStyleSheet("color:#e06a6a; font-size:12px;")
        self.notes.hide()
        self.layout().itemAt(0).widget().layout().insertWidget(1, err)
        self.b_skip.hide(); self.b_now.hide()
        self.b_later.setText("Close"); self.b_later.show()

    # ---- signals ----
    def _on_now(self):
        self._done = True
        self.update_now.emit()

    def _on_skip(self):
        self._done = True
        self.skip.emit()
        self.accept()

    def _on_later(self):
        if not self._done:
            self.later.emit()
        self.accept()

    def closeEvent(self, e):
        if not self._done:
            self.later.emit()
            self._done = True
        super().closeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._on_later()
        else:
            super().keyPressEvent(e)

    # ---- drag the frameless window ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def _mb(n):
    return f"{n / (1024 * 1024):.1f} MB"


def _lum(hexcolor):
    c = QColor(hexcolor)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


def _lighten(hexcolor):
    return QColor(hexcolor).lighter(115).name()

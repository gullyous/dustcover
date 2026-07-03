import os as _os, sys
sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")))
_os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import update_dialog as ud

fails = []
def check(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: fails.append(n)

acc = "#39d6e0"
body = "What's new in v1.5.1\n\n### Added\n- **Bold** and `code` item\n- plain item\n\n---\nfooter"
h = ud.notes_to_html(body, acc)
check("heading uses accent", acc in h and "Added" in h)
check("bold rendered", "<b>Bold</b>" in h)
check("code rendered in accent", "code" in h)
check("bullets present", h.count("&bull;") == 2)
check("divider rendered", "<hr" in h)
check("whats-new line dim", "new in v1.5.1" in h and ud._SUBTLE in h)
# html injection is escaped
hx = ud.notes_to_html("- <script>alert(1)</script>", acc)
check("html escaped (no raw tag)", "<script>" not in hx and "&lt;script&gt;" in hx)

# byte formatting
check("mb format", ud._mb(66_300_000) == "63.2 MB")

# dialog construction + signals
dlg = ud.UpdateDialog("Widget v1.5.1", "v1.5.1", "1.5.0", body)
got = {"now": 0, "skip": 0, "later": 0}
dlg.update_now.connect(lambda: got.__setitem__("now", got["now"] + 1))
dlg.skip.connect(lambda: got.__setitem__("skip", got["skip"] + 1))
dlg.later.connect(lambda: got.__setitem__("later", got["later"] + 1))

dlg.b_now.click()
check("Update now emits update_now", got["now"] == 1)
check("update_now marks done (no later on close)", dlg._done)
dlg.close(); check("no later after done", got["later"] == 0)

dlg2 = ud.UpdateDialog("v1.5.1", "v1.5.1", "1.5.0", body)
sk = {"n": 0}; dlg2.skip.connect(lambda: sk.__setitem__("n", 1))
dlg2.b_skip.click()
check("Skip emits skip", sk["n"] == 1)

dlg3 = ud.UpdateDialog("v1.5.1", "v1.5.1", "1.5.0", body)
lt = {"n": 0}; dlg3.later.connect(lambda: lt.__setitem__("n", 1))
dlg3.close()
check("closing without action emits later once", lt["n"] == 1)

# downloading state
dlg4 = ud.UpdateDialog("v1.5.1", "v1.5.1", "1.5.0", body)
dlg4.set_downloading()
check("downloading hides Update-now button", dlg4.b_now.isHidden())
check("downloading shows progress box", not dlg4.dl_box.isHidden())
dlg4.set_progress(33_150_000, 66_300_000)
check("progress at 50%", dlg4.bar.value() == 500)
check("progress text has mb", "MB" in dlg4.status.text() and "50%" in dlg4.status.text())
dlg4.set_progress(10, 0)   # unknown total -> indeterminate
check("unknown total -> indeterminate range", dlg4.bar.maximum() == 0)
dlg4.set_installing()
check("installing text", "install" in dlg4.status.text().lower())
dlg4.show_error("boom")
check("error hides notes + shows Close", dlg4.notes.isHidden() and dlg4.b_later.text() == "Close")

print("\nUpdateDialog:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)

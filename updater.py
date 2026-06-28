# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 gullyous

"""
updater.py
----------
In-app auto-update for the TIDAL Now-Playing widget.

Checks the official GitHub release of gullyous/Tidal-Widget, and (when running
as the packaged PyInstaller --onefile --windowed .exe) downloads the new
TidalNowPlaying.exe, optionally verifies its SHA-256 against a SHA256SUMS.txt
asset published in the SAME release, swaps the running exe via a detached helper
(the freshly-downloaded exe re-launched in --apply-update mode), and restarts.

Security posture (see README "Updates and privacy"):
  * HTTPS only, TLS verification ALWAYS on (system trust store). Never falls
    back to plain HTTP. A TLS failure aborts the update.
  * All URLs come from the releases/latest API JSON for the HARDCODED
    OWNER/REPO. The asset host is asserted to be a github.com /
    githubusercontent.com subdomain before downloading.
  * Never installs silently: the GUI always prompts before applying.
  * Checksum verification is integrity-only (it cannot prove authenticity,
    since whoever can publish a release can publish a matching checksum).
    Authenticode signing is the planned authenticity fix.

Networking uses ONLY the Python standard library (urllib).

Qt contract:
  Signals (all delivered on the GUI thread):
    update_available(dict)   -> a newer, non-skipped release was found
    up_to_date()             -> checked OK, already on the latest version
    check_failed(str)        -> the check could not complete (network/parse/etc.)
  Methods:
    check(silent=True)       -> run the network check on a background thread
    download_and_apply(rel)  -> download + verify + swap + restart (frozen);
                                open the release page (source)
    stop()                   -> join any running check thread (call on quit)

The helper branch (maybe_run_helper) must run at the very top of main() BEFORE
any Qt objects are created.
"""

import ctypes
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import threading
import webbrowser

import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import config

# --- Fixed identity (NEVER taken from user input / config / redirects) -------

OWNER = "gullyous"
REPO = "Tidal-Widget"
LATEST_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{OWNER}/{REPO}/releases/latest"

ASSET_NAME = "TidalNowPlaying.exe"
SUMS_NAME = "SHA256SUMS.txt"

# Hosts we will accept a download from, after redirects are resolved.
ALLOWED_HOST_SUFFIXES = (
    "github.com",
    "githubusercontent.com",
)

USER_AGENT = (
    f"TidalNowPlaying-Updater/{getattr(config, 'APP_VERSION', '0')} "
    f"(+https://github.com/{OWNER}/{REPO})"
)

API_HEADERS = {
    "User-Agent": USER_AGENT,                  # required by GitHub
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

API_TIMEOUT = 10            # seconds for the JSON metadata request
DOWNLOAD_TIMEOUT = 60       # seconds, per-read on the binary download
CHUNK = 64 * 1024
MAX_ASSET_BYTES = 500 * 1024 * 1024   # sanity cap

# Reuse the OS trust store. Never disable verification.
_SSL_CTX = ssl.create_default_context()

# Windows process-creation flags for a fully-detached, windowless helper.
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACH_FLAGS = (DETACHED_PROCESS | CREATE_NO_WINDOW |
                CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB)


# =============================================================================
#  Frozen / path helpers
# =============================================================================
def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def current_exe_path() -> str:
    # onefile: the real on-disk .exe the user launched (NOT _MEIPASS).
    return os.path.realpath(sys.executable)


def current_exe_dir() -> str:
    return os.path.dirname(current_exe_path())


def _log(msg: str):
    # Updater must stay non-fatal; logging only.
    print(f"[updater] {msg}")


def _safe_unlink(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# =============================================================================
#  Network: fetch latest release metadata (stdlib only)
# =============================================================================
def fetch_latest():
    """Return a normalized latest-release dict, or None on ANY failure.

    Never raises. None means 'could not check; stay on current version'.
    """
    req = urllib.request.Request(LATEST_URL, headers=API_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT, context=_SSL_CTX) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            data = json.loads(resp.read().decode(charset))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            if e.headers.get("x-ratelimit-remaining") == "0":
                _log(f"GitHub rate limit hit. Resets at epoch "
                     f"{e.headers.get('x-ratelimit-reset')}.")
            else:
                _log(f"GitHub returned {e.code} (forbidden).")
        elif e.code == 404:
            _log("No latest release found.")
        else:
            _log(f"GitHub HTTP error {e.code}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        _log(f"Network error contacting GitHub: {e.reason}")
        return None
    except socket.timeout:
        _log("Timed out contacting GitHub.")
        return None
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        _log(f"Could not parse GitHub response: {e}")
        return None
    except Exception as e:  # last-resort guard; never crash the app
        _log(f"Unexpected error checking for updates: {e}")
        return None

    if not isinstance(data, dict):
        return None
    if data.get("draft") or data.get("prerelease"):
        _log("Latest release is a draft/prerelease; ignoring.")
        return None
    if not data.get("tag_name"):
        return None

    return {
        "tag_name": data.get("tag_name"),
        "name": data.get("name") or data.get("tag_name"),
        "html_url": data.get("html_url") or RELEASE_PAGE,
        "body": data.get("body") or "",
        "prerelease": bool(data.get("prerelease")),
        "draft": bool(data.get("draft")),
        "assets": [
            {
                "name": a.get("name"),
                "browser_download_url": a.get("browser_download_url"),
                "size": a.get("size"),
                "content_type": a.get("content_type"),
                "state": a.get("state"),
            }
            for a in (data.get("assets") or [])
            if isinstance(a, dict)
        ],
    }


# --- Version comparison ------------------------------------------------------
def _parse_version(s):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    for sep in ("-", "+", " "):
        idx = s.find(sep)
        if idx != -1:
            s = s[:idx]
    parts = []
    for piece in s.split("."):
        piece = piece.strip()
        if piece.isdigit():
            parts.append(int(piece))
        else:
            num = ""
            for ch in piece:
                if ch.isdigit():
                    num += ch
                else:
                    break
            if num:
                parts.append(int(num))
            else:
                break
    return tuple(parts) if parts else None


def is_newer(current, tag):
    """True iff `tag` is strictly newer than `current`. Unparseable -> False."""
    cur = _parse_version(current)
    new = _parse_version(tag)
    if cur is None or new is None:
        return False
    n = max(len(cur), len(new))
    cur += (0,) * (n - len(cur))
    new += (0,) * (n - len(new))
    return new > cur


# --- Asset selection ---------------------------------------------------------
def find_asset(release, name):
    if not release:
        return None
    want = name.lower()
    for a in release.get("assets", []):
        if (a.get("name") or "").lower() == want and a.get("state") == "uploaded":
            return a
    return None


def _host_allowed(url) -> bool:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


# --- Streaming download ------------------------------------------------------
def download_asset(url, dest):
    """Stream-download `url` to `dest` atomically. Returns True on success.

    Verifies host is GitHub before downloading. Writes a temp file in the same
    directory, then os.replace()s to dest. Never raises.
    """
    if not url:
        return False
    if not url.lower().startswith("https://"):
        _log("Refusing non-HTTPS download URL.")
        return False
    if not _host_allowed(url):
        _log(f"Refusing download from unexpected host: {url}")
        return False

    # CDN download wants only User-Agent (no GitHub Accept/version headers).
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")

    d = os.path.dirname(os.path.abspath(dest)) or "."
    written = 0
    part = None
    try:
        os.makedirs(d, exist_ok=True)
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=_SSL_CTX) as resp:
            # Belt-and-suspenders: assert the *final* (post-redirect) host too.
            final_url = resp.geturl()
            if not _host_allowed(final_url):
                _log(f"Refusing: redirected to unexpected host: {final_url}")
                return False
            clen = resp.headers.get("Content-Length")
            expected = int(clen) if (clen and clen.isdigit()) else None
            if expected is not None and expected > MAX_ASSET_BYTES:
                _log(f"Refusing download: {expected} bytes exceeds cap.")
                return False

            fd, part = tempfile.mkstemp(prefix=".upd-", dir=d)
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_ASSET_BYTES:
                        raise IOError("Download exceeded maximum allowed size.")
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())

        if expected is not None and written != expected:
            _log(f"Size mismatch: got {written}, expected {expected}.")
            _safe_unlink(part)
            return False
        if written == 0:
            _log("Downloaded zero bytes.")
            _safe_unlink(part)
            return False

        os.replace(part, dest)   # atomic on same volume
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout,
            IOError, OSError) as e:
        _log(f"Download failed: {e}")
        _safe_unlink(part)
        return False
    except Exception as e:
        _log(f"Unexpected download error: {e}")
        _safe_unlink(part)
        return False


def fetch_text(url):
    """Fetch a small text asset (e.g. SHA256SUMS.txt) over verified TLS.

    Returns the decoded text or None. Used for the optional checksum file.
    """
    if not url or not url.lower().startswith("https://") or not _host_allowed(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT, context=_SSL_CTX) as resp:
            if not _host_allowed(resp.geturl()):
                return None
            raw = resp.read(1024 * 1024)  # checksum files are tiny; cap at 1 MiB
            return raw.decode("utf-8", "replace")
    except Exception as e:
        _log(f"Could not fetch checksum file: {e}")
        return None


def verify_sha256(file_path, sums_text, asset_name):
    """Verify file_path against a 'sha256sum'-format SHA256SUMS.txt body.

    Returns True only on a confirmed match. Missing entry / read error -> False.
    """
    want = None
    for line in (sums_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*").lower() == asset_name.lower():
            want = parts[0].lower()
            break
    if not want:
        return False
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return False
    return h.hexdigest().lower() == want


def _looks_like_pe(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


# =============================================================================
#  Stale-file sweep (call once at normal startup)
# =============================================================================
def sweep_leftovers():
    """Delete .new / .old / .upd-* stragglers next to the exe. Best-effort."""
    if not is_frozen():
        return
    try:
        exe = current_exe_path()
        d = current_exe_dir()
        base = os.path.basename(exe)
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if name == base + ".new" or name == base + ".old" or name.startswith(".upd-"):
                _safe_unlink(p)
    except OSError:
        pass


# =============================================================================
#  Self-update helper (the freshly-downloaded exe, re-launched)
# =============================================================================
def maybe_run_helper() -> bool:
    """Call at the very top of main(), BEFORE creating any Qt objects.

    Returns True if we ran as the swap helper (caller should then exit).
    """
    if len(sys.argv) >= 4 and sys.argv[1] == "--apply-update":
        try:
            old_pid = int(sys.argv[2])
        except ValueError:
            return True
        target = sys.argv[3]
        _apply_update(old_pid, target)
        return True
    return False


def _wait_for_exit(pid: int, timeout: float) -> bool:
    PROCESS_SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x0
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not h:
        return True  # already gone
    try:
        return k32.WaitForSingleObject(h, int(timeout * 1000)) == WAIT_OBJECT_0
    finally:
        k32.CloseHandle(h)


def _relaunch(exe: str):
    if not os.path.exists(exe):
        return
    try:
        subprocess.Popen(
            [exe],
            creationflags=DETACH_FLAGS,
            close_fds=True,
            cwd=os.path.dirname(exe),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _try_replace(src, dst, attempts=5, delay=0.5):
    """os.replace with retries, to ride out transient AV/lock contention."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return True
        except OSError:
            if i + 1 < attempts:
                time.sleep(delay)
    return False


def _apply_update(old_pid: int, target: str):
    """Runs as the new exe (currently named *.new). Swap and restart."""
    me = current_exe_path()             # ...\TidalNowPlaying.exe.new
    # Hardening: only ever swap our own canonical exe name, never an arbitrary
    # path handed to us on the command line.
    if os.path.basename(target).lower() != ASSET_NAME.lower():
        return
    backup = target + ".old"

    if not _wait_for_exit(old_pid, timeout=30.0):
        # Old process won't die: leave the canonical exe untouched, keep .new
        # for a retry next launch.
        return
    time.sleep(0.3)  # let the image-section handle release

    moved_old = False
    swapped = False
    try:
        _safe_unlink(backup)
        if os.path.exists(target):
            os.replace(target, backup)   # target -> .old (atomic)
            moved_old = True
        swapped = _try_replace(me, target)   # .new -> target (with retries)
    except OSError:
        swapped = False

    # If the forward swap failed after moving the old exe aside, make sure a
    # working exe still exists at the canonical path (never strand the user).
    if not swapped and moved_old and not os.path.exists(target):
        if not _try_replace(backup, target):
            try:
                import shutil
                shutil.copy2(backup, target)   # last resort: keep an exe in place
            except OSError:
                pass

    if os.path.exists(target):
        _relaunch(target)
    elif os.path.exists(backup):
        _relaunch(backup)   # never leave the user with nothing to run

    if swapped:
        _safe_unlink(backup)


# =============================================================================
#  Updater QObject
# =============================================================================
class Updater(QObject):
    update_available = Signal(dict)   # normalized release dict
    up_to_date = Signal(bool)         # arg: was this a silent check?
    check_failed = Signal(str, bool)  # message, silent?
    download_done = Signal(str, str)  # status, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._lock = threading.Lock()

    # ---- check -----------------------------------------------------------
    def check(self, silent=True):
        """Run the network check on a background thread.

        `silent` controls only how the *caller* reacts to up_to_date/failure
        (startup check stays quiet; the tray item reports loudly). Results are
        emitted via Qt signals, which Qt delivers on the GUI thread because the
        emitting QObject lives there (queued cross-thread connection).
        """
        with self._lock:
            if self._thread and self._thread.is_alive():
                return  # one check at a time
            self._thread = threading.Thread(
                target=self._do_check, args=(silent,), daemon=True)
            self._thread.start()

    def _do_check(self, silent):
        try:
            rel = fetch_latest()
            if rel is None:
                self.check_failed.emit("Could not reach GitHub to check for updates.", silent)
                return
            if not is_newer(getattr(config, "APP_VERSION", "0"), rel["tag_name"]):
                self.up_to_date.emit(silent)
                return
            # Honor a persisted "skip this version" choice (silent checks only;
            # a loud manual check should still surface a skipped version).
            if silent and self._is_skipped(rel["tag_name"]):
                self.up_to_date.emit(silent)
                return
            self.update_available.emit(rel)
        except Exception as e:
            self.check_failed.emit(str(e), silent)

    # ---- skip-version persistence (QSettings, not a checkbox) ------------
    def _is_skipped(self, tag) -> bool:
        try:
            import settings
            s = settings._store()
            return s.value("skipped_version", "", str) == tag
        except Exception:
            return False

    def skip_version(self, tag):
        try:
            import settings
            s = settings._store()
            s.setValue("skipped_version", tag)
            s.sync()
        except Exception as e:
            _log(f"Could not persist skipped version: {e}")

    # ---- download + apply ------------------------------------------------
    def download_and_apply(self, release):
        """Download, verify, swap, and restart.

        Frozen: returns ("relaunching", None) on success after spawning the
        detached helper; the GUI layer should then quit the app. On failure
        returns ("download-failed"/"verify-failed"/"spawn-failed", message).

        Source: opens the release page and returns ("source", None).
        """
        if not is_frozen():
            webbrowser.open(release.get("html_url") or RELEASE_PAGE)
            return ("source", None)

        exe = current_exe_path()
        new_path = exe + ".new"

        asset = find_asset(release, ASSET_NAME)
        if not asset or not asset.get("browser_download_url"):
            return ("download-failed", f"{ASSET_NAME} not found in the release.")

        if not download_asset(asset["browser_download_url"], new_path):
            _safe_unlink(new_path)
            return ("download-failed", "The download failed or was rejected.")

        if not _looks_like_pe(new_path):
            _safe_unlink(new_path)
            return ("download-failed", "The downloaded file is not a Windows program.")

        # Optional integrity gate: verify against SHA256SUMS.txt if present.
        sums_asset = find_asset(release, SUMS_NAME)
        if sums_asset and sums_asset.get("browser_download_url"):
            sums_text = fetch_text(sums_asset["browser_download_url"])
            if sums_text is None:
                _safe_unlink(new_path)
                return ("verify-failed", "Could not download the checksum file.")
            if not verify_sha256(new_path, sums_text, ASSET_NAME):
                _safe_unlink(new_path)
                return ("verify-failed",
                        "The downloaded file failed its SHA-256 checksum check.")
        else:
            _log("No SHA256SUMS.txt in release; skipping checksum verification.")

        pid = os.getpid()
        try:
            subprocess.Popen(
                [new_path, "--apply-update", str(pid), exe],
                creationflags=DETACH_FLAGS,
                close_fds=True,
                cwd=os.path.dirname(exe),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            _safe_unlink(new_path)
            return ("spawn-failed", str(e))

        return ("relaunching", None)

    def download_async(self, release):
        """Run download_and_apply on a background thread so the GUI never
        freezes during the (potentially large) download. Result is delivered
        on the GUI thread via the download_done(status, message) signal."""
        threading.Thread(target=self._download_worker, args=(release,),
                         daemon=True).start()

    def _download_worker(self, release):
        try:
            status, msg = self.download_and_apply(release)
        except Exception as e:
            status, msg = "spawn-failed", str(e)
        self.download_done.emit(status, msg or "")

    # ---- lifecycle -------------------------------------------------------
    def stop(self):
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)

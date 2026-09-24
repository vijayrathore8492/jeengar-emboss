"""Release check and one-click download. Never blocks the UI, never installs by itself.

On start: ask GitHub for the latest release, pick the asset that fits this OS/CPU
(mac-arm64 .dmg, windows -setup.exe, linux .AppImage), remember it.
On request: stream that asset into the user's Downloads folder with progress, then
open it (dmg mounts, setup.exe runs, AppImage replaces the running file if we can).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from . import REPO, __version__

RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
_state: dict = {"checked": False, "latest": None, "url": RELEASES_URL, "newer": False, "error": None,
                "asset": None, "asset_size": 0,
                "download": {"status": "idle", "pct": 0, "path": None, "error": None}}
_lock = threading.Lock()


def _tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split("-")[0].split(".") if x.isdigit())


def _wanted_suffix() -> list[str]:
    """Asset name endings that fit this machine, best first."""
    if sys.platform == "darwin":
        arch = "arm64" if platform.machine() == "arm64" else "intel"
        return [f"mac-{arch}.dmg"]
    if sys.platform.startswith("win"):
        return ["windows-setup.exe", "windows.zip"]
    return ["linux-x86_64.AppImage", "linux-x86_64.tar.gz"]


def _pick(assets: list[dict]) -> dict | None:
    for suf in _wanted_suffix():
        for a in assets:
            if a.get("name", "").endswith(suf):
                return a
    return None


def _check() -> None:
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": f"jeengar-emboss/{__version__}"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.load(r)
        tag = d.get("tag_name", "")
        a = _pick(d.get("assets") or [])
        with _lock:
            _state.update(latest=tag.lstrip("v"), url=d.get("html_url") or RELEASES_URL,
                          newer=_tuple(tag) > _tuple(__version__),
                          asset=a and {"name": a["name"], "url": a["browser_download_url"]},
                          asset_size=int(a.get("size", 0)) if a else 0)
    except Exception as e:  # noqa: BLE001  (offline workshop is normal)
        with _lock:
            _state["error"] = str(e)[:80]
    with _lock:
        _state["checked"] = True


def start() -> None:
    threading.Thread(target=_check, daemon=True).start()


def status() -> dict:
    with _lock:
        return {"version": __version__, **json.loads(json.dumps(_state))}


# ------------------------------------------------------------- download --
def _downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    return d if d.is_dir() else Path.home()


def _open(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _download() -> None:
    with _lock:
        a = _state["asset"]
        dl = _state["download"]
        if not a or dl["status"] == "running":
            return
        dl.update(status="running", pct=0, path=None, error=None)
    try:
        dest = _downloads_dir() / a["name"]
        tmp = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(a["url"], headers={"User-Agent": f"jeengar-emboss/{__version__}"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or _state["asset_size"] or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    with _lock:
                        dl["pct"] = round(100 * got / total, 1)
        tmp.replace(dest)
        # Linux AppImage: if we ARE an AppImage, swap ourselves in place so the next launch is new
        me = os.environ.get("APPIMAGE")
        if me and dest.suffix == ".AppImage":
            try:
                shutil.copy2(dest, me)
                os.chmod(me, 0o755)
                with _lock:
                    dl.update(status="done", pct=100, path=me, error=None, restartable=True)
                return
            except OSError:
                pass  # fall through: leave the file in Downloads
        if dest.suffix == ".AppImage":
            os.chmod(dest, 0o755)
        _open(dest)
        with _lock:
            dl.update(status="done", pct=100, path=str(dest))
    except Exception as e:  # noqa: BLE001
        with _lock:
            dl.update(status="error", error=str(e)[:120])


def restart() -> None:
    """Linux AppImage only: launch the (already replaced) file and exit this process."""
    me = os.environ.get("APPIMAGE")
    if not me or not Path(me).exists():
        raise ValueError("restart is only available for the installed AppImage")
    # the new instance needs port 8765, so it must start after we are gone
    subprocess.Popen(["/bin/sh", "-c", f'sleep 1.5; exec "{me}"'], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def download() -> dict:
    threading.Thread(target=_download, daemon=True).start()
    return status()["download"]

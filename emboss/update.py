"""Once per start, ask GitHub whether a newer release exists. Never blocks the UI."""

from __future__ import annotations

import json
import threading
import urllib.request

from . import REPO, __version__

RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
_result: dict = {"checked": False, "latest": None, "url": RELEASES_URL, "newer": False, "error": None}


def _tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split("-")[0].split(".") if x.isdigit())


def _check() -> None:
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": f"jeengar-emboss/{__version__}"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.load(r)
        tag = d.get("tag_name", "")
        _result.update(latest=tag.lstrip("v"), url=d.get("html_url") or RELEASES_URL,
                       newer=_tuple(tag) > _tuple(__version__))
    except Exception as e:  # noqa: BLE001  (offline workshop is normal)
        _result["error"] = str(e)[:80]
    _result["checked"] = True


def start() -> None:
    threading.Thread(target=_check, daemon=True).start()


def status() -> dict:
    return {"version": __version__, **_result}

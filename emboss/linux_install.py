"""
Linux only: put the AppImage where a desktop expects an app, so it is one click from
the menu and the in-app update can replace it in place.

  ~/Applications/JeengarEmboss.AppImage          the app (unversioned name = stable menu entry)
  ~/.local/share/applications/jeengar-emboss.desktop
  ~/.local/share/icons/hicolor/512x512/apps/jeengar-emboss.png

Nothing here needs root. If we are already running from ~/Applications, the menu entry is
(re)written silently on start; if we are running from Downloads, the UI offers a button.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import ASSETS

APP_DIR = Path.home() / "Applications"
TARGET = APP_DIR / "JeengarEmboss.AppImage"
DESKTOP = Path.home() / ".local" / "share" / "applications" / "jeengar-emboss.desktop"
ICON = Path.home() / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "jeengar-emboss.png"


def running_appimage() -> Path | None:
    p = os.environ.get("APPIMAGE")
    return Path(p) if sys.platform.startswith("linux") and p and Path(p).exists() else None


def status() -> dict:
    src = running_appimage()
    if not src:
        return {"applicable": False}
    # "installed" = this very build is in ~/Applications with a menu entry (same file, or an identical copy)
    same = TARGET.exists() and (src.resolve() == TARGET.resolve() or TARGET.stat().st_size == src.stat().st_size)
    return {"applicable": True, "installed": bool(same and DESKTOP.exists()),
            "target": str(TARGET), "source": str(src)}


def _write_menu_entry() -> None:
    ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS / "icon.png", ICON)
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text(
        "[Desktop Entry]\nType=Application\nName=Jeengar Emboss\n"
        "Comment=Engrave logos and text on leather\n"
        f"Exec={TARGET}\nIcon=jeengar-emboss\nTerminal=false\nCategories=Graphics;Utility;\n"
        "StartupWMClass=Jeengar Emboss\n")
    DESKTOP.chmod(0o755)
    for cmd in (["update-desktop-database", str(DESKTOP.parent)],
                ["gtk-update-icon-cache", "-q", str(Path.home() / ".local" / "share" / "icons" / "hicolor")]):
        try:
            subprocess.run(cmd, check=False, timeout=10, capture_output=True)
        except Exception:  # noqa: BLE001
            pass


def install() -> dict:
    """Copy the running AppImage to ~/Applications (if it is not already there) and add the menu entry."""
    src = running_appimage()
    if not src:
        raise ValueError("Not running as an AppImage")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if src.resolve() != TARGET.resolve():
        tmp = TARGET.with_suffix(".part")
        shutil.copy2(src, tmp)
        os.chmod(tmp, 0o755)
        tmp.replace(TARGET)
    else:
        os.chmod(TARGET, 0o755)
    _write_menu_entry()
    return status()


def ensure_menu_entry_if_installed() -> None:
    """On start: if we run from ~/Applications, keep the menu entry fresh (icon, path) without asking."""
    try:
        src = running_appimage()
        if src and TARGET.exists() and src.resolve() == TARGET.resolve():
            _write_menu_entry()
    except Exception:  # noqa: BLE001
        pass

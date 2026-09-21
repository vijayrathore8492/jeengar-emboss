"""
Where things live, in a source checkout and in a packaged (PyInstaller) app.

  RES   read-only resources shipped with the app: ui/, assets/fonts, seed data.
        Source: the repo folder. Frozen: sys._MEIPASS (the _internal folder).
  DATA  per-user, survives updates: calibration.json, machine.json, uploads/,
        out/ (g-code, logs).
          macOS   ~/Library/Application Support/Jeengar Emboss
          Windows %APPDATA%\\Jeengar Emboss
          Linux   ~/.local/share/jeengar-emboss  (or $XDG_DATA_HOME)
        Override with JEENGAR_EMBOSS_HOME=/some/dir (handy for a USB stick).

On first run with an empty DATA dir, files from an old in-folder layout
(calibration.json, machine.json, out/, uploads next to emboss.py) are copied
over, so upgrading from the script version keeps presets.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
APP_NAME = "Jeengar Emboss"

if FROZEN:
    RES = Path(sys._MEIPASS)                       # type: ignore[attr-defined]
    APP_DIR = Path(sys.executable).resolve().parent
else:
    RES = Path(__file__).resolve().parent.parent
    APP_DIR = RES

UI_DIR = RES / "ui"
FONT_DIR = RES / "assets" / "fonts"
ASSETS = RES / "assets"


def _default_data_dir() -> Path:
    env = os.environ.get("JEENGAR_EMBOSS_HOME")
    if env:
        return Path(env).expanduser()
    if not FROZEN:
        # running from source: keep everything beside the code, as before
        return RES
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "jeengar-emboss"


DATA = _default_data_dir()
OUT = DATA / "out"
UPLOADS = OUT / "uploads"
CALIB = DATA / "calibration.json"
MACHINE = DATA / "machine.json"
LOG = OUT / "emboss.log"


def ensure() -> None:
    """Create the data dir; migrate from an old side-by-side layout once."""
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if DATA == RES:
        return
    marker = DATA / ".migrated"
    if marker.exists():
        return
    # candidates: next to the app bundle / exe, and the old script folder
    for old in {APP_DIR, APP_DIR.parent, APP_DIR.parent.parent, APP_DIR.parent.parent.parent, RES}:
        try:
            if (old / "calibration.json").exists() and not CALIB.exists():
                shutil.copy2(old / "calibration.json", CALIB)
            if (old / "machine.json").exists() and not MACHINE.exists():
                shutil.copy2(old / "machine.json", MACHINE)
            if (old / "out" / "uploads").is_dir():
                UPLOADS.mkdir(parents=True, exist_ok=True)
                for p in (old / "out" / "uploads").iterdir():
                    if p.is_file() and not (UPLOADS / p.name).exists():
                        shutil.copy2(p, UPLOADS / p.name)
        except OSError:
            pass
    marker.write_text("ok")

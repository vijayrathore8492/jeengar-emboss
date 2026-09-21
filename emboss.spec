# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Jeengar Emboss. One-folder build (fast start, easy to inspect).
#   pip install pyinstaller
#   pyinstaller emboss.spec
# Output: dist/Jeengar Emboss/   (Windows, Linux)   or   dist/Jeengar Emboss.app (macOS)

import sys
from pathlib import Path

HERE = Path(SPECPATH)
NAME = "Jeengar Emboss"
import re
VERSION = re.search(r'__version__ = "([^"]+)"', (HERE / "emboss" / "__init__.py").read_text()).group(1)

datas = [
    (str(HERE / "ui"), "ui"),
    (str(HERE / "assets" / "jeengar-wordmark.svg"), "assets"),
    (str(HERE / "assets" / "icon.png"), "assets"),
]
# fonts, without the _old folder
for p in sorted((HERE / "assets" / "fonts").glob("*.[to]tf")):
    datas.append((str(p), "assets/fonts"))

hiddenimports = [
    "emboss.server", "emboss.cli", "emboss.artwork", "emboss.gcode", "emboss.grbl",
    "emboss.materials", "emboss.text", "emboss.paths", "emboss.update",
    "serial.tools.list_ports",
    "serial.tools.list_ports_posix", "serial.tools.list_ports_osx",
    "serial.tools.list_ports_linux", "serial.tools.list_ports_windows",
    "PIL.ImageFont", "PIL.ImageDraw", "PIL.PngImagePlugin", "PIL.JpegImagePlugin",
    "fontTools.ttLib",
    "resvg_py",
    "webview", "webview.platforms.cocoa", "webview.platforms.winforms", "webview.platforms.edgechromium",
    "webview.platforms.gtk", "clr", "clr_loader",
]

a = Analysis(
    [str(HERE / "emboss.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    icon = str(HERE / "assets" / "icon.icns")
elif sys.platform.startswith("win"):
    icon = str(HERE / "assets" / "icon.ico")
else:
    icon = None

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    strip=False,
    upx=False,
    # Windows/Linux: a console window shows the log and closing it quits the app.
    # macOS: a proper .app with no terminal; quit from the UI (Advanced > Quit) or the Dock.
    console=(sys.platform != "darwin"),
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=icon,
        bundle_identifier="com.jeengar.emboss",
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleDisplayName": NAME,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )

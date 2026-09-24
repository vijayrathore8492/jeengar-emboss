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
if sys.platform.startswith("linux"):
    # Linux window = Qt WebEngine, fully bundled (host GTK/WebKit is never touched: mixing
    # a bundled typelib with the distro's libwebkit2gtk broke on Zorin).
    hiddenimports += ["webview.platforms.qt", "qtpy", "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
                      "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel", "PyQt6.QtNetwork"]

a = Analysis(
    [str(HERE / "emboss.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest",
              "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth",
              "PyQt6.QtPositioning", "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtSql", "PyQt6.QtTest",
              "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtPdf", "PyQt6.QtPdfWidgets", "PyQt6.QtSvgWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform.startswith("linux"):
    # Never ship these: they must come from the host or they shadow newer system copies and
    # break the distro's GPU/driver stack (seen on Zorin: GLIBCXX_3.4.32 not found).
    _HOST_ONLY = ("libstdc++.so", "libgcc_s.so", "libGL.so", "libGLX.so", "libEGL.so", "libgbm.so", "libdrm.so",
                  "libglapi.so", "libGLdispatch.so", "libglib-2.0.so", "libgio-2.0.so", "libgobject-2.0.so",
                  "libgmodule-2.0.so", "libdbus-1.so", "libasound.so", "libpulse.so", "libfontconfig.so")
    a.binaries = [b for b in a.binaries if not any(Path(b[0]).name.startswith(h) for h in _HOST_ONLY)]

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
    # No console anywhere: the app window (or Advanced > Quit) is how you leave.
    # Debugging on Windows/Linux: run "Jeengar Emboss" ui --no-browser from a terminal;
    # the log is also in the data folder (out/emboss.log).
    console=False,
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

"""
Native app window around the web UI, via pywebview (WKWebView on macOS,
Edge WebView2 on Windows, WebKitGTK on Linux). The HTTP server keeps running
underneath; this is only the frame. Closing the window quits the app.
"""

from __future__ import annotations

import os
import threading

import sys

from . import __version__
from .paths import ASSETS

ICON = ASSETS / "icon.png"


def _dock_icon() -> None:
    """macOS: a plain python process shows pywebview's default Dock icon; use ours.
    (The packaged .app carries icon.icns, so this matters only when run from source.)"""
    if sys.platform != "darwin" or not ICON.exists():
        return
    try:
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initWithContentsOfFile_(str(ICON))
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:  # noqa: BLE001
        pass


def run(url: str, on_close=None) -> None:
    import webview  # noqa: WPS433  (imported here so the CLI works without it)

    w = webview.create_window(
        f"Jeengar Emboss {__version__}", url,
        width=1280, height=860, min_size=(960, 640),
        text_select=True, zoomable=True,
    )

    def closed():
        if on_close:
            try:
                on_close()
            except Exception:  # noqa: BLE001
                pass
        # give the serial port a moment to close, then leave for real
        threading.Timer(0.3, lambda: os._exit(0)).start()

    w.events.closed += closed
    gui = "qt" if sys.platform.startswith("linux") else None   # Linux: bundled Qt WebEngine, never host GTK
    webview.start(func=_dock_icon, gui=gui, private_mode=False, icon=str(ICON) if ICON.exists() else None)

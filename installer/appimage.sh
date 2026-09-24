#!/usr/bin/env bash
# Wrap the PyInstaller one-folder build into a single AppImage. Run from the repo root after
# `pyinstaller emboss.spec`. Usage: installer/appimage.sh <version>
set -euo pipefail
V="${1:?version}"
APP="Jeengar Emboss"
DIR="AppDir"
rm -rf "$DIR"; mkdir -p "$DIR/usr/bin" "$DIR/usr/share/applications" "$DIR/usr/share/icons/hicolor/512x512/apps"
cp -r "dist/$APP/." "$DIR/usr/bin/"
cp assets/icon.png "$DIR/usr/share/icons/hicolor/512x512/apps/jeengar-emboss.png"
cp assets/icon.png "$DIR/jeengar-emboss.png"
cat > "$DIR/jeengar-emboss.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Jeengar Emboss
Comment=Engrave logos and text on leather with a GRBL diode laser
Exec=jeengar-emboss
Icon=jeengar-emboss
Categories=Graphics;Utility;
Terminal=false
DESK
cp "$DIR/jeengar-emboss.desktop" "$DIR/usr/share/applications/"
cat > "$DIR/AppRun" <<'RUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
export QTWEBENGINE_DISABLE_SANDBOX=1          # Chromium's sandbox cannot run from a FUSE mount
export QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox ${QTWEBENGINE_CHROMIUM_FLAGS:-}"
exec "$HERE/usr/bin/Jeengar Emboss" "$@"
RUN
chmod +x "$DIR/AppRun"
if [ ! -x appimagetool ]; then
  curl -sSL -o appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x appimagetool
fi
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$DIR" "pkg/JeengarEmboss-$V-linux-x86_64.AppImage"
chmod +x "pkg/JeengarEmboss-$V-linux-x86_64.AppImage"

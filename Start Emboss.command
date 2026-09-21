#!/bin/bash
# Double-click to start Jeengar Emboss (macOS).
cd "$(dirname "$0")"
# Prefer a python.org / Homebrew Python over Apple's old Command Line Tools copy.
PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null)
    if [ -n "$v" ] && [ "$v" -ge 310 ]; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  osascript -e 'display dialog "Jeengar Emboss needs Python 3.10 or newer. Install it from python.org, then double-click again." buttons {"OK"}'
  open "https://www.python.org/downloads/macos/"
  exit 1
fi
echo "Using $PY ($($PY --version))"
if [ ! -f .deps-ok ]; then
  echo "First run: installing libraries (one minute)..."
  "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1
  "$PY" -m pip install --quiet -r requirements.txt && touch .deps-ok
  "$PY" -m pip install --quiet -r requirements-svg.txt || echo "(SVG library not available for this Python; PNG and text still work)"
fi
echo "Starting Jeengar Emboss. Close this window to quit."
"$PY" emboss.py

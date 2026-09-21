#!/bin/bash
# Start Jeengar Emboss (Linux). Double-click, or run from a terminal.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed: sudo apt install python3 python3-pip"; read -p "Enter to close"; exit 1
fi
if ! groups | grep -q dialout; then
  echo "Adding you to the dialout group so the laser's USB port can be opened."
  echo "You will need to log out and in once after this."
  sudo usermod -aG dialout "$USER"
fi
if [ ! -f .deps-ok ]; then
  echo "First run: installing libraries (one minute)..."
  python3 -m pip install --quiet -r requirements.txt && touch .deps-ok
  python3 -m pip install --quiet -r requirements-svg.txt || echo "(SVG library unavailable; PNG and text still work)"
fi
echo "Starting Jeengar Emboss. Close this window to quit."
python3 emboss.py

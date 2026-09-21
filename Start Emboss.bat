@echo off
REM Double-click to start Jeengar Emboss (Windows).
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python 3 is not installed. Install it from python.org and TICK "Add python.exe to PATH", then double-click again.
  start https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist .deps-ok (
  echo First run: installing libraries (one minute)...
  python -m pip install --quiet -r requirements.txt && echo ok > .deps-ok
  python -m pip install --quiet -r requirements-svg.txt
)
echo Starting Jeengar Emboss. Close this window to quit.
python emboss.py
pause

# Jeengar Emboss

Laser-engrave a logo, a name or a monogram on leather with a **Creality CR-Laser Falcon 5W**
(or any GRBL diode laser). Pick the leather, type the text or drop in a logo, aim, burn.

Built by [Jeengar](https://jeengar.com), a Rajasthani leather house, for personalising
its own bags in the workshop — and shared because the Falcon is a good machine with poor
software. Runs on macOS, Windows and Linux; no LightBurn, no Rayforge, no G-code by hand.

![JG](assets/icon.png)

## What it does

- **Text or artwork.** Type a name (any script the fonts cover, incl. Devanagari and emoji),
  or drop a PNG / SVG. Dark pixels burn. You give the width in millimetres; the file's own
  size is ignored.
- **Leather-aware settings.** Choose the leather type and colour; the app proposes power,
  speed, line pitch and passes from saved *looks* (Light, Standard, Deep, …) that you
  calibrate once per leather with test cells. Every number stays editable, live, with the
  machine's limits enforced.
- **Aim where the head is.** No homing needed. A faint aiming dot shows where the burn will
  land; arrow buttons jog the head; *Show outline* traces the artwork's rectangle at 1.5 %
  power so you can check placement on the actual bag before burning.
- **Pixel-exact preview** of what will burn, warnings for hairlines thinner than the beam,
  live progress, Stop at any time (also Esc).
- **Auto-connect, auto-recover.** Finds the laser on USB, notices when it is switched off or
  unplugged, reconnects when it is back and tells you to re-aim (power-cycling resets the
  head position).
- **Fonts.** 60 bundled Google Fonts grouped by use (serif, capitals, script, Devanagari…),
  any `.ttf`/`.otf` you add, and the fonts installed on your computer.

## Install

Download from the [latest release](https://github.com/vijayrathore8492/jeengar-emboss/releases/latest):

| | File | First launch |
|---|---|---|
| macOS (Apple Silicon) | `JeengarEmboss-<v>-mac-arm64.dmg` | Drag to Applications. The app is not notarised: right-click → **Open** → Open, once. |
| Windows 10/11 | `JeengarEmboss-<v>-windows-setup.exe` | Run it: Next → Next → Finish. Start Menu and desktop icon, Add/Remove Programs entry. SmartScreen: *More info → Run anyway*, once. Older Falcons need the CH340 USB driver. (A plain `.zip` is also there if you prefer no installer.) |
| Linux (x86-64) | `JeengarEmboss-<v>-linux-x86_64.AppImage` | One file: `chmod +x`, double-click (needs `libfuse2` on distros without it: `sudo apt install libfuse2`). On first run the app offers **Add to apps menu** — it copies itself to `~/Applications` and adds a launcher entry with the icon; updates then replace it in place. `sudo usermod -aG dialout $USER`, log out and in. (`.tar.gz` also available.) |

Nothing else to install — Python and every library are inside the bundle.

The app opens in its own window. Closing it releases the laser and quits.
`Jeengar Emboss --browser` uses your browser instead; `--no-browser` runs the local server only.

**Updates.** On start the app checks GitHub. If there is a newer release a bar appears at the top:
*Download* fetches the right file for this computer into Downloads and opens it — the Windows
installer replaces the old version, the Mac dmg opens for you to drag over, an AppImage replaces
itself in place. Nothing installs behind your back, and your data folder is never touched.

Your data lives outside the app, so updates never touch it:
`~/Library/Application Support/Jeengar Emboss` (macOS), `%APPDATA%\Jeengar Emboss` (Windows),
`~/.local/share/jeengar-emboss` (Linux). Set `JEENGAR_EMBOSS_HOME=/some/folder` to put it
elsewhere, e.g. a USB stick shared between laptops. It holds `calibration.json` (your looks),
`fonts/` (your fonts), uploaded artwork, G-code and the log.

## Using it

1. **What to emboss** — *Text* (font, weight, alignment, letter-spacing, a symbols & emoji
   picker) or *Logo or image* (PNG/SVG; tick *invert* for light artwork on a dark background).
   Width in mm.
2. **Leather** — type (veg-tan, coated, suede) and colour. Pick a *look*; the four boxes
   below (power %, speed mm/min, lines/mm, passes) fill in and can be edited on the spot.
   *Mode*: **solid** for logos and text (every pixel burns at the set power), **shaded** for
   photographs (power follows the pixel's darkness — test it on each leather first).
3. **Where** — press **DOT**, drive the head with the arrows (step 0.1 / 1 / 5 / 20 mm)
   until the dot sits at the artwork's bottom-left corner (or its centre, under *More
   position options*). *Show outline on the leather* traces the box.
4. **Burn** → confirm. Watch the bar. **Stop** or Esc aborts instantly.

Leave 8 mm of free travel to the left of the anchor: each raster row starts early so the
head is at full speed when the beam turns on.

### Calibrating a leather (once per leather / colour group)

Under *Advanced*: **Cells** burns a row of small squares, each with its own
`power/speed/passes` — e.g. `10/5000/1, 30/4000/1, 100/8000/1, 100/10000/2` — on an offcut.
Photograph it, pick the cells you like, and **Save look** with a name (Light, Standard, Deep,
Darkest, Max…) and optionally make it the default. Colours are grouped by how much of the
455 nm blue beam they absorb — light (natural, tan, cream…), mid (brown, cherry, olive,
navy…), dark (black) — so one calibration covers a group.

What we found on veg-tan (12 lines/mm), for a starting point, not a rule: energy per pass
(power × lines/mm ÷ speed) below ~0.03 marks the finish only; 0.06–0.11 gives brown;
~0.16 near black; on dark leathers a pale, clean mark comes from **high power at high speed**
(100 % at 8000–10000 mm/min, one pass), and a second pass adds little. Focus matters more
than any number: set it with the stepped tool every time the material thickness changes.

### Fonts

Three sources, all in the Font menu:

- **Bundled** — 60 Google Fonts (SIL Open Font License, see `assets/fonts/OFL.txt`).
- **My fonts** — *Add a font…* under the text box uploads a `.ttf`/`.otf`; *Open my fonts
  folder* shows where they live. Family and weight are read from the file, so names don't
  matter. Use this for typefaces you are licensed to use but may not redistribute.
- **Installed on this computer** — the operating system's fonts, scanned at start
  (italics skipped; *Rescan fonts* after installing new ones).

Characters the chosen font lacks fall back to Noto Serif Devanagari, then Noto Emoji
(monochrome — what a one-colour laser can burn). For a solid heart use `♥` rather than the
colour emoji.

## Why it works better than the generic tools on this machine

| Problem with the Falcon in general tools | What this does |
|---|---|
| Power % is fiction (Max Power 200 vs `$30`) | Reads `$30` from the controller and scales S to it; 100 % is the real 5 W |
| Dark bands at letter edges | M4 dynamic power, overscan sized from the controller's own acceleration `$120` |
| Tone shifts inside a row | Gaps crossed with `G1 S0` at constant feed, never `G0` |
| Fill-only SVG traced as an outline | Always rasters; there is no contour mode |
| Mark lands 20 mm off | Crops to the ink, ignores the SVG canvas |
| Board stalls on status polling | Never sends `?` during a job |
| No aiming dot at low power | Creality's firmware only fires while moving: the dot is a 0.05 mm wiggle job |
| macOS "device reports readiness to read but returned no data" | Tolerated; the ESP32 USB-modem quirk is harmless |
| App still says "connected" after a power cycle | Watches the port, reconnects, warns that the head position is now 0,0 |

Rules the app enforces from the machine: speed ≤ `$110`, width ≤ `$130` − 20 mm, power 1–100 %,
lines/mm 4–20, passes 1–5. Opening the USB port resets the board, so the app opens it once
and keeps it for the whole session — aim, outline and burn share one origin.

## Running from source

```
git clone https://github.com/vijayrathore8492/jeengar-emboss
cd jeengar-emboss
python3 -m pip install -r requirements.txt -r requirements-svg.txt   # Python 3.10+
python3 emboss.py
```

`Start Emboss.command` (macOS), `Start Emboss.bat` (Windows) and `start-emboss.sh` (Linux)
do the same with a double-click, installing the libraries on first run. On macOS use the
python.org Python, not Apple's — the launcher picks it for you. `requirements-svg.txt`
(resvg) is only needed for SVG input.

### Command line

Everything the window does is also a command, useful for scripting or a headless box:

```
python3 emboss.py ports                                    # which USB port is the laser
python3 emboss.py info                                     # read $$ from the controller
python3 emboss.py fonts                                    # list font families and weights
python3 emboss.py preview LOGO.svg --width 45 --leather veg-tan --colour tan
python3 emboss.py aim                                      # drive the head with arrow keys, q to finish
python3 emboss.py frame   LOGO.svg --width 45
python3 emboss.py run     LOGO.svg --width 45 --leather veg-tan --colour tan --frame-first
python3 emboss.py run --text "Priya ♥" --font "Great Vibes" --width 40 --leather veg-tan --colour black
python3 emboss.py test-grid --leather veg-tan --colour tan --speeds 8000,5000,3000 --powers 10,30,100
python3 emboss.py calibrate --leather veg-tan --colour tan --name Standard --power 30 --speed 4000
```

`--power --speed --lines-per-mm --passes --mode --preset` override any run; `--x --y` place a
job at fixed coordinates instead of the head position; `--center` anchors the artwork's centre.
The CLI opens the port per command, so aim and run are not guaranteed to share an origin —
that guarantee is the reason the window exists.

## Layout

```
emboss.py              entry point (no arguments = open the app)
emboss/server.py       local HTTP server + JSON API behind the window
emboss/window.py       native window (pywebview)
emboss/cli.py          the commands above
emboss/artwork.py      PNG / SVG / text -> bitmap at the job pitch, hairline check, preview
emboss/text.py         text and emoji rendering; font index (bundled, mine, OS)
emboss/gcode.py        raster G-code, outline, test cells
emboss/grbl.py         serial streaming, $$ read, head position, jog, abort
emboss/materials.py    leather x colour groups, seed values, calibration file
emboss/paths.py        where resources and user data live (source vs packaged)
emboss/update.py       release check
ui/index.html          the page
assets/fonts/          bundled Google Fonts (OFL)
emboss.spec            PyInstaller build
.github/workflows/     builds the three bundles on every v* tag
```

### Making a release

1. Bump `__version__` in `emboss/__init__.py` — the tag must match it.
2. `git commit -am "vX.Y.Z" && git push && git tag vX.Y.Z && git push --tags`
3. GitHub Actions builds macOS, Windows and Linux bundles, smoke-tests them (including that
   the OS fonts are found), and attaches them with `SHA256SUMS.txt` to the release. ~3 minutes.

## Licence

Code: MIT. Bundled fonts: SIL OFL 1.1. The Jeengar name, wordmark and app icon are
trademarks of Jeengar Industries LLP and are not covered by the licence — see `LICENSE`.
Not affiliated with or endorsed by Creality.

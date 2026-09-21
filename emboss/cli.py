"""
emboss.py — command line front end. The UI will call the same functions.

    emboss.py                            open the browser UI (everything below, with buttons)
    emboss.py ports
    emboss.py info                       read $$ from the Falcon, save machine.json
    emboss.py preview ART --width 45 --leather veg-tan --colour tan
    emboss.py aim                        jog the head to where the logo goes (faint dot on)
    emboss.py frame   ART --width 45     outline at the head position
    emboss.py test-grid --leather veg-tan --colour tan
    emboss.py run     ART --width 45 --leather veg-tan --colour tan
    emboss.py run --text "Priya ❤" --font great-vibes --width 40 --leather veg-tan --colour tan
    emboss.py fonts                      list the bundled fonts
    (--x --y override the head position; --center anchors the artwork centre there)
    emboss.py calibrate --leather veg-tan --colour tan --power 28 --speed 1600
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from . import artwork, gcode, text as textmod
from .materials import Calibration, LEATHER_TYPES, Settings, colour_group
from .grbl import Grbl, GrblError, find_ports, print_progress

from .paths import CALIB, MACHINE, OUT, RES as ROOT  # noqa: F401

DEFAULT_S30 = 1000.0
DEFAULT_ACCEL = 350.0
DEFAULT_RAPID = 3000.0


# ---------------------------------------------------------------- helpers --
def load_machine() -> dict:
    if MACHINE.exists():
        return json.loads(MACHINE.read_text())
    return {}


def pick_port(arg: str | None) -> str:
    if arg:
        return arg
    m = load_machine()
    if m.get("port"):
        return m["port"]
    ports = find_ports()
    if not ports:
        sys.exit("No serial ports found. Is the Falcon plugged in and powered?")
    return ports[0][0]


def connect(args) -> Grbl:
    port = pick_port(getattr(args, "port", None))
    print(f"Connecting to {port} ...")
    try:
        g = Grbl(port, verbose=getattr(args, "verbose", False))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not open {port}: {e}\n"
                 f"On Linux: sudo usermod -aG dialout $USER, then log out/in.\n"
                 f"Close Rayforge / LightBurn first: only one program can own the port.")
    g.unlock()
    return g


def machine_params(g: Grbl | None, args) -> tuple[int, float, float, str]:
    """(s_max, accel, rapid, source)"""
    if g is not None:
        s = g.settings()
        if not s:
            g.close()
            sys.exit("Controller returned no $$ settings.")
        m = {"port": g.port, "read_at": time.strftime("%Y-%m-%d %H:%M"), "settings": s}
        MACHINE.write_text(json.dumps(m, indent=2))
        if s.get("32", 0) != 1:
            print("!! $32 (laser mode) is OFF. Raster power ramping needs it. Setting $32=1.")
            g.set_setting(32, 1)
        return int(s["30"]), s.get("120", DEFAULT_ACCEL), s.get("110", DEFAULT_RAPID), "controller"
    m = load_machine()
    if m.get("settings"):
        s = m["settings"]
        return int(s["30"]), s.get("120", DEFAULT_ACCEL), s.get("110", DEFAULT_RAPID), f"machine.json ({m['read_at']})"
    print(f"!! machine.json not found; assuming $30={DEFAULT_S30:g}. Run `emboss.py info` first for real numbers.")
    return int(DEFAULT_S30), DEFAULT_ACCEL, DEFAULT_RAPID, "ASSUMED"


def resolve_settings(args) -> tuple[Settings, str]:
    cal = Calibration(CALIB)
    st, src = cal.resolve(args.leather, args.colour, getattr(args, "preset", None))
    over = {}
    if getattr(args, "power", None) is not None:
        over["power"] = args.power / 100.0
    for f in ("speed", "lines_per_mm", "passes", "mode", "threshold"):
        v = getattr(args, f, None)
        if v is not None:
            over[f] = v
    if over:
        st = replace(st, **over)
        src += " + overrides"
    return st, src


def describe(st: Settings, src: str, s_max: int) -> None:
    print(f"  settings : {src}")
    print(f"  power    : {st.power*100:.0f}%  (S{int(round(s_max*st.power))} of $30={s_max})")
    print(f"  speed    : {st.speed:g} mm/min")
    print(f"  pitch    : {st.pitch():.3f} mm  ({st.lines_per_mm:g} lines/mm)")
    print(f"  passes   : {st.passes}   mode: {st.mode}")
    if st.note:
        print(f"  note     : {st.note}")


def art_source(args):
    """(thing artwork.load accepts, short name). Either a file or rendered text."""
    if getattr(args, "text", None):
        im = textmod.render(args.text, args.font, weight=int(getattr(args, "weight", 400) or 400),
                            align=args.align, letter_spacing=args.letter_spacing)
        safe = "".join(c if c.isalnum() else "_" for c in args.text)[:24] or "text"
        return im, f"text_{safe}"
    if not args.art:
        sys.exit("Give an artwork file (PNG/SVG) or --text \"...\".")
    return args.art, Path(args.art).stem


def build_art_job(args, st: Settings, s_max: int, accel: float, title: str,
                  g: Grbl | None = None) -> tuple[gcode.Job, artwork.Bitmap, float, float, str]:
    src, _ = art_source(args)
    bm = artwork.load(src, args.width, st.lines_per_mm, invert=getattr(args, "invert", False))
    x0, y0, osrc = origin(g, args, bm.width_mm, bm.height_mm)
    over = gcode.overscan_mm(st.speed, accel)
    job = gcode.Job()
    gcode.header(job, title)
    if getattr(args, "frame_first", False):
        gcode.frame(job, x0, y0, bm.width_mm, bm.height_mm, s_max)
        job.lines.append("G4 P2")  # 2 s pause so you can see it
    for _ in range(st.passes):
        gcode.raster(job, bm, st, x0, y0, s_max, over)
    gcode.footer(job, x0, y0)
    return job, bm, x0, y0, osrc


def report_art(bm: artwork.Bitmap, st: Settings, job: gcode.Job, rapid: float,
               x0: float, y0: float, osrc: str = "") -> None:
    fr = artwork.feature_report(bm, st.threshold)
    print(f"  artwork  : {bm.width_mm:.1f} x {bm.height_mm:.1f} mm  ({bm.cols} x {bm.rows} px)")
    print(f"  placed   : bottom-left X{x0:.1f} Y{y0:.1f}  ->  top-right X{x0+bm.width_mm:.1f} Y{y0+bm.height_mm:.1f}   ({osrc})")
    print(f"  raster   : {job.rows} rows, burn {job.burn_mm:.0f} mm, travel {job.travel_mm:.0f} mm")
    print(f"  est time : {job.estimate_s(st.speed, rapid)/60:.1f} min")
    if fr["thin_fraction"] > 0.35:
        print(f"  !! {fr['thin_fraction']*100:.0f}% of the ink is in strokes ~1 px wide at this size. "
              f"Hairlines will bloom shut. Make the artwork wider or raise lines/mm.")
    if x0 < 8:
        print("  !! Less than 8 mm left of the artwork for overscan. Move the head right, or the X rail will be hit.")


def confirm(prompt: str = "Start burning? [y/N] ") -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def origin(g: Grbl | None, args, w: float = 0.0, h: float = 0.0) -> tuple[float, float, str]:
    """Bottom-left of the job in work mm. Default anchor = current head position."""
    if args.x is not None and args.y is not None:
        ax, ay, src = args.x, args.y, "--x --y"
    elif g is not None:
        ax, ay = g.position()
        src = "head position"
    else:
        ax, ay, src = 20.0, 20.0, "no laser connected, assumed X20 Y20"
    if getattr(args, "center", False):
        ax -= w / 2
        ay -= h / 2
    return ax, ay, src


# --------------------------------------------------------------- commands --
def cmd_ports(args):
    for dev, desc in find_ports():
        print(f"{dev:28s} {desc}")
    if not find_ports():
        print("(none)")


def cmd_info(args):
    g = connect(args)
    try:
        s = g.settings()
        MACHINE.write_text(json.dumps({"port": g.port, "read_at": time.strftime("%Y-%m-%d %H:%M"),
                                       "settings": s}, indent=2))
        print(f"Saved {MACHINE.name}\n")
        want = {"30": "max S (power scale)", "32": "laser mode (must be 1)",
                "110": "X max rate mm/min", "111": "Y max rate mm/min",
                "120": "X accel mm/s^2", "121": "Y accel mm/s^2",
                "100": "X steps/mm", "101": "Y steps/mm",
                "130": "X travel mm", "131": "Y travel mm", "22": "homing enabled"}
        for k, label in want.items():
            v = s.get(k)
            print(f"  ${k:<4}= {v if v is not None else '?':<10} {label}")
        if s.get("32", 0) != 1:
            print("\n!! $32=0: laser mode is OFF. Run:  emboss.py set 32 1")
        print(f"\nStatus: {g.status()}")
    finally:
        g.close()


def cmd_set(args):
    g = connect(args)
    try:
        g.set_setting(args.n, args.value)
        print(f"${args.n}={args.value:g} set. Re-run `info` to confirm.")
    finally:
        g.close()


def cmd_preview(args):
    s_max, accel, rapid, src_m = machine_params(None, args)
    st, src = resolve_settings(args)
    _, name = art_source(args)
    job, bm, x0, y0, osrc = build_art_job(args, st, s_max, accel, f"preview {name}")
    OUT.mkdir(exist_ok=True)
    stem = OUT / name
    artwork.preview_png(bm, f"{stem}_preview.png", None if st.mode == "gray" else st.threshold)
    Path(f"{stem}.gcode").write_text(job.text())
    print(f"machine  : {src_m}")
    describe(st, src, s_max)
    report_art(bm, st, job, rapid, x0, y0, osrc)
    print(f"  wrote    : {stem}_preview.png  and  {stem}.gcode")


def cmd_frame(args):
    st, _ = resolve_settings(args)
    src, _ = art_source(args)
    bm = artwork.load(src, args.width, st.lines_per_mm)
    g = connect(args)
    try:
        s_max, accel, rapid, _ = machine_params(g, args)
        x0, y0, osrc = origin(g, args, bm.width_mm, bm.height_mm)
        job = gcode.Job()
        gcode.header(job, "frame")
        gcode.frame(job, x0, y0, bm.width_mm, bm.height_mm, s_max,
                    power=args.frame_power / 100.0, repeat=args.repeat)
        gcode.footer(job, x0, y0)
        print(f"Framing {bm.width_mm:.1f} x {bm.height_mm:.1f} mm, bottom-left X{x0:.1f} Y{y0:.1f} ({osrc}), "
              f"{args.frame_power:g}% power x{args.repeat}")
        g.stream(job.lines, print_progress)
    finally:
        g.close()


def cmd_test_grid(args):
    """Grid of filled squares: columns = speed, rows = power. Fastest / lowest first."""
    speeds = [float(v) for v in args.speeds.split(",")]
    powers = [float(v) for v in args.powers.split(",")]
    cell, gap = args.cell, args.gap
    st, src = resolve_settings(args)
    sq = gcode.square_bitmap(cell, st.lines_per_mm)

    g = None if args.dry_run else connect(args)
    try:
        s_max, accel, rapid, src_m = machine_params(g, args)
        W = len(speeds) * (cell + gap) - gap
        H = len(powers) * (cell + gap) - gap
        gx, gy, osrc = origin(g, args, W, H)
        job = gcode.Job()
        gcode.header(job, f"test grid {args.leather}/{args.colour}")
        gcode.frame(job, gx - 2, gy - 2, W + 4, H + 4, s_max, repeat=1)
        # run slowest speeds and highest powers LAST so a bad cell can be aborted late
        for pi, pw in enumerate(sorted(powers)):
            for si, sp in enumerate(sorted(speeds, reverse=True)):
                cs = replace(st, power=pw / 100.0, speed=sp, passes=1)
                cx = gx + si * (cell + gap)
                cy = gy + pi * (cell + gap)
                job.lines.append(f"; cell speed={sp:g} power={pw:g}%")
                gcode.raster(job, sq, cs, cx, cy, s_max, gcode.overscan_mm(sp, accel))
        gcode.footer(job, gx, gy)

        # legend
        OUT.mkdir(exist_ok=True)
        legend = OUT / f"testgrid_{args.leather}_{colour_group(args.colour)}.txt"
        rows = ["Test grid legend (bottom-left of the grid at X%.1f Y%.1f, %s)" % (gx, gy, osrc),
                "Columns left->right = speed mm/min: " + ", ".join(f"{s:g}" for s in sorted(speeds, reverse=True)),
                "Rows bottom->top   = power %:      " + ", ".join(f"{p:g}" for p in sorted(powers)),
                f"Cell {cell} mm, gap {gap} mm, {st.lines_per_mm:g} lines/mm, $30={s_max} ({src_m})", ""]
        for pw in sorted(powers, reverse=True):
            rows.append(f"{pw:5g}% | " + "  ".join(f"{sp:6g}" for sp in sorted(speeds, reverse=True)))
        rows.append("      +" + "-" * (8 * len(speeds)))
        rows.append("        " + "  ".join(f"{sp:6g}" for sp in sorted(speeds, reverse=True)))
        legend.write_text("\n".join(rows) + "\n")
        print("\n".join(rows))
        print(f"  grid     : {W:.0f} x {H:.0f} mm, est {job.estimate_s(min(speeds), rapid)/60:.1f} min max")
        print(f"  legend   : {legend}")
        if args.dry_run:
            p = OUT / "testgrid.gcode"
            p.write_text(job.text())
            print(f"  wrote    : {p}")
            return
        if not confirm():
            return
        g.stream(job.lines, print_progress)
        print("Done. Photograph the grid next to the legend and pick the best cell.")
    finally:
        if g:
            g.close()


def cmd_run(args):
    g = None if args.dry_run else connect(args)
    try:
        s_max, accel, rapid, src_m = machine_params(g, args)
        st, src = resolve_settings(args)
        _, name = art_source(args)
        job, bm, x0, y0, osrc = build_art_job(args, st, s_max, accel,
                                              f"run {name} {args.leather}/{args.colour}", g)
        OUT.mkdir(exist_ok=True)
        stem = OUT / f"{name}_{args.leather}_{colour_group(args.colour)}"
        artwork.preview_png(bm, f"{stem}_preview.png", None if st.mode == "gray" else st.threshold)
        Path(f"{stem}.gcode").write_text(job.text())
        print(f"machine  : {src_m}")
        describe(st, src, s_max)
        report_art(bm, st, job, rapid, x0, y0, osrc)
        print(f"  preview  : {stem}_preview.png")
        if args.dry_run:
            print(f"  wrote    : {stem}.gcode  (dry run, nothing sent)")
            return
        if not args.yes and not confirm():
            return
        print("Burning. Ctrl-C = laser off + abort.")
        pr = g.stream(job.lines, print_progress)
        print(f"Finished in {time.time()-pr.started:.0f}s.")
    except GrblError as e:
        sys.exit(f"\nGRBL error: {e}")
    finally:
        if g:
            g.close()


def _getch():
    """One keypress, no Enter. Windows and POSIX."""
    try:
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch = {b"H": "w", b"P": "s", b"K": "a", b"M": "d"}.get(msvcrt.getch(), "")
            return ch
        return ch.decode("ascii", "replace")
    except ImportError:
        import termios, tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":  # arrow keys: ESC [ A/B/C/D
                seq = sys.stdin.read(2)
                ch = {"[A": "w", "[B": "s", "[D": "a", "[C": "d"}.get(seq, "")
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def cmd_aim(args):
    """Move the head with the keyboard, with a faint dot on, to where the logo goes."""
    g = connect(args)
    steps = [0.1, 1, 5, 20]
    si = 1
    try:
        if not args.no_dot:
            s_max = int(g.settings().get("30", DEFAULT_S30))
            g.pointer(True, max(1, int(round(s_max * args.dot / 100))))
        print("Arrows / WASD move the head. [ ] change step. q = laser off + quit.")
        print("Leave the head where the logo's BOTTOM-LEFT corner (or its centre, with --center) should be.")
        while True:
            x, y = g.position()
            sys.stdout.write(f"\r  X{x:8.2f}  Y{y:8.2f}   step {steps[si]:g} mm      ")
            sys.stdout.flush()
            ch = _getch().lower()
            if ch in ("q", "\x03", "\r", "\n"):
                break
            elif ch == "w":
                g.jog(0, steps[si])
            elif ch == "s":
                g.jog(0, -steps[si])
            elif ch == "a":
                g.jog(-steps[si], 0)
            elif ch == "d":
                g.jog(steps[si], 0)
            elif ch == "[":
                si = max(0, si - 1)
            elif ch == "]":
                si = min(len(steps) - 1, si + 1)
        x, y = g.position()
        print(f"\nHead at X{x:.2f} Y{y:.2f}. Now run `frame` or `run` without --x --y and the job anchors here.")
    finally:
        g.pointer(False)
        g.close()


def cmd_calibrate(args):
    cal = Calibration(CALIB)
    st, _ = cal.resolve(args.leather, args.colour)
    over = {"power": args.power / 100.0, "speed": args.speed}
    for f in ("lines_per_mm", "passes", "mode", "threshold"):
        if getattr(args, f, None) is not None:
            over[f] = getattr(args, f)
    st = replace(st, note=args.note or st.note, **over)
    cal.save(args.leather, args.colour, st, name=args.name, make_default=not args.no_default)
    print(f"Saved {args.leather}/{colour_group(args.colour)} preset '{args.name}' -> {CALIB.name}")
    describe(st, "calibrated", int(load_machine().get("settings", {}).get("30", DEFAULT_S30)))


# ------------------------------------------------------------------ parser --
def _material(p):
    p.add_argument("--leather", required=True, choices=LEATHER_TYPES)
    p.add_argument("--colour", "--color", required=True, help="tracker colour, e.g. tan, natural-brown, cherry, black")
    p.add_argument("--preset", help="named calibration preset (default: the group's default)")


def _overrides(p):
    p.add_argument("--power", type=float, help="override power %% (real optical)")
    p.add_argument("--speed", type=float, help="override mm/min")
    p.add_argument("--lines-per-mm", type=float, dest="lines_per_mm")
    p.add_argument("--passes", type=int)
    p.add_argument("--mode", choices=("binary", "gray"))
    p.add_argument("--threshold", type=int)


def _placement(p):
    p.add_argument("--x", type=float, default=None, help="mm from machine X0 (default: where the head is now)")
    p.add_argument("--y", type=float, default=None, help="mm from machine Y0 (default: where the head is now)")
    p.add_argument("--center", action="store_true", help="the anchor is the artwork centre, not bottom-left")


def _art(p):
    p.add_argument("art", nargs="?", help="PNG or SVG. Dark = burn. Omit when using --text.")
    p.add_argument("--text", help="engrave text instead of a file; \\n for a new line; emoji OK")
    p.add_argument("--font", default="Libre Bodoni", help="family, e.g. 'Libre Bodoni', 'Great Vibes'; see `fonts`")
    p.add_argument("--weight", type=int, default=400, help="400 regular, 700 bold, ... (nearest available is used)")
    p.add_argument("--align", choices=("left", "center", "right"), default="center")
    p.add_argument("--letter-spacing", type=float, default=0.0, dest="letter_spacing",
                   help="extra tracking in em, e.g. 0.1 for spaced capitals")
    p.add_argument("--width", type=float, required=True, help="ink width in mm")
    p.add_argument("--invert", action="store_true", help="artwork is light-on-dark")


def _port(p):
    p.add_argument("--port")
    p.add_argument("--verbose", action="store_true")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="emboss.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ui", help="open the app (default when run with no command)")
    p.add_argument("--port-http", type=int, default=8765)
    p.add_argument("--browser", action="store_true", help="open in the web browser instead of the app window")
    p.add_argument("--no-browser", action="store_true", help="server only, open nothing (for scripts and tests)")
    p.set_defaults(fn=lambda a: __import__("emboss.server", fromlist=["serve"]).serve(
        a.port_http, open_browser=not a.no_browser, window=not (a.browser or a.no_browser)))

    sub.add_parser("ports").set_defaults(fn=cmd_ports)
    sub.add_parser("fonts").set_defaults(fn=lambda a: print("\n".join(f"{k}: {', '.join(map(str, v))}" for k, v in textmod.families().items())))

    p = sub.add_parser("info"); _port(p); p.set_defaults(fn=cmd_info)

    p = sub.add_parser("set"); _port(p)
    p.add_argument("n", type=int); p.add_argument("value", type=float); p.set_defaults(fn=cmd_set)

    p = sub.add_parser("preview"); _art(p); _material(p); _overrides(p); _placement(p)
    p.add_argument("--frame-first", action="store_true"); p.set_defaults(fn=cmd_preview)

    p = sub.add_parser("frame"); _art(p); _placement(p); _port(p)
    p.add_argument("--leather", default="veg-tan", choices=LEATHER_TYPES)
    p.add_argument("--colour", "--color", default="tan")
    p.add_argument("--frame-power", type=float, default=1.0, help="%% (default 1)")
    p.add_argument("--repeat", type=int, default=3); p.set_defaults(fn=cmd_frame)

    p = sub.add_parser("test-grid"); _material(p); _overrides(p); _placement(p); _port(p)
    p.add_argument("--speeds", default="3000,2000,1500,1000")
    p.add_argument("--powers", default="10,20,30,40")
    p.add_argument("--cell", type=float, default=6.0); p.add_argument("--gap", type=float, default=3.0)
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_test_grid)

    p = sub.add_parser("run"); _art(p); _material(p); _overrides(p); _placement(p); _port(p)
    p.add_argument("--frame-first", action="store_true", help="trace the outline at 1%% first, pause 2 s, then burn")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("aim", help="jog the head with the keyboard to where the logo goes"); _port(p)
    p.add_argument("--dot", type=float, default=0.5, help="pointer power %% (default 0.5)")
    p.add_argument("--no-dot", action="store_true"); p.set_defaults(fn=cmd_aim)

    p = sub.add_parser("calibrate"); _material(p)
    p.add_argument("--power", type=float, required=True); p.add_argument("--speed", type=float, required=True)
    p.add_argument("--lines-per-mm", type=float, dest="lines_per_mm"); p.add_argument("--passes", type=int)
    p.add_argument("--mode", choices=("binary", "gray")); p.add_argument("--threshold", type=int)
    p.add_argument("--note"); p.add_argument("--name", default="calibrated")
    p.add_argument("--no-default", action="store_true", help="save but keep the current default")
    p.set_defaults(fn=cmd_calibrate)

    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["ui"]
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

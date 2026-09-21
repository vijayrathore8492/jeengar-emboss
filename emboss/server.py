"""
Local web UI: `emboss.py ui` starts this on http://127.0.0.1:8765 and opens
the browser. Standard library only (no Flask), so it runs wherever the
engine runs.

Why a UI that stays open matters on this machine: opening the USB port
resets the Falcon's board, and with no homing switches the head position is
whatever the board last knew. The CLI opens the port per command; this
server opens it ONCE and keeps it, so aim -> frame -> burn keep one origin.
"""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import traceback
import webbrowser
from dataclasses import replace

import serial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from . import artwork, gcode, text as textmod, update
from .materials import COLOUR_GROUPS, LEATHER_TYPES, Calibration, colour_group, key as cal_key, seed as seed_settings
from .grbl import Grbl, GrblError, find_ports

from . import paths
from .paths import CALIB, MACHINE, OUT, UI_DIR, UPLOADS, RES as ROOT  # noqa: F401

COLOURS = [c for names in COLOUR_GROUPS.values() for c in names]


class State:
    def __init__(self):
        self.pos_cache = (None, 0.0)
        self.g: Grbl | None = None
        self.port: str | None = None
        self.settings: dict[str, float] = {}
        self.busy: str | None = None          # "frame" | "run" | "grid" | None
        self.progress = {"acked": 0, "total": 0, "pct": 0.0, "eta_s": 0, "started": 0.0}
        self.log: list[str] = []
        self.lock = threading.Lock()          # one laser action at a time
        self.error: str | None = None
        self.dot_on = False
        self.dot_power = 3.0
        self.want_port: str | None = None     # port to auto-reconnect to
        self.last_reconnect = 0.0
        self.notice: str | None = None
        self.connecting = False               # watchdog must not touch the port mid-handshake
        self.missing_since = 0.0              # when the watchdog first saw the port gone

    def say(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.log.append(line)
        self.log = self.log[-60:]
        try:
            print(msg)                      # windowed builds have no stdout; the file log is the record
        except Exception:  # noqa: BLE001
            pass
        try:
            OUT.mkdir(exist_ok=True)
            with open(paths.LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # -- machine ------------------------------------------------------------
    @property
    def s_max(self) -> int:
        return int(self.settings.get("30", 1000))

    @property
    def accel(self) -> float:
        return float(self.settings.get("120", 350))

    @property
    def rapid(self) -> float:
        return float(self.settings.get("110", 3000))

    def connect(self, port: str | None) -> None:
        if self.g:
            self.g.close()
            self.g = None
        if not port:
            ports = find_ports()
            if not ports:
                raise GrblError("no serial ports found")
            port = ports[0][0]
        self.say(f"connecting to {port}")
        self.connecting = True
        self.missing_since = 0.0
        try:
            g = Grbl(port)
            g.unlock()
            self.settings = g.settings()
            if not self.settings:
                g.close()
                raise GrblError("controller returned no $$ settings")
            if self.settings.get("32", 0) != 1:
                self.say("laser mode $32 was off, setting $32=1")
                g.set_setting(32, 1)
                self.settings["32"] = 1
            self.g = g
        finally:
            self.connecting = False
        self.port = port
        self.want_port = port
        self.notice = None
        MACHINE.write_text(json.dumps({"port": port, "read_at": time.strftime("%Y-%m-%d %H:%M"),
                                       "settings": self.settings}, indent=2))
        self.say(f"connected. $30={self.s_max} $32={self.settings.get('32')} "
                 f"$110={self.rapid:g} $120={self.accel:g}")

    def disconnect(self, wanted: bool = True) -> None:
        if self.g:
            try:
                self.g.close()
            except Exception:  # noqa: BLE001
                pass
        self.g = None
        self.port = None
        if wanted:
            self.want_port = None
            self.say("disconnected")

    def lost(self, why: str) -> None:
        """The board went away under us (power cycle, cable). Keep want_port so we retry."""
        if self.g:
            self.say(f"LASER DISCONNECTED: {why}")
            self.disconnect(wanted=False)
            self.busy = None
            self.dot_on = False
            self.pos_cache = (None, 0.0)
            self.error = "Laser disconnected (power off or cable). Reconnecting when it is back; re-aim before burning."
            self.notice = "Laser was power-cycled: head position reset to 0,0. Re-aim before the next burn."

    def watchdog(self) -> None:
        """Called on every /api/state: detect a vanished port, auto-reconnect.
        Debounced: Windows drops the COM port for a moment when the board resets."""
        if self.connecting:
            return
        present = {d for d, _ in find_ports()}
        if self.g and self.port not in present:
            if not self.missing_since:
                self.missing_since = time.time()
            elif time.time() - self.missing_since > 3.0:
                self.lost("port vanished")
        else:
            self.missing_since = 0.0
        if not self.g and self.want_port and self.want_port in present \
                and time.time() - self.last_reconnect > 4.0:
            self.last_reconnect = time.time()
            try:
                self.connect(self.want_port)
                self.say("reconnected after power cycle; head position is 0,0 now")
            except Exception as e:  # noqa: BLE001
                self.say(f"reconnect failed: {e}")

    def need(self) -> Grbl:
        if not self.g:
            raise GrblError("not connected to the laser")
        if self.busy == "dot":
            self.stop_dot()
        if self.busy:
            raise GrblError(f"busy: {self.busy}")
        return self.g

    def stop_dot(self) -> None:
        if self.g and self.busy == "dot":
            self.g.request_stop()
            for _ in range(60):
                if self.busy != "dot":
                    break
                time.sleep(0.1)

    def start_dot(self) -> None:
        g = self.need()
        x, y = g.position()
        sv = max(1, int(round(self.s_max * self.dot_power / 100)))
        run_lines("dot", g.pointer_lines(x, y, sv), quiet=True)
        self.say(f"aiming dot ON S{sv} at X{x:.2f} Y{y:.2f}")


S = State()


# ------------------------------------------------------------------ jobs --
def _ns(p: dict) -> SimpleNamespace:
    """Request JSON -> the attribute bag cli helpers expect."""
    ov = p.get("overrides") or {}
    return SimpleNamespace(
        art=str(UPLOADS / p["file"]) if p.get("source") == "file" and p.get("file") else None,
        text=p.get("text") if p.get("source") == "text" else None,
        font=p.get("font", "Libre Bodoni"), weight=int(p.get("weight") or 400), align=p.get("align", "center"),
        letter_spacing=float(p.get("letter_spacing") or 0),
        width=float(p["width"]), invert=bool(p.get("invert")),
        leather=p["leather"], colour=p["colour"],
        power=ov.get("power"), speed=ov.get("speed"), lines_per_mm=ov.get("lines_per_mm"),
        passes=ov.get("passes"), mode=ov.get("mode"), threshold=None,
        x=p.get("x") if p.get("anchor") == "xy" else None,
        y=p.get("y") if p.get("anchor") == "xy" else None,
        center=bool(p.get("center")), frame_first=bool(p.get("frame_first")),
        preset=p.get("preset") or None,
    )


def build(p: dict, want_position: bool) -> dict:
    from . import cli
    args = _ns(p)
    st, src = cli.resolve_settings(args)
    if args.text is None and args.art is None:
        raise ValueError("no artwork: type some text or choose a file")
    art, name = cli.art_source(args)
    bm = artwork.load(art, args.width, st.lines_per_mm, invert=args.invert)

    if args.x is not None and args.y is not None:
        ax, ay, osrc = float(args.x), float(args.y), "fixed X/Y"
    elif want_position and S.g and not S.busy:
        ax, ay = S.g.position()
        osrc = "head position"
    else:
        ax, ay, osrc = 20.0, 20.0, "head position (connect to read)"
    if args.center:
        ax -= bm.width_mm / 2
        ay -= bm.height_mm / 2

    over = gcode.overscan_mm(st.speed, S.accel)
    job = gcode.Job()
    gcode.header(job, f"{name} {args.leather}/{args.colour}")
    if args.frame_first:
        gcode.frame(job, ax, ay, bm.width_mm, bm.height_mm, S.s_max)
        job.lines.append("G4 P2")
    for _ in range(st.passes):
        gcode.raster(job, bm, st, ax, ay, S.s_max, over)
    gcode.footer(job, ax, ay)

    fr = artwork.feature_report(bm, st.threshold)
    warnings = []
    if fr["thin_fraction"] > 0.35:
        warnings.append(f"{fr['thin_fraction']*100:.0f}% of the ink is in hairline strokes at this size; "
                        "they will bloom shut. Make it wider or raise lines/mm.")
    if ax < 8:
        warnings.append("Less than 8 mm to the left of the artwork for run-up; move the head right.")
    if not S.g:
        warnings.append("Not connected: power scale assumed, position assumed.")
    elif "SEED" in src:
        warnings.append("Uncalibrated preset for this leather. Burn a test grid first.")

    buf = io.BytesIO()
    artwork.preview_png(bm, buf, None if st.mode == "gray" else st.threshold, scale=3)
    return {
        "png": base64.b64encode(buf.getvalue()).decode(),
        "name": name, "width_mm": round(bm.width_mm, 1), "height_mm": round(bm.height_mm, 1),
        "px": [bm.cols, bm.rows], "x0": round(ax, 2), "y0": round(ay, 2), "origin": osrc,
        "settings": {"power": round(st.power * 100), "speed": st.speed,
                     "lines_per_mm": st.lines_per_mm, "passes": st.passes, "mode": st.mode,
                     "s_value": int(round(S.s_max * st.power)), "s_max": S.s_max, "source": src,
                     "note": st.note},
        "est_min": round(job.estimate_s(st.speed, S.rapid) / 60, 1),
        "lines": len(job.lines), "warnings": warnings,
        "_job": job, "_bm": bm, "_st": st,
    }


def _progress(pr) -> None:
    el = time.time() - pr.started
    eta = (el / pr.acked * (pr.total - pr.acked)) if pr.acked else 0
    S.progress = {"acked": pr.acked, "total": pr.total, "pct": round(pr.pct(), 1),
                  "eta_s": int(eta), "started": pr.started}


def run_lines(kind: str, lines: list[str], quiet: bool = False) -> None:
    """Stream in a background thread; state.busy guards the laser."""
    g = S.need()
    S.busy = kind

    def work():
        S.error = None
        try:
            if not quiet:
                S.say(f"{kind}: {len(lines)} lines")
            pr = g.stream(lines, None if quiet else _progress)
            if not quiet:
                S.say(f"{kind} done in {time.time()-pr.started:.0f}s")
        except (OSError, serial.SerialException) as e:
            S.lost(f"during {kind}: {e}")
        except GrblError as e:
            if kind == "dot" and "stopped" in str(e):
                pass
            else:
                S.error = str(e)
                S.say(f"{kind} stopped: {e}")
        except Exception as e:  # noqa: BLE001
            S.error = str(e)
            S.say(f"{kind} failed: {e}\n{traceback.format_exc()}")
        finally:
            S.busy = None

    threading.Thread(target=work, daemon=True).start()


def cells_lines(p: dict) -> tuple[list[str], dict]:
    """A row of cells, each with its own power/speed/passes: [{power, speed, passes}, ...].
    Cells 1..N left to right, 3 mm apart; a second row starts after 8 cells."""
    from . import cli
    cells = p["cells"]
    cell, gap = float(p.get("cell", 6)), float(p.get("gap", 3))
    args = _ns({**p, "width": 1, "source": "text", "text": "x"})
    st, _ = cli.resolve_settings(args)
    sq = gcode.square_bitmap(cell, st.lines_per_mm)
    per_row = 8
    W = min(len(cells), per_row) * (cell + gap) - gap
    H = ((len(cells) - 1) // per_row + 1) * (cell + gap) - gap
    if p.get("anchor") == "xy":
        gx, gy = float(p["x"]), float(p["y"])
    else:
        gx, gy = S.need().position()
    job = gcode.Job()
    gcode.header(job, f"cells {args.leather}/{args.colour}")
    gcode.frame(job, gx - 2, gy - 2, W + 4, H + 4, S.s_max, power=0.01, repeat=1)
    for i, c in enumerate(cells):
        pw, sp, n = float(c["power"]), float(c["speed"]), int(c.get("passes") or 1)
        cx = gx + (i % per_row) * (cell + gap)
        cy = gy + (i // per_row) * (cell + gap)
        cs = replace(st, power=pw / 100.0, speed=sp, passes=n)
        job.lines.append(f"; cell {i+1}: {pw:g}% {sp:g} x{n}")
        for _ in range(n):
            gcode.raster(job, sq, cs, cx, cy, S.s_max, gcode.overscan_mm(sp, S.accel))
    gcode.footer(job, gx, gy)
    legend = {"cells": cells, "cell": cell, "gap": gap, "lines_per_mm": st.lines_per_mm,
              "x0": round(gx, 1), "y0": round(gy, 1), "w": W, "h": H,
              "est_min": round(sum(job.estimate_s(float(c["speed"]), S.rapid) for c in cells) / 60 / len(cells), 1)}
    S.say(f"cells {args.leather}/{colour_group(args.colour)}: " +
          ", ".join(f"{c['power']}/{c['speed']}x{c.get('passes',1)}" for c in cells) + f" at X{gx:.1f} Y{gy:.1f}")
    return job.lines, legend


def testgrid_lines(p: dict) -> tuple[list[str], dict]:
    from . import cli
    speeds = sorted((float(v) for v in p["speeds"]), reverse=True)
    powers = sorted(float(v) for v in p["powers"])
    cell, gap = float(p.get("cell", 6)), float(p.get("gap", 3))
    args = _ns({**p, "width": 1, "source": "text", "text": "x"})
    st, _ = cli.resolve_settings(args)
    passes = int(p.get("passes") or 1)
    sq = gcode.square_bitmap(cell, st.lines_per_mm)
    W = len(speeds) * (cell + gap) - gap
    H = len(powers) * (cell + gap) - gap
    if p.get("anchor") == "xy":
        gx, gy = float(p["x"]), float(p["y"])
    else:
        gx, gy = S.need().position()
    job = gcode.Job()
    gcode.header(job, f"test grid {args.leather}/{args.colour}")
    gcode.frame(job, gx - 2, gy - 2, W + 4, H + 4, S.s_max, repeat=1)
    for pi, pw in enumerate(powers):
        for si, sp in enumerate(speeds):
            cs = replace(st, power=pw / 100.0, speed=sp, passes=passes)
            for _ in range(passes):
                gcode.raster(job, sq, cs, gx + si * (cell + gap), gy + pi * (cell + gap),
                             S.s_max, gcode.overscan_mm(sp, S.accel))
    gcode.footer(job, gx, gy)
    legend = {"speeds": speeds, "powers": powers, "cell": cell, "gap": gap,
              "passes": passes, "lines_per_mm": st.lines_per_mm,
              "x0": round(gx, 1), "y0": round(gy, 1), "w": W, "h": H,
              "est_min": round(job.estimate_s(min(speeds), S.rapid) / 60, 1)}
    S.say(f"test grid {args.leather}/{colour_group(args.colour)}: speeds {speeds} powers {powers} "
          f"lpm {st.lines_per_mm:g} passes {passes} at X{gx:.1f} Y{gy:.1f}")
    OUT.mkdir(exist_ok=True)
    (OUT / f"testgrid_{args.leather}_{colour_group(args.colour)}.json").write_text(json.dumps(legend, indent=1))
    return job.lines, legend


# --------------------------------------------------------------- http --
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path, ctype: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._file(UI_DIR / "index.html", "text/html; charset=utf-8")
        if self.path.startswith("/fonts/"):
            p = textmod.FONT_DIR / Path(self.path).name
            if p.exists():
                return self._file(p, "font/ttf")
        if self.path == "/api/state":
            S.watchdog()
            pos, t = S.pos_cache
            if S.g and not S.busy and time.time() - t > 2.0:  # (dot counts as busy: no polling)
                try:
                    pos = S.g.position()
                except (OSError, serial.SerialException) as e:
                    S.lost(str(e))
                    pos = None
                except Exception as e:  # noqa: BLE001
                    S.say(f"position read failed: {e}")
                S.pos_cache = (pos, time.time())
            cal = Calibration(CALIB).data
            presets = {k: {"default": v.get("default"), "presets": v["presets"]} for k, v in cal.items()}
            seeds = {f"{l}/{grp}": seed_settings(l, COLOUR_GROUPS[grp][0]).to_dict() for l in LEATHER_TYPES for grp in COLOUR_GROUPS}
            return self._json({
                "presets": presets, "seeds": seeds,
                "connected": bool(S.g), "port": S.port, "ports": find_ports(),
                "settings": {k: S.settings.get(k) for k in ("30", "32", "110", "111", "120", "121")},
                "busy": S.busy, "dot_on": S.dot_on, "progress": S.progress, "notice": S.notice, "error": S.error, "log": S.log[-15:],
                "position": pos, "fonts": textmod.available(), "font_groups": textmod.grouped(), "leathers": list(LEATHER_TYPES),
                "colours": COLOURS, "calibrated": sorted(cal.keys()),
                "uploads": sorted(p.name for p in UPLOADS.glob("*")) if UPLOADS.exists() else [],
                "update": update.status(),
            })
        self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        p = json.loads(self.rfile.read(n) or b"{}")
        try:
            fn = getattr(self, "api_" + self.path.split("/api/", 1)[1].replace("-", "_"), None)
            if not fn:
                return self.send_error(404)
            out = fn(p) or {}
            return self._json({"ok": True, **out})
        except (OSError, serial.SerialException) as e:
            S.lost(f"api {self.path}: {e}")
            return self._json({"ok": False, "error": S.error or str(e)}, 400)
        except (GrblError, ValueError) as e:
            S.say(f"api {self.path}: {e}")
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            S.say(f"api {self.path} failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    # -- api --
    def api_connect(self, p):
        S.connect(p.get("port") or None)

    def api_disconnect(self, p):
        S.disconnect()

    def api_upload(self, p):
        UPLOADS.mkdir(parents=True, exist_ok=True)
        name = Path(p["name"]).name
        (UPLOADS / name).write_bytes(base64.b64decode(p["data"]))
        return {"file": name}

    def api_font_upload(self, p):
        fam, w = textmod.add_font(p["name"], base64.b64decode(p["data"]))
        S.say(f"font added: {fam} {w}")
        return {"family": fam, "weight": w}

    def api_fonts_rescan(self, p):
        n = len(textmod.rescan())
        S.say(f"fonts rescanned: {n} families")
        return {"families": n}

    def api_open_fonts_folder(self, p):
        import subprocess, sys
        textmod.MY_FONT_DIR.mkdir(parents=True, exist_ok=True)
        d = str(textmod.MY_FONT_DIR)
        if sys.platform == "darwin":
            subprocess.Popen(["open", d])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", d])
        else:
            subprocess.Popen(["xdg-open", d])
        return {"path": d}

    def api_preview(self, p):
        r = build(p, want_position=True)
        return {k: v for k, v in r.items() if not k.startswith("_")}

    def api_jog(self, p):
        g = S.need()
        g.jog(float(p.get("dx", 0)), float(p.get("dy", 0)))
        x, y = g.position()
        S.pos_cache = ((x, y), time.time())
        S.say(f"jog {p.get('dx',0)},{p.get('dy',0)} -> X{x:.2f} Y{y:.2f}")
        S.notice = None
        if S.dot_on:
            S.start_dot()
        return {"position": [x, y]}

    def api_dot(self, p):
        S.dot_power = float(p.get("power", S.dot_power))
        S.dot_on = bool(p.get("on"))
        if S.dot_on:
            S.start_dot()
        else:
            S.need()
            S.say("aiming dot off")

    def api_frame(self, p):
        S.dot_on = False
        S.need()
        r = build(p, want_position=True)
        bm = r["_bm"]
        job = gcode.Job()
        gcode.header(job, "frame")
        gcode.frame(job, r["x0"], r["y0"], bm.width_mm, bm.height_mm, S.s_max,
                    power=float(p.get("frame_power", 1.5)) / 100, repeat=int(p.get("repeat", 2)))
        gcode.footer(job, r["x0"], r["y0"])
        run_lines("frame", job.lines)
        return {"x0": r["x0"], "y0": r["y0"]}

    def api_run(self, p):
        S.dot_on = False
        S.need()
        r = build(p, want_position=True)
        OUT.mkdir(exist_ok=True)
        (OUT / f"{r['name']}_{p['leather']}_{colour_group(p['colour'])}.gcode").write_text(r["_job"].text())
        run_lines("run", r["_job"].lines)
        return {"lines": r["lines"], "est_min": r["est_min"]}

    def api_testgrid(self, p):
        S.dot_on = False
        lines, legend = cells_lines(p) if p.get("cells") else testgrid_lines(p)
        if p.get("dry_run"):
            return {"legend": legend}
        run_lines("grid", lines)
        return {"legend": legend}

    def api_stop(self, p):
        if S.g:
            S.g.request_stop()
            if not S.busy:
                S.g.abort()
        S.say("stop requested")

    def api_update_download(self, p):
        return {"download": update.download()}

    def api_quit(self, p):
        """Close the app (the packaged Mac app has no terminal window to close)."""
        if S.busy and S.busy != "dot":
            raise GrblError("a job is running; press Stop first")
        S.stop_dot()
        S.say("quit from UI")
        threading.Timer(0.3, lambda: __import__("os")._exit(0)).start()

    def api_raw(self, p):
        """Debug: send one line, return the controller's reply lines."""
        g = S.need()
        if p.get("cmd") == "?":
            return {"reply": [g.status()]}
        return {"reply": g.cmd(p["cmd"], timeout=float(p.get("timeout", 5)))}

    def api_calibrate(self, p):
        cal = Calibration(CALIB)
        name = (p.get("name") or "calibrated").strip()
        st, _ = cal.resolve(p["leather"], p["colour"])
        st = replace(st, power=float(p["power"]) / 100, speed=float(p["speed"]),
                     lines_per_mm=float(p.get("lines_per_mm") or st.lines_per_mm),
                     passes=int(p.get("passes") or 1), note=p.get("note") or "")
        cal.save(p["leather"], p["colour"], st, name=name, make_default=bool(p.get("make_default", True)))
        S.say(f"preset '{name}' for {p['leather']}/{colour_group(p['colour'])}: "
              f"{st.power*100:.0f}% @ {st.speed:g}, {st.lines_per_mm:g} l/mm, {st.passes} pass")

    def api_preset_delete(self, p):
        Calibration(CALIB).delete(p["leather"], p["colour"], p["name"])
        S.say(f"preset '{p['name']}' deleted")

    def api_preset_default(self, p):
        cal = Calibration(CALIB)
        e = cal.data.get(cal_key(p["leather"], p["colour"]))
        if e and p["name"] in e["presets"]:
            e["default"] = p["name"]
            cal.path.write_text(json.dumps(cal.data, indent=2))
            S.say(f"default preset -> '{p['name']}'")


def serve(port: int = 8765, open_browser: bool = True, window: bool = False) -> None:
    """window=True: native app window (pywebview) around the UI; falls back to the browser
    when no web engine is available (some Linux boxes)."""
    paths.ensure()
    update.start()
    threading.Thread(target=textmod.rescan, daemon=True).start()   # OS font scan, off the request path
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    S.say(f"--- Jeengar Emboss {update.status()['version']} started, UI at {url}; data in {paths.DATA}")

    def shutdown():
        try:
            S.stop_dot()
        except Exception:  # noqa: BLE001
            pass
        if S.g:
            S.g.close()

    if window:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            from . import window as win
            win.run(url, on_close=shutdown)   # blocks until the window is closed
            return
        except Exception as e:  # noqa: BLE001
            S.say(f"no app window available ({e.__class__.__name__}: {e}); opening the browser instead")
            webbrowser.open(url)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
            finally:
                shutdown()
            return

    try:
        print("(Ctrl-C to quit)")
    except Exception:  # noqa: BLE001
        pass
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()

"""
Minimal GRBL streamer for the Falcon's ESP32 board (115200 baud).

* Character-counting protocol: keeps the controller's 128-byte RX buffer full
  without ever overflowing it, so raster rows stream smoothly.
* Never sends `?` status polls during a job (the Creality board stalls on
  them). Progress is counted from `ok` replies instead.
* Reads `$$` so power can be scaled to the controller's real `$30`.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

RX_BUFFER = 127  # bytes; GRBL 1.1 default is 128, keep one spare
BAUD = 115200

_HINTS = ("ch340", "cp210", "usb serial", "usb-serial", "usbserial", "usbmodem",
          "ttyacm", "ttyusb", "espressif", "usbmodem", "silicon labs", "wch", "grbl", "arduino", "ftdi")


def find_ports() -> list[tuple[str, str]]:
    """[(device, description)] with the likeliest laser port first."""
    ports = []
    for p in list_ports.comports():
        desc = f"{p.description or ''} {p.manufacturer or ''} {p.device}".lower()
        score = sum(h in desc for h in _HINTS)
        ports.append((score, p.device, p.description or ""))
    ports.sort(reverse=True)
    return [(d, desc) for _, d, desc in ports]


class GrblError(RuntimeError):
    pass


@dataclass
class Progress:
    sent: int = 0
    acked: int = 0
    total: int = 0
    started: float = 0.0

    def pct(self) -> float:
        return 100.0 * self.acked / self.total if self.total else 0.0


class Grbl:
    def __init__(self, port: str, baud: int = BAUD, verbose: bool = False):
        self.port = port
        self.verbose = verbose
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.stop_requested = False
        self.lock = threading.RLock()   # one conversation with the board at a time
        self._wake()

    # -- basics -------------------------------------------------------------
    def _wake(self) -> None:
        self.ser.write(b"\r\n\r\n")
        time.sleep(2.0)                     # board resets on open (DTR)
        self.ser.reset_input_buffer()

    def close(self) -> None:
        try:
            self.ser.write(b"M5\n")
            time.sleep(0.2)
        finally:
            self.ser.close()

    def _readline(self, timeout: float) -> str | None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                line = self.ser.readline().decode("ascii", "replace").strip()
            except serial.SerialException as e:
                # macOS + ESP32 native USB (usbmodem): select() says readable,
                # read() returns nothing, pyserial raises. Not a disconnect.
                if "returned no data" in str(e):
                    time.sleep(0.02)
                    continue
                raise
            if line:
                if self.verbose:
                    print("  <", line)
                return line
        return None

    def cmd(self, line: str, timeout: float = 5.0) -> list[str]:
        """Send one line, return everything up to and including ok/error."""
        with self.lock:
            return self._cmd(line, timeout)

    def _cmd(self, line: str, timeout: float) -> list[str]:
        if self.verbose:
            print("  >", line)
        self.ser.write((line.strip() + "\n").encode("ascii"))
        out: list[str] = []
        t0 = time.time()
        while time.time() - t0 < timeout:
            l = self._readline(0.5)
            if l is None:
                continue
            out.append(l)
            if l == "ok":
                return out
            if l.startswith("error:") or l.startswith("ALARM:"):
                raise GrblError(f"{line!r} -> {l}")
        raise GrblError(f"timeout waiting for ok after {line!r}")

    # -- settings -----------------------------------------------------------
    def settings(self) -> dict[str, float]:
        out = self.cmd("$$", timeout=5.0)
        d: dict[str, float] = {}
        for l in out:
            if l.startswith("$") and "=" in l:
                k, v = l[1:].split("=", 1)
                try:
                    d[k] = float(v.split()[0])
                except ValueError:
                    pass
        return d

    def set_setting(self, n: int, value: float) -> None:
        self.cmd(f"${n}={value:g}")

    def unlock(self) -> None:
        try:
            self.cmd("$X")
        except GrblError:
            pass

    def status(self) -> str:
        """One `?` query. Only call this when idle, never mid-job."""
        with self.lock:
            self.ser.write(b"?")
            t0 = time.time()
            while time.time() - t0 < 1.5:
                l = self._readline(0.5)
                if l and l.startswith("<"):
                    return l
            return ""

    def position(self) -> tuple[float, float]:
        """Current head position in WORK coordinates (what G90 moves use).

        GRBL reports MPos or WPos depending on $10, and the work offset (WCO)
        only every few reports, so poll until both are known. Idle only.
        """
        wco = None
        mpos = wpos = None
        for _ in range(6):
            st = self.status()
            for part in st.strip("<>").split("|"):
                if part.startswith("WPos:"):
                    wpos = tuple(float(v) for v in part[5:].split(",")[:2])
                elif part.startswith("MPos:"):
                    mpos = tuple(float(v) for v in part[5:].split(",")[:2])
                elif part.startswith("WCO:"):
                    wco = tuple(float(v) for v in part[4:].split(",")[:2])
            if wpos is not None:
                return wpos
            if mpos is not None and wco is not None:
                return (mpos[0] - wco[0], mpos[1] - wco[1])
            time.sleep(0.2)
        if mpos is not None:  # no WCO seen: assume none set
            return mpos
        raise GrblError("could not read head position from status report")

    def wait_idle(self, timeout: float = 30.0) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if "Idle" in self.status():
                return
            time.sleep(0.1)

    def jog(self, dx: float = 0.0, dy: float = 0.0, feed: float = 3000.0) -> None:
        """Relative jog ($J=), waits until the move is done."""
        with self.lock:
            self.cmd(f"$J=G91 X{dx:.3f} Y{dy:.3f} F{feed:g}")
            self.wait_idle()

    def pointer_lines(self, x: float, y: float, s: int, seconds: float = 600.0) -> list[str]:
        """This firmware fires the diode only while moving, so an aiming dot is
        a 0.05 mm wiggle in X at low power. ~600 s worth of lines; stop() ends it."""
        n = int(seconds * 600 / 60 / 0.1)  # moves per period at F600, 0.1 mm per pair
        lines = ["G21", "G90", f"G0 X{x:.3f} Y{y:.3f}", "F600", f"M3 S{s}"]
        for _ in range(n):
            lines.append(f"G1 X{x+0.05:.3f}")
            lines.append(f"G1 X{x-0.05:.3f}")
        lines += ["M5", f"G0 X{x:.3f} Y{y:.3f}"]
        return lines

    # -- realtime -----------------------------------------------------------
    def hold(self) -> None:
        self.ser.write(b"!")

    def resume(self) -> None:
        self.ser.write(b"~")

    def abort(self) -> None:
        """Feed hold (decelerate, laser off), then soft reset and unlock.
        Holding first means no lost steps, so position survives."""
        self.ser.write(b"!")
        time.sleep(0.6)
        self.ser.write(b"\x18")
        time.sleep(1.0)
        self.ser.reset_input_buffer()
        self.ser.write(b"M5\n")
        time.sleep(0.3)
        self.unlock()

    # -- streaming ----------------------------------------------------------
    def request_stop(self) -> None:
        """Ask a running stream() to abort (laser off) at its next loop."""
        self.stop_requested = True

    def stream(self, lines: list[str], progress=None) -> Progress:
        with self.lock:
            return self._stream(lines, progress)

    def _stream(self, lines: list[str], progress=None) -> Progress:
        self.stop_requested = False
        pr = Progress(total=0, started=time.time())
        clean = [l.strip() for l in lines if l.strip() and not l.strip().startswith(";")]
        pr.total = len(clean)
        outstanding: list[int] = []   # byte lengths of sent-but-unacked lines
        i = 0
        last_report = 0.0
        try:
            while pr.acked < pr.total:
                if self.stop_requested:
                    self.abort()
                    raise GrblError("stopped by user")
                # fill the buffer
                while i < pr.total:
                    n = len(clean[i]) + 1
                    if sum(outstanding) + n > RX_BUFFER:
                        break
                    self.ser.write((clean[i] + "\n").encode("ascii"))
                    outstanding.append(n)
                    i += 1
                    pr.sent = i
                # drain replies
                l = self._readline(0.05)
                if l is None:
                    continue
                if l == "ok":
                    if outstanding:
                        outstanding.pop(0)
                    pr.acked += 1
                elif l.startswith("error:") or l.startswith("ALARM:"):
                    self.abort()
                    raise GrblError(f"controller said {l} at line {pr.acked + 1}: "
                                    f"{clean[min(pr.acked, pr.total - 1)]!r}")
                if progress and time.time() - last_report > 0.5:
                    progress(pr)
                    last_report = time.time()
        except KeyboardInterrupt:
            self.abort()
            raise
        if progress:
            progress(pr)
        return pr


def print_progress(pr: Progress) -> None:
    el = time.time() - pr.started
    eta = (el / pr.acked * (pr.total - pr.acked)) if pr.acked else 0.0
    sys.stdout.write(f"\r  {pr.pct():5.1f}%  {pr.acked}/{pr.total} lines  "
                     f"{el:5.0f}s elapsed  ~{eta:4.0f}s left   ")
    sys.stdout.flush()
    if pr.acked >= pr.total:
        print()

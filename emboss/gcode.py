"""
Raster G-code for GRBL laser mode ($32=1).

Design choices, each of which fixes something seen on the Falcon:

* M4 (dynamic power). GRBL scales S with the head's actual velocity, so the
  ends of every line, where the head is still accelerating, do not get a
  darker band. M3 (constant power) is used only for the framing outline.
* Overscan. Each row starts and ends `overscan` mm outside the ink so the
  head is at full speed before the first burning pixel. Computed from the
  controller's own acceleration ($120) plus a margin, not guessed.
* Gaps inside a row are crossed with G1 S0, not G0. G0 would decelerate and
  re-accelerate, and the feed change shows as a tone change at every
  letter edge. G1 S0 keeps the feed constant and the laser off.
* Bidirectional. Alternate rows run right-to-left; halves the job time.
* S is derived from $30 at run time, so `power` is real optical fraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .artwork import Bitmap
from .materials import Settings


@dataclass
class Job:
    lines: list[str] = field(default_factory=list)
    burn_mm: float = 0.0     # G1 distance with laser on
    travel_mm: float = 0.0   # G1 S0 + G0 distance
    rows: int = 0

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def estimate_s(self, speed: float, rapid: float = 3000.0) -> float:
        return self.burn_mm / (speed / 60.0) + self.travel_mm / (rapid / 60.0)


def overscan_mm(speed: float, accel: float, margin: float = 1.0) -> float:
    """Distance to reach `speed` (mm/min) at `accel` (mm/s^2), plus margin."""
    v = speed / 60.0
    return round(v * v / (2.0 * max(accel, 1.0)) + margin, 2)


def _f(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def header(job: Job, title: str) -> None:
    job.lines += [
        f"; {title}",
        "G21",            # mm
        "G90",            # absolute
        "G94",            # feed per minute
        "M5",             # laser off while positioning
    ]


def footer(job: Job, x: float, y: float) -> None:
    job.lines += ["M5", f"G0 X{_f(x)} Y{_f(y)}", "; end"]


def raster(job: Job, bm: Bitmap, st: Settings, x0: float, y0: float,
           s_max: int, overscan: float, s_floor: int = 0) -> None:
    """Append one raster pass of `bm` with its bottom-left ink corner at (x0, y0)."""
    p = bm.pitch
    speed = st.speed
    gray = bm.gray
    if st.mode == "binary":
        # 0 or 1 per pixel
        level = (gray < st.threshold).astype(np.int32)
        s_of = lambda lv: int(round(s_max * st.power)) if lv else 0  # noqa: E731
    else:
        # 0..255 coverage -> S proportional to darkness
        level = (255 - gray.astype(np.int32))
        level[level < 8] = 0  # kill near-white noise
        s_of = lambda lv: 0 if lv == 0 else max(s_floor, int(round(s_max * st.power * lv / 255.0)))  # noqa: E731

    job.lines.append("M4 S0")
    job.lines.append(f"F{_f(speed)}")
    ltr = True
    cur_x = None
    cur_y = None

    for r in range(bm.rows):
        row = level[r]
        nz = np.nonzero(row)[0]
        if len(nz) == 0:
            continue
        y = y0 + (bm.rows - 1 - r) * p
        # pixel i covers [x0 + i*p, x0 + (i+1)*p)
        first, last = int(nz[0]), int(nz[-1]) + 1
        # segments of constant level between first..last
        segs = []
        i = first
        while i < last:
            lv = int(row[i])
            j = i + 1
            while j < last and int(row[j]) == lv:
                j += 1
            segs.append((i, j, lv))
            i = j

        if ltr:
            start_x = x0 + first * p - overscan
            end_x = x0 + last * p + overscan
            order = segs
        else:
            start_x = x0 + last * p + overscan
            end_x = x0 + first * p - overscan
            order = list(reversed(segs))

        # rapid to the row lead-in
        if cur_x is not None:
            job.travel_mm += abs(start_x - cur_x) + abs(y - (cur_y or y))
        job.lines.append(f"G0 X{_f(start_x)} Y{_f(y)}")
        cur_x, cur_y = start_x, y

        for (i, j, lv) in order:
            xa = x0 + (i if ltr else j) * p
            xb = x0 + (j if ltr else i) * p
            s = s_of(lv)
            if xa != cur_x:  # lead-in / gap, laser off, constant feed
                job.lines.append(f"G1 X{_f(xa)} S0")
                job.travel_mm += abs(xa - cur_x)
            job.lines.append(f"G1 X{_f(xb)} S{s}")
            if s:
                job.burn_mm += abs(xb - xa)
            else:
                job.travel_mm += abs(xb - xa)
            cur_x = xb
        job.lines.append(f"G1 X{_f(end_x)} S0")  # run-out
        job.travel_mm += abs(end_x - cur_x)
        cur_x = end_x
        ltr = not ltr
        job.rows += 1

    job.lines.append("M5")


def frame(job: Job, x0: float, y0: float, w: float, h: float,
          s_max: int, power: float = 0.01, speed: float = 3000, repeat: int = 3) -> None:
    """Visible outline of the job area at ~1% power so it can be positioned."""
    s = max(1, int(round(s_max * power)))
    job.lines += [f"G0 X{_f(x0)} Y{_f(y0)}", f"M3 S{s}", f"F{_f(speed)}"]
    for _ in range(repeat):
        job.lines += [
            f"G1 X{_f(x0 + w)} Y{_f(y0)}",
            f"G1 X{_f(x0 + w)} Y{_f(y0 + h)}",
            f"G1 X{_f(x0)} Y{_f(y0 + h)}",
            f"G1 X{_f(x0)} Y{_f(y0)}",
        ]
    job.lines.append("M5")
    job.burn_mm += 2 * (w + h) * repeat


def square_bitmap(size_mm: float, lines_per_mm: float) -> Bitmap:
    n = max(1, int(round(size_mm * lines_per_mm)))
    return Bitmap(gray=np.zeros((n, n), dtype=np.uint8), width_mm=n / lines_per_mm,
                  height_mm=n / lines_per_mm, pitch=1.0 / lines_per_mm)

"""
Artwork loading: PNG / SVG -> grayscale bitmap sized to the job.

Output convention: numpy uint8 array, 0 = full burn, 255 = untouched leather,
one pixel per raster line in Y and the same pitch in X. Rendered with 4x
supersampling and box-filtered down so edges land on the right pixel even
when the pitch is coarse.

Fixes the two import hazards seen with the wordmark in Rayforge:
  * size ambiguity (px vs viewBox vs mm): we ignore the file's own size and
    scale the INK to the width you ask for;
  * canvas offset: we crop to the ink bounding box, so a mark that sits at the
    bottom of a big square canvas is placed where you said, not 20 mm low.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

SUPERSAMPLE = 4


@dataclass
class Bitmap:
    gray: np.ndarray        # uint8, 0=burn .. 255=skip, shape (rows, cols)
    width_mm: float
    height_mm: float
    pitch: float            # mm per pixel (both axes)

    @property
    def rows(self) -> int:
        return self.gray.shape[0]

    @property
    def cols(self) -> int:
        return self.gray.shape[1]


def _render_svg(path: Path, px_width: int) -> Image.Image:
    try:
        import resvg_py  # prebuilt wheels for Linux / macOS / Windows
    except ImportError as e:
        raise RuntimeError("SVG needs the resvg-py library: python3 -m pip install resvg-py "
                           "(PNG and text work without it)") from e
    svg = path.read_text(encoding="utf-8")
    png = resvg_py.svg_to_bytes(svg_string=svg, width=px_width, background="#ffffff")
    return Image.open(io.BytesIO(bytes(png)))


def _flatten(im: Image.Image) -> Image.Image:
    """RGBA/LA/P -> L on a white ground."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("L")


def _ink_bbox(gray: Image.Image, threshold: int = 250) -> tuple[int, int, int, int]:
    arr = np.asarray(gray)
    ink = arr < threshold
    rows = np.where(ink.any(axis=1))[0]
    cols = np.where(ink.any(axis=0))[0]
    if len(rows) == 0:
        raise ValueError("Artwork has no ink (everything is white / transparent).")
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def load(path: "str | Path | Image.Image", width_mm: float, lines_per_mm: float,
         invert: bool = False) -> Bitmap:
    """`path` may be a PNG/SVG path or an already-rendered PIL image (text)."""
    if not isinstance(path, Image.Image):
        path = Path(path)
    pitch = 1.0 / lines_per_mm
    target_cols = max(1, int(round(width_mm / pitch)))
    ss_cols = target_cols * SUPERSAMPLE

    if isinstance(path, Image.Image):
        im = _flatten(path)
        if invert:
            im = ImageOps.invert(im)
        x0, y0, x1, y1 = _ink_bbox(im)
        im = im.crop((x0, y0, x1, y1))
    elif path.suffix.lower() == ".svg":
        # Render generously, crop to ink, then re-render at the exact size so
        # the ink (not the canvas) is `width_mm` wide.
        probe = _flatten(_render_svg(path, 2000))
        x0, y0, x1, y1 = _ink_bbox(probe)
        ink_frac = (x1 - x0) / probe.width
        full = _flatten(_render_svg(path, int(round(ss_cols / ink_frac))))
        x0, y0, x1, y1 = _ink_bbox(full)
        im = full.crop((x0, y0, x1, y1))
    else:
        im = _flatten(Image.open(path))
        if invert:
            im = ImageOps.invert(im)
        x0, y0, x1, y1 = _ink_bbox(im)
        im = im.crop((x0, y0, x1, y1))

    if invert and not isinstance(path, Image.Image) and path.suffix.lower() == ".svg":
        im = ImageOps.invert(im)

    # scale ink to ss_cols wide, keep aspect
    ss_rows = max(1, int(round(im.height * ss_cols / im.width)))
    im = im.resize((ss_cols, ss_rows), Image.LANCZOS)

    rows = max(1, int(round(ss_rows / SUPERSAMPLE)))
    im = im.resize((target_cols, rows), Image.BOX)  # box filter = coverage
    gray = np.asarray(im, dtype=np.uint8)

    return Bitmap(gray=gray, width_mm=target_cols * pitch,
                  height_mm=rows * pitch, pitch=pitch)


def feature_report(bm: Bitmap, threshold: int = 128) -> dict:
    """How much of the ink lives in strokes only one or two pixels wide.

    A diode spot on leather blooms to ~0.15-0.25 mm. Anything thinner than
    ~2 pixels at the job pitch will fill in and the artwork loses contrast.
    """
    ink = bm.gray < threshold
    if not ink.any():
        return {"ink_px": 0, "thin_fraction": 1.0, "min_stroke_mm": 0.0}

    def erode(m: np.ndarray) -> np.ndarray:
        out = m.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            out &= np.roll(m, (dy, dx), axis=(0, 1))
        return out

    def dilate(m: np.ndarray) -> np.ndarray:
        out = m.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            out |= np.roll(m, (dy, dx), axis=(0, 1))
        return out

    e1 = erode(ink)
    # ink not within 1 px of a survivor = strokes at most 2 px wide
    thin = float((ink & ~dilate(e1)).sum() / ink.sum())
    # crude min-stroke estimate: erode until empty
    n, m = 0, ink
    while m.any() and n < 100:
        m = erode(m)
        n += 1
    return {
        "ink_px": int(ink.sum()),
        "thin_fraction": float(thin),
        "max_stroke_mm": float(2 * n * bm.pitch),
    }


def preview_png(bm: Bitmap, path: str | Path, threshold: int | None = 128,
                scale: int = 4) -> None:
    """What will actually burn, magnified. Black = burn."""
    if threshold is None:
        arr = bm.gray
    else:
        arr = np.where(bm.gray < threshold, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr).resize((bm.cols * scale, bm.rows * scale), Image.NEAREST)
    im.save(path, format="PNG")

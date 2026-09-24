"""
Text -> bitmap, with font families, weights, Devanagari and emoji.

Fonts live in assets/fonts as  <Family>-<weight>.ttf  (e.g. LibreBodoni-700.ttf).
Drop any .ttf/.otf there in that naming and it appears in the app. All bundled
faces are Google Fonts under the OFL.

Fallback per character: chosen family -> Noto Serif Devanagari (same weight
or nearest) -> Noto Emoji (monochrome; what a one-colour laser can burn).
So "Priya ♥" renders Priya in the chosen face and the heart from Noto,
and "आकांक्षा" works in any family, drawn from the Devanagari serif.

Rendering is at a large em (600 px); artwork.load_image scales the INK to the
width asked for, exactly like a logo.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

__import__('logging').getLogger('fontTools').setLevel(__import__('logging').ERROR)

from .paths import FONT_DIR  # noqa: E402
EM_PX = 600
WEIGHT_NAMES = {300: "Light", 400: "Regular", 500: "Medium", 600: "Semibold", 700: "Bold", 900: "Black"}

# display order and grouping in the UI
GROUPS = {
    "Jeengar brand": ["Libre Bodoni", "EB Garamond", "Raleway", "Copperplate"],
    "Serif": ["Playfair Display", "Bodoni Moda", "Cormorant Garamond", "Libre Baskerville", "Merriweather", "Lora",
              "PT Serif", "Source Serif 4", "Crimson Text", "Spectral", "Old Standard TT", "Abril Fatface"],
    "Capitals & display": ["Cinzel", "Cinzel Decorative", "Bebas Neue", "Anton", "Oswald", "Special Elite",
                           "Pirata One", "MedievalSharp", "Amatic SC", "Permanent Marker"],
    "Sans": ["Montserrat", "Poppins", "Inter", "Roboto", "Open Sans", "Lato", "Nunito", "Josefin Sans"],
    "Script & handwriting": ["Great Vibes", "Pinyon Script", "Alex Brush", "Allura", "Parisienne", "Tangerine",
                             "Dancing Script", "Sacramento", "Satisfy", "Courgette", "Pacifico", "Lobster",
                             "Kaushan Script", "Marck Script", "Caveat"],
    "Devanagari": ["Tiro Devanagari Hindi", "Noto Serif Devanagari", "Noto Sans Devanagari", "Rozha One", "Martel",
                   "Yatra One", "Hind", "Mukta", "Karma", "Kalam", "Baloo 2"],
}
DEVANAGARI_FALLBACK = "Noto Serif Devanagari"
SYMBOL_FALLBACKS = ("Noto Sans Symbols", "Noto Sans Symbols 2")   # stars, crowns, flowers, suns, ticks
EMOJI_FALLBACK = "Noto Emoji"

# legacy slugs from the first version
_LEGACY = {"libre-bodoni": ("Libre Bodoni", 400), "libre-bodoni-bold": ("Libre Bodoni", 700),
           "eb-garamond": ("EB Garamond", 400), "raleway": ("Raleway", 400), "cinzel": ("Cinzel", 400),
           "great-vibes": ("Great Vibes", 400), "NotoEmoji": ("Noto Emoji", 400)}

_cmap_cache: dict[str, set[int]] = {}

# ---------------------------------------------------------------- font index --
# Three sources, in priority order (a family found earlier wins):
#   1. bundled   assets/fonts/<Family>-<weight>.ttf   (Google Fonts, OFL)
#   2. my fonts  <user data>/fonts/*.ttf|otf         (dropped in by the operator,
#                any file name: family and weight are read from the font itself)
#   3. OS fonts  the system font folders             (read-only; italics skipped)
# The index is built once at start and after "Rescan"; it is cheap to read.

from .paths import DATA

MY_FONT_DIR = DATA / "fonts"
SOURCE_LABEL = {"bundled": None, "mine": "My fonts", "system": "Installed on this computer"}

_index: dict[str, dict] | None = None      # family -> {"weights": {w: Path}, "source": str}
_index_lock = __import__("threading").Lock()


def _system_font_dirs() -> list[Path]:
    import os, sys
    home = Path.home()
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
                Path("/Library/Fonts"), home / "Library" / "Fonts"]
    if sys.platform.startswith("win"):
        return [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Microsoft" / "Windows" / "Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts",
            Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "fonts"]


def _split_camel(stem: str) -> str:
    # LibreBodoni -> Libre Bodoni ; EBGaramond -> EB Garamond ; OldStandardTT -> Old Standard TT ; Baloo2 -> Baloo 2
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", stem)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s


def _font_meta(path: Path) -> tuple[str, int, bool] | None:
    """(family, weight, italic) from the font's own tables; None if unreadable."""
    try:
        f = TTFont(str(path), lazy=True, fontNumber=0)
        n = f["name"]
        fam = n.getDebugName(16) or n.getDebugName(1)
        sub = (n.getDebugName(17) or n.getDebugName(2) or "").lower()
        w = int(getattr(f["OS/2"], "usWeightClass", 400) or 400) if "OS/2" in f else 400
        italic = "italic" in sub or "oblique" in sub or bool(f["head"].macStyle & 2)
        if "fvar" in f:   # variable font: expose the default instance only
            w = 400 if 350 <= w <= 450 else w
        f.close()
        if not fam or fam.startswith("."):      # hidden system faces (macOS .SF NS, .Keyboard...)
            return None
        w = min((300, 400, 500, 600, 700, 900), key=lambda x: abs(x - w)) if w not in WEIGHT_NAMES else w
        return fam.strip(), w, italic
    except Exception:  # noqa: BLE001
        return None


def _scan_dir(d: Path, source: str, into: dict[str, dict], by_name: bool) -> None:
    if not d.is_dir():
        return
    for p in sorted(d.rglob("*") if source == "system" else d.glob("*")):
        if p.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        if by_name:
            m = re.match(r"(.+?)-(\d{3})$", p.stem)
            fam, w, italic = (_split_camel(m.group(1)), int(m.group(2)), False) if m else (_split_camel(p.stem), 400, False)
        else:
            meta = _font_meta(p)
            if not meta:
                continue
            fam, w, italic = meta
        if italic:
            continue
        e = into.get(fam)
        if e and e["source"] != source:
            continue                       # an earlier source already provides this family
        e = into.setdefault(fam, {"weights": {}, "source": source})
        e["weights"].setdefault(w, p)


def rescan() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    _scan_dir(FONT_DIR, "bundled", idx, by_name=True)
    _scan_dir(MY_FONT_DIR, "mine", idx, by_name=False)
    for d in _system_font_dirs():
        _scan_dir(d, "system", idx, by_name=False)
    global _index
    with _index_lock:
        _index = idx
    return idx


def _idx() -> dict[str, dict]:
    with _index_lock:
        if _index is not None:
            return _index
    return rescan()


def families() -> dict[str, list[int]]:
    """{family: [weights]} across all sources."""
    return {k: sorted(v["weights"]) for k, v in _idx().items()}


def grouped() -> list[dict]:
    """[{group, fonts:[{family, weights}]}] in display order: bundled groups, then My fonts, then OS fonts."""
    idx = _idx()
    out, seen = [], set()
    for g, names in GROUPS.items():
        fs = [{"family": n, "weights": sorted(idx[n]["weights"])} for n in names if n in idx]
        seen.update(n for n in names if n in idx)
        if fs:
            out.append({"group": g, "fonts": fs})
    hidden = set(SYMBOL_FALLBACKS) | {EMOJI_FALLBACK}
    extra = [{"family": n, "weights": sorted(v["weights"])} for n, v in idx.items()
             if n not in seen and v["source"] == "bundled" and n not in hidden]
    if extra:
        out.append({"group": "Other", "fonts": extra})
        seen.update(f["family"] for f in extra)
    for src in ("mine", "system"):
        fs = [{"family": n, "weights": sorted(v["weights"])} for n, v in sorted(idx.items())
              if v["source"] == src and n not in seen]
        if fs:
            out.append({"group": SOURCE_LABEL[src], "fonts": fs})
    return out


def add_font(name: str, data: bytes) -> tuple[str, int]:
    """Save an uploaded .ttf/.otf into My fonts; returns (family, weight). Rejects unreadable files."""
    MY_FONT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)
    if Path(safe).suffix.lower() not in (".ttf", ".otf"):
        raise ValueError("Only .ttf and .otf font files can be added")
    dest = MY_FONT_DIR / safe
    dest.write_bytes(data)
    meta = _font_meta(dest)
    if not meta:
        dest.unlink(missing_ok=True)
        raise ValueError("That file is not a readable font")
    rescan()
    return meta[0], meta[1]


def font_path(family: str, weight: int = 400) -> Path:
    if family in _LEGACY:
        family, weight = _LEGACY[family][0], weight if weight != 400 else _LEGACY[family][1]
    idx = _idx()
    if family not in idx:
        p = Path(family)
        if p.exists():
            return p
        raise ValueError(f"Unknown font '{family}'. Known: {', '.join(sorted(idx))}")
    ws = idx[family]["weights"]
    w = min(ws, key=lambda x: abs(x - weight))
    return ws[w]


def available() -> list[str]:
    return list(families())


def _cmap(path: Path) -> set[int]:
    k = str(path)
    if k not in _cmap_cache:
        _cmap_cache[k] = set(TTFont(str(path), fontNumber=0).getBestCmap().keys())
    return _cmap_cache[k]


def _runs(text: str, chain: list[Path]) -> list[tuple[str, Path]]:
    """Split a line into runs by the first font in `chain` that has each character."""
    cmaps = [(p, _cmap(p)) for p in chain]
    out: list[tuple[str, Path]] = []
    for ch in text:
        cp = ord(ch)
        if cp in (0xFE0F, 0xFE0E):
            continue
        f = chain[0]
        if not (ch.isspace() or cp in cmaps[0][1]):
            for p, cm in cmaps[1:]:
                if cp in cm or cp == 0x200D:
                    f = p
                    break
        # Devanagari combining marks must stay in the run of their base
        if out and (0x0900 <= cp <= 0x097F) and 0x0900 <= ord(out[-1][0][-1]) <= 0x097F:
            f = out[-1][1]
        if out and out[-1][1] == f:
            out[-1] = (out[-1][0] + ch, f)
        else:
            out.append((ch, f))
    return out


def render(text: str, font: str = "Libre Bodoni", weight: int = 400, align: str = "center",
           line_gap: float = 0.15, letter_spacing: float = 0.0) -> Image.Image:
    """Black text on white, cropped to ink by the caller. `text` may contain \\n."""
    main = font_path(font, weight)
    chain = [main]
    try:
        dev = font_path(DEVANAGARI_FALLBACK, weight)
        if dev != main:
            chain.append(dev)
    except ValueError:
        pass
    for fam in SYMBOL_FALLBACKS + (EMOJI_FALLBACK,):
        try:
            chain.append(font_path(fam))
        except ValueError:
            pass
    fonts = {p: ImageFont.truetype(str(p), int(EM_PX * (0.92 if p.stem.startswith("NotoEmoji") else 1.0)))
             for p in chain}
    lines = text.replace("\\n", "\n").split("\n")

    line_h = int(EM_PX * (1.0 + line_gap))
    widths, runs_per_line = [], []
    for ln in lines:
        runs = _runs(ln, chain)
        w = sum(fonts[f].getlength(s) + letter_spacing * EM_PX * len(s) for s, f in runs)
        widths.append(int(w))
        runs_per_line.append(runs)
    W = max(widths) + EM_PX
    H = line_h * len(lines) + EM_PX

    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    for li, runs in enumerate(runs_per_line):
        x = EM_PX // 2 if align == "left" else (W - EM_PX // 2 - widths[li]) if align == "right" else (W - widths[li]) // 2
        y = EM_PX // 2 + li * line_h + EM_PX
        for s, f in runs:
            if letter_spacing:
                for ch in s:
                    d.text((x, y), ch, font=fonts[f], fill=0, anchor="ls")
                    x += fonts[f].getlength(ch) + letter_spacing * EM_PX
            else:
                d.text((x, y), s, font=fonts[f], fill=0, anchor="ls")
                x += fonts[f].getlength(s)
    return im

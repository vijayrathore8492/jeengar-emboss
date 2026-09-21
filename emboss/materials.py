"""
Material presets for the Creality CR-Laser Falcon 5W (455 nm diode, no air assist).

Every number here is a STARTING POINT, not a calibrated value. The first real
job on every leather is `emboss.py test-grid`, after which the winning cell is
written into calibration.json and overrides the seed below.

Power is always REAL optical power as a fraction of the 5 W maximum. The
S-value sent to the controller is derived from GRBL's $30 at run time, so a
25% here is 25% whether $30 is 200 or 1000.

Physics that drives the presets
-------------------------------
* 455 nm is blue. Dark pigment absorbs it strongly, light leather reflects a
  lot of it. So black needs LESS power than natural, not more.
* On natural / tan veg-tan the goal is a caramelised brown: moderate power,
  moderate speed, no char. Too slow = black soot and a raised crust.
* On dark leather the beam cannot make it "darker". The mark reads as a
  matte, slightly lighter, de-glossed surface. Goal is a clean ablation:
  higher speed, one pass, tighter line pitch so it reads as a solid area.
* Coated / corrected-grain: the beam ablates the finish coat before it ever
  reaches fibre, so keep power low and speed high or it goes patchy grey.
* Suede / nubuck: nap ignites early. Lowest power, fastest speed.
* No air assist means smoke settles back on the surface and haloes the
  mark. Faster passes leave less smoke per mm. If a mark haloes, raise speed
  and add a pass rather than raising power.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, replace
from pathlib import Path

LEATHER_TYPES = ("veg-tan", "coated", "suede")

# Colours as they appear in the Product Tracker, grouped by how much 455 nm
# light they absorb. Add a colour here and it inherits its group's tuning.
COLOUR_GROUPS: dict[str, tuple[str, ...]] = {
    "light": ("natural", "natural-brown", "tan", "white", "cream"),
    "mid": ("brown", "cherry", "dark-olive", "olive", "green", "grey", "gray",
            "purple", "navy", "red"),
    "dark": ("black",),
}


def colour_group(colour: str) -> str:
    c = colour.strip().lower().replace(" ", "-").replace("_", "-")
    for grp, names in COLOUR_GROUPS.items():
        if c in names:
            return grp
    raise ValueError(
        f"Unknown colour '{colour}'. Known: "
        + ", ".join(n for names in COLOUR_GROUPS.values() for n in names)
    )


@dataclass
class Settings:
    power: float          # 0..1, real optical fraction of 5 W
    speed: float          # mm/min
    lines_per_mm: float   # raster line pitch = 1 / lines_per_mm
    passes: int
    mode: str = "binary"  # "binary" (threshold) or "gray" (per-pixel power)
    threshold: int = 128  # binary mode: pixel < threshold burns
    note: str = ""

    def pitch(self) -> float:
        return 1.0 / self.lines_per_mm

    def to_dict(self) -> dict:
        return asdict(self)


# (leather, colour_group) -> seed Settings
_SEEDS: dict[tuple[str, str], Settings] = {
    ("veg-tan", "light"): Settings(0.30, 1500, 8, 1, note="rich brown target"),
    ("veg-tan", "mid"):   Settings(0.24, 1800, 8, 1, note="mark reads darker/matte"),
    ("veg-tan", "dark"):  Settings(0.20, 2000, 10, 1, note="clean matte ablation, no brown"),
    ("coated", "light"):  Settings(0.20, 2500, 10, 1, note="ablates finish coat; keep fast"),
    ("coated", "mid"):    Settings(0.18, 2500, 10, 1),
    ("coated", "dark"):   Settings(0.15, 2800, 10, 1),
    ("suede", "light"):   Settings(0.14, 3000, 8, 1, note="nap ignites early"),
    ("suede", "mid"):     Settings(0.12, 3000, 8, 1),
    ("suede", "dark"):    Settings(0.10, 3000, 8, 1),
}


def key(leather: str, colour: str) -> str:
    return f"{leather}/{colour_group(colour)}"


def seed(leather: str, colour: str) -> Settings:
    if leather not in LEATHER_TYPES:
        raise ValueError(f"Unknown leather '{leather}'. Known: {', '.join(LEATHER_TYPES)}")
    return replace(_SEEDS[(leather, colour_group(colour))])


class Calibration:
    """calibration.json:
    {"veg-tan/mid": {"default": "dark matte",
                     "presets": {"dark matte": {power, speed, lines_per_mm, passes, ...},
                                 "light tone": {...}}}}
    A leather/colour group can hold several named presets; one is the default.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, dict] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        # migrate the old single-dict form
        for k, v in list(self.data.items()):
            if "presets" not in v:
                self.data[k] = {"default": "calibrated", "presets": {"calibrated": v}}

    def presets(self, leather: str, colour: str) -> tuple[dict[str, dict], str | None]:
        e = self.data.get(key(leather, colour))
        if not e:
            return {}, None
        return e["presets"], e.get("default")

    def resolve(self, leather: str, colour: str, preset: str | None = None) -> tuple[Settings, str]:
        s = seed(leather, colour)
        presets, default = self.presets(leather, colour)
        name = preset or default
        if name and name in presets:
            s = replace(s, **{f: v for f, v in presets[name].items() if hasattr(s, f)})
            return s, f"calibrated: {name}"
        return s, "SEED preset, uncalibrated"

    def save(self, leather: str, colour: str, s: Settings, name: str = "calibrated",
             make_default: bool = True) -> None:
        k = key(leather, colour)
        e = self.data.setdefault(k, {"default": name, "presets": {}})
        e["presets"][name] = s.to_dict()
        if make_default or not e.get("default"):
            e["default"] = name
        self.path.write_text(json.dumps(self.data, indent=2))

    def delete(self, leather: str, colour: str, name: str) -> None:
        k = key(leather, colour)
        e = self.data.get(k)
        if e and name in e["presets"]:
            del e["presets"][name]
            if e.get("default") == name:
                e["default"] = next(iter(e["presets"]), None)
            if not e["presets"]:
                del self.data[k]
            self.path.write_text(json.dumps(self.data, indent=2))

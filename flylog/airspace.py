"""Airspace check: read an OpenAir file and find where a flight entered airspaces.

OpenAir is the text format used by most flight instruments and by public
airspace files. Supported: AC, AY (extended format), AN, AL, AH, DP, V X=, V D=, DA, DB, DC.

By default only airspaces that constrain a paraglider are checked: classes E
and G, and gliding sectors, are free to fly in VMC (see `constrains_paragliders`).

Vertical limits:
- FL: compared with the barometric (standard pressure) altitude of the track,
- MSL / AMSL: compared with the GPS altitude,
- AGL / SFC: terrain height is unknown here, so infringements depending on a
  limit above ground are flagged `uncertain`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .geo import LocalProjection
from .parser import Fix, Flight

FT = 0.3048
NM = 1852.0

_COORD = re.compile(r"(\d+):(\d+(?:\.\d+)?)(?::(\d+(?:\.\d+)?))?\s*([NSEW])", re.I)


@dataclass
class Limit:
    meters: float
    ref: str  # "MSL", "FL", "AGL" or "UNL"

    def __str__(self) -> str:
        if self.ref == "UNL":
            return "illimité"
        if self.ref == "FL":
            return f"FL{round(self.meters / FT / 100)}"
        if self.ref == "AGL" and self.meters == 0:
            return "sol"
        return f"{round(self.meters)} m {'sol' if self.ref == 'AGL' else 'AMSL'}"


@dataclass
class Airspace:
    name: str
    cls: str
    floor: Limit
    ceiling: Limit
    points: list[tuple[float, float]] = field(default_factory=list)  # lat, lon
    kind: str = ""  # AY line of the extended format: CTR, TMA, R, P, Q, RMZ…

    @property
    def label(self) -> str:
        cls = f"classe {self.cls}" if self.cls not in ("UNC", "") else ""
        return " · ".join(x for x in (self.kind, cls) if x)


RESTRICTED_KINDS = {"R", "P", "Q", "CTR", "RMZ", "TMZ", "ZSM"}


def constrains_paragliders(space: Airspace) -> bool:
    """False for airspaces a paraglider may enter freely in VMC (class E and G,
    gliding sectors), unless they are restricted/prohibited/danger zones."""
    if space.kind in RESTRICTED_KINDS:
        return True
    if space.kind == "GSEC":
        return False
    return space.cls not in ("E", "G")


def parse_coord(text: str) -> tuple[float, float]:
    parts = _COORD.findall(text)
    if len(parts) != 2:
        raise ValueError(f"Coordonnée illisible : {text!r}")
    values = []
    for deg, minutes, seconds, hemi in parts:
        v = int(deg) + float(minutes) / 60 + (float(seconds) / 3600 if seconds else 0)
        values.append(-v if hemi.upper() in "SW" else v)
    lat, lon = values
    return lat, lon


def parse_limit(text: str) -> Limit:
    t = text.strip().upper().replace(" ", "")
    if t.startswith("UNL") or not t:
        return Limit(math.inf, "UNL")
    if t in ("SFC", "GND", "0", "0FT"):
        return Limit(0.0, "AGL")
    if t.startswith("FL"):
        return Limit(float(t[2:]) * 100 * FT, "FL")
    m = re.match(r"(\d+(?:\.\d+)?)(FT|F|M)?(.*)", t)
    if not m:
        raise ValueError(f"Limite illisible : {text!r}")
    value = float(m.group(1)) * (1 if m.group(2) == "M" else FT)
    ref = "AGL" if any(k in m.group(3) for k in ("AGL", "ASFC", "SFC", "GND")) else "MSL"
    return Limit(value, ref)


def _arc(center: tuple[float, float], radius_m: float, start_deg: float, end_deg: float,
         clockwise: bool, full: bool = False) -> list[tuple[float, float]]:
    proj = LocalProjection(*center)
    if full:
        span = 360.0
    elif clockwise:
        span = (end_deg - start_deg) % 360
    else:
        span = -((start_deg - end_deg) % 360)
    steps = max(2, int(abs(span) / 5))
    out = []
    for s in range(steps + 1):
        a = math.radians(start_deg + span * s / steps)
        out.append(proj.to_latlon(radius_m * math.sin(a), radius_m * math.cos(a)))
    return out


def parse_openair(text: str) -> list[Airspace]:
    airspaces: list[Airspace] = []
    current: Airspace | None = None
    center: tuple[float, float] | None = None
    clockwise = True

    for raw in text.splitlines():
        line = raw.split("*", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(" ")
        key, value = key.upper(), value.strip()
        try:
            if key == "AC":
                current = Airspace(name="", cls=value, floor=Limit(0, "AGL"), ceiling=Limit(math.inf, "UNL"))
                airspaces.append(current)
                center, clockwise = None, True
            elif current is None:
                continue
            elif key == "AY":
                current.kind = value.upper()
            elif key == "AN":
                current.name = value
            elif key == "AL":
                current.floor = parse_limit(value)
            elif key == "AH":
                current.ceiling = parse_limit(value)
            elif key == "DP":
                current.points.append(parse_coord(value))
            elif key == "V":
                var, _, val = value.partition("=")
                if var.strip().upper() == "X":
                    center = parse_coord(val)
                elif var.strip().upper() == "D":
                    clockwise = val.strip() != "-"
            elif key == "DC" and center:
                current.points.extend(_arc(center, float(value) * NM, 0, 0, True, full=True))
            elif key == "DA" and center:
                r, a1, a2 = (float(v) for v in value.split(","))
                current.points.extend(_arc(center, r * NM, a1, a2, clockwise))
            elif key == "DB" and center:
                c1, c2 = (parse_coord(v) for v in value.split(",", 1)) if value.count(",") == 1 else \
                    _split_db(value)
                proj = LocalProjection(*center)
                (x1, y1), (x2, y2) = proj.to_xy(*c1), proj.to_xy(*c2)
                r = math.hypot(x1, y1)
                current.points.extend(_arc(center, r, math.degrees(math.atan2(x1, y1)),
                                           math.degrees(math.atan2(x2, y2)), clockwise))
        except ValueError:
            continue  # skip a malformed line, keep the rest of the file
    return [a for a in airspaces if len(a.points) >= 3]


def _split_db(value: str) -> tuple[tuple[float, float], tuple[float, float]]:
    coords = _COORD.findall(value)
    if len(coords) != 4:
        raise ValueError(value)
    text = [" ".join(f"{d}:{m}{':' + s if s else ''} {h}" for d, m, s, h in coords[i:i + 2]) for i in (0, 2)]
    return parse_coord(text[0]), parse_coord(text[1])


def read_openair(path: str | Path) -> list[Airspace]:
    return parse_openair(Path(path).read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- check


@dataclass
class Infringement:
    airspace: Airspace
    start: datetime
    end: datetime
    max_inside_m: float  # deepest vertical penetration above the floor
    lat: float
    lon: float
    alt: int
    uncertain: bool

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


def _inside(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _alt_for(limit: Limit, fix: Fix) -> float:
    if limit.ref == "FL":
        return fix.pressure_alt or fix.alt
    return fix.alt


def _above(fix: Fix, limit: Limit) -> bool:
    if limit.ref == "UNL":
        return False
    if limit.ref == "AGL":
        return limit.meters == 0 or fix.alt >= limit.meters  # ground height unknown (≥ 0)
    return _alt_for(limit, fix) >= limit.meters


def check_airspaces(flight: Flight, airspaces: list[Airspace],
                    all_airspaces: bool = False) -> list[Infringement]:
    fixes = [f for f in flight.fixes if f.valid]
    if not all_airspaces:
        airspaces = [a for a in airspaces if constrains_paragliders(a)]
    if not fixes:
        return []
    proj = LocalProjection(fixes[0].lat, fixes[0].lon)
    track = [proj.to_xy(f.lat, f.lon) for f in fixes]
    xs, ys = [p[0] for p in track], [p[1] for p in track]
    bbox = (min(xs), max(xs), min(ys), max(ys))

    found: list[Infringement] = []
    for space in airspaces:
        poly = [proj.to_xy(*p) for p in space.points]
        px, py = [p[0] for p in poly], [p[1] for p in poly]
        if max(px) < bbox[0] or min(px) > bbox[1] or max(py) < bbox[2] or min(py) > bbox[3]:
            continue
        uncertain = (space.floor.ref == "AGL" and space.floor.meters > 0) or space.ceiling.ref == "AGL"
        run: list[int] = []
        for i, (f, (x, y)) in enumerate(zip(fixes, track)):
            hit = _above(f, space.floor) and not _above(f, space.ceiling) and _inside(x, y, poly)
            if hit:
                run.append(i)
            if run and (not hit or i == len(fixes) - 1):
                inside = [fixes[k] for k in run]
                deepest = max(inside, key=lambda k: _alt_for(space.floor, k))
                found.append(Infringement(
                    airspace=space, start=inside[0].time, end=inside[-1].time,
                    max_inside_m=max(0.0, _alt_for(space.floor, deepest) - space.floor.meters)
                    if space.floor.ref != "AGL" else 0.0,
                    lat=deepest.lat, lon=deepest.lon, alt=deepest.alt, uncertain=uncertain,
                ))
                run = []
    return sorted(found, key=lambda inf: inf.start)

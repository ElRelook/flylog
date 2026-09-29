"""Generate synthetic but realistic IGC flights for demos and tests.

    python scripts/generate_example.py > examples/vol_exemple.igc   # the reference flight
    python scripts/generate_example.py --demo                       # examples/demo/*.igc

The reference flight takes off from Saint-Hilaire-du-Touvet (Chartreuse) and
lands in Lumbin, with three known thermals: tests rely on it.
"""

from __future__ import annotations

import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

TAKEOFF = (45.3065, 5.8870, 990)
LANDING = (45.2998, 5.9084, 245)
WIND = (1.5, 0.3)  # m/s east, north
REFERENCE_PHASES = [("glide", 60), ("thermal", 170, 2.3), ("glide", 150),
                    ("thermal", 260, 1.8), ("glide", 120), ("thermal", 90, 1.2)]


class Projection:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        lat = self.lat0 + y / 111_320
        lon = self.lon0 + x / (111_320 * math.cos(math.radians(self.lat0)))
        return lat, lon

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        y = (lat - self.lat0) * 111_320
        x = (lon - self.lon0) * 111_320 * math.cos(math.radians(self.lat0))
        return x, y


def igc_coord(value: float, pos: str, neg: str, deg_len: int) -> str:
    hemi = pos if value >= 0 else neg
    value = abs(value)
    deg = int(value)
    minutes = round((value - deg) * 60 * 1000)
    return f"{deg:0{deg_len}d}{minutes:05d}{hemi}"


def simulate(takeoff=TAKEOFF, landing=LANDING, phases=REFERENCE_PHASES, wind=WIND,
             heading_deg: float = 200, rng: random.Random | None = None) -> list[tuple[float, float, float]]:
    """Local x/y/alt points, one per second: wait on takeoff, fly the phases, land."""
    rng = rng or random.Random(42)
    x, y, alt = 0.0, 0.0, float(takeoff[2])
    heading = math.radians(heading_deg)  # direction of flight, 0 = north
    points: list[tuple[float, float, float]] = []

    def step(speed, sink, turn=0.0):
        nonlocal x, y, alt, heading
        heading += turn
        x += speed * math.sin(heading) + wind[0]
        y += speed * math.cos(heading) + wind[1]
        alt += -sink + rng.gauss(0, 0.4)
        points.append((x, y, alt))

    for _ in range(30):  # waiting on takeoff
        points.append((x, y, alt + rng.gauss(0, 0.3)))

    for phase in phases:
        if phase[0] == "glide":
            for _ in range(phase[1]):
                step(10, 1.1, rng.gauss(0, 0.02))
        else:
            _, duration, climb = phase
            for _ in range(duration):
                step(9, -(climb + rng.gauss(0, 0.5)), 9 / 30)

    lx, ly = Projection(*takeoff[:2]).to_xy(*landing[:2])
    while alt > landing[2] + 5:  # final glide, then spiral down over the landing
        if math.hypot(lx - x, ly - y) > 80:
            heading = math.atan2(lx - x, ly - y)
            step(10, 1.2)
        else:
            step(8, 2.5, 8 / 40)
    for _ in range(20):  # on the ground
        points.append((x, y, landing[2] + rng.gauss(0, 0.3)))
    return points


def to_igc(points, start: datetime, takeoff=TAKEOFF, pilot="Pilote Demo", glider="Voile EN-B") -> str:
    proj = Projection(*takeoff[:2])
    lines = ["AXCT FlyLog example", f"HFDTEDATE:{start:%d%m%y},01", f"HFPLTPILOTINCHARGE:{pilot}",
             f"HFGTYGLIDERTYPE:{glider}", "HFGIDGLIDERID:"]
    for i, (x, y, alt) in enumerate(points):
        lat, lon = proj.to_latlon(x, y)
        t = start + timedelta(seconds=i)
        a = round(alt)
        lines.append(f"B{t:%H%M%S}{igc_coord(lat, 'N', 'S', 2)}{igc_coord(lon, 'E', 'W', 3)}A{a - 12:05d}{a:05d}")
    return "\n".join(lines) + "\n"


# Demo logbook: a season of simulated flights on real takeoffs around Grenoble.
DEMO_SITES = [
    ((45.3065, 5.8870, 990), (45.2998, 5.9084, 245), 200),   # Saint-Hilaire → Lumbin
    ((45.2069, 5.8837, 1720), (45.2310, 5.8480, 230), 250),  # Chamrousse → vallée
    ((45.3990, 6.1720, 1540), (45.3908, 6.1395, 470), 230),  # Allevard → Allevard
    ((45.2580, 5.6650, 1100), (45.2300, 5.6900, 250), 160),  # Vercors / Saint-Nizier
]


def demo_flights(n: int = 12) -> list[tuple[str, str]]:
    rng = random.Random(7)
    flights = []
    day = datetime(2026, 3, 28, 11, 30)
    for k in range(n):
        takeoff, landing, heading = DEMO_SITES[k % len(DEMO_SITES)] if k % 3 else DEMO_SITES[0]
        phases = [("glide", rng.randint(40, 120))]
        for _ in range(rng.randint(5, 9 + k // 2)):
            phases += [("thermal", rng.randint(90, 300), round(rng.uniform(0.9, 2.8), 1)),
                       ("glide", rng.randint(90, 260))]
        wind = (rng.uniform(-2, 2), rng.uniform(-2, 2))
        points = simulate(takeoff, landing, phases, wind, heading + rng.uniform(-40, 40), rng)
        start = day.replace(hour=rng.randint(10, 13), minute=rng.randint(0, 59))
        flights.append((f"demo-{start:%Y-%m-%d}.igc", to_igc(points, start, takeoff)))
        day += timedelta(days=rng.randint(6, 18))
    return flights


if __name__ == "__main__":
    if "--demo" in sys.argv:
        out = Path(__file__).parent.parent / "examples" / "demo"
        out.mkdir(parents=True, exist_ok=True)
        names = []
        for name, text in demo_flights():
            (out / name).write_text(text, encoding="utf-8")
            names.append(name)
        (out / "index.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
        print(f"{len(names)} vols de démo écrits dans {out}")
    else:
        sys.stdout.write(to_igc(simulate(), datetime(2026, 9, 18, 12, 30, 0)))

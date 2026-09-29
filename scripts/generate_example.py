"""Generate a synthetic but realistic IGC flight for demos and tests.

Takeoff: Saint-Hilaire-du-Touvet (Chartreuse), landing: Lumbin.
Usage: python scripts/generate_example.py > examples/vol_exemple.igc
"""

import math
import random
from datetime import datetime, timedelta

TAKEOFF = (45.3065, 5.8870, 990)
LANDING = (45.2998, 5.9084, 245)
WIND = (1.5, 0.3)  # m/s east, north

random.seed(42)


def to_latlon(x, y):
    lat = TAKEOFF[0] + y / 111_320
    lon = TAKEOFF[1] + x / (111_320 * math.cos(math.radians(TAKEOFF[0])))
    return lat, lon


def to_xy(lat, lon):
    y = (lat - TAKEOFF[0]) * 111_320
    x = (lon - TAKEOFF[1]) * 111_320 * math.cos(math.radians(TAKEOFF[0]))
    return x, y


def igc_coord(value, pos, neg, deg_len):
    hemi = pos if value >= 0 else neg
    value = abs(value)
    deg = int(value)
    minutes = round((value - deg) * 60 * 1000)
    return f"{deg:0{deg_len}d}{minutes:05d}{hemi}"


def simulate():
    x, y, alt = 0.0, 0.0, float(TAKEOFF[2])
    heading = math.radians(200)  # direction of flight, 0 = north
    points = []

    def step(speed, sink, turn=0.0):
        nonlocal x, y, alt, heading
        heading += turn
        x += speed * math.sin(heading) + WIND[0]
        y += speed * math.cos(heading) + WIND[1]
        alt += -sink + random.gauss(0, 0.4)
        points.append((x, y, alt))

    for _ in range(30):  # waiting on takeoff
        points.append((x, y, alt + random.gauss(0, 0.3)))

    phases = [("glide", 60), ("thermal", 170, 2.3), ("glide", 150),
              ("thermal", 260, 1.8), ("glide", 120), ("thermal", 90, 1.2)]
    for phase in phases:
        if phase[0] == "glide":
            for _ in range(phase[1]):
                step(10, 1.1, random.gauss(0, 0.02))
        else:
            _, duration, climb = phase
            for _ in range(duration):
                step(9, -(climb + random.gauss(0, 0.5)), 9 / 30)

    lx, ly = to_xy(LANDING[0], LANDING[1])
    while alt > LANDING[2] + 5:  # final glide, then spiral down over the landing
        dist = math.hypot(lx - x, ly - y)
        if dist > 80:
            heading = math.atan2(lx - x, ly - y)
            step(10, 1.2)
        else:
            step(8, 2.5, 8 / 40)
    for _ in range(20):  # on the ground
        points.append((x, y, LANDING[2] + random.gauss(0, 0.3)))
    return points


def main():
    start = datetime(2026, 9, 18, 12, 30, 0)
    print("AXCT FlyLog example")
    print(f"HFDTEDATE:{start:%d%m%y},01")
    print("HFPLTPILOTINCHARGE:Pilote Demo")
    print("HFGTYGLIDERTYPE:Voile EN-B")
    print("HFGIDGLIDERID:")
    for i, (x, y, alt) in enumerate(simulate()):
        lat, lon = to_latlon(x, y)
        t = start + timedelta(seconds=i)
        a = round(alt)
        print(f"B{t:%H%M%S}{igc_coord(lat, 'N', 'S', 2)}{igc_coord(lon, 'E', 'W', 3)}"
              f"A{a - 12:05d}{a:05d}")


if __name__ == "__main__":
    main()

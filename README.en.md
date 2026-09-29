# 🪂 FlyLog

[![tests](https://github.com/ElRelook/flylog/actions/workflows/tests.yml/badge.svg)](https://github.com/ElRelook/flylog/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
[![demo](https://img.shields.io/badge/demo-online-0284c7)](https://elrelook.github.io/flylog/)

*[Version française](README.md)*

**Free flight (paragliding, hang gliding) IGC track analysis**: stats, thermals, wind, score, airspace check, logbook and video overlay. The interface is in French.

👉 **[Try it online](https://elrelook.github.io/flylog/)** · [sample flight](https://elrelook.github.io/flylog/?demo=vol) · [demo logbook](https://elrelook.github.io/flylog/?demo=carnet)

![Flight analysis](docs/capture-vol.png)

## Features

**Single flight**
- 📊 Stats: duration, distance, max altitude, total climb, vario, speed
- 🌀 Thermal detection (climb rate, duration, top), adjustable threshold
- 🧭 Piloting: time circling, left/right turns, ground glide ratio, load factor
- 💨 **Wind estimate** from thermal drift
- 🏆 **XContest-style score**: free distance (3 turnpoints), flat and FAI triangles
- ⚠️ **Airspace check** from any OpenAir file (French data: [planeur-net](https://github.com/planeur-net/airspace))
- ⚡ Highlights: strongest climb and sink, top speed, spiral dives
- ▶️ Animated replay, GPX and KML (Google Earth 3D) export, **shareable image**

**Logbook**
- 📒 Syncs the folder where **Syride** stores your flights (or any folder of IGC files)
- 🗺️ **All your tracks on one map**, plus a **thermal hotspot map** built from every flight
- 📈 Progress over time, hours per month, yearly goal, 18 badges
- 🆚 **Side-by-side comparison** of two flights
- 📍 Takeoff names (ParaglidingEarth)

**Video overlay**: a transparent video (vario, altitude, speed, mini-map, profile) to lay over GoPro or Insta360 footage, automatically synced on the clip's recording time.

![Logbook](docs/capture-carnet.png)

## Web app

**There is no server**: the `flylog` Python package runs in the browser with [Pyodide](https://pyodide.org), so the web app and the CLI share the same, tested code. **Your files never leave your computer**, and the logbook is stored in your browser. It is also an installable app (PWA) that works offline and, on Android, shows up in the *Share* menu for `.igc` files.

Run it locally: `python -m http.server 8000`, then open http://localhost:8000.

## Command line

```bash
pip install "flylog-igc[plot]"

flylog flight.igc                                 # full analysis in the terminal
flylog flight.igc --map map.html --profile profile.png --gpx f.gpx --kml f.kml
flylog flight.igc --airspace france.txt           # OpenAir airspace check
flylog sync && flylog carnet                      # logbook
flylog overlay flight.igc overlay.mov --video GX010123.MP4
```

```python
from flylog import read_igc, compute_stats
from flylog.score import best_scores

flight = read_igc("flight.igc")
print(compute_stats(flight).max_alt, best_scores(flight)[0].points)
```

## How it works

| What | How |
|---|---|
| Thermals | averaged vario > 0.5 m/s for ≥ 30 s, climbs less than 45 s apart are merged |
| Circling | unwrapped heading rate > 6°/s |
| Wind | over whole turns the airspeed vector cancels out: the average drift is the wind |
| Load factor | coordinated turn: n = √(1 + (v·ω/g)²) |
| Score | dynamic programming (free distance) and triangle search with ≤ 20 % closing, on a resampled track |
| Airspace | point-in-polygon (OpenAir circles and arcs → polygons), FL limits vs. pressure altitude, AMSL vs. GPS altitude |

All values are **estimated from GPS fixes** (usually 1 per second): good for comparing flights. For airspace, always check NOTAMs and official charts.

## Development

```bash
pip install -e ".[dev,plot]"
pytest --cov=flylog && ruff check . && mypy
```

Flights in `examples/` are **simulated** by `scripts/generate_example.py`; no real track is committed.

## License

MIT

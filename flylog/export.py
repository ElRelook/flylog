"""Export a full flight analysis as plain data (dicts / JSON), e.g. for the web UI."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .parser import Flight
from .stats import compute_stats, vario
from .thermals import Thermal, detect_thermals


def thermals_to_dicts(thermals: list[Thermal], t0: datetime) -> list[dict]:
    return [
        {
            "start_s": (t.start - t0).total_seconds(),
            "end_s": (t.end - t0).total_seconds(),
            "start": t.start.isoformat(),
            "duration_s": t.duration_s,
            "gain_m": t.gain_m,
            "avg_climb": round(t.avg_climb, 2),
            "base_alt": t.base_alt,
            "top_alt": t.top_alt,
            "lat": t.lat,
            "lon": t.lon,
        }
        for t in thermals
    ]


def flight_summary(flight: Flight, min_climb: float = 0.5) -> dict:
    """Everything needed to display a flight: metadata, track, stats and thermals."""
    stats = compute_stats(flight)
    fixes = [f for f in flight.fixes if f.valid]
    t0 = fixes[0].time

    stats_dict = asdict(stats)
    stats_dict["duration"] = stats.duration.total_seconds()

    return {
        "date": flight.date.isoformat() if flight.date else None,
        "pilot": flight.pilot,
        "glider": flight.glider,
        "start": t0.isoformat(),
        "track": {
            "t": [(f.time - t0).total_seconds() for f in fixes],
            "lat": [round(f.lat, 6) for f in fixes],
            "lon": [round(f.lon, 6) for f in fixes],
            "alt": [f.alt for f in fixes],
            "vario": [round(v, 2) for v in vario(fixes, 10)],
        },
        "stats": stats_dict,
        "thermals": thermals_to_dicts(detect_thermals(flight, min_climb=min_climb), t0),
    }

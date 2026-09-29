"""Export a full flight analysis as plain data (dicts / JSON), e.g. for the web UI."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .logbook import analyze_flight
from .metrics import estimate_wind, notable_moments, piloting_metrics
from .parser import Flight, parse_igc
from .score import best_scores
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
    thermals = detect_thermals(flight, min_climb=min_climb)
    metrics = asdict(piloting_metrics(flight, thermals))
    if metrics["wind"]:
        metrics["wind"]["time"] = metrics["wind"]["time"].isoformat()
    rel = lambda t: (t - t0).total_seconds()  # noqa: E731

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
        "thermals": thermals_to_dicts(thermals, t0),
        "metrics": metrics,
        "winds": [
            {"t": rel(w.time), "alt": w.alt, "speed_kmh": round(w.speed_kmh, 1),
             "direction_deg": round(w.direction_deg)}
            for w in estimate_wind(flight, thermals)
        ],
        "moments": [
            {"kind": m.kind, "label": m.label, "t": rel(m.time), "value": m.value,
             "lat": m.lat, "lon": m.lon, "alt": m.alt, "duration_s": m.duration_s}
            for m in notable_moments(flight)
        ],
        "scores": [
            {"kind": s.kind, "label": s.label, "distance_km": round(s.distance_km, 2),
             "points": round(s.points, 2), "turnpoints": s.turnpoints,
             "closing_km": round(s.closing_km, 2), "closing": s.closing}
            for s in best_scores(flight)
        ],
    }


def logbook_entry(text: str, file_id: str, path: str, max_points: int = 400) -> dict:
    """One logbook line plus a lightweight track (for the map of all flights)."""
    flight = parse_igc(text)
    entry = analyze_flight(flight, file_id, path)
    fixes = [f for f in flight.fixes if f.valid]
    step = max(1, len(fixes) // max_points)
    return {
        "entry": asdict(entry),
        "track": [[round(f.lat, 5), round(f.lon, 5)] for f in fixes[::step]],
    }

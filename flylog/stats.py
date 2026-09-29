"""Flight statistics: distances, altitudes, climb rates, speeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .geo import haversine
from .parser import Fix, Flight

__all__ = ["haversine", "vario", "ground_speed", "FlightStats", "compute_stats"]


def _windowed(fixes: list[Fix], window_s: float, fn) -> list[float]:
    """For each fix i, apply fn(earliest fix within window_s before i, fix i, dt)."""
    out: list[float] = []
    j = 0
    for i, fix in enumerate(fixes):
        while (fix.time - fixes[j].time).total_seconds() > window_s:
            j += 1
        dt = (fix.time - fixes[j].time).total_seconds()
        out.append(fn(fixes[j], fix, dt) if dt > 0 else 0.0)
    return out


def vario(fixes: list[Fix], window_s: float = 10) -> list[float]:
    """Vertical speed (m/s) averaged over a sliding window."""
    return _windowed(fixes, window_s, lambda a, b, dt: (b.alt - a.alt) / dt)


def ground_speed(fixes: list[Fix], window_s: float = 10) -> list[float]:
    """Ground speed (km/h) averaged over a sliding window."""
    return _windowed(
        fixes, window_s, lambda a, b, dt: haversine(a.lat, a.lon, b.lat, b.lon) / dt * 3.6
    )


def _smoothed(values: list[int], half_width: int = 2) -> list[float]:
    n = len(values)
    return [
        sum(values[max(0, i - half_width): i + half_width + 1])
        / len(values[max(0, i - half_width): i + half_width + 1])
        for i in range(n)
    ]


@dataclass
class FlightStats:
    duration: timedelta
    track_distance_km: float
    straight_distance_km: float
    max_distance_from_takeoff_km: float
    takeoff_alt: int
    landing_alt: int
    max_alt: int
    min_alt: int
    total_gain_m: int
    max_climb: float
    max_sink: float
    max_speed_kmh: float


def compute_stats(flight: Flight) -> FlightStats:
    fixes = [f for f in flight.fixes if f.valid]
    if len(fixes) < 2:
        raise ValueError("Pas assez de points GPS valides pour analyser le vol.")

    first, last = fixes[0], fixes[-1]
    track = sum(
        haversine(a.lat, a.lon, b.lat, b.lon) for a, b in zip(fixes, fixes[1:])
    )
    alts = [f.alt for f in fixes]
    smooth = _smoothed(alts)
    gain = sum(max(0.0, b - a) for a, b in zip(smooth, smooth[1:]))
    v = vario(fixes)

    return FlightStats(
        duration=last.time - first.time,
        track_distance_km=track / 1000,
        straight_distance_km=haversine(first.lat, first.lon, last.lat, last.lon) / 1000,
        max_distance_from_takeoff_km=max(
            haversine(first.lat, first.lon, f.lat, f.lon) for f in fixes
        ) / 1000,
        takeoff_alt=first.alt,
        landing_alt=last.alt,
        max_alt=max(alts),
        min_alt=min(alts),
        total_gain_m=round(gain),
        max_climb=max(v),
        max_sink=min(v),
        max_speed_kmh=max(ground_speed(fixes)),
    )

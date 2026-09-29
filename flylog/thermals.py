"""Detect thermals: sustained periods of climb."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .parser import Fix, Flight
from .stats import vario


@dataclass
class Thermal:
    start: datetime
    end: datetime
    base_alt: int
    top_alt: int
    lat: float
    lon: float

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def gain_m(self) -> int:
        return self.top_alt - self.base_alt

    @property
    def avg_climb(self) -> float:
        return self.gain_m / self.duration_s if self.duration_s else 0.0


def _build(fixes: list[Fix]) -> Thermal:
    alts = [f.alt for f in fixes]
    return Thermal(
        start=fixes[0].time,
        end=fixes[-1].time,
        base_alt=min(alts),
        top_alt=max(alts),
        lat=sum(f.lat for f in fixes) / len(fixes),
        lon=sum(f.lon for f in fixes) / len(fixes),
    )


def detect_thermals(
    flight: Flight,
    min_climb: float = 0.5,
    min_duration_s: float = 30,
    min_gain_m: int = 30,
    window_s: float = 20,
    max_gap_s: float = 45,
) -> list[Thermal]:
    """Find segments where the averaged vario stays above `min_climb` m/s.

    Climbs separated by less than `max_gap_s` (a weak spot in a turn,
    re-centering the core) are merged into a single thermal.
    """
    fixes = [f for f in flight.fixes if f.valid]
    rates = vario(fixes, window_s)

    # (start, end) index ranges of climbing fixes
    ranges: list[list[int]] = []
    for i, rate in enumerate(rates):
        if rate < min_climb:
            continue
        gap = (fixes[i].time - fixes[ranges[-1][1]].time).total_seconds() if ranges else None
        if gap is not None and gap <= max_gap_s:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])

    thermals = [_build(fixes[a: b + 1]) for a, b in ranges if b > a]
    return [
        t for t in thermals if t.duration_s >= min_duration_s and t.gain_m >= min_gain_m
    ]

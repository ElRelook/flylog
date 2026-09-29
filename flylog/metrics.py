"""Piloting metrics: circling, glides, wind, load factor and notable moments.

Everything is estimated from GPS fixes only (usually 1 per second), so values
like the load factor are approximations, good for comparing flights.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .geo import LocalProjection, bearing, haversine
from .parser import Fix, Flight
from .stats import ground_speed, vario
from .thermals import Thermal, detect_thermals

G = 9.81
CIRCLING_RATE = 6.0  # deg/s: a 360° in less than 60 s


def _valid(flight: Flight) -> list[Fix]:
    return [f for f in flight.fixes if f.valid]


def cumulative_heading(fixes: list[Fix]) -> list[float]:
    """Unwrapped heading (degrees, can exceed 360): its slope is the turn rate."""
    out = [0.0]
    last = None
    for a, b in zip(fixes, fixes[1:]):
        if haversine(a.lat, a.lon, b.lat, b.lon) < 1:  # not moving: keep heading
            out.append(out[-1])
            continue
        h = bearing(a.lat, a.lon, b.lat, b.lon)
        delta = 0.0 if last is None else (h - last + 180) % 360 - 180
        last = h
        out.append(out[-1] + delta)
    return out


def turn_rates(fixes: list[Fix], window_s: float = 10) -> list[float]:
    """Signed turn rate in deg/s (positive = turning right), over a sliding window."""
    heading = cumulative_heading(fixes)
    out, j = [], 0
    for i, f in enumerate(fixes):
        while (f.time - fixes[j].time).total_seconds() > window_s:
            j += 1
        dt = (f.time - fixes[j].time).total_seconds()
        out.append((heading[i] - heading[j]) / dt if dt else 0.0)
    return out


def load_factor(speed_ms: float, turn_rate_deg_s: float) -> float:
    """Load factor (G) of a coordinated turn: sqrt(1 + (v·ω/g)²)."""
    omega = math.radians(turn_rate_deg_s)
    return math.sqrt(1 + (speed_ms * omega / G) ** 2)


# ---------------------------------------------------------------- glides


@dataclass
class Glide:
    start: datetime
    end: datetime
    distance_m: float
    alt_loss_m: int

    @property
    def ratio(self) -> float:
        return self.distance_m / self.alt_loss_m if self.alt_loss_m > 0 else math.inf

    @property
    def speed_kmh(self) -> float:
        dt = (self.end - self.start).total_seconds()
        return self.distance_m / dt * 3.6 if dt else 0.0


def detect_glides(flight: Flight, min_duration_s: float = 30, min_loss_m: int = 20) -> list[Glide]:
    """Straight flight segments (not circling) where altitude is lost."""
    fixes = _valid(flight)
    rates = turn_rates(fixes)
    glides: list[Glide] = []
    start = None
    for i, rate in enumerate(rates + [math.inf]):  # sentinel closes the last segment
        straight = abs(rate) < CIRCLING_RATE
        if straight and start is None:
            start = i
        elif not straight and start is not None:
            seg = fixes[start:i]
            if len(seg) > 1:
                dist = sum(haversine(a.lat, a.lon, b.lat, b.lon) for a, b in zip(seg, seg[1:]))
                loss = seg[0].alt - seg[-1].alt
                dur = (seg[-1].time - seg[0].time).total_seconds()
                if dur >= min_duration_s and loss >= min_loss_m:
                    glides.append(Glide(seg[0].time, seg[-1].time, dist, loss))
            start = None
    return glides


# ---------------------------------------------------------------- wind


@dataclass
class WindEstimate:
    time: datetime
    alt: int
    speed_kmh: float
    direction_deg: float  # where the wind blows FROM (meteorological convention)


def estimate_wind(flight: Flight, thermals: list[Thermal] | None = None) -> list[WindEstimate]:
    """Wind from thermal drift: over whole circles, the air-relative motion cancels
    out, so the pilot's average ground velocity is the wind."""
    fixes = _valid(flight)
    if len(fixes) < 2:
        return []
    thermals = detect_thermals(flight) if thermals is None else thermals
    heading = cumulative_heading(fixes)
    proj = LocalProjection(fixes[0].lat, fixes[0].lon)
    index = {f.time: i for i, f in enumerate(fixes)}

    out: list[WindEstimate] = []
    for t in thermals:
        a, b = index.get(t.start), index.get(t.end)
        if a is None or b is None or t.duration_s < 60:
            continue
        turns = int(abs(heading[b] - heading[a]) // 360)
        if turns < 1:
            continue
        # End exactly after a whole number of turns.
        e = next(k for k in range(a, b + 1) if abs(heading[k] - heading[a]) >= turns * 360)
        dt = (fixes[e].time - fixes[a].time).total_seconds()
        if dt <= 0:
            continue
        x0, y0 = proj.to_xy(fixes[a].lat, fixes[a].lon)
        x1, y1 = proj.to_xy(fixes[e].lat, fixes[e].lon)
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        out.append(WindEstimate(
            time=fixes[a].time,
            alt=round(sum(f.alt for f in fixes[a:e + 1]) / (e - a + 1)),
            speed_kmh=math.hypot(vx, vy) * 3.6,
            direction_deg=(math.degrees(math.atan2(vx, vy)) + 180) % 360,
        ))
    return out


def average_wind(estimates: list[WindEstimate]) -> WindEstimate | None:
    if not estimates:
        return None
    vx = sum(w.speed_kmh * math.sin(math.radians(w.direction_deg)) for w in estimates) / len(estimates)
    vy = sum(w.speed_kmh * math.cos(math.radians(w.direction_deg)) for w in estimates) / len(estimates)
    return WindEstimate(
        time=estimates[0].time,
        alt=round(sum(w.alt for w in estimates) / len(estimates)),
        speed_kmh=math.hypot(vx, vy),
        direction_deg=math.degrees(math.atan2(vx, vy)) % 360,
    )


# ---------------------------------------------------------------- moments


@dataclass
class Moment:
    kind: str  # "climb", "sink", "speed", "g", "spiral"
    label: str
    time: datetime
    value: float
    lat: float
    lon: float
    alt: int
    duration_s: float = 0.0


def notable_moments(flight: Flight) -> list[Moment]:
    """Strongest climb and sink, top speed, max load factor and spiral dives."""
    fixes = _valid(flight)
    if len(fixes) < 10:
        return []
    climb = vario(fixes, 10)
    sink = vario(fixes, 5)
    speed = ground_speed(fixes, 10)
    rate5 = turn_rates(fixes, 5)
    speed5 = ground_speed(fixes, 5)
    g = [load_factor(s / 3.6, r) for s, r in zip(speed5, rate5)]

    def at(kind: str, label: str, values: list[float], pick) -> Moment:
        i = pick(range(len(values)), key=values.__getitem__)
        f = fixes[i]
        return Moment(kind, label, f.time, round(values[i], 1), f.lat, f.lon, f.alt)

    moments = [
        at("climb", "Plus forte montée (10 s)", climb, max),
        at("sink", "Plus forte descente (5 s)", sink, min),
        at("speed", "Vitesse sol max (10 s)", speed, max),
        at("g", "Facteur de charge max (estimé)", g, max),
    ]

    # Spiral dives: tight turn + strong sink for at least 5 s.
    start = None
    for i in range(len(fixes) + 1):
        spiral = i < len(fixes) and abs(rate5[i]) > 25 and sink[i] < -5
        if spiral and start is None:
            start = i
        elif not spiral and start is not None:
            seg = range(start, i)
            dur = (fixes[i - 1].time - fixes[start].time).total_seconds()
            if dur >= 5:
                worst = min(seg, key=sink.__getitem__)
                f = fixes[worst]
                moments.append(Moment(
                    "spiral", f"Spirale : {max(g[k] for k in seg):.1f} G, "
                              f"-{fixes[start].alt - fixes[i - 1].alt} m",
                    f.time, round(sink[worst], 1), f.lat, f.lon, f.alt, dur,
                ))
            start = None
    return moments


# ---------------------------------------------------------------- summary


@dataclass
class PilotingMetrics:
    circling_pct: float
    left_turn_pct: float  # share of circling time turning left
    avg_thermal_climb: float | None
    avg_glide_ratio: float | None
    best_glide_ratio: float | None
    avg_glide_speed_kmh: float | None
    max_g: float
    wind: WindEstimate | None


def piloting_metrics(flight: Flight, thermals: list[Thermal] | None = None) -> PilotingMetrics:
    fixes = _valid(flight)
    thermals = detect_thermals(flight) if thermals is None else thermals
    rates = turn_rates(fixes)
    circling = [r for r in rates if abs(r) >= CIRCLING_RATE]
    glides = detect_glides(flight)
    # Best glide: long glides really sinking (≥ 0.5 m/s), not cruising in lift.
    long_glides = [
        gl for gl in glides
        if gl.distance_m >= 1000 and gl.alt_loss_m / (gl.end - gl.start).total_seconds() >= 0.5
    ]
    total_dist = sum(gl.distance_m for gl in glides)
    total_loss = sum(gl.alt_loss_m for gl in glides)
    total_time = sum((gl.end - gl.start).total_seconds() for gl in glides)
    th_time = sum(t.duration_s for t in thermals)
    g5 = [load_factor(s / 3.6, r) for s, r in zip(ground_speed(fixes, 5), turn_rates(fixes, 5))]

    return PilotingMetrics(
        circling_pct=100 * len(circling) / len(rates) if rates else 0.0,
        left_turn_pct=100 * sum(r < 0 for r in circling) / len(circling) if circling else 0.0,
        avg_thermal_climb=sum(t.gain_m for t in thermals) / th_time if th_time else None,
        avg_glide_ratio=total_dist / total_loss if total_loss else None,
        best_glide_ratio=max((gl.ratio for gl in long_glides), default=None),
        avg_glide_speed_kmh=total_dist / total_time * 3.6 if total_time else None,
        max_g=max(g5, default=1.0),
        wind=average_wind(estimate_wind(flight, thermals)),
    )

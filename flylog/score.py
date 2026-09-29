"""Flight score, XContest style: free distance, flat triangle and FAI triangle.

The track is downsampled before optimizing, so the result is an estimate
(usually within a few percent of the official score).

- free distance: start, up to 3 turnpoints, end (coefficient 1.0)
- flat triangle: closing distance ≤ 20 % of the perimeter (coefficient 1.2)
- FAI triangle: same, with every side ≥ 28 % of the perimeter (coefficient 1.4)

Triangle distance = perimeter - closing distance.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geo import haversine
from .parser import Flight

COEFFICIENTS = {"free": 1.0, "flat": 1.2, "fai": 1.4}
LABELS = {"free": "Distance libre", "flat": "Triangle plat", "fai": "Triangle FAI"}
MAX_CLOSING = 0.20
FAI_MIN_SIDE = 0.28


@dataclass
class Score:
    kind: str
    distance_km: float
    points: float
    turnpoints: list[tuple[float, float]]  # lat, lon (free: start, TPs, end)
    closing_km: float = 0.0
    closing: tuple[tuple[float, float], tuple[float, float]] | None = None

    @property
    def label(self) -> str:
        return LABELS[self.kind]


def _sample(flight: Flight, n: int) -> list[tuple[float, float]]:
    fixes = [f for f in flight.fixes if f.valid]
    if len(fixes) <= n:
        return [(f.lat, f.lon) for f in fixes]
    step = (len(fixes) - 1) / (n - 1)
    return [(fixes[round(i * step)].lat, fixes[round(i * step)].lon) for i in range(n)]


def _matrix(pts: list[tuple[float, float]]) -> list[list[float]]:
    n = len(pts)
    d = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d[i][j] = d[j][i] = haversine(*pts[i], *pts[j]) / 1000
    return d


def free_distance(flight: Flight, n: int = 300, turnpoints: int = 3) -> Score | None:
    pts = _sample(flight, n)
    if len(pts) < 2:
        return None
    d = _matrix(pts)
    n = len(pts)
    best = [0.0] * n  # best path ending at j with the legs processed so far
    back: list[list[int]] = []
    for _ in range(turnpoints + 1):
        new, arg = [0.0] * n, [0] * n
        for j in range(n):
            bj, bi = -1.0, j
            dj = d[j]
            for i in range(j + 1):
                v = best[i] + dj[i]
                if v > bj:
                    bj, bi = v, i
            new[j], arg[j] = bj, bi
        best = new
        back.append(arg)

    end = max(range(n), key=best.__getitem__)
    path = [end]
    for arg in reversed(back):
        path.append(arg[path[-1]])
    path.reverse()
    km = best[end]
    return Score("free", km, km * COEFFICIENTS["free"], [pts[i] for i in path])


def triangles(flight: Flight, n: int = 120) -> tuple[Score | None, Score | None]:
    """Best flat triangle and best FAI triangle (either may be None)."""
    pts = _sample(flight, n)
    n = len(pts)
    if n < 4:
        return None, None
    d = _matrix(pts)

    # closing[i][k]: shortest distance between a point before i and a point after k.
    closing = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for k in range(n - 1, i - 1, -1):
            c = d[i][k]
            if i > 0:
                c = min(c, closing[i - 1][k])
            if k < n - 1:
                c = min(c, closing[i][k + 1])
            closing[i][k] = c

    best: dict[str, tuple[float, tuple[int, int, int]] | None] = {"flat": None, "fai": None}
    for i in range(n):
        di = d[i]
        for k in range(i + 2, n):
            close, dik, dk = closing[i][k], di[k], d[k]
            for j in range(i + 1, k):
                a, b = di[j], dk[j]
                p = a + b + dik
                if p <= 0 or close > MAX_CLOSING * p:
                    continue
                km = p - close
                if best["flat"] is None or km > best["flat"][0]:
                    best["flat"] = (km, (i, j, k))
                if min(a, b, dik) >= FAI_MIN_SIDE * p and (best["fai"] is None or km > best["fai"][0]):
                    best["fai"] = (km, (i, j, k))

    def build(kind: str) -> Score | None:
        found = best[kind]
        if not found:
            return None
        km, (i, j, k) = found
        # Recover the closing pair for display.
        s, e = min(((s, e) for s in range(i + 1) for e in range(k, n)), key=lambda se: d[se[0]][se[1]])
        return Score(kind, km, km * COEFFICIENTS[kind], [pts[i], pts[j], pts[k]],
                     closing_km=d[s][e], closing=(pts[s], pts[e]))

    return build("flat"), build("fai")


def best_scores(flight: Flight) -> list[Score]:
    """All available scores, best first."""
    flat, fai = triangles(flight)
    scores = [s for s in (free_distance(flight), flat, fai) if s is not None]
    return sorted(scores, key=lambda s: s.points, reverse=True)

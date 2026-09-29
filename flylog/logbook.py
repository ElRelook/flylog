"""Logbook: keep a summary of every flight found in a folder (e.g. Syride's sync folder)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .metrics import piloting_metrics
from .parser import Flight, read_igc
from .score import best_scores
from .stats import compute_stats
from .thermals import detect_thermals

# Bump when the analysis changes: the next sync re-analyzes every flight.
ANALYSIS_VERSION = 3


def default_source() -> Path:
    """Folder where SYS-PC-Tool / the Syride app copy every synced flight."""
    return Path.home() / "Documents" / "Syride"


def default_db() -> Path:
    """Stored outside any repository so personal tracks are never committed by mistake."""
    return Path.home() / ".flylog" / "carnet.json"


@dataclass
class LogEntry:
    id: str
    path: str
    date: str | None
    takeoff_time: str
    duration_s: float
    distance_km: float
    max_distance_km: float
    takeoff_alt: int
    max_alt: int
    gain_m: int
    max_climb: float
    thermals: int
    best_thermal_m: int
    glider: str | None
    takeoff_lat: float
    takeoff_lon: float
    # Added in analysis version 3 (defaults keep older logbooks loadable).
    score_points: float = 0.0
    score_kind: str = ""
    avg_thermal_climb: float | None = None
    glide_ratio: float | None = None
    circling_pct: float = 0.0
    left_turn_pct: float = 0.0
    max_g: float = 1.0
    # [lat, lon, avg climb m/s, gain m, top alt m, start minute of day UTC]
    thermal_spots: list[list[float]] = field(default_factory=list)


@dataclass
class SyncResult:
    added: list[LogEntry]
    known: int
    errors: list[tuple[str, str]]
    rebuilt: bool = False


def _file_id(path: Path) -> str:
    """Content hash: the same flight copied in several folders is counted once."""
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def analyze_file(path: Path, file_id: str) -> LogEntry:
    return analyze_flight(read_igc(path), file_id, str(path))


def analyze_flight(flight: Flight, file_id: str, path: str) -> LogEntry:
    stats = compute_stats(flight)
    thermals = detect_thermals(flight)
    first = next(f for f in flight.fixes if f.valid)
    metrics = piloting_metrics(flight, thermals)
    scores = best_scores(flight)
    return LogEntry(
        id=file_id,
        path=path,
        date=flight.date.isoformat() if flight.date else None,
        takeoff_time=first.time.isoformat(),
        duration_s=stats.duration.total_seconds(),
        distance_km=round(stats.track_distance_km, 2),
        max_distance_km=round(stats.max_distance_from_takeoff_km, 2),
        takeoff_alt=stats.takeoff_alt,
        max_alt=stats.max_alt,
        gain_m=stats.total_gain_m,
        max_climb=round(stats.max_climb, 1),
        thermals=len(thermals),
        best_thermal_m=max((t.gain_m for t in thermals), default=0),
        glider=flight.glider,
        takeoff_lat=round(first.lat, 5),
        takeoff_lon=round(first.lon, 5),
        score_points=round(scores[0].points, 1) if scores else 0.0,
        score_kind=scores[0].kind if scores else "",
        avg_thermal_climb=_round(metrics.avg_thermal_climb, 2),
        glide_ratio=_round(metrics.avg_glide_ratio, 1),
        circling_pct=round(metrics.circling_pct, 1),
        left_turn_pct=round(metrics.left_turn_pct, 1),
        max_g=round(metrics.max_g, 2),
        thermal_spots=[
            [round(t.lat, 5), round(t.lon, 5), round(t.avg_climb, 2), t.gain_m, t.top_alt,
             t.start.hour * 60 + t.start.minute]
            for t in thermals
        ],
    )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _read(db: Path) -> dict:
    if not db.exists():
        return {"flights": []}
    return json.loads(db.read_text(encoding="utf-8"))


def load(db: Path) -> dict[str, LogEntry]:
    return {e["id"]: LogEntry(**e) for e in _read(db)["flights"]}


def is_outdated(db: Path) -> bool:
    raw = _read(db)
    return bool(raw["flights"]) and raw.get("analysis_version") != ANALYSIS_VERSION


def save(db: Path, entries: dict[str, LogEntry]) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    flights = sorted((asdict(e) for e in entries.values()), key=lambda e: e["takeoff_time"])
    db.write_text(json.dumps({"analysis_version": ANALYSIS_VERSION, "flights": flights}, indent=1, ensure_ascii=False),
                  encoding="utf-8")


def sync(source: Path, db: Path) -> SyncResult:
    """Add every new .igc file found under `source` to the logbook stored in `db`.

    If the logbook was built by an older version of the analysis, every flight
    is analyzed again.
    """
    rebuild = is_outdated(db)
    entries = {} if rebuild else load(db)
    added: list[LogEntry] = []
    errors: list[tuple[str, str]] = []
    known = 0

    for path in sorted(p for p in source.rglob("*") if p.suffix.lower() == ".igc"):
        file_id = _file_id(path)
        if file_id in entries:
            known += 1
            continue
        try:
            entry = analyze_file(path, file_id)
        except (ValueError, StopIteration) as e:
            errors.append((str(path), str(e) or "aucun point GPS valide"))
            continue
        entries[file_id] = entry
        added.append(entry)

    if added or rebuild:
        save(db, entries)
    return SyncResult(added=added, known=known, errors=errors, rebuilt=rebuild)


@dataclass
class Totals:
    flights: int
    duration_s: float
    distance_km: float
    gain_m: int
    best_alt: LogEntry | None
    longest: LogEntry | None
    farthest: LogEntry | None
    by_year: dict[str, tuple[int, float]]


def totals(entries: list[LogEntry]) -> Totals:
    by_year: dict[str, tuple[int, float]] = {}
    for e in entries:
        year = e.takeoff_time[:4]
        n, d = by_year.get(year, (0, 0.0))
        by_year[year] = (n + 1, d + e.duration_s)
    return Totals(
        flights=len(entries),
        duration_s=sum(e.duration_s for e in entries),
        distance_km=sum(e.distance_km for e in entries),
        gain_m=sum(e.gain_m for e in entries),
        best_alt=max(entries, key=lambda e: e.max_alt, default=None),
        longest=max(entries, key=lambda e: e.duration_s, default=None),
        farthest=max(entries, key=lambda e: e.distance_km, default=None),
        by_year=dict(sorted(by_year.items())),
    )

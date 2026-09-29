"""Parse IGC flight logs (the standard format written by paragliding instruments)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass
class Fix:
    """A single GPS position recorded by the instrument (IGC "B" record)."""

    time: datetime
    lat: float
    lon: float
    valid: bool
    pressure_alt: int
    gps_alt: int

    @property
    def alt(self) -> int:
        """Best available altitude: GPS if recorded, else barometric."""
        return self.gps_alt if self.gps_alt else self.pressure_alt


@dataclass
class Flight:
    date: date | None = None
    pilot: str | None = None
    glider: str | None = None
    fixes: list[Fix] = field(default_factory=list)


_DATE_RE = re.compile(r"^HFDTE(?:DATE:)?(\d{2})(\d{2})(\d{2})")
_HEADERS = {
    "HFPLTPILOTINCHARGE": "pilot",
    "HFPLTPILOT": "pilot",
    "HFGTYGLIDERTYPE": "glider",
}


def _coord(digits: str, hemisphere: str, deg_len: int) -> float:
    """Convert IGC 'DDMMmmm' / 'DDDMMmmm' into decimal degrees."""
    degrees = int(digits[:deg_len])
    minutes = int(digits[deg_len:]) / 1000
    value = degrees + minutes / 60
    return -value if hemisphere in "SW" else value


def parse_igc(text: str) -> Flight:
    flight = Flight()
    day = date(1970, 1, 1)
    previous: datetime | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("HFDTE"):
            m = _DATE_RE.match(line)
            if m:
                dd, mm, yy = (int(g) for g in m.groups())
                day = flight.date = date(2000 + yy, mm, dd)
            continue

        if line.startswith("H") and ":" in line:
            key, value = line.split(":", 1)
            attr = _HEADERS.get(key)
            if attr and value.strip() and getattr(flight, attr) is None:
                setattr(flight, attr, value.strip())
            continue

        if line.startswith("B") and len(line) >= 35:
            t = datetime.combine(day, datetime.strptime(line[1:7], "%H%M%S").time())
            # Flights crossing midnight UTC: keep timestamps increasing.
            if previous and t < previous:
                t += timedelta(days=1)
            previous = t
            flight.fixes.append(
                Fix(
                    time=t,
                    lat=_coord(line[7:14], line[14], 2),
                    lon=_coord(line[15:23], line[23], 3),
                    valid=line[24] == "A",
                    pressure_alt=int(line[25:30]),
                    gps_alt=int(line[30:35]),
                )
            )

    return flight


def read_igc(path: str | Path) -> Flight:
    return parse_igc(Path(path).read_text(encoding="utf-8", errors="replace"))

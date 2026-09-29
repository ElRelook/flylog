"""Takeoff site names, from the public ParaglidingEarth database.

Lookups are cached in ~/.flylog/sites.json (one request per new place), and any
network problem simply leaves the site unnamed.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.paraglidingearth.com/api/geojson/getAroundLatLngSites.php"
USER_AGENT = "FlyLog (https://github.com/ElRelook/flylog)"
MAX_DISTANCE_M = 1500


def default_cache() -> Path:
    return Path.home() / ".flylog" / "sites.json"


def _key(lat: float, lon: float) -> str:
    return f"{lat:.3f},{lon:.3f}"  # ~100 m


class SiteNamer:
    def __init__(self, cache: Path | None = None, timeout: float = 5.0):
        self.cache_path = cache or default_cache()
        self.timeout = timeout
        self.online = True
        try:
            self.cache: dict[str, str | None] = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def fetch(self, lat: float, lon: float) -> str | None:
        """Nearest takeoff within MAX_DISTANCE_M, or None."""
        query = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lng": f"{lon:.5f}", "distance": 2, "limit": 1})
        req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            data = json.load(res)
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if float(props.get("distance", 1e9)) <= MAX_DISTANCE_M and props.get("name"):
                return str(props["name"]).strip()
        return None

    def name(self, lat: float, lon: float) -> str | None:
        key = _key(lat, lon)
        if key in self.cache:
            return self.cache[key]
        if not self.online:
            return None
        try:
            name = self.fetch(lat, lon)
        except (OSError, ValueError):
            self.online = False  # offline or API down: don't retry for every flight
            return None
        self.cache[key] = name
        return name

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

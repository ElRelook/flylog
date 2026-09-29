"""FlyLog: analyse de traces de vol libre (fichiers IGC)."""

from .parser import Fix, Flight, parse_igc, read_igc
from .stats import FlightStats, compute_stats, haversine
from .thermals import Thermal, detect_thermals

__version__ = "0.1.0"
__all__ = [
    "Fix", "Flight", "FlightStats", "Thermal",
    "compute_stats", "detect_thermals", "haversine", "parse_igc", "read_igc",
]

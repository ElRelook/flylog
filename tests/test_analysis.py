from pathlib import Path

import pytest

from flylog import compute_stats, detect_thermals, haversine, read_igc
from flylog.cli import main

EXAMPLE = Path(__file__).parent.parent / "examples" / "vol_exemple.igc"


@pytest.fixture(scope="module")
def flight():
    return read_igc(EXAMPLE)


def test_haversine_one_degree_latitude():
    assert haversine(45, 5, 46, 5) == pytest.approx(111_195, rel=1e-3)


def test_haversine_same_point():
    assert haversine(45.3, 5.88, 45.3, 5.88) == 0


def test_stats(flight):
    s = compute_stats(flight)
    assert s.takeoff_alt == pytest.approx(990, abs=5)
    assert s.landing_alt == pytest.approx(245, abs=5)
    assert s.max_alt > 1500
    assert s.max_climb > 1.5
    assert s.max_sink < -1
    assert 10 < s.track_distance_km < 30
    assert 30 < s.max_speed_kmh < 60


def test_detects_the_three_thermals(flight):
    thermals = detect_thermals(flight)
    assert len(thermals) == 3
    assert thermals[0].avg_climb == pytest.approx(2.3, abs=0.4)
    assert all(t.gain_m > 50 for t in thermals)


def test_stats_needs_fixes():
    from flylog import Flight

    with pytest.raises(ValueError):
        compute_stats(Flight())


def test_cli_runs(capsys):
    assert main([str(EXAMPLE)]) == 0
    assert "thermique" in capsys.readouterr().out

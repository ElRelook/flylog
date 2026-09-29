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


def _flight_from_altitudes(alts):
    from datetime import datetime, timedelta

    from flylog import Fix, Flight

    t0 = datetime(2026, 1, 1, 12)
    return Flight(fixes=[
        Fix(t0 + timedelta(seconds=i), 45.3, 5.88, True, a, a) for i, a in enumerate(alts)
    ])


def test_short_pause_in_climb_is_merged_into_one_thermal():
    climb = [1000 + 2 * i for i in range(90)]
    pause = [climb[-1]] * 30
    climb2 = [pause[-1] + 2 * i for i in range(90)]
    thermals = detect_thermals(_flight_from_altitudes(climb + pause + climb2))
    assert len(thermals) == 1
    assert thermals[0].gain_m == pytest.approx(356, abs=5)


def test_long_glide_separates_thermals():
    climb = [1000 + 2 * i for i in range(90)]
    glide = [climb[-1] - i for i in range(120)]
    climb2 = [glide[-1] + 2 * i for i in range(90)]
    assert len(detect_thermals(_flight_from_altitudes(climb + glide + climb2))) == 2

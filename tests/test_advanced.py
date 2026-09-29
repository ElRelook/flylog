import math
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from flylog import Fix, Flight, detect_thermals, read_igc
from flylog.airspace import check_airspaces, parse_coord, parse_limit, parse_openair
from flylog.formats import to_gpx, to_kml
from flylog.geo import LocalProjection
from flylog.metrics import estimate_wind, load_factor, notable_moments, piloting_metrics
from flylog.score import best_scores, free_distance, triangles

EXAMPLE = Path(__file__).parent.parent / "examples" / "vol_exemple.igc"


@pytest.fixture(scope="module")
def flight():
    return read_igc(EXAMPLE)


def _flight_from_xy(points, alt=1500, lat0=45.3, lon0=5.9):
    """Build a flight from local x/y points (meters), one fix per second."""
    proj = LocalProjection(lat0, lon0)
    t0 = datetime(2026, 7, 1, 12)
    fixes = []
    for i, (x, y) in enumerate(points):
        lat, lon = proj.to_latlon(x, y)
        fixes.append(Fix(t0 + timedelta(seconds=i), lat, lon, True, alt, alt))
    return Flight(fixes=fixes)


def _walk(corners, step=10):
    """Points every `step` meters along a polyline."""
    pts = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        pts += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    return pts + [corners[-1]]


# ---------------------------------------------------------------- metrics


def test_wind_matches_the_simulated_wind(flight):
    # The example flight is simulated with a 1.5 m/s east + 0.3 m/s north wind:
    # 5.5 km/h blowing from ~259°.
    winds = estimate_wind(flight)
    assert len(winds) == 3
    for w in winds:
        assert w.speed_kmh == pytest.approx(5.5, abs=1)
        assert w.direction_deg == pytest.approx(259, abs=10)


def test_piloting_metrics(flight):
    m = piloting_metrics(flight)
    assert 40 < m.circling_pct < 80
    assert m.left_turn_pct < 20  # the simulation only turns right
    assert m.avg_thermal_climb == pytest.approx(1.8, abs=0.4)
    assert 7 < m.avg_glide_ratio < 12
    assert m.wind.speed_kmh == pytest.approx(5.5, abs=1)


def test_load_factor():
    assert load_factor(10, 0) == 1
    # 45° bank at 10 m/s: ω = g·tan(45°)/v → 2 G·cos... n = 1/cos(45°) ≈ 1.41
    omega = math.degrees(9.81 / 10)
    assert load_factor(10, omega) == pytest.approx(math.sqrt(2), rel=1e-3)


def test_spiral_is_a_notable_moment():
    # 20 s at 30°/s (radius ~25 m at 13 m/s) losing 12 m/s.
    pts, alt = [], []
    for i in range(60):
        a = math.radians(30 * i)
        pts.append((25 * math.sin(a), 25 * math.cos(a)))
        alt.append(2000 - 12 * max(0, i - 20))
    fl = _flight_from_xy(pts)
    for f, a in zip(fl.fixes, alt):
        f.gps_alt = f.pressure_alt = a
    kinds = [m.kind for m in notable_moments(fl)]
    assert "spiral" in kinds


# ---------------------------------------------------------------- score


def test_free_distance_of_a_straight_line():
    fl = _flight_from_xy(_walk([(0, 0), (20_000, 0)]))
    assert free_distance(fl).distance_km == pytest.approx(20, rel=0.01)


def test_triangles():
    # Equilateral 10 km sides, closed: a valid FAI triangle of 30 km.
    s = 10_000
    corners = [(0, 0), (s, 0), (s / 2, s * math.sqrt(3) / 2), (0, 0)]
    flat, fai = triangles(_flight_from_xy(_walk(corners, 50)))
    assert fai is not None and flat is not None
    assert fai.distance_km == pytest.approx(30, rel=0.03)
    assert fai.points == pytest.approx(fai.distance_km * 1.4)
    assert best_scores(_flight_from_xy(_walk(corners, 50)))[0].kind == "fai"


def test_open_track_has_no_triangle():
    flat, fai = triangles(_flight_from_xy(_walk([(0, 0), (30_000, 0)], 100)))
    assert flat is None and fai is None


# ---------------------------------------------------------------- airspace

OPENAIR = """\
* test file
AC D
AN CTR TEST
AL SFC
AH FL100
V X=45:18:23 N 005:53:13 E
DC 1

AC R
AN HIGH ZONE
AL FL195
AH UNL
DP 45:00:00 N 005:00:00 E
DP 46:00:00 N 005:00:00 E
DP 46:00:00 N 007:00:00 E
DP 45:00:00 N 007:00:00 E

AC P
AN FAR AWAY
AL SFC
AH 3000FT AMSL
DP 48:00:00 N 002:00:00 E
DP 48:10:00 N 002:00:00 E
DP 48:10:00 N 002:10:00 E

AC Q
AN ARC ZONE
AL 1000FT AGL
AH 5000M
V X=45:18:23 N 005:53:13 E
V D=+
DB 45:19:00 N 005:53:13 E, 45:18:23 N 005:54:00 E
DP 45:18:23 N 005:53:13 E
"""


def test_parse_coord_and_limits():
    lat, lon = parse_coord("45:18:23 N 005:53:13 E")
    assert lat == pytest.approx(45.3064, abs=1e-4)
    assert lon == pytest.approx(5.8869, abs=1e-4)
    assert parse_coord("45:30.5S 005:30.0W") == (pytest.approx(-45.5083, abs=1e-4), pytest.approx(-5.5, abs=1e-4))
    assert parse_limit("FL100").ref == "FL"
    assert parse_limit("FL100").meters == pytest.approx(3048)
    assert parse_limit("SFC").ref == "AGL"
    assert parse_limit("3000FT AMSL").meters == pytest.approx(914.4)
    assert parse_limit("1000FT AGL").ref == "AGL"
    assert parse_limit("5000M").meters == 5000
    assert parse_limit("UNL").ref == "UNL"


def test_parse_openair_shapes():
    spaces = {a.name: a for a in parse_openair(OPENAIR)}
    assert set(spaces) == {"CTR TEST", "HIGH ZONE", "FAR AWAY", "ARC ZONE"}
    assert len(spaces["CTR TEST"].points) > 30  # circle approximated
    assert len(spaces["HIGH ZONE"].points) == 4


def test_check_airspaces(flight):
    found = check_airspaces(flight, parse_openair(OPENAIR))
    names = {inf.airspace.name for inf in found}
    assert "CTR TEST" in names       # takeoff is inside the 1 NM circle
    assert "HIGH ZONE" not in names  # flight stays below FL195
    assert "FAR AWAY" not in names
    ctr = next(inf for inf in found if inf.airspace.name == "CTR TEST")
    assert ctr.start == flight.fixes[0].time
    assert not ctr.uncertain


# ---------------------------------------------------------------- exports


def test_gpx(flight):
    root = ET.fromstring(to_gpx(flight))
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    points = root.findall(".//g:trkpt", ns)
    assert len(points) == len(flight.fixes)
    assert points[0].find("g:time", ns).text == "2026-09-18T12:30:00Z"


def test_kml(flight):
    root = ET.fromstring(to_kml(flight))
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    placemarks = root.findall(".//k:Placemark", ns)
    assert len(placemarks) == 1 + len(detect_thermals(flight))


# ---------------------------------------------------------------- overlay


def test_overlay_frame(flight):
    pytest.importorskip("PIL")
    from flylog.overlay import OverlayRenderer, Telemetry

    tel = Telemetry.from_flight(flight)
    mid = tel.at(100.5)
    assert tel.alt[100] <= mid["alt"] <= tel.alt[101] or tel.alt[101] <= mid["alt"] <= tel.alt[100]
    img = OverlayRenderer(tel, 1280, 720).frame(120)
    assert img.size == (1280, 720)
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 0  # transparent background


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg non installé")
def test_overlay_video(flight, tmp_path):
    pytest.importorskip("PIL")
    from flylog.overlay import main

    out = tmp_path / "overlay.webm"
    assert main([str(EXAMPLE), str(out), "--start", "12:32:00", "--utc", "--duration", "1",
                 "--fps", "5", "--size", "640x360"]) == 0
    assert out.stat().st_size > 0


def test_overlay_outside_flight(tmp_path, capsys):
    from flylog.overlay import main

    assert main([str(EXAMPLE), str(tmp_path / "o.mov"), "--start", "08:00", "--utc"]) == 1
    assert "pas dans le vol" in capsys.readouterr().err or not shutil.which("ffmpeg")


def test_class_e_and_gliding_sectors_are_ignored_by_default(flight):
    text = """\
AC E
AY TMA
AN TMA CLASS E
AL SFC
AH FL100
V X=45:18:23 N 005:53:13 E
DC 2
AC UNC
AY R
AN R ZONE
AL SFC
AH FL100
V X=45:18:23 N 005:53:13 E
DC 2
"""
    spaces = parse_openair(text)
    assert {s.kind for s in spaces} == {"TMA", "R"}
    assert [i.airspace.name for i in check_airspaces(flight, spaces)] == ["R ZONE"]
    assert len(check_airspaces(flight, spaces, all_airspaces=True)) == 2

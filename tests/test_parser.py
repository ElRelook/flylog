from datetime import date, datetime

import pytest

from flylog import parse_igc

SAMPLE = """\
AXCT123
HFDTEDATE:180926,01
HFPLTPILOTINCHARGE:Jean Vol
HFGTYGLIDERTYPE:Ozone Rush 6
B1230004518390N00553220EA0097800990
B1230014518380S00553230WV0097000982
B2359594518380N00553230EA0097000982
B0000014518380N00553230EA0097000982
"""


def test_headers():
    flight = parse_igc(SAMPLE)
    assert flight.date == date(2026, 9, 18)
    assert flight.pilot == "Jean Vol"
    assert flight.glider == "Ozone Rush 6"


def test_fix_coordinates():
    fix = parse_igc(SAMPLE).fixes[0]
    assert fix.time == datetime(2026, 9, 18, 12, 30, 0)
    assert fix.lat == pytest.approx(45 + 18.390 / 60)
    assert fix.lon == pytest.approx(5 + 53.220 / 60)
    assert fix.pressure_alt == 978
    assert fix.alt == 990
    assert fix.valid


def test_southern_western_hemispheres_and_validity():
    fix = parse_igc(SAMPLE).fixes[1]
    assert fix.lat < 0 and fix.lon < 0
    assert not fix.valid


def test_midnight_rollover():
    fixes = parse_igc(SAMPLE).fixes
    assert fixes[3].time > fixes[2].time
    assert fixes[3].time.date() == date(2026, 9, 19)


def test_small_time_glitch_is_dropped_not_a_new_day():
    # Seen on a real Syride file: the clock jumps back 9 s mid-flight.
    igc = """\
HFDTE090526
B1236154518390N00553220EA0097800990
B1236164518390N00553220EA0097800990
B1236074518390N00553220EA0097800990
B1236174518390N00553220EA0097800990
"""
    fixes = parse_igc(igc).fixes
    assert len(fixes) == 3
    assert fixes[-1].time == datetime(2026, 5, 9, 12, 36, 17)


def test_old_date_header_format():
    assert parse_igc("HFDTE010725\n").date == date(2025, 7, 1)

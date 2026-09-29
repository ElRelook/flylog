import shutil
from pathlib import Path

import pytest

from flylog import logbook
from flylog.cli import main

EXAMPLE = Path(__file__).parent.parent / "examples" / "vol_exemple.igc"


@pytest.fixture
def syride_dir(tmp_path):
    """A fake Syride folder: one flight per day folder, plus a duplicate and a broken file."""
    src = tmp_path / "Syride" / "Parapente"
    (src / "2026-09-18").mkdir(parents=True)
    shutil.copy(EXAMPLE, src / "2026-09-18" / "flight-a.igc")
    (src / "backup").mkdir()
    shutil.copy(EXAMPLE, src / "backup" / "flight-a-copy.IGC")
    (src / "2026-09-19").mkdir()
    (src / "2026-09-19" / "empty.igc").write_text("AXXX\nHFDTE190926\n")
    return src


def test_sync_adds_each_flight_once(syride_dir, tmp_path):
    db = tmp_path / "carnet.json"
    result = logbook.sync(syride_dir, db)
    assert len(result.added) == 1
    assert result.known == 1  # the duplicate copy
    assert len(result.errors) == 1
    assert db.exists()

    entry = result.added[0]
    assert entry.date == "2026-09-18"
    assert entry.thermals == 3
    assert entry.max_alt > 1500


def test_sync_is_incremental(syride_dir, tmp_path):
    db = tmp_path / "carnet.json"
    logbook.sync(syride_dir, db)
    again = logbook.sync(syride_dir, db)
    assert again.added == []
    assert again.known == 2
    assert len(logbook.load(db)) == 1


def test_totals(syride_dir, tmp_path):
    db = tmp_path / "carnet.json"
    logbook.sync(syride_dir, db)
    t = logbook.totals(list(logbook.load(db).values()))
    assert t.flights == 1
    assert t.by_year == {"2026": (1, t.duration_s)}
    assert t.best_alt is t.longest is t.farthest


def test_cli_sync_and_carnet(syride_dir, tmp_path, capsys):
    db = str(tmp_path / "carnet.json")
    assert main(["sync", "--source", str(syride_dir), "--db", db]) == 0
    assert "1 nouveau(x) vol(s)" in capsys.readouterr().out
    assert main(["carnet", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "Carnet de vol : 1 vols" in out
    assert "18/09/2026" in out


def test_cli_carnet_empty(tmp_path):
    assert main(["carnet", "--db", str(tmp_path / "none.json")]) == 1


def test_cli_sync_missing_folder(tmp_path):
    assert main(["sync", "--source", str(tmp_path / "nope"), "--db", str(tmp_path / "c.json")]) == 1


def test_outdated_logbook_is_rebuilt(syride_dir, tmp_path):
    import json

    db = tmp_path / "carnet.json"
    logbook.sync(syride_dir, db)
    raw = json.loads(db.read_text(encoding="utf-8"))
    raw["analysis_version"] = 1
    raw["flights"][0]["duration_s"] = 999_999
    db.write_text(json.dumps(raw), encoding="utf-8")

    result = logbook.sync(syride_dir, db)
    assert result.rebuilt
    assert len(result.added) == 1
    assert list(logbook.load(db).values())[0].duration_s < 3600

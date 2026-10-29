"""Run: uv run --with pytest --with "pandas<3" pytest -q  (the 2024 engine breaks on pandas 3)"""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import export_fighters_json as ex  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "six_bouts.csv"
WEIGHTS = ROOT / "tests" / "fixtures" / "six_bouts_weights.csv"


def engine_ratings(tmp_path, monkeypatch):
    """Run UPDATEDufceloengine.py itself on the fixture and return its elo_ratings."""
    pytest.importorskip("pandas")
    shutil.copy(FIXTURE, tmp_path / "ufcfights_update.csv")
    monkeypatch.chdir(tmp_path)
    return runpy.run_path(str(ROOT / "UPDATEDufceloengine.py"))["elo_ratings"]


def test_final_ratings_match_the_engine(tmp_path, monkeypatch):
    expected = engine_ratings(tmp_path, monkeypatch)
    elo, _ = ex.replay(ex.read_fights(FIXTURE))
    assert elo == pytest.approx(expected)
    assert set(elo) == {"Ann Alpha", "Bea Beta", "Cat Gamma", "Dee Delta"}


def test_a_finish_moves_the_rating_more_than_a_decision():
    assert ex.k_factor("KO/TKO Punch") == pytest.approx(46)
    assert ex.k_factor("SUB Rear Naked Choke") == pytest.approx(46)
    assert ex.k_factor("U-DEC") == 40


def test_draw_and_no_contest_leave_ratings_unchanged():
    _, history = ex.replay(ex.read_fights(FIXTURE))
    ann = history["Ann Alpha"]
    assert [b[2] for b in ann] == ["W", "W", "D"]
    assert ann[2][3] == ann[1][3]  # the draw is the last bout of the night
    bea = history["Bea Beta"]
    assert bea[1][2] == "NC" and bea[1][3] == bea[0][3]


def test_a_fighter_with_two_bouts_is_dropped():
    doc = ex.build(ex.read_fights(FIXTURE), {})
    names = {f["name"] for f in doc["fighters"]}
    assert "Dee Delta" not in names  # two bouts
    assert {"Ann Alpha", "Bea Beta", "Cat Gamma"} <= names
    assert doc["n_fighters"] == 3


def test_ids_carry_the_first_year_so_names_from_different_eras_differ():
    ids = ex.make_ids({"José Aldo": 2008, "Jose Aldo": 2011, "Ann Alpha": 1999})
    assert ids["José Aldo"] == "jose-aldo-2008"
    assert ids["Jose Aldo"] == "jose-aldo-2011"
    assert ids["Ann Alpha"] == "ann-alpha-1999"
    clash = ex.make_ids({"José Aldo": 2008, "Jose Aldo": 2008})
    assert len(set(clash.values())) == 2


def test_output_is_json_with_the_newest_date(tmp_path):
    out = tmp_path / "fighters.json"
    ex.export(FIXTURE, [WEIGHTS], out)
    doc = json.loads(out.read_text())
    assert doc["last_event_date"] == "2001-03-03"
    assert doc["n_bouts"] == 6
    assert doc["method"] == ex.METHOD
    bea = next(f for f in doc["fighters"] if f["name"] == "Bea Beta")
    assert bea["weight_classes"] == ["Lightweight", "Welterweight"]
    assert bea["first_year"] == 1999 and bea["last_year"] == 2001
    assert bea["peak"] >= bea["current"]
    assert [b[0] for b in bea["bouts"]] == sorted(b[0] for b in bea["bouts"])
    assert all(isinstance(b[-1], int) for b in bea["bouts"])


def test_over_the_size_limit_drops_opponents_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "SIZE_LIMIT", 10)
    out = tmp_path / "fighters.json"
    ex.export(FIXTURE, [WEIGHTS], out)
    doc = json.loads(out.read_text())
    assert doc["bout_fields"] == ["date", "result", "elo_after"]
    assert all(len(b) == 3 for f in doc["fighters"] for b in f["bouts"])


def test_the_full_list_fits_under_a_megabyte(tmp_path):
    if not ex.DEFAULT_FIGHTS.exists():
        pytest.skip("no data/ufcfights.csv")
    out = tmp_path / "fighters.json"
    doc = ex.export(ex.DEFAULT_FIGHTS, ex.DEFAULT_WEIGHTS, out)
    assert out.stat().st_size <= ex.SIZE_LIMIT
    jones = next(f for f in doc["fighters"] if f["name"] == "Jon Jones")
    assert jones["peak"] == max(b[-1] for b in jones["bouts"])

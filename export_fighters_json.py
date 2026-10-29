"""Write fighters.json: every UFC fighter's Elo after each bout, for the /ufc page.

Replays the rating from UPDATEDufceloengine.py (start 1000, K 40, K x1.15 for a
KO/TKO or submission, draws and no contests leave both ratings unchanged) over a
dated fight list in the shape ufcstatswebscraper.py writes, oldest bout first.

    python3 export_fighters_json.py                      # data/ufcfights.csv -> fighters.json
    python3 export_fighters_json.py --out ../site/public/ufc/fighters.json

Standard library only, so it runs without the notebook's pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

INITIAL_ELO = 1000
BASE_K = 40
FINISH_MULTIPLIER = 1.15
MIN_BOUTS = 3
SIZE_LIMIT = 1_000_000

METHOD = (
    f"Elo from {INITIAL_ELO}, K {BASE_K}, K x{FINISH_MULTIPLIER} for a KO/TKO or "
    f"submission; draws and no contests leave both ratings unchanged; "
    f"fighters with fewer than {MIN_BOUTS} UFC bouts are left out"
)

DEFAULT_FIGHTS = HERE / "data" / "ufcfights.csv"
DEFAULT_WEIGHTS = [HERE / "data" / "weight_classes.csv", HERE / "newufcfights.csv"]


# --- the engine, as UPDATEDufceloengine.py has it -------------------------------

def expected_score(elo_a: float, elo_b: float) -> float:
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def update_elo(winner_elo: float, loser_elo: float, k: float) -> tuple[float, float]:
    expected_win = expected_score(winner_elo, loser_elo)
    return (
        round(winner_elo + k * (1 - expected_win), 2),
        round(loser_elo + k * (0 - (1 - expected_win)), 2),
    )


def k_factor(method: str) -> float:
    m = (method or "").upper()
    return BASE_K * FINISH_MULTIPLIER if ("KO" in m or "SUB" in m) else BASE_K


# --- input -----------------------------------------------------------------------

def clean(text: str) -> str:
    """The scrape leaves newlines and runs of spaces inside cells ("draw\\n\\n\\ndraw")."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalise_result(raw: str) -> str:
    """fighter_1's outcome: 'win', 'draw' or 'nc'. ufcstats repeats it ('draw draw')."""
    first = clean(raw).lower().split(" ")[0] if clean(raw) else ""
    return first if first in ("win", "draw", "nc") else "nc"


def parse_date(text: str) -> date:
    return datetime.strptime(clean(text), "%B %d, %Y").date()


def read_fights(path: Path) -> list[dict]:
    """Rows oldest first. The scrape is newest first, and within an event the main
    event comes first, so reversing the file order inside a date keeps the order the
    engine used (it reverses the whole file)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, r in enumerate(rows):
        out.append({
            "i": i,
            "event": clean(r["event"]),
            "date": parse_date(r["event_date"]),
            "f1": clean(r["fighter_1"]),
            "f2": clean(r["fighter_2"]),
            "result": normalise_result(r["result"]),
            "method": clean(r.get("method", "")),
        })
    out.sort(key=lambda r: (r["date"], -r["i"]))
    return out


def read_weights(paths: list[Path]) -> dict[tuple[str, str, str], str]:
    """(event, fighter_1, fighter_2) -> weight class. Earlier files win."""
    found: dict[tuple[str, str, str], str] = {}
    for p in paths:
        if not p.exists():
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                wc = clean(r.get("weight_class") or r.get("weight") or "")
                if not wc:
                    continue
                key = (clean(r["event"]), clean(r["fighter_1"]), clean(r["fighter_2"]))
                found.setdefault(key, wc)
    return found


# --- ids ------------------------------------------------------------------------

def slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "fighter"


def make_ids(first_years: dict[str, int]) -> dict[str, str]:
    """name -> id, the name's slug plus the year of its first UFC bout, so a name that
    comes back in another era does not collide with the first one. A slug clash
    (two spellings that fold to the same ASCII) gets a numeric suffix."""
    ids: dict[str, str] = {}
    taken: set[str] = set()
    for name in sorted(first_years, key=lambda n: (first_years[n], n)):
        base = f"{slug(name)}-{first_years[name]}"
        cand, n = base, 2
        while cand in taken:
            cand, n = f"{base}-{n}", n + 1
        taken.add(cand)
        ids[name] = cand
    return ids


# --- the replay -----------------------------------------------------------------

RESULT_CODE = {("win", True): "W", ("win", False): "L", ("draw", True): "D",
               ("draw", False): "D", ("nc", True): "NC", ("nc", False): "NC"}


def replay(fights: list[dict]) -> tuple[dict[str, float], dict[str, list]]:
    """Ratings after the last bout, and each name's bouts as
    (date, opponent name, result code, elo after, event)."""
    elo: dict[str, float] = {}
    history: dict[str, list] = {}
    for r in fights:
        f1, f2 = r["f1"], r["f2"]
        e1, e2 = elo.setdefault(f1, INITIAL_ELO), elo.setdefault(f2, INITIAL_ELO)
        if r["result"] == "win":
            n1, n2 = update_elo(e1, e2, k_factor(r["method"]))
        else:
            n1, n2 = e1, e2
        elo[f1], elo[f2] = n1, n2
        history.setdefault(f1, []).append((r["date"], f2, RESULT_CODE[(r["result"], True)], n1, r["event"]))
        history.setdefault(f2, []).append((r["date"], f1, RESULT_CODE[(r["result"], False)], n2, r["event"]))
    return elo, history


def build(fights: list[dict], weights: dict, *, generated_at: str | None = None,
          with_opponents: bool = True) -> dict:
    elo, history = replay(fights)
    first_years = {name: h[0][0].year for name, h in history.items()}
    ids = make_ids(first_years)

    classes: dict[str, list[str]] = {}
    for r in fights:
        wc = weights.get((r["event"], r["f1"], r["f2"]))
        if wc:
            for name in (r["f1"], r["f2"]):
                if wc not in classes.setdefault(name, []):
                    classes[name].append(wc)

    fighters = []
    for name, h in history.items():
        if len(h) < MIN_BOUTS:
            continue
        bouts = []
        for d, opp, res, after, _event in h:
            row = [d.isoformat(), ids[opp], res, round(after)] if with_opponents \
                else [d.isoformat(), res, round(after)]
            bouts.append(row)
        fighters.append({
            "id": ids[name],
            "name": name,
            "first_year": h[0][0].year,
            "last_year": h[-1][0].year,
            "weight_classes": classes.get(name, []),
            "peak": round(max(b[3] for b in h)),
            "current": round(elo[name]),
            "bouts": bouts,
        })
    fighters.sort(key=lambda f: (-f["peak"], f["id"]))

    # Opponents who were left out (under MIN_BOUTS) still need a name on the chart.
    kept = {f["id"] for f in fighters}
    others = {}
    if with_opponents:
        for f in fighters:
            for b in f["bouts"]:
                if b[1] not in kept:
                    others[b[1]] = None
        by_id = {v: k for k, v in ids.items()}
        others = {i: by_id[i] for i in sorted(others)}

    return {
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_event_date": fights[-1]["date"].isoformat() if fights else None,
        "n_bouts": len(fights),
        "n_fighters": len(fighters),
        "method": METHOD,
        "bout_fields": ["date", "opponent_id", "result", "elo_after"] if with_opponents
        else ["date", "result", "elo_after"],
        "other_names": others,
        "fighters": fighters,
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def export(fights_path: Path, weight_paths: list[Path], out: Path) -> dict:
    fights = read_fights(fights_path)
    weights = read_weights(weight_paths)
    doc = build(fights, weights)
    text = dumps(doc)
    if len(text.encode()) > SIZE_LIMIT:
        doc = build(fights, weights, generated_at=doc["generated_at"], with_opponents=False)
        text = dumps(doc)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fights", type=Path, default=DEFAULT_FIGHTS,
                    help="dated fight list, as ufcstatswebscraper.py writes it")
    ap.add_argument("--weights", type=Path, nargs="*", default=DEFAULT_WEIGHTS,
                    help="CSVs with a weight_class or weight column, first match wins")
    ap.add_argument("--out", type=Path, default=HERE / "fighters.json")
    args = ap.parse_args(argv)
    doc = export(args.fights, args.weights, args.out)
    size = args.out.stat().st_size
    print(f"{args.out}: {size:,} bytes, {doc['n_fighters']} fighters, "
          f"{doc['n_bouts']} bouts through {doc['last_event_date']}")
    for f in doc["fighters"][:3]:
        print(f"  {f['name']}: peak {f['peak']}")
    return 0 if size <= SIZE_LIMIT else 1


if __name__ == "__main__":
    sys.exit(main())

A common question within the mixed martial arts world is who is the greatest fighter of all time? I wanted to offer a solution to solve that. I first devised a web scraper that scrapes ufcstats.com. This would leave me with every result in UFC history, starting with the first ever fight between Gordon Gordeau and Taylor Wily, and currently ending with the most recent of Sean O'Malley and Merab Dvalishvili. I then took the data to create an elo engine ranking system in python. The code follows how normal chess elo engines work, following the common elo formula.

This repository contains all code for the project, as well as the csv files from webscraping, and then the final list of the elo's starting with the highest. 

To find your favorite fighter go to the current_fighters_elo.csv (or fighter_peak_elo.csv) file and you can search!

Youtube Video Link:
https://www.youtube.com/watch?v=PLwhzlyjEgU

## fighters.json, for mcgrathtrading.com/ufc

`export_fighters_json.py` replays the same Elo as `UPDATEDufceloengine.py` (start 1000, K 40, K x1.15 for a KO/TKO or submission; draws and no contests change nothing) over a dated fight list, and writes every fighter's rating after each bout to one `fighters.json` (fighters with fewer than 3 bouts left out, kept under 1 MB). The site at mcgrathtrading.com/ufc reads it to chart a fighter and list the all-time, per-era and per-weight-class top tens.

Inputs: `data/ufcfights.csv` (the dated list in the shape `ufcstatswebscraper.py` writes, bouts through 2025-09-13) and, for weight classes, `data/weight_classes.csv` then `newufcfights.csv`. No pandas needed:

```bash
python3 export_fighters_json.py --out ../tommcgrath-personal-website/public/ufc/fighters.json
```

To refresh: run `ufcstatswebscraper.py`, move its `ufcfights.csv` to `data/ufcfights.csv`, run the exporter as above, and open a PR on the site.

Tests (they run `UPDATEDufceloengine.py` itself on a six-bout fixture and check the exporter lands on the same ratings):

```bash
uv run --with pytest --with "pandas<3" pytest -q
```


"""
dev/build_cz_regional_prices.py — rebuild engine/cz_regional_prices.csv, the
Czech sale-price benchmark engine/regional_prices_cz loads.

Source: ČSÚ's open dataset CEN0402, "Průměrné kupní ceny nemovitostí – zdroj
dat ČÚZK (od 2019)": the average purchase price per m² of flats (Byty
[Kč/m2]) by kraj and okres, for each year and each three-year period, from
the cadastre's records of each transfer with a stated price. ČSÚ drops
improbable extremes and takes the plain mean of the rest; it publishes no
figure from fewer than 3 records.

    https://data.csu.gov.cz/opendata/sady/CEN0402/distribuce/csv
    https://data.csu.gov.cz/datastat/info/SADA/CEN0402

Every row comes from that one dataset and one period (the latest year by
default), so no listing is judged against two measures. Prague is a kraj in
the dataset and its own okres in the app's table, so its kraj figure is
written for both. ČSÚ has no figure for Prague's or Brno's own districts.

Run from sovereign_final/:

    python3 dev/build_cz_regional_prices.py                  # downloads it
    python3 dev/build_cz_regional_prices.py --csv CEN0402.csv [--period 2025]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

URL = "https://data.csu.gov.cz/opendata/sady/CEN0402/distribuce/csv"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "engine", "cz_regional_prices.csv")
FLATS = "Byty [Kč/m2]"
ALL_SIZES = "Celkem"
PRAHA = "Hlavní město Praha"


def read_rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def latest_year(rows: list[dict]) -> str:
    years = {r["Roční a 3-letá období"] for r in rows if r["Druh nemovitosti"] == FLATS}
    return max(y for y in years if y.isdigit())


def build(rows: list[dict], period: str, checked: str, digest: str) -> list[dict]:
    """The CSV rows engine/regional_prices_cz.load_medians reads: one per
    kraj and okres with a figure for `period`."""
    from engine.regional_prices_cz import KRAJ_NAMES, OKRES_KRAJ
    source = f"ČSÚ CEN0402, průměrná kupní cena bytů (data ČÚZK), staženo {checked}"
    print(f"CEN0402.csv sha256 {digest}")
    out = []
    for r in rows:
        if (r["Druh nemovitosti"] != FLATS or r["Počet obyvatel obce"] != ALL_SIZES
                or r["Roční a 3-letá období"] != period or not r["Hodnota"]):
            continue
        kraj, okres = r["Území-Kraj"].strip(), r["Území-Okres"].strip()
        value = r["Hodnota"].strip()
        if okres:
            if okres not in OKRES_KRAJ:
                raise SystemExit(f"okres {okres!r} is not in OKRES_KRAJ")
            out.append({"level": "okres", "name": okres, "median_czk_m2": value,
                        "period": period, "source": source})
        elif kraj:
            if kraj not in KRAJ_NAMES.values():
                raise SystemExit(f"kraj {kraj!r} is not in KRAJ_NAMES")
            out.append({"level": "kraj", "name": kraj, "median_czk_m2": value,
                        "period": period, "source": source})
            if kraj == PRAHA:                       # Prague is its own okres too
                out.append({"level": "okres", "name": PRAHA, "median_czk_m2": value,
                            "period": period, "source": source})
    okresy = {r["name"] for r in out if r["level"] == "okres"}
    missing = set(OKRES_KRAJ) - okresy
    if missing:
        print(f"⚠ no {period} figure for: {', '.join(sorted(missing))}", file=sys.stderr)
    return sorted(out, key=lambda r: (r["level"] != "kraj", r["name"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="a downloaded CEN0402.csv (default: download it)")
    ap.add_argument("--period", help="a year or a three-year period (default: the latest year)")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    if args.csv:
        raw = open(args.csv, "rb").read()
    else:
        with urllib.request.urlopen(URL, timeout=60) as resp:
            raw = resp.read()
    rows = read_rows(raw.decode("utf-8-sig"))
    period = args.period or latest_year(rows)
    out = build(rows, period, date.today().isoformat(), hashlib.sha256(raw).hexdigest())
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "name", "median_czk_m2", "period", "source"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"✅ {args.out}: {sum(r['level'] == 'kraj' for r in out)} kraje, "
          f"{sum(r['level'] == 'okres' for r in out)} okresy ({period})")


if __name__ == "__main__":
    main()

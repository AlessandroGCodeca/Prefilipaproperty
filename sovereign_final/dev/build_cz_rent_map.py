"""
dev/build_cz_rent_map.py — rebuild engine/rent_cz_mf.json from the Ministry
of Finance's rent map (Cenová mapa nájemného, vyhláška 456/2024 Sb.).

The MF publishes the map every quarter, within 45 days of its end, as an XLSX
on https://mf.gov.cz/cs/rozpoctova-politika/podpora-projektoveho-rizeni/
cenova-mapa/cenova-mapa-infografika. For each municipality (and, in Prague
and the ORP towns, each cadastral area) and each size category it gives the
rent of a "reference flat": unfurnished, over five years old, without a
balcony, terrace, garage or lift, energies and services not included — the
bare rent engine.financial models, before its own balcony / parking /
furnished premiums.

What goes into the JSON, per municipality: the reference flat's rent for size
category 2 (2+kk, 2+1 — the typical investor flat), in Kč/m²/month; for a
municipality split into cadastral areas, the median of theirs. Municipality
names that two or more municipalities share are left out: a listing's
"Nová Ves" can't say which one it is. engine/rent_cz uses a figure only
where the Deloitte Rent Index (RENT_PER_M2_CZ) has none.

    pip install openpyxl          # this script only; the app reads the JSON
    python dev/build_cz_rent_map.py                      # download the newest
    python dev/build_cz_rent_map.py 2026-08-15_Cenova-mapa.xlsx
"""

import json
import os
import re
import statistics
import sys
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "engine", "rent_cz_mf.json")
PAGE = ("https://mf.gov.cz/cs/rozpoctova-politika/podpora-projektoveho-rizeni/"
        "cenova-mapa/cenova-mapa-infografika")
SHEET = "Cenové mapy nájemného"
# The sheet has the four size categories side by side, each block starting
# with its "VK" column: VK1 at column 4, VK2 at 14, VK3 at 24, VK4 at 34.
# Size category 2 (2+kk, 2+1): its rent and its data coverage.
VK2_RENT, VK2_COVERAGE = 15, 22
KRAJ, KU, OBEC = 0, 1, 2


def newest_xlsx_url() -> str:
    with urllib.request.urlopen(urllib.request.Request(
            PAGE, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    files = sorted(set(re.findall(r'href="(/assets/attachments/[^"]*Cenova-mapa[^"]*\.xlsx)"',
                                  html)))
    if not files:
        sys.exit(f"No rent-map XLSX linked from {PAGE}")
    return "https://mf.gov.cz" + files[-1]   # named by date: the last is newest


def build(path: str, published: str) -> dict:
    """{town name: [Kč/m², data coverage]} and the source note.

    A row is a municipality (no cadastral area), or one cadastral area of an
    ORP town or Prague: a town is its (kraj, obec) rows, by their median.
    Two municipalities of one name in one kraj can't be told apart: left out.
    Across kraje, a name keeps the municipality with the clearly best data
    coverage — "Kladno" is the city (5), not the village in Pardubický kraj
    (1); a tie is left out."""
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True)[SHEET]
    rows = ws.iter_rows(values_only=True)
    head = next(rows)
    assert (head[VK2_RENT - 1], head[VK2_RENT], head[VK2_COVERAGE]) == (
        "VK", "Nájemné referenčního bytu za m² v Kč za 1 měsíc", "Datová pokrytost"), \
        "The sheet's layout changed: check the VK2 columns"
    units = defaultdict(lambda: {"rents": [], "coverage": 0, "whole": 0})
    for row in rows:
        if not row[OBEC] or row[VK2_RENT] in (None, ""):
            continue
        u = units[(row[KRAJ], row[OBEC].strip())]
        u["rents"].append(float(row[VK2_RENT]))
        u["coverage"] = max(u["coverage"], int(row[VK2_COVERAGE] or 0))
        u["whole"] += row[KU] is None          # a whole municipality's row
    by_name = defaultdict(list)
    left_out = 0
    for (_kraj, obec), u in units.items():
        if u["whole"] > 1:                      # two of that name in one kraj
            left_out += 1
            continue
        by_name[obec.lower()].append(u)
    out = {}
    for name, cands in sorted(by_name.items()):
        cands.sort(key=lambda u: u["coverage"], reverse=True)
        if len(cands) > 1 and cands[0]["coverage"] == cands[1]["coverage"]:
            left_out += len(cands)
            continue
        best = cands[0]
        out[name] = [round(statistics.median(best["rents"])), best["coverage"]]
    return {
        "source": (f"Ministerstvo financí ČR, Cenová mapa nájemného (vyhláška 456/2024 Sb.), "
                   f"{published}: the reference flat's rent (unfurnished, over 5 years old, "
                   f"no balcony, garage or lift; energies not included), size category 2 "
                   f"(2+kk, 2+1), Kč/m²/month; a town split into cadastral areas by their "
                   f"median. {left_out} municipalities whose name can't be told apart from "
                   f"another's are left out."),
        "published": published,
        "columns": ["kc_per_m2", "data_coverage_1_to_5"],
        "rents": out,
    }


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        url = newest_xlsx_url()
        path = os.path.join(os.getcwd(), url.rsplit("/", 1)[-1])
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, path)
    published = (re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path)) or [None, "?"])[1]
    data = build(path, published)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"Wrote {len(data['rents'])} municipalities to {OUT}")


if __name__ == "__main__":
    main()

"""
dev/build_cz_rent_map.py — rebuild data/cz_rent_map.csv and
data/cz_rent_map_surcharges.csv from the Ministry of Finance's rent map.

engine/rent_map_cz reads them: the Czech baseline rent for a place the
Deloitte Rent Index doesn't name. MF publishes the map each quarter (within
45 days of the quarter's end) as an XLSX linked from

    https://mf.gov.cz/cs/rozpoctova-politika/podpora-projektoveho-rizeni/cenova-mapa/cenova-mapa-infografika

e.g. https://mf.gov.cz/assets/attachments/2026-08-15_Cenova-mapa.xlsx. Two
sheets are read:

  * "Cenové mapy nájemného": one row per obec, or per katastrální území of an
    ORP town and of Prague — Kraj, Katastrální území, Obec, Kód obce (the KÚ's
    code on a KÚ row), then four blocks, one per size category (VK 1–4): the
    reference flat's rent, the 95 % interval, the new-build rent, min, max,
    median (Kč/m² a month) and the data coverage (1–5).
    → data/cz_rent_map.csv, one row per place and size category.
  * "Základní informace": what a balcony, terrace, furniture, a garage and a
    lift add to the reference flat's rent, Kč/m² by size category.
    → data/cz_rent_map_surcharges.csv.

The headers are checked against the layout above: a changed file stops the
script rather than shifting a column.

Run from sovereign_final/ with the downloaded file (or its URL):

    python3 dev/build_cz_rent_map.py 2026-08-15_Cenova-mapa.xlsx
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.rent_map_cz import PLACES_COLUMNS, SURCHARGE_COLUMNS  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data")
MAP_SHEET, INFO_SHEET = "Cenové mapy nájemného", "Základní informace"
# Each block's header cells, in order, as they start (folded comparisons
# would hide a renamed column, so these are MF's own words).
BLOCK = ("VK", "Nájemné referenčního bytu", "Dolní interval", "Horní interval",
         "Nájemné referenčního bytu novostavby", "Minimální hodnota", "Maximální hodnota",
         "Mediánová hodnota", "Datová pokrytost")
BLOCK_KEYS = ("vk", "ref", "low", "high", "new_build", "min", "max", "median", "coverage")
LEAD = ("Kraj", "Katastrální území", "Obec", "Kód obce")
FEATURE_WORDS = {"balkón": "balcony", "terasa": "terrace", "vybavennost": "furnished",
                 "garáž": "garage", "výtah": "lift"}


def _cell(v) -> str:
    return "" if v is None else str(v).strip()


def _blocks(header: tuple) -> list[int]:
    """The column each size category's block starts at, checked."""
    head = [_cell(h) for h in header]
    if tuple(head[:4]) != LEAD:
        raise SystemExit(f"{MAP_SHEET}: unexpected first columns {head[:4]}")
    starts = [i for i, h in enumerate(head) if h == "VK"]
    if len(starts) != 4:
        raise SystemExit(f"{MAP_SHEET}: expected 4 size-category blocks, found {len(starts)}")
    for s in starts:
        got = head[s:s + len(BLOCK)]
        if len(got) < len(BLOCK) or not all(g.startswith(w) for g, w in zip(got, BLOCK)):
            raise SystemExit(f"{MAP_SHEET}: block at column {s} reads {got}")
    return starts


def places(ws) -> list[dict]:
    rows = ws.iter_rows(values_only=True)
    starts = _blocks(next(rows))
    out = []
    for r in rows:
        if not r or not _cell(r[0]):
            continue
        kraj, ku, obec, code = (_cell(x) for x in r[:4])
        for s in starts:
            vals = dict(zip(BLOCK_KEYS, r[s:s + len(BLOCK)]))
            if vals["ref"] is None:
                continue
            out.append({"kraj": kraj, "obec": obec, "code": code, "ku": ku,
                        **{k: _cell(vals[k]) for k in BLOCK_KEYS}})
    return out


def release_info(ws, source_name: str) -> str:
    """"2026-08-15 (ID 26.15.08.001; data 1.7.2021–30.6.2026)" from the file
    name and the info sheet's text."""
    text = " ".join(_cell(c) for row in ws.iter_rows(values_only=True) for c in row if c)
    parts = []
    m = re.search(r"ID:\s*([\d.]+)", text)
    if m:
        parts.append(f"ID {m.group(1)}")
    m = re.search(r"od\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+do\s+(\d{1,2}\.\d{1,2}\.\d{4})", text)
    if m:
        parts.append(f"data {m.group(1)}–{m.group(2)}")
    d = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(source_name))
    head = d.group(1) if d else os.path.basename(source_name)
    return f"{head} ({'; '.join(parts)})" if parts else head


def surcharges(ws, release: str) -> list[dict]:
    """The reference flat's (not the new build's) surcharge table."""
    # The info sheet's tables don't all start in column A: each row from its
    # first filled cell.
    rows = [tuple(r[next((j for j, c in enumerate(r) if _cell(c)), len(r)):])
            for r in ws.iter_rows(values_only=True)]
    for i, r in enumerate(rows):
        title = _cell(r[0]) if r else ""
        if title.startswith("Přehled cen cenotvorných parametrů") and "novostavb" not in title:
            break
    else:
        raise SystemExit(f"{INFO_SHEET}: no surcharge table for the reference flat")
    head = [_cell(h).lower() for h in rows[i + 1]]
    cols = {}
    for j, h in enumerate(head):
        for word, key in FEATURE_WORDS.items():
            if f'"{word}"' in h:
                cols[key] = j
    if set(cols) != set(FEATURE_WORDS.values()):
        raise SystemExit(f"{INFO_SHEET}: surcharge columns read {head}")
    out = []
    for r in rows[i + 2:i + 6]:
        m = re.fullmatch(r"VK\s*([1-4])", _cell(r[0]))
        if not m:
            raise SystemExit(f"{INFO_SHEET}: surcharge row reads {r}")
        out.append({"vk": m.group(1), **{k: _cell(r[j]) for k, j in cols.items()},
                    "release": release})
    return out


def _write(path: str, columns: tuple, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def _fetch(url: str) -> str:
    import requests
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    fd, path = tempfile.mkstemp(suffix="_" + os.path.basename(url))
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("xlsx", help="MF's Cenova-mapa.xlsx, or its https:// URL")
    ap.add_argument("--out-dir", default=OUT_DIR)
    a = ap.parse_args(argv)
    import openpyxl
    path = _fetch(a.xlsx) if a.xlsx.startswith(("http://", "https://")) else a.xlsx
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    release = release_info(wb[INFO_SHEET], a.xlsx)
    rows = places(wb[MAP_SHEET])
    sur = surcharges(wb[INFO_SHEET], release)
    os.makedirs(a.out_dir, exist_ok=True)
    _write(os.path.join(a.out_dir, "cz_rent_map.csv"), PLACES_COLUMNS, rows)
    _write(os.path.join(a.out_dir, "cz_rent_map_surcharges.csv"), SURCHARGE_COLUMNS, sur)
    n_places = len({r["code"] for r in rows})
    print(f"{n_places} places, {len(rows)} rows → {a.out_dir}/cz_rent_map.csv; "
          f"surcharges for VK {', '.join(r['vk'] for r in sur)}; release {release}")


if __name__ == "__main__":
    main()

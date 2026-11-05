"""
dev/build_cz_property_tax_data.py — rebuild engine/property_tax_cz_data.json.

engine/property_tax_cz reads the rates from the law and each city's ordinance;
this script supplies the geography and the populations they apply to, from
official downloads:

  * RÚIAN address places (ČÚZK, monthly), one CSV per municipality:
      https://vdp.cuzk.gov.cz/vymenny_format/csv/<YYYYMMDD>_OB_ADR_csv.zip
    → which Prague city parts (městské části) each old district ("Praha 1"–
      "Praha 10", obvod Prahy) and each quarter (část obce) covers, and which
      Ostrava district (městský obvod) each Ostrava quarter lies in.
  * RÚIAN full data (ČÚZK) for each city that rates flats by cadastral area:
      https://vdp.cuzk.gov.cz/vymenny_format/soucasna/<YYYYMMDD>_OB_<code>_UKSH.xml.zip
    → which cadastral areas each quarter's flats stand in (buildings' flats
      counted through their parcel).
  * Population of municipalities (ČSÚ, 1 January of the year before the tax
    year — the figure the RUD decree in force on 1 January carries, § 12f):
      https://csu.gov.cz/produkty/pocet-obyvatel-v-obcich  (table 3, .xlsx)

A place that holds under SHARE_MIN of a district's or quarter's addresses
(flats, for cadastral areas) is left out, so a few stray addresses across a
boundary don't set the rate.

Run from sovereign_final/ after downloading the files:

    python3 dev/build_cz_property_tax_data.py --adr 20261031_OB_ADR_csv.zip \
        --vfr 20261031_OB_554791_UKSH.xml.zip [--vfr ...] --population 1300722503.xlsx
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

SHARE_MIN = 0.10
PRAHA, OSTRAVA = "554782", "554821"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "engine", "property_tax_cz_data.json")


def _keep(counter: collections.Counter) -> list[str]:
    """The places holding at least SHARE_MIN of the total, largest first."""
    total = sum(counter.values())
    return [k for k, n in counter.most_common() if total and n / total >= SHARE_MIN]


def _adr_rows(z: zipfile.ZipFile, code: str) -> list[dict]:
    name = next(n for n in z.namelist() if f"_OB_{code}_" in n)
    return list(csv.DictReader(io.StringIO(z.read(name).decode("cp1250")), delimiter=";"))


def _praha_part(name: str) -> str:
    """RÚIAN's "Praha-Kunratice" is the engine's "Kunratice"; "Praha 4" stays."""
    return name[len("Praha-"):] if name.startswith("Praha-") else name


def addresses(path: str) -> dict:
    z = zipfile.ZipFile(path)
    old, quarters = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for r in _adr_rows(z, PRAHA):
        part = _praha_part(r["Název MOMC"])
        old[r["Název obvodu Prahy"]][part] += 1
        quarters[r["Název části obce"]][part] += 1
    ostrava = collections.defaultdict(collections.Counter)
    for r in _adr_rows(z, OSTRAVA):
        ostrava[r["Název části obce"]][r["Název MOMC"]] += 1
    return {"praha_old_districts": {k: _keep(v) for k, v in sorted(old.items())},
            "praha_quarters": {k: _keep(v) for k, v in sorted(quarters.items())},
            "ostrava_quarters": {k: _keep(v) for k, v in sorted(ostrava.items())}}


def _local(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _code(el):
    c = _child(el, "Kod")
    return c.text if c is not None else None


def cadastral_quarters(path: str) -> tuple[str, dict]:
    """(city, {quarter: [cadastral areas holding its flats]})."""
    z = zipfile.ZipFile(path)
    buildings, parcel_area, quarter_name, area_name, city = [], {}, {}, {}, None
    with z.open(z.namelist()[0]) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            t = _local(el.tag)
            if t == "StavebniObjekt" and _child(el, "IdentifikacniParcela") is not None:
                quarter, parcel = _child(el, "CastObce"), _child(_child(el, "IdentifikacniParcela"), "Id")
                flats = _child(el, "PocetBytu")
                buildings.append((_code(quarter) if quarter is not None else None,
                                  parcel.text if parcel is not None else None,
                                  int(flats.text) if flats is not None and flats.text else 0))
                el.clear()
            elif t == "Parcela" and _child(el, "Id") is not None and _child(el, "KatastralniUzemi") is not None:
                parcel_area[_child(el, "Id").text] = _code(_child(el, "KatastralniUzemi"))
                el.clear()
            elif t == "CastObce" and _child(el, "Nazev") is not None:
                quarter_name[_code(el)] = _child(el, "Nazev").text
                el.clear()
            elif t == "KatastralniUzemi" and _child(el, "Nazev") is not None:
                area_name[_code(el)] = _child(el, "Nazev").text
                el.clear()
            elif t == "Obec" and _child(el, "Nazev") is not None:
                city = _child(el, "Nazev").text
    flats_by = collections.defaultdict(collections.Counter)
    for quarter, parcel, flats in buildings:
        if quarter and parcel in parcel_area and flats:
            flats_by[quarter_name.get(quarter, quarter)][area_name.get(parcel_area[parcel])] += flats
    return city, {k: _keep(v) for k, v in sorted(flats_by.items())}


def municipalities(path: str) -> list[list]:
    """[[name, okres, population], …] from ČSÚ's table 3; Prague's okres is
    "Hlavní město Praha", as engine.regional_prices_cz names it."""
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    out, okres = [], None
    for row in ws.iter_rows(values_only=True):
        first, code, name, pop = (list(row) + [None] * 4)[:4]
        if isinstance(first, str) and first.startswith("Okres "):
            okres = first[len("Okres "):].strip()
        elif isinstance(code, int) and isinstance(name, str) and isinstance(pop, (int, float)):
            out.append([name.strip(), "Hlavní město Praha" if first == "CZ0100" else okres, int(pop)])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--adr", required=True, help="RÚIAN address-place CSV export (.zip)")
    ap.add_argument("--vfr", action="append", default=[], help="RÚIAN full data of a city (.xml.zip)")
    ap.add_argument("--population", required=True, help="ČSÚ population of municipalities (.xlsx)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    data = {"sources": {
        "addresses": os.path.basename(a.adr),
        "cadastral": [os.path.basename(p) for p in a.vfr],
        "population": os.path.basename(a.population),
        "share_min": SHARE_MIN}}
    data.update(addresses(a.adr))
    data["city_quarters"] = {}
    for path in a.vfr:
        city, quarters = cadastral_quarters(path)
        data["city_quarters"][city] = quarters
    data["municipalities"] = municipalities(a.population)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"wrote {a.out}: {len(data['municipalities'])} municipalities, "
          f"{len(data['praha_quarters'])} Prague quarters, {len(data['city_quarters'])} cities", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

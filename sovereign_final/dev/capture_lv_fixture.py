"""
dev/capture_lv_fixture.py — turn a real LV into an anonymised test fixture.

modules/lv_screen and the part C locator were written without live LV reports
to check against (the cadastre geo-blocks many foreign IPs). Every real LV you
capture here becomes a regression test in tests/test_lv_tiers.py
(test_fixture_lv), so the screen is checked against what the cadastre
actually prints.

Run from sovereign_final/, from a Slovak IP:

    # fetch an LV straight from the cadastre
    python3 dev/capture_lv_fixture.py --lv 4321 --area Petržalka --name petrzalka_bank_lien
    # or anonymise an LV text you already saved (e.g. by dev/lv_known_flat.py)
    python3 dev/capture_lv_fixture.py --file logs/lv_4321.txt --name petrzalka_bank_lien

Add --redact "Novák,Hlavná 12,Kováčová" with every name and street address on
the LV. Birth numbers (rodné čísla), birth dates and IČO-free personal lines
are blanked automatically; names cannot be found reliably, so they are yours to
list. It writes:

    tests/fixtures/lv/<name>.txt            the anonymised text
    tests/fixtures/lv/<name>.expected.json  what the screen says today

READ BOTH before committing. Fix the .expected.json to what the výpis really
shows — the point is to catch the screen being wrong, so a verdict copied from
the screen proves nothing until you have checked it against the paper.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tests", "fixtures", "lv")

# Rodné číslo (YYMMDD/XXXX), "nar. 1.1.1970" / "dátum narodenia 01.01.1970".
_RODNE_CISLO = re.compile(r"\b\d{6}\s*/\s*\d{3,4}\b")
_BIRTH_DATE = re.compile(r"(?i)(nar\.?|narodenia:?)\s*\d{1,2}\.\s*\d{1,2}\.\s*\d{4}")


def anonymise(text: str, redact: list[str]) -> str:
    text = _RODNE_CISLO.sub("[RČ]", text)
    text = _BIRTH_DATE.sub(lambda m: f"{m.group(1)} [dátum]", text)
    for i, needle in enumerate(n.strip() for n in redact if n.strip()):
        text = re.sub(re.escape(needle), f"[OSOBA{i + 1}]", text, flags=re.I)
    return text


def expected_from_screen(text: str) -> dict:
    from modules.debt_bot import _parse_lv
    from modules.lv_screen import part_c_start
    res = _parse_lv(text)
    out = {
        "status": res["status"],
        "flags": sorted({e["flag"] for e in res["entries"] if e["blocking"]}),
        "soft": sorted({e["flag"] for e in res["entries"]
                        if e.get("tier") == "soft" and not e["blocking"]}),
        "_checked_against_the_vypis": False,
    }
    if part_c_start(text) is None:
        out["no_part_c"] = True
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--lv", help="LV number to fetch (needs --area)")
    src.add_argument("--file", help="an LV text already saved")
    ap.add_argument("--area", help="katastrálne územie (name or code)")
    ap.add_argument("--name", required=True, help="fixture name, e.g. nitra_private_lien")
    ap.add_argument("--redact", default="", help="comma-separated names/addresses to blank")
    a = ap.parse_args()

    if a.lv:
        if not a.area:
            ap.error("--lv needs --area")
        from kataster_scraper import enrich_lv
        res = enrich_lv(a.area, a.lv)
        if res["status"] != "OK" or not res.get("lv_text"):
            sys.exit(f"LV lookup {res['status']}: {res['detail']}")
        text = res["lv_text"]
    else:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()

    text = anonymise(text, a.redact.split(","))
    os.makedirs(FIXTURES, exist_ok=True)
    base = os.path.join(FIXTURES, re.sub(r"[^a-z0-9_]+", "_", a.name.lower()))
    with open(base + ".txt", "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(base + ".expected.json", "w", encoding="utf-8") as fh:
        json.dump(expected_from_screen(text), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wrote {base}.txt and {base}.expected.json — read both, check the "
          f"verdict against the výpis, set _checked_against_the_vypis to true.")


if __name__ == "__main__":
    main()

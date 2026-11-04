"""
engine/property_tax_cz.py — daň z nemovitých věcí on a Czech flat.

A flat (zdanitelná jednotka, group "ostatní zdanitelné jednotky") is taxed on
its floor area, not its value (zákon 338/1992 Sb., as amended by the 2024
consolidation package):

    tax = floor area × 1.22 × 3.50 Kč × the municipality's size coefficient
          × its local coefficient × the inflation coefficient

The size coefficient follows the municipality's population (§ 11 odst. 4:
1.0 / 1.4 / 1.6 / 2.0 / 2.5 / 3.5, every statutory city and four spa towns
3.5, Prague 4.5; an ordinance may raise it a step in chosen areas); the local
coefficient (0.5–5.0, § 12) is set by ordinance, 1.0 where there is none.

🏛️ UPDATE TAX RATES reads both for every Czech municipality from the official
sources (modules/tax_rates_cz) into the property_tax_cz table, and this
module charges them: by city part or cadastral area where an ordinance sets
them so (Praha 3 pays more than Praha 2), the municipality's highest where
the listing names none. Until that has run, or for a place it doesn't know,
every place outside Prague is taxed at 3.5 — the highest coefficient outside
Prague, which may overstate, never understate, the tax — and the local
coefficient is 1.0 unless CZ_PROPERTY_TAX_LOCAL_COEF says otherwise.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

# Kč per m² for a flat, after the 2024 consolidation package (§ 11 odst. 1 j).
RATE_PER_M2 = 3.50
# The flat's floor area is grossed up for its share of the common parts.
UNIT_COEFFICIENT = 1.22
# Set by the Ministry of Finance each year; 1.0 for 2026.
INFLATION_COEFFICIENT = 1.0
# Population bands → coefficient (upper bound of the band, coefficient).
SIZE_COEFFICIENTS = ((1_000, 1.0), (6_000, 1.4), (10_000, 1.6), (25_000, 2.0),
                     (50_000, 2.5), (None, 3.5))
PRAGUE_COEFFICIENT = 4.5
# The coefficient for a place whose population isn't known here.
UNKNOWN_PLACE_COEFFICIENT = 3.5
LOCAL_COEFFICIENT = float(os.getenv("CZ_PROPERTY_TAX_LOCAL_COEF", "1.0") or 1.0)

SOURCE = {
    "source": ("zákon 338/1992 Sb. o dani z nemovitých věcí as in force in 2026 (read from "
               "zakonyprolidi.cz): 3.50 Kč/m² for a flat (§ 11 odst. 1 j), × 1.22, size "
               "coefficients 1.0–3.5 by population and 4.5 for Prague (§ 11 odst. 4), raised a "
               "step by ordinance (§ 11 odst. 5), local coefficient 0.5–5.0 (§ 12), the "
               "population of the decree in force on 1 January (§ 12f), ordinances in force by "
               "§ 16a; inflation coefficient 1.0 for 2026. Per municipality: 🏛️ UPDATE TAX "
               "RATES, from sbirkapp.gov.cz, the Czech Statistical Office and ARES. Without it, "
               "3.5 outside Prague and local 1.0 (UNVERIFIED)."),
    "checked": "2026-11-03 (zakonyprolidi.cz, sbirkapp.gov.cz)",
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def size_coefficient(district: str) -> float:
    """Prague's 4.5, or the 3.5 upper bound for anywhere else (see the
    module docstring) — the coefficient used without stored data."""
    if "praha" in _fold(district) or "prague" in _fold(district):
        return PRAGUE_COEFFICIENT
    return UNKNOWN_PLACE_COEFFICIENT


# ── Coefficients read for every municipality (modules/tax_rates_cz) ──────────
_stored: dict | None = None
# A municipality's name counts only as a whole name, and not as its okres
# around it: "Brno-venkov", "Praha-východ", "Plzeň-jih" are other places.
_TAIL = r"(?![a-z0-9])(?!\s*-\s*(?:venkov|jih|sever|vychod|zapad)\b)"


def reload() -> None:
    """Forget the stored coefficients: the next lookup reads them again."""
    global _stored
    _stored = None


def _load() -> dict:
    """{"places": {code: {"name", "years": {year: (size, local, sources)}}},
    "names": [(folded name, code)] longest first, unique names only}."""
    try:
        import database
        conn = database.get_conn()
    except Exception:
        return {}
    try:
        if not database._has_table(conn, "property_tax_cz"):
            return {}
        rows = conn.execute("SELECT code, tax_year, name, okres, size, local, sources "
                            "FROM property_tax_cz").fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    places: dict[str, dict] = {}
    for r in rows:
        p = places.setdefault(r["code"], {"name": r["name"], "okres": r["okres"] or "",
                                          "years": {}})
        p["years"][r["tax_year"]] = (json.loads(r["size"]), json.loads(r["local"]),
                                     json.loads(r["sources"] or "[]"))
    count: dict[str, int] = {}
    for p in places.values():
        count[_fold(p["name"])] = count.get(_fold(p["name"]), 0) + 1
    # (name, district or "", code), longest name first. A name several
    # municipalities share (Lhota, 25 of them) counts only with its district
    # named beside it.
    names = sorted(((_fold(p["name"]), _fold(p["okres"]) if count[_fold(p["name"])] > 1 else "", code)
                    for code, p in places.items()), key=lambda t: -len(t[0]))
    return {"places": places, "names": names}


def stored() -> dict:
    global _stored
    if _stored is None:
        _stored = _load()
    return _stored


def _year() -> int:
    try:
        from config import TAX_YEAR
        return int(TAX_YEAR)
    except Exception:
        from datetime import date
        return date.today().year


def coefficients(district: str, year: int | None = None) -> tuple[float, float, str]:
    """(size coefficient, local coefficient, where they come from) for a flat
    in `district` in tax year `year` (default config.TAX_YEAR)."""
    year = year or _year()
    data = stored()
    key = _fold(district)
    if data and key:
        code = next((c for n, okres, c in data["names"]
                     if re.search(rf"(?<![a-z0-9]){re.escape(n)}{_TAIL}", key)
                     and (not okres or okres in key)), None)
        place = data["places"].get(code) if code else None
        if place:
            have = [y for y in place["years"] if y <= year] or list(place["years"])
            size, local, sources = place["years"][max(have)]
            areas = sorted(set(size) | set(local), key=len, reverse=True)
            area = next((a for a in areas if a and re.search(
                rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", key)), None)
            if area:
                s, lc = size.get(area, size[""]), local.get(area, local[""])
                where = f"{place['name']}, {area}"
            elif (len(set(size.values())) > 1 or len(set(local.values())) > 1) and any(
                    a.startswith(_fold(place["name"])) for a in areas if a):
                # Rated by city part ("praha 3", "praha-kolovraty") and none
                # named: its highest, which may overstate, never understate,
                # the tax. Areas that are outlying villages (Pelhřimov's) leave
                # the town itself at its main figure.
                s, lc = max(size.values()), max(local.values())
                where = f"{place['name']} — by city part, none named: its highest"
            else:
                s, lc = size[""], local[""]
                where = place["name"]
            how = "; ".join(sources) if sources else "no ordinance: the act's defaults"
            return s, lc, f"{where} (size {s:g} × local {lc:g}; {how})"
    return (size_coefficient(district), LOCAL_COEFFICIENT,
            "UNVERIFIED — municipality not read yet: 3.5 outside Prague, local "
            f"{LOCAL_COEFFICIENT:g}")


def annual_tax(size_m2: float, district: str = "", year: int | None = None) -> float:
    """Kč a year for a flat of `size_m2` m² in `district`."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    size, local, _ = coefficients(district, year)
    return round(size_m2 * UNIT_COEFFICIENT * RATE_PER_M2 * size * local
                 * INFLATION_COEFFICIENT, 2)

"""
engine/property_tax_sk.py — daň z bytov on a Slovak flat.

A flat is taxed on its floor area, not its value (zákon 582/2004 Z. z.
o miestnych daniach, § 14–16):

    tax = every started m² of the flat's floor area × the municipality's
          yearly rate per m²

The act's own rate, 0.033 €/m² (§ 16 ods. 1), is only the default: each
municipality sets its rate by VZN (§ 16 ods. 2), and the act limits it only
relative to the municipality's other flat rates (its highest at most 10× its
lowest). The cities below charge 0.75–1.35 €/m², 20–40 times the default.

Bratislava's rate depends on the cadastral area's pásmo (A–D). A city part is
taxed at the highest pásmo among its areas: Ružinov at Nivy's 1.35 (its
Ružinov and Trnávka areas pay 1.25), and a bare "Bratislava II" at its
dearest city part's. A place not in the table is taxed at the highest rate in
it, 1.35 €/m². That is not a legal ceiling (a municipality may set more), so
such a listing's tax is UNVERIFIED. A 60 m² flat pays about €45–81 a year in
the cities below, so the approximation hardly moves a cash flow.
"""

from __future__ import annotations

import math

from engine import regional_prices as rp

# § 16 ods. 1 — what a municipality without its own rate would charge. Shown
# for reference; the table and the fallback below are what the engine uses.
STATUTORY_RATE_PER_M2 = 0.033

# Bratislava (VZN 13/2019 as amended by VZN 16/2023): pásmo A 1.20, B 1.20,
# C 1.25, D 1.35 €/m², unchanged for 2026. Pásma by cadastral area —
# A: Vajnory, Podunajské Biskupice, Vrakuňa, Devínska Nová Ves; B: Čunovo,
# Devín, Dúbravka, Jarovce, Karlova Ves, Lamač, Rača, Rusovce, Záhorská
# Bystrica; C: Nové Mesto, Vinohrady, Ružinov, Trnávka, Petržalka;
# D: Staré Mesto, Nivy. City parts are named as in engine.regional_prices.
BA_PART_RATE_PER_M2 = {
    "staré mesto": 1.35, "stare mesto": 1.35,
    "ružinov":     1.35, "ruzinov":     1.35,   # Nivy (D); its other areas are C
    "nové mesto":  1.25, "nove mesto":  1.25,   # Nové Mesto and Vinohrady (C)
    "petržalka":   1.25, "petrzalka":   1.25,
    "rača":        1.20, "raca":        1.20,
    "karlova ves": 1.20,
    "dúbravka":    1.20, "dubravka":    1.20,
    "lamač":       1.20, "lamac":       1.20,
    "devínska":    1.20, "devinska":    1.20,
    "devín":       1.20, "devin":       1.20,
    "záhorská":    1.20, "zahorska":    1.20,
    "jarovce":     1.20,
    "rusovce":     1.20,
    "čunovo":      1.20, "cunovo":      1.20,
    "vajnory":     1.20,
    "podunajské":  1.20, "podunajske":  1.20,
    "vrakuňa":     1.20, "vrakuna":     1.20,
}
_BA_PARTS_BY_LENGTH = sorted(BA_PART_RATE_PER_M2, key=len, reverse=True)
# "Bratislava I"–"V" with no city part named: the okres's dearest city part.
BA_OKRES_RATE_PER_M2 = {"I": 1.35, "II": 1.35, "III": 1.25, "IV": 1.20, "V": 1.25}

# Other cities: €/m² a year for a flat, and where the figure comes from.
CITY_RATE_PER_M2 = {
    "bratislava":      (1.35, "Bratislava city-wide — pásmo D, the highest (no city part named)"),
    "košice":          (1.27, "Košice — the I. category; II. pays 1.207, III. 1.143"),
    "žilina":          (1.20, "Žilina — the Žilina and Závodie areas; the rest pay 1.10"),
    "trnava":          (1.00, "Trnava"),
    "banská bystrica": (1.00, "Banská Bystrica"),
    "prešov":          (0.953, "Prešov"),
    "trenčín":         (0.88, "Trenčín"),
    "nitra":           (0.75, "Nitra"),
}
CITY_RATE_PER_M2.update({
    "kosice": CITY_RATE_PER_M2["košice"], "zilina": CITY_RATE_PER_M2["žilina"],
    "banska bystrica": CITY_RATE_PER_M2["banská bystrica"],
    "presov": CITY_RATE_PER_M2["prešov"], "trencin": CITY_RATE_PER_M2["trenčín"],
})
_CITIES_BY_LENGTH = sorted(CITY_RATE_PER_M2, key=len, reverse=True)

# A place the table doesn't know: the highest rate in it (see the docstring).
UNKNOWN_PLACE_RATE_PER_M2 = max(
    [r for r, _ in CITY_RATE_PER_M2.values()] + list(BA_PART_RATE_PER_M2.values()))

SOURCE = {
    "source": (
        "zákon 582/2004 Z. z. § 16 (0.033 €/m², a municipality's own rate by VZN, "
        "its highest flat rate ≤ 10× its lowest) — full texts at financnasprava.sk "
        "and static.slov-lex.sk. Bratislava: VZN 16/2023 (bratislava.sk), pásma "
        "A–D 1.20/1.20/1.25/1.35 €/m² and the pásmo of each cadastral area from "
        "the city's tax page; unchanged for 2026 per dospelak.sk and staruch.eu. "
        "Košice: kosice.sk 'Miestne dane' for 2026 (VZN 132, príloha 1) "
        "1.270/1.207/1.143 by category. Žilina: zilina.sk, 1.20 Žilina and "
        "Závodie / 1.10 elsewhere from 2024, the same in the draft VZN for 2026. "
        "Trnava: VZN 529 (trnava.sk) 1.00; realne.sk the same for 2026. Nitra: "
        "nitra.sk 0.75, unchanged in the 2026 budget. Banská Bystrica: VZN 14/2022 "
        "(banskabystrica.sk) 1.00 from 2023. Prešov: VZN 11/2024 (presov.sk) "
        "0.953. Trenčín: trencin.sk, 0.85 → 0.88 for 2026 as proposed in Nov 2025. "
        "All read via web search — slov-lex.sk and the cities' sites could not be "
        "fetched from here. UNVERIFIED: whether Žilina's draft and Trenčín's "
        "proposal were adopted as written; whether Banská Bystrica and Prešov "
        "changed their rate for 2026; which category each part of Košice is in "
        "(the highest is used); any place not in the table (taxed at 1.35)."),
    "checked": "2026-10-31 (web search)",
}


def rate_source(district: str) -> tuple[float, str]:
    """(€/m² a year for a flat in `district`, what the rate is). A Bratislava
    city part is matched as engine.regional_prices matches it: with
    "Bratislava" named, or alone when it is unambiguous ("Petržalka", not
    "Staré Mesto", which Košice also has)."""
    key = (district or "").lower()
    if key:
        ba = "bratislava" in key
        if ba or not rp._names_non_ba_town(key):
            for part in _BA_PARTS_BY_LENGTH:
                if (part in key if ba else
                        part not in rp._GENERIC_BA_PARTS and rp._has_place(part, key)):
                    return BA_PART_RATE_PER_M2[part], f"{rp._title(part)}, Bratislava"
        if ba:
            m = rp._BA_OKRES_RE.search(key)
            if m:
                okres = m.group(1).upper()
                return (BA_OKRES_RATE_PER_M2[okres],
                        f"Bratislava {okres} — its dearest city part (none named)")
        for city in _CITIES_BY_LENGTH:
            if rp._has_place(city, key, rp._CITY_TAIL):
                return CITY_RATE_PER_M2[city]
    return (UNKNOWN_PLACE_RATE_PER_M2,
            "UNVERIFIED — place not in the table; its highest rate is used")


def annual_tax(size_m2: float, district: str = "") -> float:
    """€ a year for a flat of `size_m2` m² in `district`: every started m²
    at the rate per m² (rate_source)."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    return round(math.ceil(size_m2 - 1e-9) * rate_source(district)[0], 2)

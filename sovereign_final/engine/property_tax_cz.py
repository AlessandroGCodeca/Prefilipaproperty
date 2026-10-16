"""
engine/property_tax_cz.py — daň z nemovitých věcí on a Czech flat.

A flat (jednotka) is taxed on its floor area, not its value (zákon
338/1992 Sb., as amended by the 2024 consolidation package):

    tax = floor area × 1.22 × rate per m² × the municipality's size
          coefficient × its local coefficient × the inflation coefficient

The size coefficient depends on the municipality's population; this app
knows only Prague's for certain, so every other place is taxed at 3.5 — the
highest coefficient outside Prague — which may overstate, never understate,
the tax. The local coefficient (0.5–5, set by each municipality's own
decree) is 1.0 unless CZ_PROPERTY_TAX_LOCAL_COEF says otherwise. A 60 m² flat
comes to a few hundred to about a thousand crowns a year, so the
approximation hardly moves a cash flow.
"""

from __future__ import annotations

import os
import unicodedata

# Kč per m² for a flat, after the 2024 consolidation package.
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
    "source": ("zákon 338/1992 Sb. o dani z nemovitých věcí after the 2024 consolidation "
               "package: 3.50 Kč/m² for a flat, × 1.22, size coefficients 1.0–3.5 and "
               "4.5 for Prague, inflation coefficient 1.0 for 2026 — as reported by "
               "e15.cz, finzi.cz, muj-pravnik.cz, nemovitostnikalkulacka.cz (read via web "
               "search; the act and financnisprava.gov.cz could not be fetched). The "
               "local coefficient per municipality is UNVERIFIED and taken as 1.0."),
    "checked": "2026-10-16 (web search)",
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def size_coefficient(district: str) -> float:
    """Prague's 4.5, or the 3.5 upper bound for anywhere else (see the
    module docstring)."""
    if "praha" in _fold(district) or "prague" in _fold(district):
        return PRAGUE_COEFFICIENT
    return UNKNOWN_PLACE_COEFFICIENT


def annual_tax(size_m2: float, district: str = "") -> float:
    """Kč a year for a flat of `size_m2` m² in `district`."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    return round(size_m2 * UNIT_COEFFICIENT * RATE_PER_M2 * size_coefficient(district)
                 * LOCAL_COEFFICIENT * INFLATION_COEFFICIENT, 2)

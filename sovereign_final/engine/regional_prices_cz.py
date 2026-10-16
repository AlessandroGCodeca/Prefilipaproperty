"""
engine/regional_prices_cz.py — Czech sale-price medians (Kč/m²): the
benchmark a Czech listing's price is judged against, and its floor and
ceiling.

engine.regional_prices delegates here for market="cz". The tables are
empty until a citable source fills them; with no median, a Czech listing has
no benchmark — it is WHITE, never a guessed GREEN.
"""

from __future__ import annotations

import unicodedata

# Kraj codes (CZ-NUTS 3 abbreviations) and names.
KRAJ_NAMES: dict[str, str] = {}
# Kč/m² medians, most specific first: city district, okres / city, kraj.
DISTRICT_MEDIAN: dict[str, float] = {}
OKRES_MEDIAN: dict[str, float] = {}
KRAJ_MEDIAN: dict[str, float] = {}

SOURCE = {"source": "UNVERIFIED — no Czech price table yet", "checked": None}

# The medians' room basis and the adjustment for other room counts. 1.0
# everywhere until a source states the spread.
ROOMS_MULTIPLIER = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def kraj_for_district(district: str) -> str | None:
    return None


def median_source(district: str) -> tuple[float | None, str]:
    """(Kč/m² median for the district's region, what it is the median of),
    or (None, "") when there is none."""
    return None, ""


def rooms_multiplier(rooms: int) -> float:
    return ROOMS_MULTIPLIER.get(min(int(rooms), 4), 1.0)


def benchmark_note(district: str, rooms=None) -> str:
    median, where = median_source(district)
    if median is None:
        return "No regional median for this district."
    return f"median of {where}: {median:,.0f} Kč/m²".replace(",", " ")

"""
engine/short_let.py — letting by the night (Airbnb, Booking) next to letting
by the year, where short lets are a real market: the Tatras and Liptov,
Bratislava I (Staré Mesto), Prague 1 and 2.

The assumptions per area are a starting point, NOT market data: the nightly
rate (ADR) and the share of nights booked (occupancy) are what a typical
1–2 room flat in that area earns in a normal year. Replace them with real
figures — Inside Airbnb's free files (insideairbnb.com, Prague is covered),
AirDNA (paid), or a local manager's figures — via SHORT_LET_<AREA>_ADR and
SHORT_LET_<AREA>_OCCUPANCY in .env. The rules change often: a town can
require registration, cap the nights or charge a tax per guest-night; check
them before buying for it.

Costs by the night: the platform's host fee, cleaning per stay, the local
tax per guest-night, a manager's share (if you use one), utilities and
internet you now pay yourself, and the flat's furnishing (spread over five
years). The building fee, property tax and loan are the same as for a long
let; income tax is worked out the same way on the larger net.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from modules.lv_screen import fold


@dataclass(frozen=True)
class Area:
    key: str
    name: str
    market: str
    patterns: tuple[str, ...]      # regexes on the folded district that place a flat here
    adr: float                     # average nightly rate
    occupancy: float               # share of nights booked over a year


AREAS = (
    Area("tatry", "Vysoké Tatry and Poprad", "sk",
         ("vysoke tatry", "tatransk", "smokovec", "strbske pleso", "zdiar", "poprad"), 105, 0.50),
    Area("liptov", "Liptov (Jasná, Liptovský Mikuláš)", "sk",
         ("demanovsk", "jasna", "liptovsky mikulas", "liptovsky jan"), 95, 0.45),
    # Not Košice's Staré Mesto, nor Bratislava II–V.
    Area("ba1", "Bratislava I (Staré Mesto)", "sk",
         (r"bratislava\s*-?\s*i(?![iv\w])", r"bratislava\W*stare\s+mesto"), 85, 0.62),
    Area("praha1", "Prague 1", "cz", (r"praha\s*-?\s*1(?!\d)", r"mala\s+strana", r"josefov",
                                      r"praha\W+(?:stare|nove)\s+mesto"), 2_600, 0.70),
    Area("praha2", "Prague 2", "cz", (r"praha\s*-?\s*2(?!\d)", r"vysehrad"), 2_100, 0.66),
)
COSTS = {
    # platform host fee, cleaning per stay, nights a stay, guests a stay, local tax a guest-night,
    # manager's share (0 = you run it), utilities + internet + insurance a month, furnishing per m²
    "sk": dict(platform=0.155, cleaning=30, stay=3.0, guests=2, local_tax=2.0, manager=0.0,
               utilities=130, furnish_m2=180),
    "cz": dict(platform=0.155, cleaning=700, stay=3.0, guests=2, local_tax=50, manager=0.0,
               utilities=3_200, furnish_m2=4_500),
}
FURNISH_YEARS = 5


def area_for(district: str, market: str = "sk") -> Area | None:
    t = fold(district or "")
    for a in AREAS:
        if a.market == market and any(re.search(p, t) for p in a.patterns):
            return a
    return None


def _env(key: str, default: float) -> float:
    raw = (os.getenv(key) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass
class ShortLet:
    area: str
    adr: float
    occupancy: float
    nights: float
    gross_monthly: float
    platform_monthly: float
    cleaning_monthly: float
    local_tax_monthly: float
    manager_monthly: float
    utilities_monthly: float
    furnishing_monthly: float
    building_monthly: float        # HOA + property tax, as for a long let
    mortgage_monthly: float
    tax_monthly: float
    surplus_monthly: float
    long_let_surplus: float
    break_even_occupancy: float    # the occupancy at which it matches the long let


def scenario(l: dict, manager: bool = False, adr: float | None = None,
             occupancy: float | None = None) -> ShortLet | None:
    """The short-let month for a scored listing row; None outside the areas."""
    from engine import financial
    market = l.get("market") or l.get("_market") or "sk"
    a = area_for(l.get("district") or "", market)
    if not a or not l.get("size_m2") or not l.get("price_eur"):
        return None
    c = COSTS[market]
    adr = adr if adr is not None else _env(f"SHORT_LET_{a.key.upper()}_ADR", a.adr)
    occ = occupancy if occupancy is not None else _env(f"SHORT_LET_{a.key.upper()}_OCCUPANCY",
                                                       a.occupancy)
    size = l["size_m2"]
    hoa = l.get("hoa_monthly") or financial.calc_hoa(size, market=market)
    ptax = l.get("property_tax_monthly") or financial.property_tax_annual(
        l["price_eur"], size, l.get("district") or "", market=market) / 12
    mortgage = l.get("mortgage_monthly") or 0.0

    def month(o: float) -> tuple[float, float, dict]:
        nights = 365 * o
        gross = nights * adr / 12
        parts = dict(platform=gross * c["platform"],
                     cleaning=nights / c["stay"] * c["cleaning"] / 12,
                     local_tax=nights * c["guests"] * c["local_tax"] / 12,
                     manager=gross * (0.20 if manager else c["manager"]),
                     utilities=c["utilities"],
                     furnishing=size * c["furnish_m2"] / FURNISH_YEARS / 12)
        net = gross - sum(parts.values()) - hoa - ptax
        rules = financial.tax_rules() if market == "sk" else financial.markets.tax_rules(None, market)
        tax = financial.calc_income_tax_personal(max(net * 12, 0.0), rules,
                                                 financial.other_annual_income(market)) / 12
        return net - tax - mortgage, tax, {**parts, "gross": gross, "nights": nights}

    surplus, tax, p = month(occ)
    long_let = l.get("surplus_personal") or 0.0
    lo, hi = 0.0, 1.0                          # occupancy where it matches the long let
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if month(mid)[0] < long_let else (lo, mid)
    return ShortLet(
        area=a.name, adr=adr, occupancy=occ, nights=round(p["nights"]),
        gross_monthly=round(p["gross"], 2), platform_monthly=round(p["platform"], 2),
        cleaning_monthly=round(p["cleaning"], 2), local_tax_monthly=round(p["local_tax"], 2),
        manager_monthly=round(p["manager"], 2), utilities_monthly=round(p["utilities"], 2),
        furnishing_monthly=round(p["furnishing"], 2), building_monthly=round(hoa + ptax, 2),
        mortgage_monthly=round(mortgage, 2), tax_monthly=round(tax, 2),
        surplus_monthly=round(surplus, 2), long_let_surplus=round(long_let, 2),
        break_even_occupancy=round(hi, 3))


def matches(district: str, market: str = "sk") -> bool:
    return area_for(district, market) is not None


"""
engine/building.py — the building and the flat's state: what the ad says
about the building, what renovating the flat would cost, what heating it
costs, and a buy–renovate–sell (flip) scenario.

Many GREEN flats are GREEN because they need work: the price is low against
the district's median, and the median is of flats in an ordinary state. The
renovation estimate puts that work into money; the flip shows whether buying
it to renovate and sell beats buying it to let.

Every figure here is an estimate for a first look — a contractor's quote and
the energy certificate replace it. The rates are per m² of the flat, in the
market's currency:

  RENOVATION_M2   by the condition the ad's text gives (description
                  enrichment): nothing for a new or renovated flat; a refresh
                  (paint, floors) for "good"; kitchen, bathroom, wiring and
                  floors for "original"; everything, with the risers' branch
                  and plaster, for "poor".
  HEAT_KWH_M2     the heat a flat of each energy class needs a year (the
                  middle of the class's band for a flat in a block, A0 to G).
  HEAT_PRICE      per kWh of heat, district heating or gas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from modules.lv_screen import fold

RENOVATION_M2 = {
    "sk": {"new": 0, "renovated": 0, "good": 150, "original": 520, "poor": 800, "unknown": 300},
    "cz": {"new": 0, "renovated": 0, "good": 3_800, "original": 13_000, "poor": 20_000,
           "unknown": 7_500},
}
RENOVATION_MONTHS = {"new": 0, "renovated": 0, "good": 1, "original": 3, "poor": 5, "unknown": 2}
# Delivered heat, kWh per m² a year, by energy class (flat in a block).
HEAT_KWH_M2 = {"A0": 20, "A1": 40, "A": 40, "B": 75, "C": 110, "D": 150, "E": 190, "F": 230,
               "G": 280}
HEAT_PRICE = {"sk": 0.13, "cz": 3.2}          # € or Kč per kWh
HEAT_UNKNOWN_KWH_M2 = 120
RENOVATED_PREMIUM = 0.10    # a renovated flat sells this much above the district median
FLIP_SELL_MONTHS = 3        # months on the market after the work


def _num(s: str) -> float | None:
    try:
        return float(s.replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


_PANEL_RE = re.compile(r"(?<!\w)panel\w*|(?<!\w)panelak\w*|(?<!\w)panelov\w*")
_BRICK_RE = re.compile(r"(?<!\w)tehl\w*|(?<!\w)cihl\w*|(?<!\w)tehlov\w*|(?<!\w)cihlov\w*")
_SKELETON_RE = re.compile(r"(?<!\w)skelet\w*|monolit\w*")
_INSULATED_RE = re.compile(r"zateplen\w*|revitalizovan\w*|revitalizaci\w*|zateplenim")
_NOT_INSULATED_RE = re.compile(r"(?:nie\s+je|neni|bez|nezateplen)\w*\s*(?:zateplen)?\w*")
_HEATING = (
    ("district", re.compile(r"ustredn\w*\s+kuren|centraln\w*\s+(?:kuren|zdroj|vytapen)|"
                            r"dialkov\w*|cz[tt]\b|teplaren")),
    ("gas boiler (flat)", re.compile(r"vlastn\w*\s+(?:plynov\w*\s+)?kotol|plynov\w*\s+kotol\s+v\s+byte|"
                                     r"lokaln\w*\s+(?:plynov\w*\s+)?kotl|vlastni\s+kotel|kombikotol")),
    ("heat pump", re.compile(r"tepeln\w*\s+cerpadl")),
    ("electric", re.compile(r"elektrick\w*\s+(?:kuren|vykurovan|vytapen)|podlahov\w*\s+elektr")),
    ("gas boiler (building)", re.compile(r"domov\w*\s+kotolna|kotolna\s+v\s+dome|domovni\s+kotelna")),
)
_COSTS_RE = re.compile(r"(?:mesacn\w*\s+(?:naklad|poplat|platb)\w*|zalohy|mesicni\s+(?:naklad|poplat)\w*|"
                       r"poplatky\s+za\s+sluzby)[^0-9]{0,40}?(\d[\d\s ]{0,6}(?:[.,]\d+)?)\s*(?:€|eur|kc)")
_FUND_RE = re.compile(r"fond\w*\s+(?:oprav|udrzby)[^0-9]{0,30}?(\d[\d\s ]{0,6}(?:[.,]\d+)?)\s*(?:€|eur|kc)")
_YEAR_RE = re.compile(r"(?:rok\s+(?:vystavby|kolaudacie|vystavby\s+domu)|postaven\w*\s+(?:v\s+roku|roku)|"
                      r"kolaudac\w*)\s*:?\s*((?:18|19|20)\d\d)")


def parse_ad(text: str) -> dict:
    """What an ad says about the building: construction, insulated (True /
    False / None), heating, year built, the monthly costs it quotes (often
    with energy advances the tenant pays) and the fond opráv when stated."""
    t = fold(text or "")
    out: dict = {"construction": None, "insulated": None, "heating": None,
                 "year_built": None, "costs_monthly": None, "fund_monthly": None}
    if _PANEL_RE.search(t):
        out["construction"] = "panel"
    elif _BRICK_RE.search(t):
        out["construction"] = "brick"
    elif _SKELETON_RE.search(t):
        out["construction"] = "skeleton"
    if re.search(r"(?:nie\s+je|neni|bez)\s+zatepl|nezateplen", t):
        out["insulated"] = False
    elif _INSULATED_RE.search(t):
        out["insulated"] = True
    for name, rx in _HEATING:
        if rx.search(t):
            out["heating"] = name
            break
    m = _YEAR_RE.search(t)
    if m:
        out["year_built"] = int(m.group(1))
    m = _COSTS_RE.search(t)
    if m:
        out["costs_monthly"] = _num(m.group(1))
    m = _FUND_RE.search(t)
    if m:
        out["fund_monthly"] = _num(m.group(1))
    return out


def renovation_cost(size_m2: float, condition: str | None, market: str = "sk") -> float:
    rates = RENOVATION_M2["cz" if market == "cz" else "sk"]
    return round((size_m2 or 0) * rates.get((condition or "unknown").lower(), rates["unknown"]))


def heating_monthly(size_m2: float, energy_class: str | None, market: str = "sk") -> float:
    """The flat's heating a month, spread over the year (paid by the tenant
    while it is let, by you while it stands empty)."""
    kwh = HEAT_KWH_M2.get((energy_class or "").upper().strip(), HEAT_UNKNOWN_KWH_M2)
    return round((size_m2 or 0) * kwh * HEAT_PRICE["cz" if market == "cz" else "sk"] / 12, 2)


def building_risks(facts: dict, now_year: int) -> list[str]:
    """Plain warnings from what is known of the building."""
    out = []
    year = facts.get("year_built")
    if year and now_year - year >= 40 and facts.get("insulated") is not True:
        out.append(f"Built {year} and not known to be insulated: expect the fond opráv to rise or "
                   f"a one-off levy for the façade, roof and risers — ask the správca.")
    if facts.get("construction") == "panel" and facts.get("insulated") is False:
        out.append("A panel block that isn't insulated: high heating bills, which tenants notice.")
    if facts.get("heating") == "electric":
        out.append("Electric heating: the dearest to run; tenants weigh it against the rent.")
    return out


@dataclass
class Flip:
    buy: float
    buying_costs: float
    renovation: float
    holding: float
    sale_price: float
    selling_costs: float
    tax: float
    profit: float
    cash_in: float
    roi: float          # profit / cash put in
    months: int
    sale_note: str


def flip(price: float, size_m2: float, district: str, condition: str | None, rooms=None,
         market: str = "sk", renovation: float | None = None, months: int | None = None,
         sale_price: float | None = None) -> Flip | None:
    """Buy at `price`, renovate, sell at the district's median for a
    renovated flat. None without a median for the district."""
    from engine import financial
    from engine.regional_prices import benchmark_median
    mk = {"market": market}
    median = benchmark_median(district, rooms, market=market)
    if sale_price is None:
        if not median:
            return None
        sale_price = median * size_m2 * (1 + RENOVATED_PREMIUM)
        note = (f"district median {median:,.0f}/m² + {RENOVATED_PREMIUM:.0%} for a renovated flat")
    else:
        note = "your sale price"
    cond = (condition or "unknown").lower()
    renovation = renovation_cost(size_m2, cond, market) if renovation is None else renovation
    months = (RENOVATION_MONTHS.get(cond, 2) + FLIP_SELL_MONTHS) if months is None else months
    buying = financial.acquisition_costs(price, **mk)
    ltv = financial.default_ltv(**mk)
    rate = financial.MORTGAGE_RATE_PA if market == "sk" else financial.markets.get(market).mortgage_rate_pa
    interest = price * ltv * rate / 12 * months
    running = (financial.calc_hoa(size_m2, **mk)
               + financial.property_tax_annual(price, size_m2, district, **mk) / 12) * months
    holding = round(interest + running, 2)
    selling = sale_price * (financial.EXIT_COST_RATE if market == "sk"
                            else financial.markets.get(market).exit_cost_rate)
    gain = sale_price - selling - price - buying - renovation - holding
    rules = financial.tax_rules() if market == "sk" else financial.markets.tax_rules(None, market)
    tax = financial.calc_income_tax_personal(max(gain, 0.0), rules,
                                             financial.other_annual_income(market))
    profit = gain - tax
    cash_in = price * (1 - ltv) + buying + renovation + holding
    return Flip(buy=price, buying_costs=round(buying, 2), renovation=renovation,
                holding=holding, sale_price=round(sale_price, 2), selling_costs=round(selling, 2),
                tax=round(tax, 2), profit=round(profit, 2), cash_in=round(cash_in, 2),
                roi=profit / cash_in if cash_in > 0 else 0.0, months=months, sale_note=note)

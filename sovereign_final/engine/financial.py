"""
engine/financial.py — Sovereign Investor Dashboard
Module B: 2026 Slovak Financial Engine

Dual-scenario analysis: Personal (Fyzická osoba) vs s.r.o.
Outputs: CoC, Net Yield, Self-Funding Ratio, Optimal Structure, and the
class — how far the asking €/m² sits below the regional median (see the
Classification Thresholds note in config.py for why not the ratio).
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    MORTGAGE_RATE_PA, LOAN_TERM_YEARS, LTV_RATIO,
    TAX_RATE_PERSONAL_LOW, TAX_RATE_PERSONAL_HIGH, TAX_THRESHOLD_PERSONAL,
    RENTAL_INCOME_EXEMPTION,
    TAX_RATE_SRO, TAX_RATE_SRO_REDUCED, SRO_REDUCED_REVENUE_LIMIT,
    DIVIDEND_TAX_RATE,
    HEALTH_LEVY_PERSONAL, PROPERTY_TAX_RATE_PA, VACANCY_RATE, OWNER_RESERVE_RATE, PROPERTY_MGMT_RATE,
    ACQUISITION_COST_RATE,
    HOA_SMALL, HOA_MEDIUM, HOA_LARGE, HOA_PREMIUM,
    GREEN_DISCOUNT, YELLOW_DISCOUNT, NEAR_FLOOR_DISCOUNT, SRO_SETUP_COST,
    RENT_PER_M2, INDUSTRIAL_ZONES, INDUSTRIAL_RENT_PREMIUM,
    PARKING_RENT_PREMIUM, FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
    BALCONY_RENT_PREMIUM,
    LTV_RATIO_INVESTOR, INVESTOR_LTV_FROM, PROPERTIES_OWNED, RATE_SHOCK_PP,
    HOLD_YEARS, APPRECIATION_RATE, RENT_GROWTH_RATE, COST_INFLATION_RATE,
    EXIT_COST_RATE, PERSONAL_CGT_EXEMPT_YEARS,
)
from engine.regional_prices import regional_median_price, REGIONAL_PRICE_FLOOR_RATIO


@dataclass
class FinancialResult:
    listing_id:             Optional[str]
    price_eur:              float
    size_m2:                float
    district:               str
    loan_amount:            float
    equity_invested:        float
    acquisition_costs:      float
    total_cash_invested:    float
    estimated_rent:         float

    # Shared costs
    mortgage_monthly:       float
    mortgage_interest_monthly:  float
    mortgage_principal_monthly: float
    hoa_monthly:            float
    property_tax_monthly:   float
    vacancy_cost:           float
    maintenance_monthly:    float
    management_monthly:     float

    # Personal scenario
    income_tax_personal:    float
    health_levy_personal:   float
    total_costs_personal:   float
    surplus_personal:       float
    ratio_personal:         float

    # s.r.o. scenario
    income_tax_sro:         float
    health_levy_sro:        float
    total_costs_sro:        float
    surplus_sro:            float
    ratio_sro:              float

    # Key metrics
    noi_monthly:            float   # net operating income (unlevered, pre-tax)
    cap_rate:               float   # NOI / price — unlevered yardstick
    cash_on_cash:           float   # levered cashflow / total cash invested
    net_rental_yield:       float
    gross_yield:            float
    principal_paydown_monthly: float
    total_return_annual:    float   # cashflow + principal paydown (excl. appreciation)
    total_roi:              float   # total return / total cash invested
    regional_median_m2:     Optional[float]  # the region's median asking €/m²
    market_discount:        Optional[float]  # 1 − (€/m²) / median; >0 = below market

    # Decision
    optimal_structure:      str
    annual_sro_saving:      float
    sro_break_even_months:  Optional[int]
    classification:         str
    recommendation:         str

    # Financing the figures were worked out with.
    mortgage_rate:          float = MORTGAGE_RATE_PA
    ltv:                    float = LTV_RATIO
    loan_term_years:        int   = LOAN_TERM_YEARS


def calc_mortgage(principal: float,
                  rate: float = MORTGAGE_RATE_PA,
                  years: int = LOAN_TERM_YEARS) -> float:
    if principal <= 0:
        return 0.0
    r = rate / 12
    n = years * 12
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def first_year_amortization(principal: float,
                            rate: float = MORTGAGE_RATE_PA,
                            years: int = LOAN_TERM_YEARS) -> tuple[float, float]:
    """Return (avg monthly interest, avg monthly principal) over the first 12
    months of an annuity loan. Splitting the payment matters because principal
    repayment is equity buildup, not a true expense — it shouldn't be counted
    against the property's return the way interest is."""
    if principal <= 0:
        return 0.0, 0.0
    payment = calc_mortgage(principal, rate, years)
    r = rate / 12
    bal = principal
    interest_total = 0.0
    for _ in range(12):
        i = bal * r
        bal -= (payment - i)
        interest_total += i
    interest_mo = interest_total / 12
    principal_mo = payment - interest_mo
    return interest_mo, principal_mo


def calc_hoa(size_m2: float) -> float:
    if size_m2 < 40:   return HOA_SMALL
    if size_m2 <= 70:  return HOA_MEDIUM
    if size_m2 <= 120: return HOA_LARGE
    return HOA_PREMIUM


def calc_income_tax_personal(annual_net: float) -> float:
    if annual_net <= 0:
        return 0.0
    if annual_net <= TAX_THRESHOLD_PERSONAL:
        return annual_net * TAX_RATE_PERSONAL_LOW
    return (TAX_THRESHOLD_PERSONAL * TAX_RATE_PERSONAL_LOW +
            (annual_net - TAX_THRESHOLD_PERSONAL) * TAX_RATE_PERSONAL_HIGH)


def sro_corporate_rate(annual_revenue: float) -> float:
    """Reduced corporate rate applies below the small-company revenue limit."""
    return TAX_RATE_SRO_REDUCED if annual_revenue <= SRO_REDUCED_REVENUE_LIMIT else TAX_RATE_SRO


def calc_tax_sro(annual_taxable: float, annual_revenue: float) -> float:
    """Combined s.r.o. tax on rental profit: corporate income tax PLUS dividend
    withholding tax on the distributed remainder (the double-taxation that makes
    s.r.o. less of a slam-dunk than a flat corporate rate suggests)."""
    if annual_taxable <= 0:
        return 0.0
    corp = annual_taxable * sro_corporate_rate(annual_revenue)
    dividend = max(annual_taxable - corp, 0) * DIVIDEND_TAX_RATE
    return corp + dividend


_CITY_ONLY_KEYS = {"bratislava", "košice"}  # used only as last-resort city fallbacks

# Bratislava's city parts in RENT_PER_M2. "Staré Mesto" and "Nové Mesto" are
# generic names (Košice has a Staré Mesto too), so a city-part rate is not used
# for a district that names a town outside Bratislava: "Staré Mesto, Košice" is
# not priced at Bratislava's Staré Mesto rent. engine/regional_prices guards
# its BA sub-district medians the same way. A district that says "bratislava"
# keeps the city-part rate.
_BA_CITY_PART_KEYS = {
    "staré mesto", "ružinov", "vrakuňa", "podunajské", "vajnory", "nové mesto",
    "rača", "dúbravka", "karlova ves", "lamač", "záhorská", "devínska",
    "petržalka", "rusovce", "jarovce", "čunovo",
}
_OUTSIDE_BA_KEYS = tuple(
    k for k in RENT_PER_M2
    if k != "default" and k not in _BA_CITY_PART_KEYS
    and not k.startswith("bratislava")
)


def _names_town_outside_bratislava(key: str) -> bool:
    return "bratislava" not in key and any(t in key for t in _OUTSIDE_BA_KEYS)

# Per-m² rates in RENT_PER_M2 represent 2-izb apartments (baseline). Smaller
# units command a per-m² premium; larger units sell at a discount. Multipliers
# derived from Q2 2026 Deloitte Rent Index data showing 1-izb at 1.15× and
# 3-izb at 0.92× of 2-izb per m².
ROOMS_RENT_MULTIPLIER = {
    1: 1.15,   # 1-izbový / garsónka
    2: 1.00,   # 2-izbový (baseline)
    3: 0.92,   # 3-izbový
    4: 0.85,   # 4+ izbový
}


def _rooms_multiplier(rooms) -> float:
    """Return the per-m² rate multiplier for a given room count. Falls back
    to the 2-izb baseline (1.0) when rooms is None, 0, or non-numeric."""
    if rooms is None:
        return 1.0
    try:
        r = int(rooms)
    except (TypeError, ValueError):
        return 1.0
    if r <= 0:
        return 1.0
    return ROOMS_RENT_MULTIPLIER.get(min(r, 4), 0.85)


def _furnished_multiplier(furnished) -> float:
    """Rent multiplier for the furnishing level parsed from the description.
    'furnished' earns the full premium, 'semi' a partial one; everything else
    (unfurnished / unknown / None) is neutral."""
    f = (furnished or "").strip().lower()
    if f == "furnished":
        return FURNISHED_RENT_PREMIUM
    if f == "semi":
        return SEMI_FURNISHED_PREMIUM
    return 1.0


_KEYS_BY_SPECIFICITY = sorted(
    (k for k in RENT_PER_M2 if k != "default" and k not in _CITY_ONLY_KEYS),
    key=len, reverse=True,
)

# A major city named anywhere in the district string falls back to a base
# (non-numbered) district rate as a reasonable approximation.
_CITY_ANCHORS = [
    ("bratislava", "bratislava iv"),   # suburban BA default
    ("košice",     "košice ii"),
    ("žilina",     "žilina"),
    ("nitra",      "nitra"),
    ("trnava",     "trnava"),
    ("prešov",     "prešov"),
    ("banská bystrica", "banská bystrica"),
    ("trenčín",    "trenčín"),
    ("poprad",     "poprad"),
    ("martin",     "martin"),
]


def match_rent_key(district: str) -> str:
    """The RENT_PER_M2 key a district string resolves to ("default" when
    nothing matches). Live rent comps are aggregated under these same keys
    (engine/rent_comps), so a live rate replaces exactly the baseline it is
    measured against."""
    key = (district or "").lower().strip()

    # 1. Exact match — including the city-only keys.
    if key in RENT_PER_M2:
        return key

    # 2. A known district name appears inside the address string.
    # Iterate longest-first so "petržalka" beats "ružinov" when both are
    # subsumed; suburbs/specific districts are preferred over bare city
    # names ("bratislava", "košice"), which are reserved as final fallbacks.
    outside_ba = _names_town_outside_bratislava(key)
    for known in _KEYS_BY_SPECIFICITY:
        if outside_ba and known in _BA_CITY_PART_KEYS:
            continue
        if known in key:
            return known

    # 3. Reverse: district token appears in a known key (longest-first so
    # "košice i" wins over plain "košice" when district is just "košice i")
    if key:
        for known in _KEYS_BY_SPECIFICITY:
            if key in known:
                return known

    # 4. City-name anchor.
    for city, fallback_key in _CITY_ANCHORS:
        if city in key:
            return fallback_key if fallback_key in RENT_PER_M2 else "default"

    return "default"


def base_rent_rate(district: str, rates=None) -> tuple[float, str, str]:
    """(€/m² for a 2-izb baseline flat, matched key, source) before the
    industrial / rooms / feature multipliers.

    `rates` is an optional {key: €/m²} of live comps (engine/rent_comps); a
    key it carries wins over the hard-coded RENT_PER_M2 baseline. source is
    "live" or "baseline" so the dashboard can say which one drove the rent.
    """
    k = match_rent_key(district)
    if rates and rates.get(k):
        return float(rates[k]), k, "live"
    return RENT_PER_M2.get(k, RENT_PER_M2["default"]), k, "baseline"


def get_rent_estimate(district: str, size_m2: float, rooms=None,
                      parking=None, furnished=None, balcony=None,
                      rates=None) -> float:
    key = (district or "").lower().strip()
    rate, _, source = base_rent_rate(district, rates)

    # A live comp already contains whatever the local employer adds to demand;
    # only the published baseline needs the industrial premium on top.
    if source == "baseline" and any(z in key for z in INDUSTRIAL_ZONES):
        rate *= INDUSTRIAL_RENT_PREMIUM
    rate *= _rooms_multiplier(rooms)
    # Description-derived premiums (only when the description was parsed; a
    # falsy parking/balcony flag and unfurnished/unknown furnishing leave rate
    # untouched).
    if parking:
        rate *= PARKING_RENT_PREMIUM
    rate *= _furnished_multiplier(furnished)
    if balcony:
        rate *= BALCONY_RENT_PREMIUM
    return round(rate * size_m2, 2)


def is_industrial_zone(district: str) -> bool:
    key = district.lower().strip()
    return any(z in key for z in INDUSTRIAL_ZONES)


def default_ltv(properties_owned: Optional[int] = None,
                on: Optional[str] = None) -> float:
    """The LTV a bank will lend at for your next purchase.

    NBS caps a 3rd-and-subsequent residential property at 70% from
    INVESTOR_LTV_FROM (1 Oct 2026). Owning 2+ already makes the next one a 3rd.
    `on` is an ISO date (default today) so tests can sit either side of it.
    """
    owned = PROPERTIES_OWNED if properties_owned is None else properties_owned
    today = on or datetime.now(timezone.utc).date().isoformat()
    if owned >= 2 and today >= INVESTOR_LTV_FROM:
        return LTV_RATIO_INVESTOR
    return LTV_RATIO


def analyse(
    price_eur: float,
    size_m2: float,
    district: str,
    listing_id: Optional[str] = None,
    rent_override: Optional[float] = None,
    ltv: Optional[float] = None,
    rooms: Optional[int] = None,
    parking=None,
    furnished=None,
    balcony=None,
    rate: float = MORTGAGE_RATE_PA,
    term_years: int = LOAN_TERM_YEARS,
    rent_rates=None,
) -> FinancialResult:
    """Score one property under both ownership structures.

    ltv defaults to default_ltv() — 80%, or the 70% investor cap when
    PROPERTIES_OWNED says this is a 3rd+ property. rate / term_years default to
    config and exist so the what-if panel and the stress test can vary them.
    rent_rates is an optional {rent key: €/m²} of live comps.
    """
    if ltv is None:
        ltv = default_ltv()

    loan_amount     = price_eur * ltv
    equity          = price_eur * (1 - ltv)
    acquisition     = price_eur * ACQUISITION_COST_RATE
    cash_invested   = equity + acquisition
    rent            = rent_override or get_rent_estimate(
        district, size_m2, rooms, parking, furnished, balcony, rates=rent_rates)
    annual_rent     = rent * 12

    # Mortgage (annuity) split into interest vs principal — principal is equity
    # buildup, not an expense, so it's tracked separately for total-return math.
    mortgage_mo     = calc_mortgage(loan_amount, rate, term_years)
    interest_mo, principal_mo = first_year_amortization(loan_amount, rate, term_years)

    # ── Operating expenses (exclude debt service & income tax) ────
    # HOA already includes the fond opráv (building shell); the owner reserve
    # covers only in-flat capex, so the two don't double-count.
    hoa_mo          = calc_hoa(size_m2)
    prop_tax_mo     = (price_eur * PROPERTY_TAX_RATE_PA) / 12
    vacancy_mo      = rent * VACANCY_RATE
    owner_reserve_mo = rent * OWNER_RESERVE_RATE
    mgmt_mo         = rent * PROPERTY_MGMT_RATE
    opex_mo         = hoa_mo + prop_tax_mo + vacancy_mo + owner_reserve_mo + mgmt_mo

    # ── NOI & cap rate (unlevered — independent of financing) ─────
    noi_mo          = rent - opex_mo
    noi_annual      = noi_mo * 12
    cap_rate        = noi_annual / price_eur if price_eur > 0 else 0

    # Cash cost of carrying the loan each month (interest + principal).
    operating_mo    = opex_mo + mortgage_mo

    # ── Personal scenario (passive §6(3): no health levy, €500 exempt) ──
    taxable_p       = max(noi_annual - RENTAL_INCOME_EXEMPTION, 0)
    tax_p_annual    = calc_income_tax_personal(taxable_p)
    levy_p_annual   = taxable_p * HEALTH_LEVY_PERSONAL  # 0 for passive rental
    tax_p_mo        = tax_p_annual / 12
    levy_p_mo       = levy_p_annual / 12
    total_p_mo      = operating_mo + tax_p_mo + levy_p_mo
    surplus_p       = rent - total_p_mo
    ratio_p         = rent / total_p_mo if total_p_mo > 0 else 0

    # ── s.r.o. scenario (deducts interest; corporate tax + dividend tax) ──
    taxable_s       = max(noi_annual - interest_mo * 12, 0)
    tax_s_annual    = calc_tax_sro(taxable_s, annual_rent)
    tax_s_mo        = tax_s_annual / 12
    levy_s_mo       = 0.0
    total_s_mo      = operating_mo + tax_s_mo + levy_s_mo
    surplus_s       = rent - total_s_mo
    ratio_s         = rent / total_s_mo if total_s_mo > 0 else 0

    # ── Key metrics (use s.r.o. as primary — usually better structure) ────
    annual_cf_sro   = surplus_s * 12
    coc             = annual_cf_sro / cash_invested if cash_invested > 0 else 0
    net_yield       = annual_cf_sro / price_eur if price_eur > 0 else 0
    gross_yield     = annual_rent / price_eur if price_eur > 0 else 0
    principal_paydown_annual = principal_mo * 12
    # Total return adds equity built via amortization (appreciation NOT modelled).
    total_return_annual = annual_cf_sro + principal_paydown_annual
    total_roi       = total_return_annual / cash_invested if cash_invested > 0 else 0

    # ── Decision ──────────────────────────────────────────────────
    annual_sro_saving   = (surplus_s - surplus_p) * 12
    optimal             = "SRO" if annual_sro_saving >= 0 else "PERSONAL"
    break_even          = math.ceil(SRO_SETUP_COST / (annual_sro_saving / 12)) \
                         if annual_sro_saving > 0 else None

    # ── Class: discount to the regional median €/m² ───────────────
    median = regional_median_price(district)
    discount = discount_to_median(price_eur, size_m2, district)
    cls = classify(discount)

    # Recommendation
    parts = []
    if discount is None:
        parts.append("⚪ WHITE — no regional price benchmark for this district.")
    else:
        where = (f"{abs(discount)*100:.0f}% {'below' if discount >= 0 else 'above'} "
                 f"the regional median (€{price_eur/size_m2:,.0f} vs €{median:,.0f}/m²)")
        label = {"GREEN": "🟢 GREEN", "YELLOW": "🟡 YELLOW", "WHITE": "⚪ WHITE"}[cls]
        parts.append(f"{label} — {where}, gross yield {gross_yield*100:.1f}%.")
        if discount > 1 - REGIONAL_PRICE_FLOOR_RATIO:
            parts.append("⚠️ Below the sanity floor — almost certainly not this "
                         "flat's own price.")
        elif discount >= NEAR_FLOOR_DISCOUNT:
            parts.append("⚠️ Close to the sanity floor — confirm the price is this "
                         "flat's own, not a deposit, an 'od €X' price or another listing's.")
    parts.append(f"Self-funding at {ltv*100:.0f}% LTV: {ratio_s*100:.0f}% (s.r.o.).")

    if annual_sro_saving > 0:
        parts.append(f"s.r.o. saves €{annual_sro_saving:,.0f}/yr vs personal. "
                     f"Setup cost recovered in {break_even} months.")
    else:
        parts.append("Personal ownership marginally better — low income band.")

    if is_industrial_zone(district):
        parts.append(f"⚙️ Industrial zone premium applied ({district}).")

    # Description-derived rent premiums (only when no manual override was given).
    if rent_override is None:
        if parking:
            parts.append("🅿️ Parking premium applied.")
        if _furnished_multiplier(furnished) > 1.0:
            parts.append(f"🛋️ Furnished premium applied ({furnished}).")
        if balcony:
            parts.append("🌿 Balcony premium applied.")

    return FinancialResult(
        listing_id            = listing_id,
        price_eur             = price_eur,
        size_m2               = size_m2,
        district              = district,
        loan_amount           = loan_amount,
        equity_invested       = equity,
        acquisition_costs     = round(acquisition, 2),
        total_cash_invested   = round(cash_invested, 2),
        estimated_rent        = rent,
        mortgage_monthly      = round(mortgage_mo, 2),
        mortgage_interest_monthly  = round(interest_mo, 2),
        mortgage_principal_monthly = round(principal_mo, 2),
        hoa_monthly           = round(hoa_mo, 2),
        property_tax_monthly  = round(prop_tax_mo, 2),
        vacancy_cost          = round(vacancy_mo, 2),
        maintenance_monthly   = round(owner_reserve_mo, 2),
        management_monthly    = round(mgmt_mo, 2),
        income_tax_personal   = round(tax_p_mo, 2),
        health_levy_personal  = round(levy_p_mo, 2),
        total_costs_personal  = round(total_p_mo, 2),
        surplus_personal      = round(surplus_p, 2),
        ratio_personal        = round(ratio_p, 4),
        income_tax_sro        = round(tax_s_mo, 2),
        health_levy_sro       = round(levy_s_mo, 2),
        total_costs_sro       = round(total_s_mo, 2),
        surplus_sro           = round(surplus_s, 2),
        ratio_sro             = round(ratio_s, 4),
        noi_monthly           = round(noi_mo, 2),
        cap_rate              = round(cap_rate, 4),
        cash_on_cash          = round(coc, 4),
        net_rental_yield      = round(net_yield, 4),
        gross_yield           = round(gross_yield, 4),
        principal_paydown_monthly = round(principal_mo, 2),
        total_return_annual   = round(total_return_annual, 2),
        total_roi             = round(total_roi, 4),
        regional_median_m2    = median,
        market_discount       = round(discount, 4) if discount is not None else None,
        optimal_structure     = optimal,
        annual_sro_saving     = round(annual_sro_saving, 2),
        sro_break_even_months = break_even,
        classification        = cls,
        recommendation        = " ".join(parts),
        mortgage_rate         = rate,
        ltv                   = ltv,
        loan_term_years       = term_years,
    )


def classify(market_discount: Optional[float]) -> str:
    """GREEN / YELLOW / WHITE from the discount to the regional median €/m².
    No benchmark (blank or unknown district) is WHITE: nothing says it's cheap.
    Neither is a price below the sanity floor — the scrapers zero those as
    deposits, "od €X" starting prices or another listing's price.

    The discount is judged at the 4 decimals it is stored and shown with. A
    price exactly 20% under the median works out to 0.19999999999999996 in
    floating point, which came out YELLOW beside a stored "20% below"."""
    if market_discount is None:
        return "WHITE"
    d = round(market_discount, 4)
    if d > 1 - REGIONAL_PRICE_FLOOR_RATIO:
        return "WHITE"
    if d >= GREEN_DISCOUNT:
        return "GREEN"
    if d >= YELLOW_DISCOUNT:
        return "YELLOW"
    return "WHITE"


def discount_to_median(price_eur: float, size_m2: float, district: str) -> Optional[float]:
    """How far the asking €/m² sits below the regional median (0.2 = 20%
    below; negative = above). None without a benchmark, a price or a size."""
    median = regional_median_price(district or "")
    if not median or not size_m2 or size_m2 <= 0 or not price_eur or price_eur <= 0:
        return None
    return 1 - (price_eur / size_m2) / median


def class_at_price(price_eur: float, size_m2: float, district: str) -> str:
    """The class a listing would get at `price_eur` — what analyse() would
    say, without the cashflow work. For a price cut or a what-if offer: a
    price below the sanity floor comes out WHITE, not as a bargain."""
    return classify(discount_to_median(price_eur, size_m2, district))


# ── Max offer price ───────────────────────────────────────────────────────────
TARGET_DISCOUNTS = {"GREEN": GREEN_DISCOUNT, "YELLOW": YELLOW_DISCOUNT}


def max_offer_price(size_m2: float, district: str, target: str = "YELLOW", *,
                    step: float = 500.0) -> Optional[float]:
    """The highest price at which the listing still classifies as `target`,
    rounded DOWN to `step`.

    The class is the discount to the regional median €/m² (classify), so the
    boundary is median × size × (1 − threshold). That figure is then checked
    through analyse() itself and stepped down if rounding left it a hair
    short, so the answer can never promise a class analyse() wouldn't give.
    Financing doesn't enter: the class doesn't depend on it. None when the
    district has no regional median (such a listing is WHITE at any price).
    """
    threshold = TARGET_DISCOUNTS[target.upper()]
    if not size_m2 or size_m2 <= 0:
        return None
    median = regional_median_price(district or "")
    if not median:
        return None
    wanted = ("GREEN",) if target.upper() == "GREEN" else ("GREEN", "YELLOW")
    price = math.floor(median * size_m2 * (1 - threshold) / step) * step
    for _ in range(4):
        if price <= 0:
            return None
        if classify(1 - (price / size_m2) / median) in wanted:
            return price
        price -= step
    return None


# ── Stress test ───────────────────────────────────────────────────────────────
def rate_shock(price_eur: float, size_m2: float, district: str, *,
               shock: float = RATE_SHOCK_PP, rate: float = MORTGAGE_RATE_PA,
               **kwargs) -> FinancialResult:
    """analyse() at the mortgage rate + `shock` (default +2 pp, the NBS
    affordability stress). Whatever else is passed goes straight through."""
    return analyse(price_eur, size_m2, district, rate=rate + shock, **kwargs)


# ── Hold-period IRR ───────────────────────────────────────────────────────────
def amortization_schedule(principal: float, rate: float = MORTGAGE_RATE_PA,
                          years: int = LOAN_TERM_YEARS) -> list[tuple[float, float, float]]:
    """Per loan year: (interest paid, principal repaid, balance at year end)."""
    if principal <= 0:
        return [(0.0, 0.0, 0.0)] * years
    payment = calc_mortgage(principal, rate, years)
    r = rate / 12
    bal = principal
    out = []
    for _ in range(years):
        interest_y = principal_y = 0.0
        for _ in range(12):
            i = bal * r
            p = min(payment - i, bal)
            bal -= p
            interest_y += i
            principal_y += p
        out.append((interest_y, principal_y, max(bal, 0.0)))
    return out


def irr(cash_flows: list[float]) -> Optional[float]:
    """Annual internal rate of return of yearly cash flows (t=0 first), by
    bisection. None when there is no sign change to solve for."""
    if not cash_flows or cash_flows[0] >= 0 or all(c <= 0 for c in cash_flows):
        return None

    def npv(r: float) -> float:
        return sum(c / (1 + r) ** t for t, c in enumerate(cash_flows))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return round((lo + hi) / 2, 4)


@dataclass
class IrrResult:
    structure:          str
    hold_years:         int
    irr:                Optional[float]
    equity_multiple:    Optional[float]
    cash_flows:         list
    sale_price:         float
    exit_costs:         float
    loan_balance_exit:  float
    exit_tax:           float
    net_sale_proceeds:  float
    total_profit:       float


def project_irr(price_eur: float, size_m2: float, district: str, *,
                structure: str = "SRO", rent: Optional[float] = None,
                ltv: Optional[float] = None, rate: float = MORTGAGE_RATE_PA,
                term_years: int = LOAN_TERM_YEARS,
                hold_years: int = HOLD_YEARS,
                appreciation: float = APPRECIATION_RATE,
                rent_growth: float = RENT_GROWTH_RATE,
                cost_inflation: float = COST_INFLATION_RATE,
                exit_cost_rate: float = EXIT_COST_RATE,
                rooms=None, parking=None, furnished=None, balcony=None,
                rent_rates=None) -> IrrResult:
    """Buy, hold `hold_years`, sell — and the IRR of the equity cash flows.

    Year 0 is the cash put in (deposit + acquisition costs). Each year after
    is that year's after-tax cashflow on the same cost model as analyse(),
    with rent growing at rent_growth, HOA at cost_inflation, and the interest
    share of the fixed annuity falling as the loan amortises (which moves the
    s.r.o. tax). The last year adds the sale: appreciated price, less exit
    costs, the loan balance still owed, and tax on the gain —
      personal: exempt once held ≥ PERSONAL_CGT_EXEMPT_YEARS, else income tax
                on the gain stacked on that year's rental income;
      s.r.o.:   corporate + dividend tax, with the sale counted as revenue (it
                usually lifts the company past the reduced-rate limit, so even a
                sale at no gain costs that year's rental profit the 10% rate).
    exit_tax is the whole extra tax the sale causes that year.
    Appreciation is not modelled anywhere else; this is the one place it shows.
    """
    structure = structure.upper()
    if ltv is None:
        ltv = default_ltv()
    if rent is None:
        rent = get_rent_estimate(district, size_m2, rooms, parking, furnished,
                                 balcony, rates=rent_rates)
    hold_years = max(int(hold_years), 1)

    loan = price_eur * ltv
    acquisition = price_eur * ACQUISITION_COST_RATE
    equity_in = price_eur * (1 - ltv) + acquisition
    payment_y = calc_mortgage(loan, rate, term_years) * 12
    schedule = amortization_schedule(loan, rate, term_years)
    prop_tax_y = price_eur * PROPERTY_TAX_RATE_PA
    hoa_mo = calc_hoa(size_m2)
    var_cost_rate = VACANCY_RATE + OWNER_RESERVE_RATE + PROPERTY_MGMT_RATE

    def personal_tax(taxable: float) -> float:
        return calc_income_tax_personal(max(taxable, 0.0))

    flows = [-equity_in]
    sale_price = exit_costs = balance = exit_tax = 0.0
    for t in range(1, hold_years + 1):
        rent_y = rent * 12 * (1 + rent_growth) ** (t - 1)
        hoa_y = hoa_mo * 12 * (1 + cost_inflation) ** (t - 1)
        noi = rent_y - hoa_y - prop_tax_y - rent_y * var_cost_rate
        if t <= term_years:
            interest, _, balance = schedule[t - 1]
            debt = payment_y
        else:
            interest, debt, balance = 0.0, 0.0, 0.0

        op_taxable_p = max(noi - RENTAL_INCOME_EXEMPTION, 0.0)
        op_taxable_s = max(noi - interest, 0.0)
        if t < hold_years:
            tax = (calc_tax_sro(op_taxable_s, rent_y) if structure == "SRO"
                   else personal_tax(op_taxable_p))
            flows.append(noi - debt - tax)
            continue

        # Exit year: operating cashflow + sale, taxed together.
        sale_price = price_eur * (1 + appreciation) ** hold_years
        exit_costs = sale_price * exit_cost_rate
        gain = max(sale_price - exit_costs - price_eur - acquisition, 0.0)
        if structure == "SRO":
            op_tax = calc_tax_sro(op_taxable_s, rent_y)
            all_tax = calc_tax_sro(op_taxable_s + gain, rent_y + sale_price)
        else:
            op_tax = personal_tax(op_taxable_p)
            taxed_gain = 0.0 if hold_years >= PERSONAL_CGT_EXEMPT_YEARS else gain
            all_tax = personal_tax(op_taxable_p + taxed_gain)
        exit_tax = all_tax - op_tax
        flows.append(noi - debt - all_tax + sale_price - exit_costs - balance)

    net_sale = sale_price - exit_costs - balance - exit_tax
    returned = sum(flows[1:])
    return IrrResult(
        structure         = structure,
        hold_years        = hold_years,
        irr               = irr(flows),
        equity_multiple   = round(returned / equity_in, 3) if equity_in > 0 else None,
        cash_flows        = [round(f, 2) for f in flows],
        sale_price        = round(sale_price, 2),
        exit_costs        = round(exit_costs, 2),
        loan_balance_exit = round(balance, 2),
        exit_tax          = round(exit_tax, 2),
        net_sale_proceeds = round(net_sale, 2),
        total_profit      = round(returned - equity_in, 2),
    )


def deal_extras(r: FinancialResult) -> dict:
    """The derived figures stored next to a score: max offer prices, the
    +2 pp rate shock and the hold-period IRRs. All are worked out on the
    score's own rent and financing, so they agree with it. (Value vs the
    regional market is already on the score: market_discount.)"""
    kw = dict(rent=r.estimated_rent, ltv=r.ltv, rate=r.mortgage_rate,
              term_years=r.loan_term_years)
    shocked = rate_shock(r.price_eur, r.size_m2, r.district,
                         rent_override=r.estimated_rent, ltv=r.ltv,
                         rate=r.mortgage_rate, term_years=r.loan_term_years)
    return {
        "max_price_green":    max_offer_price(r.size_m2, r.district, "GREEN"),
        "max_price_yellow":   max_offer_price(r.size_m2, r.district, "YELLOW"),
        "stress_surplus_sro": shocked.surplus_sro,
        "stress_ratio_sro":   shocked.ratio_sro,
        "irr_sro":            project_irr(r.price_eur, r.size_m2, r.district,
                                          structure="SRO", **kw).irr,
        "irr_personal":       project_irr(r.price_eur, r.size_m2, r.district,
                                          structure="PERSONAL", **kw).irr,
    }


def compute_deal_score(row: dict) -> tuple[int, str]:
    """Blend financial + location + energy + risk into a single 0–100 deal score
    and an A–D grade, so ranking reflects more than just financing-sensitive
    cashflow (a GREEN deal in a POOR location shouldn't outrank a solid one).

    Each component contributes points out of its own max; only components with
    data are counted, and the score is rescaled to 100 over the available maxima
    so a missing location score (no Google API) doesn't unfairly sink the grade.

    Components & weights:
      Financial (50): cap rate (25) + discount to the regional median (25)
      Location  (30): location_score / 100
      Energy    (10): A→10, B→7, C→4, else partial
      Condition (10): new→10, renovated→8, good→5, original→2, poor→0
                      (parsed from the listing description; skipped when unknown)
      Risk      (10): clean LV / no construction / no noise / not in Q100 flood area

    Returns (score 0–100, grade in {A,B,C,D}). Returns (0, "—") when there's no
    financial data to score at all.
    """
    points = 0.0
    max_pts = 0.0

    # ── Financial (yield + discount) ──
    # The self-funding ratio used to be the second half. It sits at 0.60–0.75
    # for flats at the median price everywhere (see config.py), so its
    # 0.80 → 1.15 scale gave nearly every listing zero points.
    cap = row.get("cap_rate")
    discount = row.get("market_discount")
    if cap is not None or discount is not None:
        if cap is not None:
            points += max(0.0, min(cap / 0.06, 1.0)) * 25   # 6%+ cap = full marks
            max_pts += 25
        if discount is not None:
            # At or above the median → 0 pts, 30%+ below → full 25
            points += max(0.0, min(discount / 0.30, 1.0)) * 25
            max_pts += 25
    else:
        return 0, "—"

    # ── Location ──
    loc = row.get("location_score")
    if loc is not None:
        points += max(0.0, min(loc / 100.0, 1.0)) * 30
        max_pts += 30

    # ── Energy class ──
    energy = (row.get("energy_class") or "").upper()
    if energy and energy != "UNKNOWN":
        energy_pts = {"A0": 10, "A1": 10, "A": 10, "B": 7, "C": 4,
                      "D": 2, "E": 1, "F": 0, "G": 0}.get(energy, 0)
        points += energy_pts
        max_pts += 10

    # ── Condition (renovation state parsed from the description) ──
    # Mirrors the energy component: only counted when a real condition is known,
    # so listings without a parsed description aren't penalised or rescaled.
    condition = (row.get("condition") or "").lower()
    cond_pts = {"new": 10, "renovated": 8, "good": 5, "original": 2, "poor": 0}
    if condition in cond_pts:
        points += cond_pts[condition]
        max_pts += 10

    # ── Risk (LV / construction / noise / flood) ──
    # Flags come from modules/risk_data; NULL (unknown) costs nothing. The
    # site flags share 8 points and the LV has its own 2, so a flat with every
    # site flag still loses points for an unverified title deed (one pool of
    # 10 hit 0 at three flags, and the LV deduction then counted for nothing).
    site_flags = sum(bool(row.get(k))
                     for k in ("construction_risk", "noise_flag", "flood_zone"))
    points += max(0, 8 - 4 * site_flags)
    if row.get("lv_status") in ("PASS", "CLEAN", None):
        points += 2
    max_pts += 10

    score = round(points / max_pts * 100) if max_pts else 0
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"
    return score, grade


def result_to_db_dict(r: FinancialResult) -> dict:
    """Convert FinancialResult to flat dict for database insertion."""
    return {
        "listing_id":             r.listing_id,
        "estimated_rent_eur":     r.estimated_rent,
        "mortgage_monthly":       r.mortgage_monthly,
        "hoa_monthly":            r.hoa_monthly,
        "property_tax_monthly":   r.property_tax_monthly,
        "vacancy_cost":           r.vacancy_cost,
        "maintenance_monthly":    r.maintenance_monthly,
        "management_monthly":     r.management_monthly,
        "income_tax_personal":    r.income_tax_personal,
        "health_levy_personal":   r.health_levy_personal,
        "total_costs_personal":   r.total_costs_personal,
        "surplus_personal":       r.surplus_personal,
        "ratio_personal":         r.ratio_personal,
        "income_tax_sro":         r.income_tax_sro,
        "health_levy_sro":        r.health_levy_sro,
        "total_costs_sro":        r.total_costs_sro,
        "surplus_sro":            r.surplus_sro,
        "ratio_sro":              r.ratio_sro,
        "noi_monthly":            r.noi_monthly,
        "cap_rate":               r.cap_rate,
        "cash_on_cash":           r.cash_on_cash,
        "net_rental_yield":       r.net_rental_yield,
        "gross_yield":            r.gross_yield,
        "principal_paydown_monthly": r.principal_paydown_monthly,
        "total_return_annual":    r.total_return_annual,
        "total_roi":              r.total_roi,
        "regional_median_m2":     r.regional_median_m2,
        "market_discount":        r.market_discount,
        "acquisition_costs":      r.acquisition_costs,
        "total_cash_invested":    r.total_cash_invested,
        "optimal_structure":      r.optimal_structure,
        "classification":         r.classification,
        "annual_sro_saving":      r.annual_sro_saving,
        "sro_break_even_months":  r.sro_break_even_months,
        "scored_at":              datetime.now(timezone.utc).isoformat(),
        "mortgage_rate_used":     r.mortgage_rate,
        "ltv_used":               r.ltv,
        "loan_term_years":        r.loan_term_years,
    }


if __name__ == "__main__":
    # Quick test — 3 representative properties
    test_cases = [
        (185_000, 52, "Bratislava II"),
        (98_000,  65, "Nitra"),
        (112_000, 58, "Žilina"),
    ]
    for price, size, district in test_cases:
        r = analyse(price, size, district)
        print(f"\n{'─'*55}")
        print(f"  {district} | €{price:,} | {size}m²")
        print(f"  Rent: €{r.estimated_rent:,.0f}/mo")
        print(f"  PERSONAL: surplus €{r.surplus_personal:+,.0f}/mo | ratio {r.ratio_personal*100:.1f}%")
        print(f"  s.r.o.:   surplus €{r.surplus_sro:+,.0f}/mo | ratio {r.ratio_sro*100:.1f}%")
        print(f"  CoC: {r.cash_on_cash*100:.2f}% | Yield: {r.net_rental_yield*100:.2f}%")
        print(f"  → {r.classification} | below market: "
              f"{(r.market_discount or 0)*100:.0f}% | Optimal: {r.optimal_structure}")
        print(f"  💡 {r.recommendation}")

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
import re
import statistics
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    MORTGAGE_RATE_PA, LOAN_TERM_YEARS, LTV_RATIO,
    tax_rules, TAX_YEAR,
    PROPERTY_TAX_RATE_PA, VACANCY_RATE, OWNER_RESERVE_RATE, PROPERTY_MGMT_RATE,
    ACQUISITION_COST_RATE,
    HOA_SMALL, HOA_MEDIUM, HOA_LARGE, HOA_PREMIUM,
    GREEN_DISCOUNT, YELLOW_DISCOUNT, NEAR_FLOOR_DISCOUNT, SRO_SETUP_COST,
    SRO_ANNUAL_RUNNING_COST, SRO_RATE_PREMIUM_PP, SRO_LTV_RATIO,
    CASHFLOW_MIN_SURPLUS,
    RENT_PER_M2, INDUSTRIAL_ZONES, INDUSTRIAL_RENT_PREMIUM,
    PARKING_RENT_PREMIUM, FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
    BALCONY_RENT_PREMIUM,
    LTV_RATIO_INVESTOR, INVESTOR_LTV_FROM, PROPERTIES_OWNED, RATE_SHOCK_PP,
    HOLD_YEARS, APPRECIATION_RATE, RENT_GROWTH_RATE, COST_INFLATION_RATE,
    EXIT_COST_RATE,
)
from engine.regional_prices import (
    benchmark_median, kraj_for_district, KRAJ_NAMES,
    REGIONAL_PRICE_FLOOR_RATIO,
)

# Bumped whenever a change to the model moves the figures of a listing that
# was already scored (here: the s.r.o.'s running cost and company-loan terms,
# the room-adjusted benchmark, the rent fallbacks). A stored score from an
# older model is redone on the next scoring run
# (database.requeue_scores_from_older_model).
SCORING_MODEL_VERSION = 2


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

    # Financing the figures were worked out with. The personal scenario uses
    # mortgage_rate / ltv; the s.r.o. borrows on its own terms (sro_financing).
    mortgage_rate:          float = MORTGAGE_RATE_PA
    ltv:                    float = LTV_RATIO
    loan_term_years:        int   = LOAN_TERM_YEARS
    sro_mortgage_rate:      float = MORTGAGE_RATE_PA + SRO_RATE_PREMIUM_PP
    sro_ltv:                float = SRO_LTV_RATIO
    loan_amount_sro:        float = 0.0
    mortgage_monthly_sro:   float = 0.0
    total_cash_invested_sro: float = 0.0
    sro_running_cost_monthly: float = 0.0

    rooms:                  Optional[int] = None
    rent_key:               str   = ""      # RENT_PER_M2 / kraj key the rent came from
    tax_year:               int   = TAX_YEAR  # the tax table the taxes came from

    @property
    def cashflow_negative(self) -> bool:
        """True when neither structure clears CASHFLOW_MIN_SURPLUS a month —
        the class says the price is cheap, not that the flat pays for itself."""
        return max(self.surplus_personal, self.surplus_sro) < CASHFLOW_MIN_SURPLUS


def is_cashflow_negative(surplus) -> bool:
    """A stored monthly surplus below CASHFLOW_MIN_SURPLUS. None (not scored)
    is not negative: there is nothing to say yet."""
    return surplus is not None and surplus < CASHFLOW_MIN_SURPLUS


def sro_financing(ltv: float, rate: float, sro_ltv: Optional[float] = None,
                  sro_rate_premium: Optional[float] = None) -> tuple[float, float]:
    """(LTV, rate) the s.r.o. borrows at, given the personal ones: a company
    loan is commercial, priced above the hypotéka rate and lent on a lower
    share of the price (config SRO_RATE_PREMIUM_PP / SRO_LTV_RATIO). The
    LTV never exceeds the personal one."""
    premium = SRO_RATE_PREMIUM_PP if sro_rate_premium is None else sro_rate_premium
    cap = SRO_LTV_RATIO if sro_ltv is None else sro_ltv
    return min(ltv, cap), rate + premium


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


def calc_income_tax_personal(annual_net: float, rules: Optional[dict] = None) -> float:
    """Personal income tax on `annual_net` under a year's tax table
    (config.tax_rules; default the current tax year)."""
    t = rules or tax_rules()
    if annual_net <= 0:
        return 0.0
    threshold = t["personal_threshold"]
    if annual_net <= threshold:
        return annual_net * t["personal_rate_low"]
    return (threshold * t["personal_rate_low"] +
            (annual_net - threshold) * t["personal_rate_high"])


def sro_corporate_rate(annual_revenue: float, rules: Optional[dict] = None) -> float:
    """Reduced corporate rate applies below the small-company revenue limit."""
    t = rules or tax_rules()
    return (t["sro_rate_reduced"] if annual_revenue <= t["sro_reduced_revenue_limit"]
            else t["sro_rate"])


def calc_tax_sro(annual_taxable: float, annual_revenue: float,
                 rules: Optional[dict] = None) -> float:
    """Combined s.r.o. tax on rental profit: corporate income tax PLUS dividend
    withholding tax on the distributed remainder (the double-taxation that makes
    s.r.o. less of a slam-dunk than a flat corporate rate suggests)."""
    t = rules or tax_rules()
    if annual_taxable <= 0:
        return 0.0
    corp = annual_taxable * sro_corporate_rate(annual_revenue, t)
    dividend = max(annual_taxable - corp, 0) * t["dividend_tax"]
    return corp + dividend


_CITY_ONLY_KEYS = {"bratislava", "košice"}  # used only as last-resort city fallbacks


def _fold(text: str) -> str:
    """Lower-case without diacritics: "Petržalka" → "petrzalka"."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()

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
    key = _fold(key)
    return "bratislava" not in key and any(_fold(t) in key for t in _OUTSIDE_BA_KEYS)

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
# A key matches only as whole words, and with or without diacritics:
# "rača" is not in "Kráčany", "bratislava i" is not the start of
# "Bratislava IV", and a portal's "petrzalka" is Petržalka.
_KEY_PATTERNS = {k: re.compile(rf"(?<!\w){re.escape(_fold(k))}(?!\w)")
                 for k in _KEYS_BY_SPECIFICITY}

# Words that name no place on their own. A district that is only these ("Nové",
# "Mesto", "Banská") used to match the first longer key containing it — "Nové"
# and "Mesto" both came out as Nové Mesto nad Váhom's €6.80.
_GENERIC_PLACE_WORDS = {
    "nove", "nova", "novy", "mesto", "stare", "stara", "stary", "nad", "pri",
    "pod", "okres", "okolie", "kraj", "banska", "spisska", "dolny", "horny",
    "velky", "velke", "maly", "male", "liptovsky", "kysucke", "dunajska",
    "rimavska", "povazska", "zlate", "turcianske", "mestska", "cast",
}


# Towns in neither RENT_PER_M2 nor anywhere near one of its keys still have a
# kraj (engine.regional_prices), and a kraj's small towns rent for far less —
# or, around Bratislava, far more — than the national €6.50 default. Such a
# town is priced at the median of its kraj's towns in the table (the cities
# and city districts left out). Keyed by the kraj's name so live rent comps
# can collect under it like any other key.
def _kraj_rent_fallbacks() -> dict[str, float]:
    by_kraj: dict[str, list[float]] = {}
    for key, rate in RENT_PER_M2.items():
        if (key == "default" or key in _BA_CITY_PART_KEYS
                or re.fullmatch(r"(bratislava|košice)( [iv]+)?", key)):
            continue
        kraj = kraj_for_district(key)
        if kraj:
            by_kraj.setdefault(kraj, []).append(rate)
    return {KRAJ_NAMES[k].lower(): round(statistics.median(v), 2)
            for k, v in by_kraj.items()}


KRAJ_RENT_FALLBACK = _kraj_rent_fallbacks()
_KEYS_BY_FOLDED = {_fold(k): k for k in list(RENT_PER_M2) + list(KRAJ_RENT_FALLBACK)
                   if k != "default"}


def baseline_rent(key: str) -> float:
    """The published-baseline €/m² for a rent key: its RENT_PER_M2 entry, its
    kraj fallback, else the national default."""
    return RENT_PER_M2.get(key) or KRAJ_RENT_FALLBACK.get(key) or RENT_PER_M2["default"]


def rent_fallback_kind(key: str) -> Optional[str]:
    """"default" (the national €/m² — the town is in no table), "kraj" (the
    median of the kraj's towns), or None for a key that names the place."""
    if not key or key == "default":
        return "default"
    if key in KRAJ_RENT_FALLBACK and key not in RENT_PER_M2:
        return "kraj"
    return None

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
    """The rent key a district string resolves to: a RENT_PER_M2 key, a kraj
    fallback (KRAJ_RENT_FALLBACK), or "default" when nothing matches. Live
    rent comps are aggregated under these same keys (engine/rent_comps), so a
    live rate replaces exactly the baseline it is measured against."""
    key = (district or "").lower().strip()
    folded = _fold(key)

    # 1. Exact match — including the city-only keys and the kraj fallbacks.
    if key in RENT_PER_M2 or key in KRAJ_RENT_FALLBACK:
        return key
    if folded in _KEYS_BY_FOLDED:
        return _KEYS_BY_FOLDED[folded]

    # 2. A known district name appears in the address string as whole words.
    # Iterate longest-first so "petržalka" beats "ružinov" when both are
    # subsumed; suburbs/specific districts are preferred over bare city
    # names ("bratislava", "košice"), which are reserved as final fallbacks.
    outside_ba = _names_town_outside_bratislava(key)
    for known in _KEYS_BY_SPECIFICITY:
        if outside_ba and known in _BA_CITY_PART_KEYS:
            continue
        if _KEY_PATTERNS[known].search(folded):
            return known

    # 3. A shortened name: the district is the first word(s) of exactly one
    # key ("Žiar" → "žiar nad hronom"). A district made only of words that
    # name no place ("Nové", "Mesto") matches nothing here.
    words = re.findall(r"\w+", folded)
    if words and not all(w in _GENERIC_PLACE_WORDS for w in words):
        prefix = " ".join(words)
        hits = [k for k in _KEYS_BY_SPECIFICITY
                if " ".join(re.findall(r"\w+", _fold(k))).startswith(prefix + " ")]
        if len(hits) == 1:
            return hits[0]

    # 4. City-name anchor.
    for city, fallback_key in _CITY_ANCHORS:
        if _fold(city) in folded:
            return fallback_key if fallback_key in RENT_PER_M2 else "default"

    # 5. A town with no rent entry of its own: its kraj's median.
    kraj = kraj_for_district(key)
    if kraj and KRAJ_NAMES[kraj].lower() in KRAJ_RENT_FALLBACK:
        return KRAJ_NAMES[kraj].lower()

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
    return baseline_rent(k), k, "baseline"


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
    tax_year: Optional[int] = None,
    sro_ltv: Optional[float] = None,
    sro_rate_premium: Optional[float] = None,
    sro_running_cost: Optional[float] = None,
) -> FinancialResult:
    """Score one property under both ownership structures.

    ltv defaults to default_ltv() — 80%, or the 70% investor cap when
    PROPERTIES_OWNED says this is a 3rd+ property. rate / term_years default to
    config and exist so the what-if panel and the stress test can vary them.
    The s.r.o. borrows on its own terms (sro_financing: rate + premium, LTV
    capped) and pays its running cost every year; sro_* override those.
    rent_rates is an optional {rent key: €/m²} of live comps. tax_year picks
    the tax table (config.tax_rules; default the current tax year).
    """
    if ltv is None:
        ltv = default_ltv()
    rules = tax_rules(tax_year)
    sro_ltv_used, sro_rate = sro_financing(ltv, rate, sro_ltv, sro_rate_premium)
    running_annual = SRO_ANNUAL_RUNNING_COST if sro_running_cost is None else sro_running_cost

    acquisition     = price_eur * ACQUISITION_COST_RATE
    rent_key        = match_rent_key(district)
    rent            = rent_override or get_rent_estimate(
        district, size_m2, rooms, parking, furnished, balcony, rates=rent_rates)
    annual_rent     = rent * 12

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

    # ── Personal scenario (passive §6(3): no health levy, €500 exempt) ──
    # Mortgage (annuity) split into interest vs principal — principal is equity
    # buildup, not an expense, so it's tracked separately for total-return math.
    loan_amount     = price_eur * ltv
    equity          = price_eur * (1 - ltv)
    cash_invested   = equity + acquisition
    mortgage_mo     = calc_mortgage(loan_amount, rate, term_years)
    interest_mo, principal_mo = first_year_amortization(loan_amount, rate, term_years)
    taxable_p       = max(noi_annual - rules["rental_exemption"], 0)
    tax_p_annual    = calc_income_tax_personal(taxable_p, rules)
    levy_p_annual   = taxable_p * rules["health_levy_personal"]  # 0 for passive rental
    tax_p_mo        = tax_p_annual / 12
    levy_p_mo       = levy_p_annual / 12
    total_p_mo      = opex_mo + mortgage_mo + tax_p_mo + levy_p_mo
    surplus_p       = rent - total_p_mo
    ratio_p         = rent / total_p_mo if total_p_mo > 0 else 0

    # ── s.r.o. scenario (company loan; deducts interest and its running
    # cost; corporate tax + dividend tax) ──
    loan_s          = price_eur * sro_ltv_used
    cash_invested_s = price_eur * (1 - sro_ltv_used) + acquisition
    mortgage_s_mo   = calc_mortgage(loan_s, sro_rate, term_years)
    interest_s_mo, principal_s_mo = first_year_amortization(loan_s, sro_rate, term_years)
    running_mo      = running_annual / 12
    taxable_s       = max(noi_annual - interest_s_mo * 12 - running_annual, 0)
    tax_s_annual    = calc_tax_sro(taxable_s, annual_rent, rules)
    tax_s_mo        = tax_s_annual / 12
    levy_s_mo       = 0.0
    total_s_mo      = opex_mo + mortgage_s_mo + running_mo + tax_s_mo + levy_s_mo
    surplus_s       = rent - total_s_mo
    ratio_s         = rent / total_s_mo if total_s_mo > 0 else 0

    # ── Key metrics (on the s.r.o.'s own financing, as before) ────
    annual_cf_sro   = surplus_s * 12
    coc             = annual_cf_sro / cash_invested_s if cash_invested_s > 0 else 0
    net_yield       = annual_cf_sro / price_eur if price_eur > 0 else 0
    gross_yield     = annual_rent / price_eur if price_eur > 0 else 0
    principal_paydown_annual = principal_s_mo * 12
    # Total return adds equity built via amortization (appreciation NOT modelled).
    total_return_annual = annual_cf_sro + principal_paydown_annual
    total_roi       = total_return_annual / cash_invested_s if cash_invested_s > 0 else 0

    # ── Decision ──────────────────────────────────────────────────
    # The s.r.o. is recommended only when it comes out ahead after its
    # running cost and company-loan terms, and that gain repays the setup
    # cost within the hold period.
    annual_sro_saving   = (surplus_s - surplus_p) * 12
    break_even          = math.ceil(SRO_SETUP_COST / (annual_sro_saving / 12)) \
                         if annual_sro_saving > 0 else None
    sro_pays            = (annual_sro_saving > 0
                           and annual_sro_saving * HOLD_YEARS > SRO_SETUP_COST)
    optimal             = "SRO" if sro_pays else "PERSONAL"

    # ── Class: discount to the room-adjusted regional median €/m² ─
    median = benchmark_median(district, rooms)
    discount = discount_to_median(price_eur, size_m2, district, rooms)
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
        if below_sanity_floor(discount):
            parts.append("⚠️ Below the sanity floor — almost certainly not this "
                         "flat's own price.")
        elif round(discount, 4) >= NEAR_FLOOR_DISCOUNT:
            parts.append("⚠️ Close to the sanity floor — confirm the price is this "
                         "flat's own, not a deposit, an 'od €X' price or another listing's.")
    best = max(surplus_p, surplus_s)
    if best < CASHFLOW_MIN_SURPLUS:
        parts.append(f"⛔ Cash-flow negative: €{best:+,.0f}/mo under the better "
                     f"structure — the class is price vs market, not income.")
    parts.append(f"Self-funding at {ltv*100:.0f}% LTV: {ratio_p*100:.0f}% personal, "
                 f"{ratio_s*100:.0f}% s.r.o. ({sro_ltv_used*100:.0f}% LTV at "
                 f"{sro_rate*100:.2f}%).")

    if sro_pays:
        parts.append(f"s.r.o. nets €{annual_sro_saving:,.0f}/yr more than personal "
                     f"after its €{running_annual:,.0f}/yr running cost. Setup cost "
                     f"recovered in {break_even} months.")
    elif annual_sro_saving > 0:
        parts.append(f"s.r.o. nets only €{annual_sro_saving:,.0f}/yr more — its "
                     f"€{SRO_SETUP_COST:,.0f} setup cost takes {break_even} months to "
                     f"recover, beyond the {HOLD_YEARS}-year hold. Personal is better.")
    else:
        parts.append(f"Personal ownership is better: the s.r.o. comes out "
                     f"€{-annual_sro_saving:,.0f}/yr worse after its running cost "
                     f"and company-loan terms.")

    if rent_override is None:
        fallback = rent_fallback_kind(rent_key)
        if fallback == "default":
            parts.append(f"⚠️ Rent uses the national default "
                         f"€{RENT_PER_M2['default']:.2f}/m² — this town is in no rent table.")
        elif fallback == "kraj":
            parts.append(f"⚠️ Rent uses the {rent_key.title()} median of its towns — "
                         f"no rent figure for this town itself.")

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
        principal_paydown_monthly = round(principal_s_mo, 2),
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
        sro_mortgage_rate     = sro_rate,
        sro_ltv               = sro_ltv_used,
        loan_amount_sro       = round(loan_s, 2),
        mortgage_monthly_sro  = round(mortgage_s_mo, 2),
        total_cash_invested_sro = round(cash_invested_s, 2),
        sro_running_cost_monthly = round(running_mo, 2),
        rooms                 = rooms,
        rent_key              = rent_key,
        tax_year              = rules["year"],
    )


def classify(market_discount: Optional[float]) -> str:
    """GREEN / YELLOW / WHITE from the discount to the regional median €/m².
    No benchmark (blank or unknown district) is WHITE: nothing says it's cheap.
    Neither is a price below the sanity floor — the scrapers zero those as
    deposits, "od €X" starting prices or another listing's price.

    The discount is judged at the 4 decimals it is stored and shown with. A
    price exactly 20% under the median works out to 0.19999999999999996 in
    floating point, which came out YELLOW beside a stored "20% below"."""
    if market_discount is None or below_sanity_floor(market_discount):
        return "WHITE"
    d = round(market_discount, 4)
    if d >= GREEN_DISCOUNT:
        return "GREEN"
    if d >= YELLOW_DISCOUNT:
        return "YELLOW"
    return "WHITE"


def below_sanity_floor(market_discount: Optional[float]) -> bool:
    """A discount so deep the price is under the regional floor — a deposit,
    an "od €X" price or another listing's, not a bargain. Judged at the 4
    decimals classify() uses, so the warning and the class always agree."""
    return (market_discount is not None
            and round(market_discount, 4) > 1 - REGIONAL_PRICE_FLOOR_RATIO)


def discount_to_median(price_eur: float, size_m2: float, district: str,
                       rooms=None) -> Optional[float]:
    """How far the asking €/m² sits below the regional median, adjusted for
    the room count (benchmark_median; 0.2 = 20% below; negative = above).
    None without a benchmark, a price or a size."""
    median = benchmark_median(district or "", rooms)
    if not median or not size_m2 or size_m2 <= 0 or not price_eur or price_eur <= 0:
        return None
    return 1 - (price_eur / size_m2) / median


def class_at_price(price_eur: float, size_m2: float, district: str,
                   rooms=None) -> str:
    """The class a listing would get at `price_eur` — what analyse() would
    say, without the cashflow work. For a price cut or a what-if offer: a
    price below the sanity floor comes out WHITE, not as a bargain."""
    return classify(discount_to_median(price_eur, size_m2, district, rooms))


# ── Max offer price ───────────────────────────────────────────────────────────
TARGET_DISCOUNTS = {"GREEN": GREEN_DISCOUNT, "YELLOW": YELLOW_DISCOUNT}


def max_offer_price(size_m2: float, district: str, target: str = "YELLOW", *,
                    rooms=None, step: float = 500.0) -> Optional[float]:
    """The highest price at which the listing still classifies as `target`,
    rounded DOWN to `step`.

    The class is the discount to the regional median €/m² (classify), so the
    boundary is median × size × (1 − threshold). That figure is then checked
    through analyse() itself and stepped down if rounding left it a hair
    short, so the answer can never promise a class analyse() wouldn't give.
    Financing doesn't enter: the class doesn't depend on it. The median is
    the room-adjusted one analyse() uses. None when the district has no
    regional median (such a listing is WHITE at any price).
    """
    threshold = TARGET_DISCOUNTS[target.upper()]
    if not size_m2 or size_m2 <= 0:
        return None
    median = benchmark_median(district or "", rooms)
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
                rent_rates=None, tax_year: Optional[int] = None,
                sro_ltv: Optional[float] = None,
                sro_rate_premium: Optional[float] = None,
                sro_running_cost: Optional[float] = None) -> IrrResult:
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

    `ltv` / `rate` are the personal terms; the s.r.o. borrows on its own
    (sro_financing) and pays its running cost every year, growing with
    cost_inflation and deductible. Every year is taxed under the tax_year
    table — later years' rules are not known yet.
    """
    structure = structure.upper()
    if ltv is None:
        ltv = default_ltv()
    rules = tax_rules(tax_year)
    running = 0.0
    if structure == "SRO":
        ltv, rate = sro_financing(ltv, rate, sro_ltv, sro_rate_premium)
        running = SRO_ANNUAL_RUNNING_COST if sro_running_cost is None else sro_running_cost
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
        return calc_income_tax_personal(max(taxable, 0.0), rules)

    flows = [-equity_in]
    sale_price = exit_costs = balance = exit_tax = 0.0
    for t in range(1, hold_years + 1):
        rent_y = rent * 12 * (1 + rent_growth) ** (t - 1)
        hoa_y = hoa_mo * 12 * (1 + cost_inflation) ** (t - 1)
        noi = (rent_y - hoa_y - prop_tax_y - rent_y * var_cost_rate
               - running * (1 + cost_inflation) ** (t - 1))
        if t <= term_years:
            interest, _, balance = schedule[t - 1]
            debt = payment_y
        else:
            interest, debt, balance = 0.0, 0.0, 0.0

        op_taxable_p = max(noi - rules["rental_exemption"], 0.0)
        op_taxable_s = max(noi - interest, 0.0)
        if t < hold_years:
            tax = (calc_tax_sro(op_taxable_s, rent_y, rules) if structure == "SRO"
                   else personal_tax(op_taxable_p))
            flows.append(noi - debt - tax)
            continue

        # Exit year: operating cashflow + sale, taxed together.
        sale_price = price_eur * (1 + appreciation) ** hold_years
        exit_costs = sale_price * exit_cost_rate
        gain = max(sale_price - exit_costs - price_eur - acquisition, 0.0)
        if structure == "SRO":
            op_tax = calc_tax_sro(op_taxable_s, rent_y, rules)
            all_tax = calc_tax_sro(op_taxable_s + gain, rent_y + sale_price, rules)
        else:
            op_tax = personal_tax(op_taxable_p)
            exempt_after = rules["personal_cgt_exempt_years"]
            taxed_gain = 0.0 if hold_years >= exempt_after else gain
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
    sro = dict(sro_ltv=r.sro_ltv, sro_rate_premium=r.sro_mortgage_rate - r.mortgage_rate,
               sro_running_cost=r.sro_running_cost_monthly * 12, tax_year=r.tax_year)
    kw = dict(rent=r.estimated_rent, ltv=r.ltv, rate=r.mortgage_rate,
              term_years=r.loan_term_years, **sro)
    shocked = rate_shock(r.price_eur, r.size_m2, r.district,
                         rent_override=r.estimated_rent, ltv=r.ltv,
                         rate=r.mortgage_rate, term_years=r.loan_term_years,
                         rooms=r.rooms, **sro)
    return {
        "max_price_green":    max_offer_price(r.size_m2, r.district, "GREEN", rooms=r.rooms),
        "max_price_yellow":   max_offer_price(r.size_m2, r.district, "YELLOW", rooms=r.rooms),
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
    # Each flag costs 4, so three go 4 below zero: floored at 0, the third
    # flag was free. The total is clamped at 0 instead.
    site_flags = sum(bool(row.get(k))
                     for k in ("construction_risk", "noise_flag", "flood_zone"))
    points += 8 - 4 * site_flags
    if row.get("lv_status") in ("PASS", "CLEAN", None):
        points += 2
    max_pts += 10

    score = max(0, round(points / max_pts * 100)) if max_pts else 0
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
        "sro_rate_used":          r.sro_mortgage_rate,
        "sro_ltv_used":           r.sro_ltv,
        "mortgage_monthly_sro":   r.mortgage_monthly_sro,
        "total_cash_invested_sro": r.total_cash_invested_sro,
        "sro_running_cost_monthly": r.sro_running_cost_monthly,
        "rent_key":               r.rent_key,
        "tax_year":               r.tax_year,
        "model_version":          SCORING_MODEL_VERSION,
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

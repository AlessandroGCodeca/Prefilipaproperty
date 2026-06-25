"""
engine/financial.py — Sovereign Investor Dashboard
Module B: 2026 Slovak Financial Engine

Dual-scenario analysis: Personal (Fyzická osoba) vs s.r.o.
Outputs: CoC, Net Yield, Self-Funding Ratio, Optimal Structure
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
    HEALTH_LEVY_PERSONAL, HEALTH_LEVY_SRO,
    PROPERTY_TAX_RATE_PA, VACANCY_RATE, OWNER_RESERVE_RATE, PROPERTY_MGMT_RATE,
    ACQUISITION_COST_RATE,
    HOA_SMALL, HOA_MEDIUM, HOA_LARGE, HOA_PREMIUM,
    GREEN_RATIO, YELLOW_RATIO, SRO_SETUP_COST,
    RENT_PER_M2, INDUSTRIAL_ZONES, INDUSTRIAL_RENT_PREMIUM,
    PARKING_RENT_PREMIUM, FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
    BALCONY_RENT_PREMIUM,
)


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

    # Decision
    optimal_structure:      str
    annual_sro_saving:      float
    sro_break_even_months:  Optional[int]
    classification:         str
    recommendation:         str


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


def get_rent_estimate(district: str, size_m2: float, rooms=None,
                      parking=None, furnished=None, balcony=None) -> float:
    key = district.lower().strip()

    # 1. Exact match — including the city-only keys.
    rate = RENT_PER_M2.get(key)

    # 2. A known district name appears inside the address string.
    # Iterate longest-first so "petržalka" beats "ružinov" when both are
    # subsumed; suburbs/specific districts are preferred over bare city
    # names ("bratislava", "košice"), which are reserved as final fallbacks.
    keys_by_specificity = sorted(
        (k for k in RENT_PER_M2 if k != "default" and k not in _CITY_ONLY_KEYS),
        key=len, reverse=True,
    )
    if rate is None:
        for known in keys_by_specificity:
            if known in key:
                rate = RENT_PER_M2[known]
                break

    # 3. Reverse: district token appears in a known key (longest-first so
    # "košice i" wins over plain "košice" when district is just "košice i")
    if rate is None and key:
        for known in keys_by_specificity:
            if key in known:
                rate = RENT_PER_M2[known]
                break

    # 4. City-name anchor: if a major city appears anywhere in the district string,
    #    use the base (non-numbered) district rate as a reasonable approximation.
    if rate is None:
        CITY_ANCHORS = [
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
        for city, fallback_key in CITY_ANCHORS:
            if city in key:
                rate = RENT_PER_M2.get(fallback_key, RENT_PER_M2["default"])
                break

    if rate is None:
        rate = RENT_PER_M2["default"]

    if any(z in key for z in INDUSTRIAL_ZONES):
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


def analyse(
    price_eur: float,
    size_m2: float,
    district: str,
    listing_id: Optional[str] = None,
    rent_override: Optional[float] = None,
    ltv: float = LTV_RATIO,
    rooms: Optional[int] = None,
    parking=None,
    furnished=None,
    balcony=None,
) -> FinancialResult:

    loan_amount     = price_eur * ltv
    equity          = price_eur * (1 - ltv)
    acquisition     = price_eur * ACQUISITION_COST_RATE
    cash_invested   = equity + acquisition
    rent            = rent_override or get_rent_estimate(
        district, size_m2, rooms, parking, furnished, balcony)
    annual_rent     = rent * 12

    # Mortgage (annuity) split into interest vs principal — principal is equity
    # buildup, not an expense, so it's tracked separately for total-return math.
    mortgage_mo     = calc_mortgage(loan_amount)
    interest_mo, principal_mo = first_year_amortization(loan_amount)

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
    levy_s_annual   = 0.0  # Exempt
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

    # Classification uses s.r.o. ratio (optimal scenario)
    if ratio_s >= GREEN_RATIO:
        cls = "GREEN"
    elif ratio_s >= YELLOW_RATIO:
        cls = "YELLOW"
    else:
        cls = "WHITE"

    # Recommendation
    parts = []
    if cls == "GREEN":
        parts.append(f"🟢 GREEN — self-funding via s.r.o. (ratio {ratio_s*100:.1f}%). Hold 20+ years.")
    elif cls == "YELLOW":
        parts.append(f"🟡 YELLOW — yield play (ratio {ratio_s*100:.1f}%). Strong income asset.")
    else:
        parts.append(f"⚪ WHITE — below threshold ({ratio_s*100:.1f}%). Flip or pass.")

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
        optimal_structure     = optimal,
        annual_sro_saving     = round(annual_sro_saving, 2),
        sro_break_even_months = break_even,
        classification        = cls,
        recommendation        = " ".join(parts),
    )


def compute_deal_score(row: dict) -> tuple[int, str]:
    """Blend financial + location + energy + risk into a single 0–100 deal score
    and an A–D grade, so ranking reflects more than just financing-sensitive
    cashflow (a GREEN deal in a POOR location shouldn't outrank a solid one).

    Each component contributes points out of its own max; only components with
    data are counted, and the score is rescaled to 100 over the available maxima
    so a missing location score (no Google API) doesn't unfairly sink the grade.

    Components & weights:
      Financial (50): cap rate (25) + self-funding ratio (25)
      Location  (30): location_score / 100
      Energy    (10): A→10, B→7, C→4, else partial
      Condition (10): new→10, renovated→8, good→5, original→2, poor→0
                      (parsed from the listing description; skipped when unknown)
      Risk      (10): clean LV / no construction / no noise

    Returns (score 0–100, grade in {A,B,C,D}). Returns (0, "—") when there's no
    financial data to score at all.
    """
    points = 0.0
    max_pts = 0.0

    # ── Financial (cap rate + self-funding ratio) ──
    cap = row.get("cap_rate")
    ratio = row.get("ratio_sro")
    if cap is not None or ratio is not None:
        if cap is not None:
            points += max(0.0, min(cap / 0.06, 1.0)) * 25   # 6%+ cap = full marks
            max_pts += 25
        if ratio is not None:
            # 0.80 ratio → 0 pts, 1.15+ (GREEN) → full 25
            points += max(0.0, min((ratio - 0.80) / 0.35, 1.0)) * 25
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

    # ── Risk (LV / construction / noise) ──
    risk_pts = 10
    if row.get("construction_risk"):
        risk_pts -= 4
    if row.get("noise_flag"):
        risk_pts -= 4
    if row.get("lv_status") not in ("PASS", "CLEAN", None):
        risk_pts -= 2
    points += max(0, risk_pts)
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
        "acquisition_costs":      r.acquisition_costs,
        "total_cash_invested":    r.total_cash_invested,
        "optimal_structure":      r.optimal_structure,
        "classification":         r.classification,
        "annual_sro_saving":      r.annual_sro_saving,
        "sro_break_even_months":  r.sro_break_even_months,
        "scored_at":              datetime.now(timezone.utc).isoformat(),
        "mortgage_rate_used":     MORTGAGE_RATE_PA,
        "ltv_used":               LTV_RATIO,
        "loan_term_years":        LOAN_TERM_YEARS,
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
        print(f"  → {r.classification} | Optimal: {r.optimal_structure}")
        print(f"  💡 {r.recommendation}")

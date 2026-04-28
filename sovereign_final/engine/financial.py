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
    TAX_RATE_SRO, HEALTH_LEVY_PERSONAL, HEALTH_LEVY_SRO,
    PROPERTY_TAX_RATE_PA, VACANCY_RATE, MAINTENANCE_RATE,
    HOA_SMALL, HOA_MEDIUM, HOA_LARGE, HOA_PREMIUM,
    GREEN_RATIO, YELLOW_RATIO, SRO_SETUP_COST,
    RENT_PER_M2, INDUSTRIAL_ZONES, INDUSTRIAL_RENT_PREMIUM,
)


@dataclass
class FinancialResult:
    listing_id:             Optional[str]
    price_eur:              float
    size_m2:                float
    district:               str
    loan_amount:            float
    equity_invested:        float
    estimated_rent:         float

    # Shared costs
    mortgage_monthly:       float
    hoa_monthly:            float
    property_tax_monthly:   float
    vacancy_cost:           float
    maintenance_monthly:    float

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
    cash_on_cash:           float
    net_rental_yield:       float
    gross_yield:            float

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


def calc_income_tax_sro(annual_net: float) -> float:
    return max(annual_net * TAX_RATE_SRO, 0)


def get_rent_estimate(district: str, size_m2: float) -> float:
    key  = district.lower().strip()
    rate = RENT_PER_M2.get(key, RENT_PER_M2["default"])
    if any(z in key for z in INDUSTRIAL_ZONES):
        rate *= INDUSTRIAL_RENT_PREMIUM
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
) -> FinancialResult:

    loan_amount     = price_eur * ltv
    equity          = price_eur * (1 - ltv)
    rent            = rent_override or get_rent_estimate(district, size_m2)

    # Shared monthly costs
    mortgage_mo     = calc_mortgage(loan_amount)
    hoa_mo          = calc_hoa(size_m2)
    prop_tax_mo     = (price_eur * PROPERTY_TAX_RATE_PA) / 12
    vacancy_mo      = rent * VACANCY_RATE
    maintenance_mo  = (price_eur * MAINTENANCE_RATE) / 12
    operating_mo    = mortgage_mo + hoa_mo + prop_tax_mo + vacancy_mo + maintenance_mo

    pre_tax_annual  = (rent - operating_mo) * 12

    # ── Personal scenario ─────────────────────────────────────────
    tax_p_annual    = calc_income_tax_personal(max(pre_tax_annual, 0))
    levy_p_annual   = max(pre_tax_annual, 0) * HEALTH_LEVY_PERSONAL
    tax_p_mo        = tax_p_annual / 12
    levy_p_mo       = levy_p_annual / 12
    total_p_mo      = operating_mo + tax_p_mo + levy_p_mo
    surplus_p       = rent - total_p_mo
    ratio_p         = rent / total_p_mo if total_p_mo > 0 else 0

    # ── s.r.o. scenario ───────────────────────────────────────────
    tax_s_annual    = calc_income_tax_sro(max(pre_tax_annual, 0))
    levy_s_annual   = 0.0  # Exempt
    tax_s_mo        = tax_s_annual / 12
    levy_s_mo       = 0.0
    total_s_mo      = operating_mo + tax_s_mo + levy_s_mo
    surplus_s       = rent - total_s_mo
    ratio_s         = rent / total_s_mo if total_s_mo > 0 else 0

    # ── Key metrics (use s.r.o. as primary — better structure) ────
    annual_cf_sro   = surplus_s * 12
    coc             = annual_cf_sro / equity if equity > 0 else 0
    net_yield       = annual_cf_sro / price_eur if price_eur > 0 else 0
    gross_yield     = (rent * 12) / price_eur if price_eur > 0 else 0

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

    return FinancialResult(
        listing_id            = listing_id,
        price_eur             = price_eur,
        size_m2               = size_m2,
        district              = district,
        loan_amount           = loan_amount,
        equity_invested       = equity,
        estimated_rent        = rent,
        mortgage_monthly      = round(mortgage_mo, 2),
        hoa_monthly           = round(hoa_mo, 2),
        property_tax_monthly  = round(prop_tax_mo, 2),
        vacancy_cost          = round(vacancy_mo, 2),
        maintenance_monthly   = round(maintenance_mo, 2),
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
        cash_on_cash          = round(coc, 4),
        net_rental_yield      = round(net_yield, 4),
        gross_yield           = round(gross_yield, 4),
        optimal_structure     = optimal,
        annual_sro_saving     = round(annual_sro_saving, 2),
        sro_break_even_months = break_even,
        classification        = cls,
        recommendation        = " ".join(parts),
    )


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
        "cash_on_cash":           r.cash_on_cash,
        "net_rental_yield":       r.net_rental_yield,
        "gross_yield":            r.gross_yield,
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

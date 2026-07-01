"""Tests for the P1 cashflow-model corrections in engine/financial.py:
  - no health levy on passive §6(3) personal rental income
  - unlevered cap rate (NOI/price), independent of financing
  - mortgage split into interest vs principal (principal = equity buildup)
  - acquisition costs folded into the cash-on-cash denominator
  - s.r.o. tax = corporate + dividend (double taxation), reduced rate for small revenue
  - industrial premium no longer double-applied to the big cities
"""

import pytest

from config import (
    HEALTH_LEVY_PERSONAL, ACQUISITION_COST_RATE, OWNER_RESERVE_RATE,
    TAX_RATE_SRO_REDUCED,
)
from engine.financial import (
    analyse, calc_mortgage, first_year_amortization,
    calc_tax_sro, sro_corporate_rate, get_rent_estimate,
)


def _deal():
    return analyse(120_000, 60.0, "Nitra")


class TestHealthLevyRemoved:
    def test_config_levy_is_zero(self):
        assert HEALTH_LEVY_PERSONAL == 0.0

    def test_personal_levy_not_charged(self):
        assert _deal().health_levy_personal == 0.0


class TestCapRate:
    def test_cap_rate_is_unlevered(self):
        # NOI/price doesn't depend on the loan — same at any LTV.
        r80 = analyse(120_000, 60.0, "Nitra", ltv=0.80)
        r50 = analyse(120_000, 60.0, "Nitra", ltv=0.50)
        assert r80.cap_rate == pytest.approx(r50.cap_rate, abs=1e-6)

    def test_cap_rate_matches_noi_over_price(self):
        r = _deal()
        assert r.cap_rate == pytest.approx((r.noi_monthly * 12) / r.price_eur, rel=1e-3)

    def test_noi_excludes_mortgage_and_tax(self):
        # NOI is rent minus operating expenses only — strictly above the cash surplus.
        r = _deal()
        assert r.noi_monthly > r.surplus_sro


class TestAmortizationSplit:
    def test_interest_plus_principal_equals_payment(self):
        payment = calc_mortgage(100_000)
        i, p = first_year_amortization(100_000)
        assert (i + p) == pytest.approx(payment, abs=0.01)

    def test_principal_is_positive(self):
        i, p = first_year_amortization(100_000)
        assert p > 0 and i > 0

    def test_total_return_adds_principal_paydown(self):
        r = _deal()
        expected = r.surplus_sro * 12 + r.principal_paydown_monthly * 12
        assert r.total_return_annual == pytest.approx(expected, abs=1.0)

    def test_zero_loan_no_amortization(self):
        assert first_year_amortization(0) == (0.0, 0.0)


class TestAcquisitionCosts:
    def test_total_cash_invested_includes_acquisition(self):
        r = _deal()
        assert r.acquisition_costs == pytest.approx(r.price_eur * ACQUISITION_COST_RATE, rel=1e-6)
        assert r.total_cash_invested == pytest.approx(
            r.equity_invested + r.acquisition_costs, abs=0.01
        )

    def test_coc_uses_total_cash_invested(self):
        r = _deal()
        assert r.cash_on_cash == pytest.approx(
            (r.surplus_sro * 12) / r.total_cash_invested, rel=1e-3
        )


class TestOwnerReserve:
    def test_maintenance_is_rent_based_not_value_based(self):
        # The 1%-of-value building reserve is gone; the field now holds the
        # in-flat owner reserve = OWNER_RESERVE_RATE × rent (HOA covers the shell).
        r = _deal()
        assert r.maintenance_monthly == pytest.approx(
            r.estimated_rent * OWNER_RESERVE_RATE, abs=0.5
        )


class TestSroTax:
    def test_reduced_rate_below_limit(self):
        assert sro_corporate_rate(50_000) == TAX_RATE_SRO_REDUCED

    def test_standard_rate_above_limit(self):
        assert sro_corporate_rate(150_000) == 0.21

    def test_combines_corporate_and_dividend(self):
        # 10% corp on 10k = 1000; dividend 10% on the remaining 9000 = 900.
        tax = calc_tax_sro(10_000, annual_revenue=50_000)
        assert tax == pytest.approx(1000 + 900, abs=1.0)

    def test_no_tax_on_loss(self):
        assert calc_tax_sro(-500, annual_revenue=50_000) == 0.0


class TestIndustrialPremiumNoLongerDoubleCounts:
    def test_zilina_uses_base_rate(self):
        # Žilina base is 10.0 €/m²/mo; the old code multiplied it by 1.12.
        rate = get_rent_estimate("Žilina", 55.0) / 55.0
        assert rate == pytest.approx(10.0, abs=0.1)

    def test_kosice_uses_base_rate(self):
        rate = get_rent_estimate("Košice", 55.0) / 55.0
        assert rate == pytest.approx(10.5, abs=0.1)

    def test_small_industrial_town_still_gets_premium(self):
        # Voderady isn't in RENT_PER_M2 → default 6.5 × 1.12 industrial premium.
        rate = get_rent_estimate("Voderady", 50.0) / 50.0
        assert rate == pytest.approx(6.5 * 1.12, abs=0.1)

"""Tests for the deal figures added to engine/financial:

- max_offer_price: the highest price that still scores YELLOW / GREEN
- market_value / discount_to_market: asking vs the regional median
- default_ltv: the NBS 70% cap on a 3rd+ property from 1 Oct 2026
- rate / term flow through analyse(); rate_shock is analyse at +2 pp
- amortization_schedule, irr, project_irr: hold-period return with exit costs
- deal_extras: everything stored next to a score agrees with that score
- compute_deal_score counts a flood-zone flag, and only a real one
"""

import pytest

from config import (
    GREEN_RATIO, YELLOW_RATIO, LTV_RATIO, LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA,
    ACQUISITION_COST_RATE,
)
from engine.financial import (
    analyse, max_offer_price, market_value, discount_to_market, default_ltv,
    rate_shock, amortization_schedule, irr, project_irr, deal_extras,
    result_to_db_dict, compute_deal_score, calc_mortgage,
)
from engine.regional_prices import CITY_MEDIAN_PRICE_PER_M2


class TestMaxOfferPrice:
    @pytest.mark.parametrize("target,ratio", [("YELLOW", YELLOW_RATIO), ("GREEN", GREEN_RATIO)])
    def test_lands_exactly_on_the_boundary(self, target, ratio):
        p = max_offer_price(58, "Žilina", target, ltv=0.8)
        assert p is not None and p % 500 == 0
        assert analyse(p, 58, "Žilina", ltv=0.8).ratio_sro >= ratio
        assert analyse(p + 500, 58, "Žilina", ltv=0.8).ratio_sro < ratio

    def test_classification_at_the_offer_is_the_target(self):
        assert analyse(max_offer_price(58, "Žilina", "GREEN", ltv=0.8), 58,
                       "Žilina", ltv=0.8).classification == "GREEN"
        assert analyse(max_offer_price(58, "Žilina", "YELLOW", ltv=0.8), 58,
                       "Žilina", ltv=0.8).classification in ("YELLOW", "GREEN")

    def test_green_is_cheaper_than_yellow(self):
        assert (max_offer_price(58, "Žilina", "GREEN", ltv=0.8)
                < max_offer_price(58, "Žilina", "YELLOW", ltv=0.8))

    def test_more_rent_allows_a_higher_price(self):
        assert (max_offer_price(58, "Žilina", rent=800, ltv=0.8)
                > max_offer_price(58, "Žilina", rent=600, ltv=0.8))

    def test_less_debt_allows_a_higher_price(self):
        assert (max_offer_price(58, "Žilina", ltv=0.5)
                > max_offer_price(58, "Žilina", ltv=0.8))

    def test_a_dearer_loan_lowers_it(self):
        assert (max_offer_price(58, "Žilina", ltv=0.8, rate=0.058)
                < max_offer_price(58, "Žilina", ltv=0.8, rate=0.038))

    def test_none_when_rent_cannot_cover_running_costs(self):
        # €40/mo can't pay the €60 HOA at any price.
        assert max_offer_price(58, "Žilina", rent=40) is None

    def test_none_without_a_size(self):
        assert max_offer_price(0, "Žilina") is None


class TestMarketValue:
    def test_city_median_times_size(self):
        assert market_value(58, "Žilina") == CITY_MEDIAN_PRICE_PER_M2["žilina"] * 58

    def test_unknown_district_has_no_market(self):
        assert market_value(58, "Atlantis") is None
        assert discount_to_market(100_000, 58, "Atlantis") is None

    def test_below_market_is_positive(self):
        mv = market_value(58, "Žilina")
        assert discount_to_market(mv * 0.8, 58, "Žilina") == pytest.approx(0.2, abs=1e-4)
        assert discount_to_market(mv * 1.1, 58, "Žilina") == pytest.approx(-0.1, abs=1e-4)


class TestDefaultLtv:
    def test_first_and_second_property_keep_80(self):
        assert default_ltv(0, on="2026-12-01") == LTV_RATIO
        assert default_ltv(1, on="2026-12-01") == LTV_RATIO

    def test_third_property_capped_from_october(self):
        assert default_ltv(2, on="2026-10-01") == LTV_RATIO_INVESTOR
        assert default_ltv(5, on="2027-03-01") == LTV_RATIO_INVESTOR

    def test_cap_not_applied_before_it_exists(self):
        assert default_ltv(2, on="2026-09-30") == LTV_RATIO

    def test_analyse_uses_it_and_records_what_it_used(self, monkeypatch):
        import engine.financial as fin
        monkeypatch.setattr(fin, "PROPERTIES_OWNED", 3)
        monkeypatch.setattr(fin, "INVESTOR_LTV_FROM", "2000-01-01")
        r = analyse(120_000, 60, "Nitra")
        assert r.ltv == LTV_RATIO_INVESTOR
        assert r.loan_amount == pytest.approx(120_000 * LTV_RATIO_INVESTOR)
        assert result_to_db_dict(r)["ltv_used"] == LTV_RATIO_INVESTOR


class TestRateAndTerm:
    def test_rate_and_term_reach_the_mortgage(self):
        base = analyse(120_000, 60, "Nitra", ltv=0.8)
        assert base.mortgage_monthly == pytest.approx(calc_mortgage(96_000), abs=0.01)
        assert analyse(120_000, 60, "Nitra", ltv=0.8, rate=0.05).mortgage_monthly > base.mortgage_monthly
        assert analyse(120_000, 60, "Nitra", ltv=0.8, term_years=30).mortgage_monthly < base.mortgage_monthly

    def test_db_dict_records_the_financing_used(self):
        d = result_to_db_dict(analyse(120_000, 60, "Nitra", ltv=0.7, rate=0.045, term_years=20))
        assert (d["ltv_used"], d["mortgage_rate_used"], d["loan_term_years"]) == (0.7, 0.045, 20)

    def test_rate_shock_is_two_points_dearer(self):
        base = analyse(120_000, 60, "Nitra", ltv=0.8)
        shocked = rate_shock(120_000, 60, "Nitra", ltv=0.8)
        assert shocked.mortgage_rate == pytest.approx(MORTGAGE_RATE_PA + 0.02)
        assert shocked.surplus_sro < base.surplus_sro
        assert shocked.ratio_sro < base.ratio_sro


class TestAmortization:
    def test_loan_is_repaid_by_the_end_of_the_term(self):
        sched = amortization_schedule(100_000, 0.04, 25)
        assert len(sched) == 25
        assert sched[-1][2] == pytest.approx(0, abs=1)
        assert sum(p for _, p, _ in sched) == pytest.approx(100_000, abs=1)

    def test_interest_falls_as_the_loan_amortises(self):
        sched = amortization_schedule(100_000, 0.04, 25)
        assert sched[0][0] > sched[10][0] > sched[20][0]


class TestIrr:
    def test_simple_cases(self):
        assert irr([-100, 110]) == pytest.approx(0.10, abs=1e-4)
        assert irr([-100, 0, 121]) == pytest.approx(0.10, abs=1e-4)

    def test_no_sign_change_has_no_irr(self):
        assert irr([100, 10]) is None
        assert irr([-100, -10]) is None
        assert irr([]) is None


class TestProjectIrr:
    def test_cash_flow_shape(self):
        res = project_irr(120_000, 60, "Nitra", ltv=0.8, hold_years=10)
        assert len(res.cash_flows) == 11
        equity_in = 120_000 * 0.2 + 120_000 * ACQUISITION_COST_RATE
        assert res.cash_flows[0] == pytest.approx(-equity_in)

    def test_personal_sale_after_five_years_is_tax_free(self):
        assert project_irr(120_000, 60, "Nitra", structure="PERSONAL", hold_years=5).exit_tax == 0

    def test_personal_sale_inside_five_years_is_taxed(self):
        res = project_irr(120_000, 60, "Nitra", structure="PERSONAL", hold_years=4,
                          appreciation=0.08)
        assert res.exit_tax > 0

    def test_sro_always_pays_tax_on_a_gain(self):
        res = project_irr(120_000, 60, "Nitra", structure="SRO", hold_years=10,
                          appreciation=0.05)
        assert res.exit_tax > 0

    def test_no_gain_no_exit_tax_under_the_revenue_limit(self):
        # €60k sale + a year's rent stays under the €100k reduced-rate limit.
        res = project_irr(60_000, 40, "Nitra", structure="SRO", hold_years=10,
                          appreciation=0.0)
        assert res.exit_tax == pytest.approx(0, abs=0.01)

    def test_a_sale_past_the_revenue_limit_loses_the_reduced_rate(self):
        # No gain on a €120k sale, but the sale is revenue: the company leaves
        # the 10% band that year, so its rental profit is taxed at 21%.
        from engine.financial import calc_tax_sro
        res = project_irr(120_000, 60, "Nitra", structure="SRO", hold_years=10,
                          appreciation=0.0)
        assert res.exit_tax > 0
        assert calc_tax_sro(1_000, 50_000) < calc_tax_sro(1_000, 150_000)

    def test_appreciation_raises_the_irr(self):
        lo = project_irr(120_000, 60, "Nitra", appreciation=0.01).irr
        hi = project_irr(120_000, 60, "Nitra", appreciation=0.05).irr
        assert hi > lo

    def test_exit_costs_lower_it(self):
        cheap = project_irr(120_000, 60, "Nitra", exit_cost_rate=0.0).irr
        dear = project_irr(120_000, 60, "Nitra", exit_cost_rate=0.06).irr
        assert dear < cheap

    def test_sale_proceeds_net_of_loan(self):
        res = project_irr(120_000, 60, "Nitra", ltv=0.8, hold_years=10, appreciation=0.0,
                          exit_cost_rate=0.0)
        assert res.sale_price == pytest.approx(120_000)
        assert res.loan_balance_exit == pytest.approx(amortization_schedule(96_000)[9][2], abs=1)


class TestDealExtras:
    def test_extras_agree_with_the_score(self):
        r = analyse(98_000, 58, "Žilina", ltv=0.8)
        e = deal_extras(r)
        assert e["max_price_green"] < e["max_price_yellow"]
        assert e["market_value_eur"] == market_value(58, "Žilina")
        assert e["discount_to_market"] == pytest.approx(1 - 98_000 / e["market_value_eur"], abs=1e-4)
        assert e["stress_ratio_sro"] < r.ratio_sro
        assert e["irr_sro"] is not None and e["irr_personal"] is not None

    def test_extras_use_the_scores_rent(self):
        r = analyse(98_000, 58, "Žilina", ltv=0.8, rent_override=900)
        assert deal_extras(r)["max_price_yellow"] == max_offer_price(58, "Žilina", rent=900, ltv=0.8)


class TestFloodInDealScore:
    BASE = {"cap_rate": 0.05, "ratio_sro": 1.1, "location_score": 70, "lv_status": "PASS"}

    def test_flood_flag_costs_points(self):
        clean, _ = compute_deal_score({**self.BASE, "flood_zone": 0})
        flooded, _ = compute_deal_score({**self.BASE, "flood_zone": 1})
        assert flooded < clean

    def test_unknown_flood_costs_nothing(self):
        assert (compute_deal_score({**self.BASE, "flood_zone": None})
                == compute_deal_score({**self.BASE, "flood_zone": 0}))

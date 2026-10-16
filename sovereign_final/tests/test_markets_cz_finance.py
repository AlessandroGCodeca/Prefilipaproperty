"""Czech tax, lending and costs (markets.CZ, engine.property_tax_cz): the
figures the engine scores a Czech listing with, and that they never reach a
Slovak one."""

import dataclasses

import pytest

import markets
from engine import financial as fin
from engine import property_tax_cz as ptax

CZ = markets.CZ


@pytest.fixture(autouse=True)
def _no_user_medians(monkeypatch):
    """The medians a user's own data/cz_regional_prices.csv loads stay out of
    these tests: each starts from the empty tables the code ships with."""
    from engine import regional_prices_cz as rpcz
    for table in ("KRAJ_MEDIAN", "OKRES_MEDIAN", "PRAHA_DISTRICT_MEDIAN",
                  "BRNO_DISTRICT_MEDIAN", "MEDIAN_SOURCE"):
        monkeypatch.setattr(rpcz, table, {})
    monkeypatch.setattr(rpcz, "_TABLES", {"kraj": rpcz.KRAJ_MEDIAN, "okres": rpcz.OKRES_MEDIAN,
                                          "praha": rpcz.PRAHA_DISTRICT_MEDIAN,
                                          "brno": rpcz.BRNO_DISTRICT_MEDIAN})
    monkeypatch.setattr(rpcz, "SOURCE", dict(rpcz._DEFAULT_SOURCE))


def _rules(year=None):
    return markets.tax_rules(year, "cz")


class TestTaxTable:
    def test_2026_table(self):
        t = _rules(2026)
        assert (t["personal_rate_low"], t["personal_rate_high"]) == (0.15, 0.23)
        assert t["personal_threshold"] == 36 * 48_967
        assert (t["rental_flat_expense_rate"], t["rental_flat_expense_cap"]) == (0.30, 600_000)
        assert t["health_levy_personal"] == 0
        assert t["personal_cgt_exempt_years"] == 10
        assert (t["sro_rate"], t["dividend_tax"]) == (0.21, 0.15)
        assert t["source"] and t["checked"]
        assert t["market"] == "cz" and not t["stale"]

    def test_a_later_year_falls_back_and_says_so(self):
        t = _rules(2031)
        assert t["year"] == 2026 and t["stale"] and t["requested"] == 2031

    def test_bands(self):
        t = _rules(2026)
        assert fin.calc_income_tax_personal(100_000, t) == pytest.approx(15_000)
        over = t["personal_threshold"] + 100_000
        assert fin.calc_income_tax_personal(over, t) == pytest.approx(
            t["personal_threshold"] * 0.15 + 100_000 * 0.23)

    def test_sro_pays_21_then_15_on_the_dividend(self):
        # No reduced small-company rate in Czechia, whatever the revenue.
        t = _rules(2026)
        assert fin.calc_tax_sro(100_000, 50_000, t) == pytest.approx(21_000 + 0.15 * 79_000)


class TestRentalBase:
    def test_flat_rate_when_it_beats_the_actual_expenses(self):
        t = _rules(2026)
        base = fin.personal_rental_base(t, noi_annual=0, rent_annual=200_000,
                                        expenses_annual=20_000, interest_annual=10_000)
        assert base == pytest.approx(200_000 * 0.70)

    def test_actual_expenses_with_interest_when_larger(self):
        t = _rules(2026)
        base = fin.personal_rental_base(t, noi_annual=0, rent_annual=200_000,
                                        expenses_annual=30_000, interest_annual=100_000)
        assert base == pytest.approx(70_000)

    def test_flat_rate_is_capped(self):
        t = _rules(2026)
        base = fin.personal_rental_base(t, noi_annual=0, rent_annual=3_000_000,
                                        expenses_annual=0, interest_annual=0)
        assert base == pytest.approx(3_000_000 - 600_000)

    def test_slovak_base_is_noi_less_the_exemption(self):
        import config
        t = config.tax_rules(2026)
        assert fin.personal_rental_base(t, noi_annual=10_000, rent_annual=1, expenses_annual=1,
                                        interest_annual=9_999) == 10_000 - 500


class TestLending:
    def test_buy_to_let_is_an_investment_mortgage_from_april_2026(self):
        assert fin.default_ltv(0, "2026-03-31", market="cz") == 0.80
        assert fin.default_ltv(0, "2026-04-01", market="cz") == 0.70
        # Slovakia still needs a 3rd+ property for its cap.
        assert fin.default_ltv(0, "2026-12-01") == 0.80

    def test_profile_has_sources(self):
        rules = CZ.lending_rules
        assert rules["regulator"] == "ČNB" and rules["dti_investor"] == 7
        assert rules["source"] and rules["checked"]
        assert 0.03 < CZ.mortgage_rate_pa < 0.09


class TestCosts:
    def test_property_tax_is_per_m2(self):
        assert ptax.annual_tax(60, "Praha 2") == pytest.approx(60 * 1.22 * 3.5 * 4.5)
        assert ptax.annual_tax(60, "Brno-střed") == pytest.approx(60 * 1.22 * 3.5 * 3.5)
        assert ptax.annual_tax(0, "Praha") == 0
        assert fin.property_tax_annual(9_999_999, 60, "Praha 2", market="cz") == \
            ptax.annual_tax(60, "Praha 2")          # not a share of the price

    def test_svj_fee_per_m2(self):
        assert fin.calc_hoa(55, market="cz") == pytest.approx(55 * CZ.hoa["per_m2"]
                                                              + CZ.hoa["per_unit"])

    def test_acquisition_is_the_katastr_fee_plus_a_share(self):
        assert fin.acquisition_costs(4_000_000, market="cz") == pytest.approx(
            4_000_000 * CZ.acquisition_cost_rate + 2_000)
        assert CZ.acquisition_costs["transfer_tax"] == 0

    def test_unverified_figures_say_so(self):
        assert "UNVERIFIED" in CZ.sro_costs["source"]
        assert "UNVERIFIED" in CZ.hold_assumptions["source"]
        assert "UNVERIFIED" in CZ.acquisition_costs["legal_fees"]


class TestCzechScore:
    def _score(self, **kw):
        return fin.analyse(4_500_000, 55, "Praha 2", rent_override=22_000, rooms=2,
                           market="cz", **kw)

    def test_scored_in_crowns_under_czech_rules(self):
        r = self._score()
        assert (r.market, r.currency, r.tax_year) == ("cz", "CZK", 2026)
        assert r.ltv == 0.70 and r.mortgage_rate == CZ.mortgage_rate_pa
        assert r.sro_mortgage_rate == pytest.approx(CZ.mortgage_rate_pa + 0.01)
        assert r.hoa_monthly == pytest.approx(55 * CZ.hoa["per_m2"])
        assert r.acquisition_costs == pytest.approx(4_500_000 * 0.01 + 2_000)
        assert "Kč" in r.recommendation and "€" not in r.recommendation

    def test_extras_and_stress_run_in_the_market(self):
        r = self._score()
        extras = fin.deal_extras(r)
        assert extras["stress_surplus_sro"] < r.surplus_sro
        # No Czech price table yet: no max offer, like any district without one.
        assert extras["max_price_yellow"] is None

    def test_a_sale_within_ten_years_is_taxed_after_it_is_not(self):
        kw = dict(rent=22_000, structure="PERSONAL", market="cz")
        assert fin.project_irr(4_500_000, 55, "Praha 2", hold_years=9, **kw).exit_tax > 0
        assert fin.project_irr(4_500_000, 55, "Praha 2", hold_years=10, **kw).exit_tax == 0

    def test_a_missing_figure_is_an_error_not_a_guess(self, monkeypatch):
        monkeypatch.setitem(markets.MARKETS, "cz",
                            dataclasses.replace(CZ, mortgage_rate_pa=None))
        with pytest.raises(LookupError, match="mortgage rate"):
            fin.analyse(4_500_000, 55, "Praha 2", rent_override=22_000, market="cz")

    def test_slovak_score_ignores_the_czech_profile(self, monkeypatch):
        before = fin.analyse(150_000, 55, "Žilina")
        monkeypatch.setitem(markets.MARKETS, "cz",
                            dataclasses.replace(CZ, mortgage_rate_pa=0.20))
        assert fin.analyse(150_000, 55, "Žilina") == before


def test_a_czech_place_without_a_rent_figure_waits_unscored(full_db, caplog):
    """No Czech rent table yet: a Czech listing is not scored, and the run
    says why once — no per-listing crash, and Slovak listings score as ever."""
    import logging
    import database as db
    from modules.cashflow_runner import run_scoring
    from tests.conftest import make_listing
    with pytest.raises(LookupError, match="rent figure for 'Plzeň 3'"):
        fin.get_rent_estimate("Plzeň 3", 55, market="cz")
    db.upsert_listing(make_listing("cz1", market="cz", currency="CZK", district="Plzeň 3",
                                   price_eur=4_500_000.0, url="https://example.cz/1"))
    db.upsert_listing(make_listing("sk1", district="Žilina"))
    with caplog.at_level(logging.INFO):
        assert run_scoring() == 1
    assert "Score error" not in caplog.text
    assert "1 CZ listing(s) not scored — Czechia: no rent figure for 'Plzeň 3'" in caplog.text

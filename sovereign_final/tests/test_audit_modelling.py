"""The modelling fixes from the October 2026 audit (A1–A7, A12).

A1  GREEN is price vs market, not income — a cash-flow flag next to it.
A2  "Bratislava I"–"V" each get their okres's weighted median, and the city
    parts without a median of their own get their okres's.
A3  The 3-room median is adjusted for the listing's room count.
A4  The s.r.o. pays a running cost and borrows on company terms; it is
    recommended only when it nets more and repays its setup cost.
A5  Towns with no rent entry get their kraj's rent, not the national default;
    fragments ("Nové", "Mesto") match nothing.
A6  The scrapers' €30k price floor is a setting.
A7  Tax figures come from a table per tax year; scores from another year's
    table or an older model are redone.
"""

import pytest

import config
from config import (
    HOLD_YEARS, MORTGAGE_RATE_PA, RENT_PER_M2, SALE_PRICE_MIN_EUR, SRO_ANNUAL_RUNNING_COST,
    SRO_LTV_RATIO, SRO_RATE_PREMIUM_PP, SRO_SETUP_COST, tax_rules,
)
from engine.financial import (
    KRAJ_RENT_FALLBACK, SCORING_MODEL_VERSION, analyse, baseline_rent, class_at_price,
    deal_extras, is_cashflow_negative, match_rent_key, max_offer_price, rate_shock,
    rent_fallback_kind, sro_financing,
)
from engine.regional_prices import (
    BA_DISTRICT_MEDIAN_PRICE_PER_M2, BA_OKRES_MEDIAN_PRICE_PER_M2, BA_OKRES_PARTS,
    CITY_MEDIAN_PRICE_PER_M2, MEDIAN_ROOMS_MULTIPLIER, benchmark_median, benchmark_note,
    median_source, regional_median_price,
)
from tests.conftest import make_listing


# ── A1 ────────────────────────────────────────────────────────────────────────
class TestCashflowFlag:
    def test_a_green_flat_that_loses_money_says_so(self):
        # 35% under the Trnava benchmark — GREEN — but the rent covers less
        # than the mortgage and costs under either structure.
        r = analyse(99_000, 54, "Trnava", rooms=2)
        assert r.classification == "GREEN"
        assert r.cashflow_negative
        assert max(r.surplus_personal, r.surplus_sro) < 0
        assert "Cash-flow negative" in r.recommendation

    def test_a_flat_that_pays_for_itself_is_not_flagged(self):
        r = analyse(60_000, 60, "Žilina", rooms=2, ltv=0.5)
        assert not r.cashflow_negative
        assert "Cash-flow negative" not in r.recommendation

    def test_stored_surplus(self):
        assert is_cashflow_negative(-0.5)
        assert not is_cashflow_negative(0)
        assert not is_cashflow_negative(12)
        assert not is_cashflow_negative(None)      # not scored: nothing to say


# ── A2 ────────────────────────────────────────────────────────────────────────
class TestBratislavaOkresMedians:
    @pytest.mark.parametrize("okres", list(BA_OKRES_PARTS))
    def test_a_bare_okres_gets_its_own_weighted_median(self, okres):
        parts = [BA_DISTRICT_MEDIAN_PRICE_PER_M2[p] for p in BA_OKRES_PARTS[okres]
                 if p in BA_DISTRICT_MEDIAN_PRICE_PER_M2]
        median = regional_median_price(f"Bratislava {okres}")
        assert median == BA_OKRES_MEDIAN_PRICE_PER_M2[okres]
        assert min(parts) <= median <= max(parts)

    def test_the_okresy_no_longer_share_the_city_median(self):
        medians = {regional_median_price(f"Bratislava {o}") for o in BA_OKRES_PARTS}
        assert len(medians) == 5
        assert CITY_MEDIAN_PRICE_PER_M2["bratislava"] not in medians

    @pytest.mark.parametrize("district,okres", [
        ("Bratislava IV", "IV"), ("Bratislava - IV", "IV"), ("okres Bratislava V", "V"),
        ("Bratislava III", "III"), ("Bratislava II", "II"), ("Bratislava I", "I"),
    ])
    def test_roman_numerals_are_read_whole(self, district, okres):
        # "Bratislava IV" is not okres I followed by a stray "V".
        assert regional_median_price(district) == BA_OKRES_MEDIAN_PRICE_PER_M2[okres]

    def test_the_weighting_follows_the_flats(self):
        # Ružinov has four times Vrakuňa's people: Bratislava II sits nearer
        # Ružinov's median than a plain average would.
        plain = sum(BA_DISTRICT_MEDIAN_PRICE_PER_M2[p] for p in ("ružinov", "vrakuňa", "podunajské")) / 3
        assert BA_OKRES_MEDIAN_PRICE_PER_M2["II"] > plain

    def test_a_named_city_part_still_beats_its_okres(self):
        assert regional_median_price("Bratislava II - Vrakuňa") == BA_DISTRICT_MEDIAN_PRICE_PER_M2["vrakuňa"]
        assert regional_median_price("Bratislava I") == BA_DISTRICT_MEDIAN_PRICE_PER_M2["staré mesto"]

    @pytest.mark.parametrize("district,okres", [
        ("Lamač, Bratislava", "IV"), ("Lamac, Bratislava", "IV"),
        ("Vajnory, Bratislava", "III"), ("Rusovce, Bratislava", "V"),
        ("Jarovce, Bratislava", "V"), ("Čunovo, Bratislava", "V"),
        ("Cunovo, Bratislava", "V"), ("Devín, Bratislava", "IV"),
        ("Záhorská Bystrica, Bratislava", "IV"),
    ])
    def test_a_city_part_without_a_median_takes_its_okres(self, district, okres):
        assert regional_median_price(district) == BA_OKRES_MEDIAN_PRICE_PER_M2[okres]
        assert "has no median of its own" in median_source(district)[1]

    def test_devinska_nova_ves_is_not_devin(self):
        assert regional_median_price("Devínska Nová Ves, Bratislava") == \
            BA_DISTRICT_MEDIAN_PRICE_PER_M2["devínska"]

    def test_bratislava_alone_is_still_the_city_figure(self):
        assert regional_median_price("Bratislava") == CITY_MEDIAN_PRICE_PER_M2["bratislava"]
        assert "city-wide" in median_source("Bratislava")[1]


# ── A3 ────────────────────────────────────────────────────────────────────────
class TestRoomAdjustedBenchmark:
    def test_small_flats_are_judged_against_a_higher_figure(self):
        base = regional_median_price("Nitra")
        assert benchmark_median("Nitra", 1) > benchmark_median("Nitra", 2) \
            > benchmark_median("Nitra", 3) == base > benchmark_median("Nitra", 4)
        assert benchmark_median("Nitra", 6) == benchmark_median("Nitra", 4)

    @pytest.mark.parametrize("rooms", [None, 0, "?"])
    def test_an_unknown_room_count_keeps_the_3_room_median(self, rooms):
        assert benchmark_median("Nitra", rooms) == regional_median_price("Nitra")

    def test_a_garsonka_at_its_market_price_is_at_market(self):
        size = 30
        price = regional_median_price("Nitra") * MEDIAN_ROOMS_MULTIPLIER[1] * size
        r = analyse(price, size, "Nitra", rooms=1)
        assert r.market_discount == pytest.approx(0, abs=1e-3)
        # Against the 3-room median it read as 15% above market.
        assert analyse(price, size, "Nitra").market_discount == pytest.approx(-0.15, abs=1e-3)

    def test_a_four_room_flat_at_the_3_room_median_is_not_a_bargain(self):
        size = 95
        price = regional_median_price("Košice") * size
        assert analyse(price, size, "Košice", rooms=4).market_discount < 0

    @pytest.mark.parametrize("rooms", [1, 2, 3, 4])
    def test_the_max_offer_earns_the_class_it_promises(self, rooms):
        for target in ("GREEN", "YELLOW"):
            price = max_offer_price(50, "Prešov", target, rooms=rooms)
            got = class_at_price(price, 50, "Prešov", rooms)
            assert got == target or (target == "YELLOW" and got == "GREEN")
            assert analyse(price, 50, "Prešov", rooms=rooms).classification == got

    def test_the_note_says_what_the_benchmark_is(self):
        note = benchmark_note("Bratislava II", 1)
        assert "Bratislava II" in note and "×1.15" in note and "1-room" in note
        assert "×" not in benchmark_note("Trnava", 3)

    def test_rescoring_settles_for_any_room_count(self, full_db):
        import database as db
        from modules.cashflow_runner import run_scoring
        for rooms in (1, 2, 3, 4, None):
            db.upsert_listing(make_listing(f"r{rooms}", rooms=rooms, district="Nitra"))
        assert run_scoring() == 5
        # The stored class and max offers match what the engine gives today,
        # so nothing is re-queued on the next run.
        assert db.requeue_scores_with_stale_class() == 0
        assert run_scoring() == 0


# ── A4 ────────────────────────────────────────────────────────────────────────
class TestSroCostsAndFinancing:
    def test_the_company_borrows_on_its_own_terms(self):
        assert sro_financing(0.8, 0.038) == (SRO_LTV_RATIO, pytest.approx(0.038 + SRO_RATE_PREMIUM_PP))
        # Never more than the personal LTV.
        assert sro_financing(0.5, 0.038)[0] == 0.5
        assert sro_financing(0.8, 0.04, sro_ltv=0.75, sro_rate_premium=0.0) == (0.75, 0.04)

    def test_with_personal_terms_and_no_running_cost_the_loans_match(self):
        r = analyse(120_000, 60, "Žilina", ltv=0.8, sro_ltv=0.8, sro_rate_premium=0.0,
                    sro_running_cost=0)
        assert r.mortgage_monthly_sro == r.mortgage_monthly
        assert r.total_cash_invested_sro == r.total_cash_invested
        assert r.sro_running_cost_monthly == 0

    def test_the_running_cost_is_paid_every_month_and_deducted(self):
        kw = dict(ltv=0.8, sro_ltv=0.8, sro_rate_premium=0.0, rent_override=1_400)
        free = analyse(150_000, 60, "Žilina", sro_running_cost=0, **kw)
        paid = analyse(150_000, 60, "Žilina", sro_running_cost=1_200, **kw)
        assert paid.sro_running_cost_monthly == 100
        lost = free.surplus_sro - paid.surplus_sro
        # €100/mo out, less the tax it saves (the profit is taxable here).
        assert 0 < lost < 100
        assert paid.income_tax_sro < free.income_tax_sro
        assert paid.surplus_personal == free.surplus_personal

    def test_the_company_loan_puts_more_cash_in(self):
        r = analyse(120_000, 60, "Žilina", ltv=0.8)
        assert r.sro_ltv == SRO_LTV_RATIO
        assert r.total_cash_invested_sro > r.total_cash_invested
        assert r.sro_mortgage_rate == pytest.approx(MORTGAGE_RATE_PA + SRO_RATE_PREMIUM_PP)

    @pytest.mark.parametrize("price", range(60_000, 420_000, 30_000))
    @pytest.mark.parametrize("rent", [None, 900, 2_000])
    def test_sro_only_when_it_repays_its_setup_cost(self, price, rent):
        r = analyse(price, 65, "Bratislava II", rent_override=rent)
        pays = (r.annual_sro_saving > 0
                and r.annual_sro_saving * HOLD_YEARS > SRO_SETUP_COST)
        assert r.optimal_structure == ("SRO" if pays else "PERSONAL")

    def test_a_small_saving_no_longer_recommends_the_sro(self):
        # The audit's card: "saves €193/yr, break-even 156 months". Under the
        # old model (no running cost, the personal loan) a flat like this was
        # SRO; the running cost alone turns it around.
        kw = dict(ltv=0.8, sro_ltv=0.8, sro_rate_premium=0.0)
        old = analyse(50_500, 35, "Banská Bystrica", rooms=1, sro_running_cost=0, **kw)
        assert old.annual_sro_saving > 0
        new = analyse(50_500, 35, "Banská Bystrica", rooms=1, **kw)
        assert new.annual_sro_saving < old.annual_sro_saving
        assert new.optimal_structure == "PERSONAL"
        assert "Personal" in new.recommendation

    def test_the_sro_can_still_win(self):
        # A high-earning flat with a large deductible interest bill.
        r = analyse(200_000, 60, "Bratislava", rent_override=3_000, ltv=0.8,
                    sro_ltv=0.8, sro_rate_premium=0.0, sro_running_cost=0)
        assert r.optimal_structure == "SRO"
        assert "nets" in r.recommendation

    def test_the_stress_test_keeps_the_company_terms(self):
        r = analyse(98_000, 58, "Žilina", ltv=0.8, rooms=2)
        e = deal_extras(r)
        shocked = rate_shock(98_000, 58, "Žilina", rent_override=r.estimated_rent,
                             ltv=0.8, rooms=2)
        assert e["stress_surplus_sro"] == shocked.surplus_sro
        assert shocked.sro_mortgage_rate == pytest.approx(r.sro_mortgage_rate + 0.02)

    def test_the_sro_irr_pays_the_running_cost(self):
        from engine.financial import project_irr
        free = project_irr(120_000, 60, "Nitra", structure="SRO", sro_running_cost=0)
        paid = project_irr(120_000, 60, "Nitra", structure="SRO",
                           sro_running_cost=SRO_ANNUAL_RUNNING_COST)
        assert paid.total_profit < free.total_profit
        personal = project_irr(120_000, 60, "Nitra", structure="PERSONAL",
                               sro_running_cost=99_999)
        assert personal.total_profit == project_irr(
            120_000, 60, "Nitra", structure="PERSONAL").total_profit


# ── A5 ────────────────────────────────────────────────────────────────────────
class TestRentFallbacks:
    @pytest.mark.parametrize("district", ["Nové", "Mesto", "nove", "Banská", "okres"])
    def test_a_fragment_matches_nothing(self, district):
        assert match_rent_key(district) == "default"

    def test_a_shortened_name_that_is_unambiguous_still_matches(self):
        assert match_rent_key("Žiar") == "žiar nad hronom"

    @pytest.mark.parametrize("district,kraj", [
        ("Prievidza", "trenčiansky kraj"), ("Stará Turá", "trenčiansky kraj"),
        ("Šamorín", "trnavský kraj"), ("Dolný Kubín", "žilinský kraj"),
        ("Banská Štiavnica", "banskobystrický kraj"),
        ("Ivanka pri Dunaji", "bratislavský kraj"),
    ])
    def test_a_town_without_a_rent_entry_gets_its_krajs(self, district, kraj):
        assert match_rent_key(district) == kraj
        assert rent_fallback_kind(kraj) == "kraj"
        assert baseline_rent(kraj) == KRAJ_RENT_FALLBACK[kraj]

    def test_the_kraj_figure_is_the_median_of_its_towns(self):
        # Bratislavský kraj's towns: Senec, Pezinok, Malacky, Stupava, Modra.
        towns = sorted(RENT_PER_M2[t] for t in ("senec", "pezinok", "malacky", "stupava", "modra"))
        assert KRAJ_RENT_FALLBACK["bratislavský kraj"] == towns[2]

    def test_whole_words_only(self):
        assert match_rent_key("Brača") != "rača"
        assert match_rent_key("Bratislava IV") == "bratislava iv"

    def test_ascii_spellings_match(self):
        assert match_rent_key("petrzalka") == "petržalka"
        assert match_rent_key("Zilina") == "žilina"
        # …without sending a Košice part to Bratislava's.
        assert match_rent_key("Stare Mesto, Kosice") == match_rent_key("Staré Mesto, Košice")

    def test_the_card_is_told(self):
        r = analyse(80_000, 50, "Nowhereville")
        assert r.rent_key == "default"
        assert "national default" in r.recommendation
        assert rent_fallback_kind("default") == "default"
        assert rent_fallback_kind("žilina") is None
        r = analyse(80_000, 50, "Prievidza")
        assert "Trenčiansky Kraj median" in r.recommendation

    def test_live_comps_blend_with_the_kraj_baseline(self):
        from engine.rent_comps import rates_from_comps, blended_rate
        rates = rates_from_comps({"trenčiansky kraj": {"n": 10, "median_eur_per_m2": 8.0}})
        assert rates["trenčiansky kraj"] == blended_rate(8.0, 10, KRAJ_RENT_FALLBACK["trenčiansky kraj"])


# ── A6 ────────────────────────────────────────────────────────────────────────
class TestPriceFloorSetting:
    def test_every_scraper_reads_the_setting(self):
        from scraper import bazos, nehnutelnosti, topreality
        for mod in (bazos, nehnutelnosti, topreality):
            assert mod._PRICE_MIN == SALE_PRICE_MIN_EUR

    def test_the_default_keeps_cheap_eastern_flats(self):
        assert SALE_PRICE_MIN_EUR < 30_000


# ── A7 ────────────────────────────────────────────────────────────────────────
class TestTaxYears:
    def test_the_current_table(self):
        t = tax_rules(2026)
        assert t["year"] == 2026 and not t["stale"]
        assert t["source"] and t["checked"]

    def test_a_year_without_a_table_uses_the_latest_and_says_so(self):
        t = tax_rules(2031)
        assert t["year"] == max(config.TAX_YEAR_RULES) and t["stale"]
        assert t["requested"] == 2031

    def test_old_names_are_the_current_years_figures(self):
        t = tax_rules()
        assert config.DIVIDEND_TAX_RATE == t["dividend_tax"]
        assert config.TAX_THRESHOLD_PERSONAL == t["personal_threshold"]

    def test_scoring_uses_the_requested_years_table(self, monkeypatch):
        later = {**config.TAX_YEAR_RULES[2026], "dividend_tax": 0.0, "checked": "test"}
        monkeypatch.setitem(config.TAX_YEAR_RULES, 2027, later)
        kw = dict(rent_override=2_500, ltv=0.5)
        now = analyse(200_000, 60, "Bratislava", tax_year=2026, **kw)
        nxt = analyse(200_000, 60, "Bratislava", tax_year=2027, **kw)
        assert now.tax_year == 2026 and nxt.tax_year == 2027
        assert nxt.income_tax_sro < now.income_tax_sro
        assert nxt.income_tax_personal == now.income_tax_personal

    def test_scores_from_another_table_or_model_are_redone(self, full_db):
        import database as db
        from modules.cashflow_runner import run_scoring
        db.upsert_listing(make_listing("t1", district="Nitra"))
        assert run_scoring() == 1
        c = full_db()
        row = c.execute("SELECT model_version, tax_year FROM cashflow_scores").fetchone()
        assert tuple(row) == (SCORING_MODEL_VERSION, tax_rules()["year"])
        assert db.requeue_scores_from_older_model() == 0

        c.execute("UPDATE cashflow_scores SET model_version = ?", (SCORING_MODEL_VERSION - 1,))
        c.commit()
        assert db.requeue_scores_from_older_model() == 1
        assert run_scoring() == 1

        c.execute("UPDATE cashflow_scores SET tax_year = 2019")
        c.commit()
        assert db.requeue_scores_from_older_model() == 1
        c.close()

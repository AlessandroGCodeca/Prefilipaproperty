"""Tests for engine/regional_prices.py — the sale-price floor lookup chain."""

import pytest

from engine.regional_prices import (
    BA_DISTRICT_MEDIAN_PRICE_PER_M2,
    CITY_MEDIAN_PRICE_PER_M2,
    GLOBAL_BLANK_DISTRICT_FLOOR,
    REGIONAL_MEDIAN_PRICE_PER_M2,
    REGIONAL_PRICE_FLOOR_RATIO,
    is_plausible_regional_price,
    kraj_for_district,
    regional_price_floor,
)


class TestKrajLookup:
    @pytest.mark.parametrize("district,kraj", [
        ("Bratislava",              "BA"),
        ("Petržalka, Bratislava",   "BA"),
        ("okres Stupava",           "BA"),
        ("Košice",                  "KE"),
        ("Trnava",                  "TT"),
        ("Žilina-okolie",           "ZA"),
        ("Banská Bystrica",         "BB"),
    ])
    def test_recognised_districts_resolve(self, district, kraj):
        assert kraj_for_district(district) == kraj

    def test_blank_returns_none(self):
        assert kraj_for_district("") is None

    def test_unknown_returns_none(self):
        assert kraj_for_district("Nowhereville") is None


class TestFloorLookupChain:
    def test_blank_district_uses_global_floor(self):
        assert regional_price_floor("") == GLOBAL_BLANK_DISTRICT_FLOOR

    def test_unknown_district_uses_global_floor(self):
        assert regional_price_floor("Nowhereville") == GLOBAL_BLANK_DISTRICT_FLOOR

    def test_ba_subdistrict_wins_over_city(self):
        # Petržalka should match the BA sub-district, not the BA city fallback
        floor = regional_price_floor("Petržalka, Bratislava")
        expected = BA_DISTRICT_MEDIAN_PRICE_PER_M2["petržalka"] * REGIONAL_PRICE_FLOOR_RATIO
        assert floor == expected

    def test_ba_subdistrict_only_fires_with_bratislava(self):
        # "Staré Mesto, Košice" must NOT use the BA Staré Mesto floor —
        # suburb names like Staré Mesto exist in multiple Slovak cities.
        floor = regional_price_floor("Staré Mesto, Košice")
        expected = CITY_MEDIAN_PRICE_PER_M2["košice"] * REGIONAL_PRICE_FLOOR_RATIO
        assert floor == expected

    def test_bratislava_city_fallback(self):
        # "Bratislava" alone doesn't match a sub-district → uses BA city floor
        floor = regional_price_floor("Bratislava")
        expected = CITY_MEDIAN_PRICE_PER_M2["bratislava"] * REGIONAL_PRICE_FLOOR_RATIO
        assert floor == expected

    def test_city_match_for_known_city(self):
        floor = regional_price_floor("Košice")
        expected = CITY_MEDIAN_PRICE_PER_M2["košice"] * REGIONAL_PRICE_FLOOR_RATIO
        assert floor == expected

    def test_kraj_fallback_for_small_town(self):
        # Stupava is in BA kraj but not in CITY or BA_DISTRICT lookups
        floor = regional_price_floor("Stupava")
        expected = REGIONAL_MEDIAN_PRICE_PER_M2["BA"] * REGIONAL_PRICE_FLOOR_RATIO
        assert floor == expected

    def test_ascii_diacritic_fold(self):
        # The dict has both ASCII and Slovak-diacritic keys
        floor_diacritic = regional_price_floor("Petržalka, Bratislava")
        floor_ascii     = regional_price_floor("Petrzalka, Bratislava")
        assert floor_diacritic == floor_ascii


class TestPlausibility:
    def test_zero_price_or_size_is_plausible(self):
        # No data → don't reject; let other filters handle it
        assert is_plausible_regional_price(0,      60.0, "Bratislava") is True
        assert is_plausible_regional_price(200_000, 0,   "Bratislava") is True

    def test_above_floor_is_plausible(self):
        # 50 000 / 30 m² = 1667 €/m² — above BA global floor of 800 but
        # below BA city floor — depends on district matching
        assert is_plausible_regional_price(150_000, 50.0, "Bratislava") is True

    def test_far_below_floor_rejected(self):
        # 10 000 / 50 = 200 €/m² — below global floor of 800
        assert is_plausible_regional_price(10_000, 50.0, "") is False

    def test_dev_project_starting_price_in_premium_district(self):
        # "od €140k" listing in Staré Mesto / 90 m² = 1555 €/m².
        # BA Staré Mesto floor = 4565 × 0.5 = 2282. Should reject.
        assert is_plausible_regional_price(140_000, 90.0,
                                           "Staré Mesto, Bratislava") is False


# ── Ceiling ───────────────────────────────────────────────────────────────────
# Every row below is verbatim from a live €/m² ranking of the database. The
# repeated €1,250,000 is one agency's property that the old max()-over-the-page
# price extraction attached to seven of its unrelated flats.
from engine.regional_prices import (  # noqa: E402
    is_above_regional_ceiling, regional_price_ceiling, pick_sale_price,
)


class TestCeilingLookup:
    def test_bratislava_city(self):
        # 3 914 median × 4
        assert regional_price_ceiling("Bratislava") == pytest.approx(15_656)

    def test_ba_subdistrict_beats_city(self):
        # Staré Mesto 4 565 × 4 — the priciest district, so the most headroom
        assert regional_price_ceiling("Staré Mesto, Bratislava") == pytest.approx(18_260)

    def test_blank_district_uses_global(self):
        assert regional_price_ceiling("") == 20_000.0

    def test_unknown_district_uses_global(self):
        assert regional_price_ceiling("Atlantis") == 20_000.0


class TestAboveCeiling:
    @pytest.mark.parametrize("price,size,district", [
        (1_250_000, 21.82, "Bratislava"),     # 57 287 €/m²
        (1_502_734, 29.0,  "Bratislava"),     # 51 818 €/m²
        (1_250_000, 58.0,  "Bratislava"),     # 21 552 €/m²
        (1_500_000, 54.0,  "Senec"),          # 27 778 €/m², title says "most affordable"
        (2_435_000, 68.0,  ""),               # 35 809 €/m², blank district
        (  182_000,  6.0,  "Košice 040 22"),  # size was the loggia, not the flat
    ])
    def test_misread_prices_rejected(self, price, size, district):
        assert is_above_regional_ceiling(price, size, district) is True

    @pytest.mark.parametrize("price,size,district,why", [
        (1_689_000, 170.0, "Staré Mesto", "genuine penthouse at ~9 900 €/m²"),
        (  182_000, 46.41, "Malacky",     "harvested CORVUS ATRIUM unit"),
        (  150_000, 29.0,  "Bratislava",  "ordinary small Ružinov flat"),
        (  450_000, 40.0,  "Staré Mesto", "small luxury flat, 11 250 €/m²"),
    ])
    def test_genuine_listings_survive(self, price, size, district, why):
        assert is_above_regional_ceiling(price, size, district) is False, why

    def test_missing_price_or_size_is_not_judged(self):
        assert is_above_regional_ceiling(0, 60.0, "Bratislava") is False
        assert is_above_regional_ceiling(200_000, 0, "Bratislava") is False


class TestPickSalePrice:
    """A listing page's € figures: deposits and per-m² rates below the sale
    price, and other listings' prices which can be well above it."""

    def test_drops_a_neighbouring_listings_price(self):
        cands = [1_000, 4_630, 250_000, 1_250_000]
        assert pick_sale_price(cands, 54.0, "Bratislava") == 250_000

    def test_still_beats_deposits_and_per_m2_rates(self):
        """The reason max() was chosen in the first place must keep working."""
        assert pick_sale_price([1_000, 3_273, 189_000], 58.0, "Bratislava") == 189_000

    def test_no_size_falls_back_to_max(self):
        cands = [1_000, 250_000, 1_250_000]
        assert pick_sale_price(cands, 0, "Bratislava") == 1_250_000

    def test_all_candidates_too_high_keeps_max(self):
        """Better a suspect price the ceiling cleanup catches than no price."""
        assert pick_sale_price([1_250_000, 2_000_000], 21.0, "Bratislava") == 2_000_000

    def test_empty(self):
        assert pick_sale_price([], 50.0, "Bratislava") == 0.0
        assert pick_sale_price(None, 50.0, "Bratislava") == 0.0

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

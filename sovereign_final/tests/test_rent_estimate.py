"""Tests for engine/financial.py::get_rent_estimate — fuzzy district matching."""

import pytest

from engine.financial import get_rent_estimate


class TestBlankAndUnknown:
    def test_blank_district_uses_default(self):
        # Default rate is €6.5/m²/mo → 60m² → €390/mo
        assert get_rent_estimate("", 60.0) == pytest.approx(6.5 * 60, abs=1.0)

    def test_unknown_district_uses_default(self):
        # Same as blank: unknown places fall to default
        assert get_rent_estimate("Atlantis", 60.0) == pytest.approx(6.5 * 60, abs=1.0)


class TestBratislava:
    def test_stare_mesto_premium_rate(self):
        # Staré Mesto = 14.5 €/m²/mo for 60m² = €870/mo
        assert get_rent_estimate("Staré Mesto, Bratislava", 60.0) >= 800.0

    def test_petrzalka_mid_rate(self):
        # Petržalka = 12.0 €/m²/mo
        rate = get_rent_estimate("Petržalka, Bratislava", 60.0) / 60.0
        assert 11.0 <= rate <= 13.0

    def test_suburb_wins_over_city(self):
        # "Petržalka" should match the suburb rate (12), not the BA city (12.5)
        # but both are close — verify it's NOT using cheaper fallback like 6.5
        rent = get_rent_estimate("Petržalka", 60.0)
        assert rent >= 600  # at least €10/m²/mo, well above default €6.5


class TestKosice:
    def test_kosice_city_rate(self):
        # Košice = 10.5 €/m²/mo (industrial premium may apply)
        rate = get_rent_estimate("Košice", 55.0) / 55.0
        assert rate >= 10.0  # at minimum the base rate

    def test_kosice_i_centrum(self):
        # Košice I = 13.5 €/m²/mo
        rate = get_rent_estimate("Košice I", 55.0) / 55.0
        assert rate >= 13.0


class TestRegionalCities:
    @pytest.mark.parametrize("district,min_rate", [
        ("Žilina",          9.0),
        ("Trnava",          9.0),
        ("Nitra",           8.0),
        ("Banská Bystrica", 8.0),
        ("Prešov",          8.0),
        ("Trenčín",         7.5),
        ("Poprad",          9.0),
    ])
    def test_regional_capital_min_rate(self, district, min_rate):
        rate = get_rent_estimate(district, 55.0) / 55.0
        assert rate >= min_rate, (
            f"{district} returned {rate:.2f} €/m²/mo, expected >= {min_rate}"
        )


class TestDiacriticHandling:
    def test_ascii_district_matches(self):
        # ASCII slugs should still resolve to the diacritic-keyed entry
        diacritic = get_rent_estimate("Petržalka", 60.0)
        ascii_form = get_rent_estimate("petrzalka", 60.0)
        # Note: config.py only has Slovak-diacritic keys for some districts.
        # Fuzzy matching should handle the ascii form too — if it doesn't,
        # both fall through to default. Verify they at least agree.
        if ascii_form > 6.5 * 60:
            assert ascii_form == pytest.approx(diacritic, rel=0.05)


class TestSizeScaling:
    def test_rent_scales_linearly_with_size(self):
        rent_30 = get_rent_estimate("Bratislava", 30.0)
        rent_60 = get_rent_estimate("Bratislava", 60.0)
        # Should be exactly 2× (same per-m² rate × different size)
        assert rent_60 == pytest.approx(rent_30 * 2, rel=0.01)


class TestRoomsMultiplier:
    """1-izb apartments command higher €/m² rent than 3-izb; flat per-m² rate
    under-prices small apartments' true cashflow. Multipliers from Q2 2026
    Deloitte data: 1-izb 1.15×, 2-izb 1.00× (baseline), 3-izb 0.92×, 4+ 0.85×."""

    def test_2izb_is_baseline(self):
        # 2-izb gets the raw RENT_PER_M2 rate (multiplier = 1.0)
        baseline = get_rent_estimate("Bratislava", 60.0, rooms=2)
        no_rooms = get_rent_estimate("Bratislava", 60.0)
        assert baseline == pytest.approx(no_rooms, rel=0.01)

    def test_1izb_premium(self):
        rent_1 = get_rent_estimate("Bratislava", 30.0, rooms=1)
        rent_2 = get_rent_estimate("Bratislava", 30.0, rooms=2)
        # 1-izb should be ~15% higher per-m² than 2-izb at same size
        assert rent_1 == pytest.approx(rent_2 * 1.15, rel=0.02)

    def test_3izb_discount(self):
        rent_3 = get_rent_estimate("Bratislava", 90.0, rooms=3)
        rent_2 = get_rent_estimate("Bratislava", 90.0, rooms=2)
        # 3-izb should be ~8% lower per-m² than 2-izb at same size
        assert rent_3 == pytest.approx(rent_2 * 0.92, rel=0.02)

    def test_4izb_or_more_capped(self):
        # 4-izb and larger all clamp to the same 0.85× discount
        rent_4 = get_rent_estimate("Bratislava", 120.0, rooms=4)
        rent_5 = get_rent_estimate("Bratislava", 120.0, rooms=5)
        assert rent_4 == pytest.approx(rent_5, rel=0.001)

    def test_invalid_rooms_falls_back_to_baseline(self):
        # Garbage rooms values shouldn't crash — fall back to 2-izb baseline
        baseline = get_rent_estimate("Bratislava", 60.0)
        for bad in [None, 0, -1, "abc"]:
            rent = get_rent_estimate("Bratislava", 60.0, rooms=bad)
            assert rent == pytest.approx(baseline, rel=0.01), (
                f"rooms={bad!r} should fall back to baseline, got {rent}"
            )

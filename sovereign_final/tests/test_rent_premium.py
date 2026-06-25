"""Tests for the description-derived rent premiums (parking / furnished) wired
into engine/financial.py::get_rent_estimate and ::analyse.

The premiums come from features parsed out of the listing description by
modules/llm_enrichment.parse_description and stored on the listing row; they
multiply the base €/m² rate so a parked or furnished unit shows higher
achievable rent (and, through the cashflow ratio / cap rate, a higher deal
score)."""

import pytest

from config import (
    PARKING_RENT_PREMIUM, FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
    BALCONY_RENT_PREMIUM,
)
from engine.financial import get_rent_estimate, analyse


BASE_ARGS = ("Bratislava", 60.0)  # 12.5 €/m², 2-izb baseline multiplier


def _base():
    return get_rent_estimate(*BASE_ARGS)


class TestParkingPremium:
    def test_parking_adds_premium(self):
        assert get_rent_estimate(*BASE_ARGS, parking=True) == pytest.approx(
            _base() * PARKING_RENT_PREMIUM, rel=0.001)

    def test_no_parking_is_neutral(self):
        for falsy in (None, 0, False):
            assert get_rent_estimate(*BASE_ARGS, parking=falsy) == pytest.approx(
                _base(), rel=0.001)


class TestFurnishedPremium:
    def test_furnished_full_premium(self):
        assert get_rent_estimate(*BASE_ARGS, furnished="furnished") == pytest.approx(
            _base() * FURNISHED_RENT_PREMIUM, rel=0.001)

    def test_semi_furnished_partial_premium(self):
        assert get_rent_estimate(*BASE_ARGS, furnished="semi") == pytest.approx(
            _base() * SEMI_FURNISHED_PREMIUM, rel=0.001)

    def test_unfurnished_and_unknown_neutral(self):
        for val in ("unfurnished", "unknown", "", None):
            assert get_rent_estimate(*BASE_ARGS, furnished=val) == pytest.approx(
                _base(), rel=0.001)

    def test_case_insensitive(self):
        assert get_rent_estimate(*BASE_ARGS, furnished="FURNISHED") == pytest.approx(
            _base() * FURNISHED_RENT_PREMIUM, rel=0.001)


class TestBalconyPremium:
    def test_balcony_adds_premium(self):
        assert get_rent_estimate(*BASE_ARGS, balcony=True) == pytest.approx(
            _base() * BALCONY_RENT_PREMIUM, rel=0.001)

    def test_no_balcony_is_neutral(self):
        for falsy in (None, 0, False):
            assert get_rent_estimate(*BASE_ARGS, balcony=falsy) == pytest.approx(
                _base(), rel=0.001)


class TestPremiumComposition:
    def test_parking_and_furnished_compound(self):
        rent = get_rent_estimate(*BASE_ARGS, parking=True, furnished="furnished")
        assert rent == pytest.approx(
            _base() * PARKING_RENT_PREMIUM * FURNISHED_RENT_PREMIUM, rel=0.001)

    def test_all_three_signals_compound(self):
        rent = get_rent_estimate(*BASE_ARGS, parking=True, furnished="furnished",
                                 balcony=True)
        assert rent == pytest.approx(
            _base() * PARKING_RENT_PREMIUM * FURNISHED_RENT_PREMIUM
            * BALCONY_RENT_PREMIUM, rel=0.001)

    def test_premiums_stack_on_rooms_multiplier(self):
        # 1-izb premium (1.15×) and a parking premium should multiply, not
        # cancel — a furnished 1-izb with parking beats the bare 1-izb.
        bare_1izb = get_rent_estimate("Bratislava", 30.0, rooms=1)
        loaded = get_rent_estimate("Bratislava", 30.0, rooms=1,
                                   parking=True, furnished="furnished")
        assert loaded == pytest.approx(
            bare_1izb * PARKING_RENT_PREMIUM * FURNISHED_RENT_PREMIUM, rel=0.001)


class TestAnalyseIntegration:
    def test_analyse_applies_premiums_to_rent(self):
        base = analyse(120_000, 60.0, "Nitra")
        loaded = analyse(120_000, 60.0, "Nitra", parking=True, furnished="furnished")
        assert loaded.estimated_rent > base.estimated_rent
        assert loaded.estimated_rent == pytest.approx(
            base.estimated_rent * PARKING_RENT_PREMIUM * FURNISHED_RENT_PREMIUM,
            rel=0.01)

    def test_higher_rent_cannot_lower_ratio(self):
        # More rent for the same costs can only help the self-funding ratio.
        base = analyse(120_000, 60.0, "Nitra")
        loaded = analyse(120_000, 60.0, "Nitra", parking=True, furnished="furnished")
        assert loaded.ratio_sro >= base.ratio_sro

    def test_rent_override_ignores_premiums(self):
        # An explicit rent override is the final word; premiums must not apply.
        r = analyse(120_000, 60.0, "Nitra", rent_override=1000.0,
                    parking=True, furnished="furnished")
        assert r.estimated_rent == pytest.approx(1000.0)

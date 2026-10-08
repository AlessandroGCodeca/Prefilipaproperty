"""Tests for the price-extraction helpers in each scraper.

Each scraper has its own _price() (or similar) helper that should:
  - Pull out the apartment SALE price from rendered text
  - Reject values outside the plausible range (config.SALE_PRICE_MIN_EUR –
    €10M; the floor used to be a hard-coded €30k)
  - Take the LARGEST match when multiple € values are present
    (other matches are deposits, fees, monthly rents, per-m² rates)
"""

import pytest

from config import SALE_PRICE_MIN_EUR as FLOOR
from scraper.bazos import _price as bazos_price, _is_plausible_price as bz_plausible
from scraper.topreality import _price_from_text as tr_price, _is_plausible_price as tr_plausible


class TestPlausibility:
    @pytest.mark.parametrize("v,plausible", [
        (    100, False),   # too small — deposit / fee
        (  5_000, False),   # too small — monthly rent
        (FLOOR - 1, False), # just below floor
        (FLOOR, True),      # at floor
        ( 50_000, True),
        (150_000, True),
        (500_000, True),
        (10_000_000, True),
        (10_000_001, False),  # above ceiling
        (999_999_999, False), # absurd
    ])
    def test_bazos_plausibility(self, v, plausible):
        assert bz_plausible(v) is plausible

    @pytest.mark.parametrize("v,plausible", [
        (   500, False),
        (FLOOR - 1, False),
        (FLOOR, True),
        (500_000, True),
        (10_000_001, False),
    ])
    def test_topreality_plausibility(self, v, plausible):
        assert tr_plausible(v) is plausible


class TestBazosPriceExtraction:
    def test_plain_price_extracted(self):
        assert bazos_price("Cena 150 000 €") == 150_000.0

    def test_with_eur_suffix(self):
        assert bazos_price("Cena 200000 EUR") == 200_000.0

    def test_returns_max_of_multiple_prices(self):
        # Card text often has both a deposit (e.g. "depozit 500 €") and the
        # real price ("cena 145 000 €") — must return the larger.
        text = "Depozit 500 €. Cena bytu 145 000 €. Mesačný poplatok 80 €."
        assert bazos_price(text) == 145_000.0

    def test_a_small_town_flat_under_the_old_30k_floor_is_kept(self):
        # A genuine eastern small-town flat; the regional floor judges it later.
        assert FLOOR < 25_000
        assert bazos_price("Predám 1-izbový byt, cena 25 000 €") == 25_000.0

    def test_ignores_below_floor(self):
        # A listing whose only € value is too small must return 0
        assert bazos_price("Depozit 1 500 €. Mesačná réžia 200 €.") == 0.0

    def test_blank_text_returns_zero(self):
        assert bazos_price("") == 0.0
        assert bazos_price(None) == 0.0

    def test_bare_digits_fallback(self):
        # When no € symbol, accept plausible bare digits
        assert bazos_price("145000") == 145_000.0


class TestTopRealityPriceExtraction:
    def test_extracts_price_with_symbol(self):
        assert tr_price("Cena 250 000 €") == 250_000.0

    def test_picks_max_plausible(self):
        # Per-m² rate appears alongside total price — total wins
        text = "Predaj bytu. Cena 180 000 € (3 600 €/m²)."
        assert tr_price(text) == 180_000.0

    def test_rejects_all_below_floor(self):
        assert tr_price("Mesačné nájomné 800 € · Depozit 1 600 €") == 0.0

    def test_blank_returns_zero(self):
        assert tr_price("") == 0.0

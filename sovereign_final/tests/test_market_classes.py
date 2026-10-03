"""Tests for the GREEN / YELLOW / WHITE classes: the discount of the asking
€/m² to the region's median, calibrated against the sanity floor.

The old classes were the s.r.o. self-funding ratio (≥ 1.15 GREEN, ≥ 1.05
YELLOW). At 3.8% / 25 years / 80% LTV, GREEN needed a price below the floor
(50% of the regional median) — where engine/regional_prices zeroes prices as
data errors — so no real listing could reach it."""

import os
import sqlite3
import tempfile

import pytest

from config import GREEN_DISCOUNT, YELLOW_DISCOUNT, NEAR_FLOOR_DISCOUNT
from engine.financial import analyse, classify
from engine.regional_prices import (
    regional_median_price, is_plausible_regional_price,
    REGIONAL_PRICE_FLOOR_RATIO, BA_DISTRICT_MEDIAN_PRICE_PER_M2,
    CITY_MEDIAN_PRICE_PER_M2,
)

REGIONS = (["Bratislava"] + [f"{d}, Bratislava" for d in BA_DISTRICT_MEDIAN_PRICE_PER_M2]
           + list(CITY_MEDIAN_PRICE_PER_M2) + ["Komárno", "Lučenec", "Bardejov"])


def _at(district, fraction_of_median, size=55.0):
    """A flat priced at `fraction_of_median` × the region's median €/m²."""
    return analyse(regional_median_price(district) * fraction_of_median * size,
                   size, district, rooms=2)


class TestClassify:
    def test_thresholds(self):
        assert classify(None) == "WHITE"
        assert classify(-0.1) == classify(0.0) == classify(0.09) == "WHITE"
        assert classify(YELLOW_DISCOUNT) == classify(0.19) == "YELLOW"
        assert classify(GREEN_DISCOUNT) == classify(0.45) == "GREEN"

    def test_below_the_floor_is_not_a_deal(self):
        # Prices the scrapers would zero as data errors never come out GREEN.
        assert classify(1 - REGIONAL_PRICE_FLOOR_RATIO + 0.01) == "WHITE"
        r = _at("Nitra", REGIONAL_PRICE_FLOOR_RATIO - 0.05)
        assert r.classification == "WHITE"
        assert "Below the sanity floor" in r.recommendation


class TestCalibratedAgainstTheFloor:
    def test_green_band_sits_clear_of_the_floor(self):
        # GREEN starts at 80% of the median; the floor is at 50%.
        assert (1 - GREEN_DISCOUNT) - REGIONAL_PRICE_FLOOR_RATIO >= 0.25

    @pytest.mark.parametrize("district", REGIONS)
    def test_every_region_reaches_green_above_the_floor(self, district):
        r = _at(district, 1 - GREEN_DISCOUNT - 0.01)
        assert r.classification == "GREEN"
        assert is_plausible_regional_price(r.price_eur, r.size_m2, district)

    @pytest.mark.parametrize("district", REGIONS)
    def test_market_priced_flat_is_white(self, district):
        assert _at(district, 1.0).classification == "WHITE"
        assert _at(district, 0.85).classification == "YELLOW"

    def test_the_old_ratio_rule_could_not_reach_green_above_the_floor(self):
        # Documents why the rule changed: at 55% of the median — just above
        # the floor — the self-funding ratio still falls short of 1.15.
        for district in ("Bratislava", "Košice", "Nitra", "Petržalka, Bratislava"):
            assert _at(district, REGIONAL_PRICE_FLOOR_RATIO + 0.05).ratio_sro < 1.15


class TestRecommendation:
    def test_states_discount_and_yield(self):
        r = _at("Nitra", 0.75)
        assert r.market_discount == pytest.approx(0.25, abs=1e-3)
        assert "25% below the regional median" in r.recommendation
        assert "gross yield" in r.recommendation

    def test_near_floor_warning(self):
        assert "sanity floor" in _at("Nitra", 1 - NEAR_FLOOR_DISCOUNT - 0.02).recommendation
        assert "sanity floor" not in _at("Nitra", 0.75).recommendation

    def test_no_benchmark(self):
        r = analyse(100_000, 50, "")
        assert r.market_discount is None and r.classification == "WHITE"
        assert "no regional price benchmark" in r.recommendation


class TestOldScoresAreReclassified:
    def test_scores_from_the_ratio_rule_are_dropped_once(self, monkeypatch):
        import database as db
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE listings (id TEXT PRIMARY KEY, classification TEXT)")
        conn.execute("CREATE TABLE cashflow_scores (listing_id TEXT PRIMARY KEY, "
                     "classification TEXT)")
        conn.execute("INSERT INTO listings VALUES ('a', 'GREEN'), ('b', 'PENDING')")
        conn.execute("INSERT INTO cashflow_scores VALUES ('a', 'GREEN')")
        conn.commit()

        db._ensure_cashflow_columns(conn)
        assert conn.execute("SELECT COUNT(*) FROM cashflow_scores").fetchone()[0] == 0
        assert dict(conn.execute("SELECT id, classification FROM listings")) == \
            {"a": "PENDING", "b": "PENDING"}

        # A second run (column now present) keeps new scores.
        conn.execute("INSERT INTO cashflow_scores (listing_id, classification) "
                     "VALUES ('a', 'YELLOW')")
        db._ensure_cashflow_columns(conn)
        assert conn.execute("SELECT COUNT(*) FROM cashflow_scores").fetchone()[0] == 1
        conn.close()
        os.unlink(path)

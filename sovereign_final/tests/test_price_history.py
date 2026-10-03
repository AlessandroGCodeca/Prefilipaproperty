"""Tests for price history, price-cut alerts and days on market.

upsert_listing used to overwrite price_eur and forget the old value, so a
price cut — the best signal a seller gives — was invisible, and the listing
kept the score worked out at its old price. Now every new asking price is
logged in price_history and the stale score is dropped for re-scoring.

A misread price (one a repair or a regional sanity check removed) must not
stay in the history, or the real price arriving later reads as a big cut.
"""

from datetime import datetime, timedelta, timezone

import pytest

import database as db
from tests.conftest import make_listing


def _history(conn_fn, lid):
    c = conn_fn()
    rows = c.execute("SELECT price_eur, observed_at FROM price_history "
                     "WHERE listing_id=? ORDER BY observed_at, id", (lid,)).fetchall()
    c.close()
    return [(r[0], r[1]) for r in rows]


def _score(conn_fn, lid, cls="WHITE"):
    c = conn_fn()
    c.execute("INSERT INTO cashflow_scores (listing_id, classification) VALUES (?,?)", (lid, cls))
    c.execute("UPDATE listings SET classification=? WHERE id=?", (cls, lid))
    c.commit()
    c.close()


def _has_score(conn_fn, lid):
    c = conn_fn()
    n = c.execute("SELECT COUNT(*) FROM cashflow_scores WHERE listing_id=?", (lid,)).fetchone()[0]
    c.close()
    return n > 0


class TestRecording:
    def test_first_sight_records_the_price(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=100_000))
        assert [p for p, _ in _history(full_db, "a")] == [100_000]

    def test_same_price_again_records_nothing(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=100_000))
        db.upsert_listing(make_listing("a", price_eur=100_000,
                                       last_seen_at="2026-09-05T08:00:00+00:00"))
        assert len(_history(full_db, "a")) == 1

    def test_a_new_price_is_logged_and_the_score_dropped(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=100_000))
        _score(full_db, "a")
        db.upsert_listing(make_listing("a", price_eur=92_000,
                                       last_seen_at="2026-09-10T08:00:00+00:00"))
        assert _history(full_db, "a") == [(100_000, "2026-09-01T08:00:00+00:00"),
                                          (92_000, "2026-09-10T08:00:00+00:00")]
        assert not _has_score(full_db, "a")
        c = full_db()
        assert c.execute("SELECT classification FROM listings WHERE id='a'").fetchone()[0] == "PENDING"
        c.close()

    def test_a_failed_price_read_records_nothing(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=100_000))
        _score(full_db, "a")
        db.upsert_listing(make_listing("a", price_eur=0))
        assert len(_history(full_db, "a")) == 1
        assert _has_score(full_db, "a")

    def test_rows_from_before_history_keep_their_first_price(self, full_db):
        # A row inserted before price_history existed has no entries.
        db.upsert_listing(make_listing("a", price_eur=100_000))
        c = full_db()
        c.execute("DELETE FROM price_history")
        c.commit()
        c.close()
        db.upsert_listing(make_listing("a", price_eur=95_000,
                                       last_seen_at="2026-09-20T08:00:00+00:00"))
        assert [p for p, _ in _history(full_db, "a")] == [100_000, 95_000]
        assert _history(full_db, "a")[0][1] == "2026-09-01T08:00:00+00:00"   # scraped_at

    def test_a_repair_restarts_the_history(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=1_250_000))
        db.set_listing_price("a", 189_000)
        assert [p for p, _ in _history(full_db, "a")] == [189_000]

    def test_clearing_a_price_clears_the_history(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=1_250_000))
        db.set_listing_price("a", 0)
        assert _history(full_db, "a") == []

    def test_a_ceiling_cleanup_forgets_the_misread(self, full_db):
        from engine.regional_prices import zero_above_regional_ceiling
        db.upsert_listing(make_listing("a", price_eur=1_250_000, size_m2=50))
        assert zero_above_regional_ceiling("bazos") == 1
        assert _history(full_db, "a") == []


class TestSummary:
    def test_repeats_are_not_changes(self):
        rows = [("a", 100, "t1"), ("a", 100, "t2"), ("a", 90, "t3"), ("a", 90, "t4")]
        s = db.summarize_price_history(rows)["a"]
        assert s["n_changes"] == 1
        assert s["first_price"] == 100 and s["last_price"] == 90
        assert s["change_pct"] == pytest.approx(-0.10)
        assert s["last_change_at"] == "t3"

    def test_unchanged_listings_are_left_out(self):
        assert db.summarize_price_history([("a", 100, "t1"), ("a", 100, "t2")]) == {}

    def test_last_change_is_against_the_previous_price(self):
        rows = [("a", 100, "t1"), ("a", 90, "t2"), ("a", 81, "t3")]
        s = db.summarize_price_history(rows)["a"]
        assert s["last_change_pct"] == pytest.approx(-0.10)
        assert s["change_pct"] == pytest.approx(-0.19)


class TestPriceDrops:
    def _cut(self, lid, old, new, days_ago):
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        first = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        db.upsert_listing(make_listing(lid, price_eur=old, now=first))
        db.upsert_listing(make_listing(lid, price_eur=new, scraped_at=first, last_seen_at=when))

    def test_recent_cut_is_reported(self, full_db):
        self._cut("a", 100_000, 94_000, days_ago=3)
        drops = db.get_price_drops(days=14)
        assert [d["id"] for d in drops] == ["a"]
        assert drops[0]["last_change_pct"] == pytest.approx(-0.06)
        assert drops[0]["first_price"] == 100_000

    def test_old_cut_is_not(self, full_db):
        self._cut("a", 100_000, 94_000, days_ago=30)
        assert db.get_price_drops(days=14) == []

    def test_rise_and_rounding_noise_are_not(self, full_db):
        self._cut("up", 100_000, 105_000, days_ago=1)
        self._cut("tiny", 100_000, 99_500, days_ago=1)
        assert db.get_price_drops(days=14) == []

    def test_a_correction_is_not_a_cut(self, full_db):
        self._cut("a", 1_000_000, 190_000, days_ago=1)
        assert db.get_price_drops(days=14) == []

    def test_rejected_and_inactive_are_left_out(self, full_db):
        self._cut("rej", 100_000, 90_000, days_ago=1)
        self._cut("gone", 100_000, 90_000, days_ago=1)
        c = full_db()
        c.execute("UPDATE listings SET lv_status='REJECTED' WHERE id='rej'")
        c.execute("UPDATE listings SET is_active=0 WHERE id='gone'")
        c.commit()
        c.close()
        assert db.get_price_drops(days=14) == []


class TestDaysOnMarket:
    def test_counts_whole_days_from_first_seen(self):
        assert db.days_on_market("2026-09-01T08:00:00+00:00",
                                 until="2026-09-11T07:00:00+00:00") == 9
        assert db.days_on_market("2026-09-01T08:00:00+00:00",
                                 until="2026-09-11T09:00:00+00:00") == 10

    def test_naive_timestamps_and_garbage(self):
        assert db.days_on_market("2026-09-01T08:00:00", until="2026-09-03T08:00:00") == 2
        assert db.days_on_market(None) is None
        assert db.days_on_market("yesterday") is None

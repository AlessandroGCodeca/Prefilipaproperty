"""Regression tests for defects the review of the PR #33 merge found that
were still open on main after PR #37:

- a price repair recorded the corrected price as a cut made today
- compute_deal_score let the third risk flag go free
- scores classed under an older rule (or median) were never redone
- the memo printed Claude's LV summary twice
- one_per_flat (Hide portal copies) picks among the filtered rows
"""

from datetime import datetime, timedelta, timezone

import database as db
from engine.duplicates import one_per_flat
from engine.financial import compute_deal_score, max_offer_price
from engine.regional_prices import CITY_MEDIAN_PRICE_PER_M2
from tests.conftest import make_listing

ZILINA = CITY_MEDIAN_PRICE_PER_M2["žilina"]


def _q(conn_fn, sql, *args):
    c = conn_fn()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(conn_fn, sql, *args):
    c = conn_fn()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _has_score(conn_fn, lid):
    return bool(_q(conn_fn, "SELECT 1 FROM cashflow_scores WHERE listing_id=?", lid))


# ── Price repair ──────────────────────────────────────────────────────────────
class TestARepairIsNotAFreshCut:
    def test_the_corrected_price_takes_the_misreads_date(self, full_db):
        now = datetime.now(timezone.utc)
        genuine = (now - timedelta(days=60)).isoformat()
        misread = (now - timedelta(days=45)).isoformat()
        db.upsert_listing(make_listing("a", price_eur=200_000, now=genuine))
        db.upsert_listing(make_listing("a", price_eur=1_250_000, scraped_at=genuine,
                                       last_seen_at=misread))
        db.set_listing_price("a", 195_000)
        # 200k → 195k happened when the misread was seen, 45 days ago — not a
        # cut in the last two weeks.
        assert db.get_price_drops(days=14) == []
        rows = _q(full_db, "SELECT price_eur, observed_at FROM price_history "
                           "WHERE listing_id='a' ORDER BY observed_at, id")
        assert [(r["price_eur"], r["observed_at"]) for r in rows] == \
            [(200_000, genuine), (195_000, misread)]

    def test_without_a_recorded_misread_it_is_dated_now(self, full_db):
        db.upsert_listing(make_listing("a", price_eur=200_000))
        _x(full_db, "UPDATE listings SET price_eur=1250000 WHERE id='a'")  # never recorded
        db.set_listing_price("a", 195_000)
        last = _q(full_db, "SELECT observed_at FROM price_history WHERE listing_id='a' "
                           "ORDER BY observed_at DESC, id DESC LIMIT 1")[0]["observed_at"]
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        assert age < timedelta(minutes=5)


# ── Deal score ────────────────────────────────────────────────────────────────
class TestEveryRiskFlagCounts:
    BASE = {"cap_rate": 0.05, "market_discount": 0.2, "location_score": 70,
            "construction_risk": 1, "noise_flag": 1, "flood_zone": 1}

    def test_the_third_flag_costs_points(self):
        three, _ = compute_deal_score({**self.BASE, "lv_status": "PASS"})
        two, _ = compute_deal_score({**self.BASE, "flood_zone": 0, "lv_status": "PASS"})
        assert three < two

    def test_three_flags_still_tell_verified_from_unverified(self):
        verified, _ = compute_deal_score({**self.BASE, "lv_status": "PASS"})
        unverified, _ = compute_deal_score({**self.BASE, "lv_status": "UNVERIFIED"})
        assert unverified < verified

    def test_the_score_never_goes_negative(self):
        worst = {"cap_rate": 0.0, "market_discount": -0.5,
                 "construction_risk": 1, "noise_flag": 1, "flood_zone": 1,
                 "lv_status": "UNVERIFIED"}
        assert compute_deal_score(worst) == (0, "D")


# ── Stale classes ─────────────────────────────────────────────────────────────
class TestStaleClassesAreRequeued:
    def _score(self, conn_fn, lid, cls, green, yellow):
        # With the median stored, so requeue_scores_without_benchmark leaves it.
        _x(conn_fn, "INSERT INTO cashflow_scores (listing_id, classification, rent_source, "
                    "max_price_green, max_price_yellow, regional_median_m2) "
                    "VALUES (?, ?, 'baseline', ?, ?, ?)",
           lid, cls, green, yellow, ZILINA)
        _x(conn_fn, "UPDATE listings SET classification=? WHERE id=?", cls, lid)

    def test_a_class_from_an_older_rule_is_dropped(self, full_db):
        # Exactly 20% under the median: GREEN since classify() judges at 4
        # decimals, YELLOW before.
        db.upsert_listing(make_listing("a", district="Žilina", size_m2=58,
                                       price_eur=ZILINA * 58 * 0.8))
        self._score(full_db, "a", "YELLOW", max_offer_price(58, "Žilina", "GREEN"),
                    max_offer_price(58, "Žilina", "YELLOW"))
        assert db.requeue_scores_with_stale_class() == 1
        assert not _has_score(full_db, "a")
        assert _q(full_db, "SELECT classification FROM listings")[0]["classification"] \
            == "PENDING"

    def test_max_offers_from_an_older_median_are_dropped(self, full_db):
        db.upsert_listing(make_listing("a", district="Žilina", size_m2=58,
                                       price_eur=ZILINA * 58))
        self._score(full_db, "a", "WHITE", 1_000, 2_000)
        assert db.requeue_scores_with_stale_class() == 1

    def test_a_rejected_listing_keeps_its_score(self, full_db):
        # Scoring skips rejected listings, so a dropped score never came back.
        db.upsert_listing(make_listing("a", district="Žilina", size_m2=58,
                                       price_eur=ZILINA * 58 * 0.8))
        self._score(full_db, "a", "YELLOW", None, None)
        db.set_lv_status("a", "REJECTED", "exekúcia", "x")
        assert db.requeue_scores_with_stale_class() == 0

    def test_a_current_score_is_kept_and_not_redone(self, full_db):
        from modules.cashflow_runner import run_scoring
        db.upsert_listing(make_listing("a", district="Žilina", size_m2=58,
                                       price_eur=ZILINA * 58 * 0.85))
        db.upsert_listing(make_listing("b", district="Atlantis", size_m2=58,
                                       price_eur=100_000))     # no benchmark
        assert run_scoring() == 2
        assert db.requeue_scores_with_stale_class() == 0
        assert run_scoring() == 0

    def test_scoring_redoes_a_stale_class(self, full_db):
        from modules.cashflow_runner import run_scoring
        db.upsert_listing(make_listing("a", district="Žilina", size_m2=58,
                                       price_eur=ZILINA * 58 * 0.8))
        self._score(full_db, "a", "YELLOW", None, None)
        assert run_scoring() == 1
        assert _q(full_db, "SELECT classification FROM cashflow_scores")[0]["classification"] \
            == "GREEN"


# ── Portal copies ─────────────────────────────────────────────────────────────
class TestOnePerFlat:
    def _rows(self):
        return [
            {"id": "a", "dup_group": "a", "lv_status": "PASS", "price_eur": 161_000},
            {"id": "b", "dup_group": "a", "lv_status": "UNVERIFIED", "price_eur": 157_000},
            {"id": "c", "dup_group": "a", "lv_status": "UNVERIFIED", "price_eur": 158_000},
            {"id": "x", "dup_group": None, "price_eur": 90_000},
        ]

    def test_the_primary_is_kept_when_it_is_there(self):
        assert [r["id"] for r in one_per_flat(self._rows())] == ["a", "x"]

    def test_a_copy_stands_in_when_the_primary_was_filtered_out(self):
        rows = [r for r in self._rows() if r["price_eur"] <= 160_000]
        assert [r["id"] for r in one_per_flat(rows)] == ["b", "x"]


# ── Memo ──────────────────────────────────────────────────────────────────────
class TestMemoLvOnce:
    def _paras(self, monkeypatch, row):
        import modules.memo as memo
        seen = []
        real = memo._Memo.para

        def para(self, text, *a, **k):
            seen.append(text)
            return real(self, text, *a, **k)
        monkeypatch.setattr(memo._Memo, "para", para)
        memo.build_memo_pdf(row)
        return "\n".join(seen)

    BASE = {"id": "x", "title": "Byt", "price_eur": 0, "size_m2": 0, "lv_status": "PASS"}

    def test_claudes_summary_is_not_printed_twice(self, monkeypatch):
        text = self._paras(monkeypatch, {**self.BASE,
                                         "lv_detail": "[Claude LOW] Bank mortgage only.",
                                         "lv_summary": "Bank mortgage only."})
        assert text.count("Bank mortgage only.") == 1

    def test_a_summary_the_detail_lacks_is_still_printed(self, monkeypatch):
        text = self._paras(monkeypatch, {**self.BASE,
                                         "lv_detail": "Flat LV read, clean.",
                                         "lv_summary": "Bank mortgage only."})
        assert "Flat LV read, clean." in text and "Bank mortgage only." in text


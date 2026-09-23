"""Tests for repairing prices that were read off a neighbouring listing.

The extraction now reads the listing's own price heading, but that only helps
listings it reads again — and get_fresh_detail_urls() treats a row with a price
and a size as complete, so the wrong values were frozen in place. A live run
after the extraction fix showed exactly that: €1,399,000 still sitting on flats
of 200, 188 and 114 m², untouched, because all three were skipped as "already
scraped recently".

get_shared_price_listings() finds them; set_listing_price() is what can write a
price back down to 0, which upsert_listing deliberately refuses to do.
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id             TEXT PRIMARY KEY,
            source         TEXT NOT NULL,
            url            TEXT NOT NULL UNIQUE,
            title          TEXT,
            price_eur      REAL NOT NULL,
            size_m2        REAL,
            district       TEXT,
            classification TEXT DEFAULT 'PENDING',
            is_active      INTEGER DEFAULT 1
        )
    """)
    # The live rows: one price on three differently-sized flats, one price on
    # two flats of the SAME size (a repeated unit type, not bleed), and
    # listings whose price nothing else shares.
    rows = [
        ("bleed-200",  1_399_000, 200.0,  1, "nehnutelnosti"),
        ("bleed-188",  1_399_000, 188.0,  1, "nehnutelnosti"),
        ("bleed-114",  1_399_000, 114.0,  1, "nehnutelnosti"),
        ("same-size-a",  549_900,  75.0,  1, "nehnutelnosti"),
        ("same-size-b",  549_900,  75.0,  1, "nehnutelnosti"),
        ("unique",       342_000,  82.0,  1, "nehnutelnosti"),
        ("inactive",   1_399_000,  95.0,  0, "nehnutelnosti"),
        ("no-size",    1_399_000,     0,  1, "nehnutelnosti"),
        ("other-src",  1_399_000, 150.0,  1, "topreality"),
        ("other-src2", 1_399_000, 160.0,  1, "topreality"),
    ]
    for rid, price, size, active, source in rows:
        conn.execute(
            "INSERT INTO listings (id, source, url, title, price_eur, size_m2,"
            " district, classification, is_active)"
            " VALUES (?,?,?,?,?,?,'Bratislava','WHITE',?)",
            (rid, source, f"http://x/{rid}", f"title {rid}", price, size, active),
        )
    conn.commit()
    conn.close()

    import database as db

    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)
    yield path
    os.unlink(path)


def _row(path, rid):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM listings WHERE id=?", (rid,)).fetchone()
    conn.close()
    return r


class TestGetSharedPriceListings:
    def test_finds_the_price_on_differently_sized_flats(self, temp_db):
        import database as db
        ids = {r["id"] for r in db.get_shared_price_listings("nehnutelnosti")}
        assert ids == {"bleed-200", "bleed-188", "bleed-114"}

    def test_same_size_repeats_are_not_suspect(self, temp_db):
        """Two 75 m² units at one price is a repeated unit type, not bleed."""
        import database as db
        ids = {r["id"] for r in db.get_shared_price_listings("nehnutelnosti")}
        assert "same-size-a" not in ids and "same-size-b" not in ids

    def test_unique_price_untouched(self, temp_db):
        import database as db
        ids = {r["id"] for r in db.get_shared_price_listings("nehnutelnosti")}
        assert "unique" not in ids

    def test_inactive_and_sizeless_rows_excluded(self, temp_db):
        import database as db
        ids = {r["id"] for r in db.get_shared_price_listings("nehnutelnosti")}
        assert "inactive" not in ids and "no-size" not in ids

    def test_scoped_to_one_source(self, temp_db):
        import database as db
        ids = {r["id"] for r in db.get_shared_price_listings("topreality")}
        assert ids == {"other-src", "other-src2"}

    def test_stricter_threshold_narrows_it(self, temp_db):
        import database as db
        assert db.get_shared_price_listings(
            "nehnutelnosti", min_distinct_sizes=4) == []

    def test_limit_respected(self, temp_db):
        import database as db
        assert len(db.get_shared_price_listings("nehnutelnosti", limit=2)) == 2

    def test_rows_carry_what_the_repair_needs(self, temp_db):
        import database as db
        row = db.get_shared_price_listings("nehnutelnosti")[0]
        for key in ("id", "url", "price_eur", "size_m2", "title"):
            assert key in row


class TestSetListingPrice:
    def test_corrects_a_price(self, temp_db):
        import database as db
        assert db.set_listing_price("bleed-200", 342_000) is True
        assert _row(temp_db, "bleed-200")["price_eur"] == 342_000

    def test_correcting_leaves_classification_alone(self, temp_db):
        """A real price replacing a wrong one doesn't need re-triage."""
        import database as db
        db.set_listing_price("bleed-200", 342_000)
        assert _row(temp_db, "bleed-200")["classification"] == "WHITE"

    def test_clearing_resets_to_pending(self, temp_db):
        """What upsert_listing refuses to do, and why this exists."""
        import database as db
        assert db.set_listing_price("bleed-200", 0) is True
        row = _row(temp_db, "bleed-200")
        assert row["price_eur"] == 0
        assert row["classification"] == "PENDING"

    def test_clearing_drops_the_enrichment_stamp(self, temp_db):
        """Otherwise the freshness skip would keep the row frozen — the exact
        reason the bad prices survived the extraction fix."""
        import database as db
        db.mark_details_enriched(["bleed-200"])
        assert db.get_fresh_detail_urls("nehnutelnosti") != set()
        db.set_listing_price("bleed-200", 0)
        assert "http://x/bleed-200" not in db.get_fresh_detail_urls("nehnutelnosti")

    def test_unknown_id(self, temp_db):
        import database as db
        assert db.set_listing_price("no-such-row", 100_000) is False
        assert db.set_listing_price("no-such-row", 0) is False


class TestRepairArgs:
    @pytest.mark.parametrize("argv,limit,dry", [
        ([], 100, False),
        (["50"], 50, False),
        (["--dry-run"], 100, True),
        (["200", "--dry-run"], 200, True),
        (["--dry-run", "25"], 25, True),
    ])
    def test_parsing(self, argv, limit, dry):
        import repair_prices
        assert repair_prices._parse_args(argv) == (limit, dry)


# ── Refusing to replace one shared price with another ─────────────────────────
class TestRepeatedAcrossSizes:
    """The first repair run "corrected" 77 listings and wrote €697,800 onto
    seven of 104–178 m² — the same fault it was repairing, with a different
    number. Two passes minutes apart also disagreed (€610,000 vs €430,000 on
    the same listings), because the carousel being read rotates. A proposal
    that repeats across sizes is therefore not written.
    """

    LIVE = [
        {"id": "a", "size_m2": 111.0,  "price": 697_800.0},
        {"id": "b", "size_m2": 119.7,  "price": 697_800.0},
        {"id": "c", "size_m2": 143.82, "price": 697_800.0},
        {"id": "d", "size_m2": 170.0,  "price": 697_800.0},
        {"id": "e", "size_m2": 178.0,  "price": 697_800.0},
        {"id": "f", "size_m2": 112.0,  "price": 697_800.0},
        {"id": "g", "size_m2": 104.5,  "price": 697_800.0},
        {"id": "ok", "size_m2": 82.0,  "price": 342_000.0},
    ]

    def test_rejects_the_seven(self):
        from repair_prices import repeated_across_sizes
        assert repeated_across_sizes(self.LIVE) == {"a", "b", "c", "d", "e", "f", "g"}

    def test_keeps_a_price_nothing_else_claims(self):
        from repair_prices import repeated_across_sizes
        assert "ok" not in repeated_across_sizes(self.LIVE)

    def test_same_size_repeat_is_allowed(self):
        """Two 75 m² units at one price is a repeated unit type, not a
        borrowed price — the properties really can share it."""
        from repair_prices import repeated_across_sizes
        proposals = [
            {"id": "u1", "size_m2": 75.0, "price": 283_500.0},
            {"id": "u2", "size_m2": 75.0, "price": 283_500.0},
        ]
        assert repeated_across_sizes(proposals) == set()

    def test_unpriced_proposals_are_not_grouped(self):
        """Several reads returning nothing must not look like a shared price."""
        from repair_prices import repeated_across_sizes
        proposals = [
            {"id": "n1", "size_m2": 60.0, "price": 0.0},
            {"id": "n2", "size_m2": 90.0, "price": 0.0},
        ]
        assert repeated_across_sizes(proposals) == set()

    def test_empty(self):
        from repair_prices import repeated_across_sizes
        assert repeated_across_sizes([]) == set()

    def test_missing_size_still_compares(self):
        from repair_prices import repeated_across_sizes
        proposals = [
            {"id": "x", "size_m2": 0, "price": 500_000.0},
            {"id": "y", "size_m2": 80.0, "price": 500_000.0},
        ]
        assert repeated_across_sizes(proposals) == {"x", "y"}

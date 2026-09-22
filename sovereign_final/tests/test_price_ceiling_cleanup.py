"""Tests for engine.regional_prices.zero_above_regional_ceiling — the cleanup
that repairs rows already holding a price picked up from a different listing.

Those rows don't fix themselves: a listing the engine believes costs €1.25M can
never score as a deal, and nothing re-reads it while its price looks set.
Zeroing sends it back to PENDING for the next scrape.
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
            price_eur      REAL NOT NULL,
            size_m2        REAL,
            district       TEXT,
            classification TEXT DEFAULT 'PENDING'
        )
    """)
    # (id, price, size, district, source) — the misreads, then the genuine ones.
    rows = [
        ("herrys-garsonka", 1_250_000, 21.82, "Bratislava",  "nehnutelnosti"),
        ("herrys-2izb",     1_250_000, 58.0,  "Bratislava",  "nehnutelnosti"),
        ("bernolakovo",     1_500_000, 54.0,  "Senec",       "nehnutelnosti"),
        ("topreality-4izb", 2_465_000, 93.0,  "",            "topreality"),
        ("penthouse",       1_689_000, 170.0, "Staré Mesto", "nehnutelnosti"),
        ("corvus-atrium",     182_000, 46.41, "Malacky",     "nehnutelnosti"),
        ("no-size",         1_250_000, 0,     "Bratislava",  "nehnutelnosti"),
    ]
    for rid, price, size, district, source in rows:
        conn.execute(
            "INSERT INTO listings (id, source, url, price_eur, size_m2, district,"
            " classification) VALUES (?,?,?,?,?,?,'WHITE')",
            (rid, source, f"http://x/{rid}", price, size, district),
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
    r = conn.execute(
        "SELECT price_eur, classification FROM listings WHERE id=?", (rid,)
    ).fetchone()
    conn.close()
    return r


class TestZeroAboveRegionalCeiling:
    def test_zeroes_the_misreads_of_that_source(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        assert zero_above_regional_ceiling("nehnutelnosti") == 3
        for rid in ("herrys-garsonka", "herrys-2izb", "bernolakovo"):
            assert _row(temp_db, rid) == (0, "PENDING"), rid

    def test_leaves_genuine_listings_alone(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        zero_above_regional_ceiling("nehnutelnosti")
        assert _row(temp_db, "penthouse") == (1_689_000, "WHITE")
        assert _row(temp_db, "corvus-atrium") == (182_000, "WHITE")

    def test_a_row_with_no_size_cannot_be_judged(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        zero_above_regional_ceiling("nehnutelnosti")
        assert _row(temp_db, "no-size") == (1_250_000, "WHITE")

    def test_scoped_to_one_source(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        zero_above_regional_ceiling("nehnutelnosti")
        assert _row(temp_db, "topreality-4izb") == (2_465_000, "WHITE")
        assert zero_above_regional_ceiling("topreality") == 1
        assert _row(temp_db, "topreality-4izb") == (0, "PENDING")

    def test_idempotent(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        assert zero_above_regional_ceiling("nehnutelnosti") == 3
        assert zero_above_regional_ceiling("nehnutelnosti") == 0

    def test_clean_database_is_a_noop(self, temp_db):
        from engine.regional_prices import zero_above_regional_ceiling
        assert zero_above_regional_ceiling("bazos") == 0

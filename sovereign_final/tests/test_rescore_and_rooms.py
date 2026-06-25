"""Tests for the P0 fixes:
  - get_unscored_cashflow() must return the `rooms` column (otherwise the
    rooms-aware rent multiplier silently never fires — it was missing from the
    SELECT, so cashflow_runner always passed rooms=None).
  - clear_cashflow_scores() must wipe scores and reset listings to PENDING so a
    re-score run reprocesses everything after the rent/tax assumptions change.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Isolated SQLite with the listings + cashflow_scores tables and a few rows
    (some scored, some not), with database.get_conn patched to point at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id            TEXT PRIMARY KEY,
            source        TEXT NOT NULL,
            url           TEXT NOT NULL UNIQUE,
            url_hash      TEXT UNIQUE,
            title         TEXT,
            price_eur     REAL NOT NULL,
            size_m2       REAL,
            rooms         REAL,
            district      TEXT,
            energy_class  TEXT DEFAULT 'UNKNOWN',
            classification TEXT DEFAULT 'PENDING',
            lv_status     TEXT DEFAULT 'PENDING',
            scraped_at    TEXT NOT NULL,
            last_seen_at  TEXT NOT NULL,
            is_active     INTEGER DEFAULT 1
        )
    """)
    conn.execute("CREATE TABLE cashflow_scores (listing_id TEXT PRIMARY KEY, classification TEXT)")

    now = datetime.now(timezone.utc).isoformat()
    # (id, rooms, scored?)
    rows = [
        ("unscored-1", 1, False),
        ("unscored-2", 3, False),
        ("scored-1",   2, True),
    ]
    for rid, rooms, scored in rows:
        conn.execute("""
            INSERT INTO listings (id, source, url, url_hash, price_eur, size_m2,
                                  rooms, district, classification, lv_status,
                                  scraped_at, last_seen_at, is_active)
            VALUES (?, 'test', ?, ?, 150000, 60, ?, 'Bratislava',
                    ?, 'PASS', ?, ?, 1)
        """, (rid, f"http://x/{rid}", rid, rooms,
              "GREEN" if scored else "PENDING", now, now))
        if scored:
            conn.execute(
                "INSERT INTO cashflow_scores (listing_id, classification) VALUES (?, 'GREEN')",
                (rid,),
            )
    conn.commit()
    conn.close()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)

    yield path
    os.unlink(path)


def test_unscored_cashflow_returns_rooms(temp_db):
    """Regression: the SELECT used to omit `rooms`, so the rooms multiplier
    never received a value. Every unscored row must expose its rooms count."""
    from database import get_unscored_cashflow
    rows = get_unscored_cashflow()
    assert len(rows) == 2  # only the two unscored listings
    by_id = {r["id"]: r for r in rows}
    assert "rooms" in by_id["unscored-1"]
    assert by_id["unscored-1"]["rooms"] == 1
    assert by_id["unscored-2"]["rooms"] == 3


def test_clear_cashflow_scores_wipes_and_resets(temp_db):
    from database import clear_cashflow_scores, get_unscored_cashflow
    # Before: one row already scored, so only 2 are unscored
    assert len(get_unscored_cashflow()) == 2
    removed = clear_cashflow_scores()
    assert removed == 1  # the single scored row
    # After clearing, all three listings are unscored again
    assert len(get_unscored_cashflow()) == 3


def test_clear_resets_classification_to_pending(temp_db):
    from database import clear_cashflow_scores
    clear_cashflow_scores()
    conn = sqlite3.connect(temp_db)
    classes = [r[0] for r in conn.execute("SELECT classification FROM listings")]
    conn.close()
    assert all(c == "PENDING" for c in classes)

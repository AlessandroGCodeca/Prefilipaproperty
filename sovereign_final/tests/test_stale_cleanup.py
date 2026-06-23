"""Tests for database.deactivate_stale_listings — keeps the dashboard from
showing listings that haven't been re-seen on the source site for weeks."""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Spin up an isolated SQLite file with the listings schema, populate
    test rows, and patch database.get_conn to point at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Apply the schema (only the listings table is needed for these tests)
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
            classification TEXT DEFAULT 'PENDING',
            lv_status     TEXT DEFAULT 'PENDING',
            scraped_at    TEXT NOT NULL,
            last_seen_at  TEXT NOT NULL,
            is_active     INTEGER DEFAULT 1
        )
    """)

    now = datetime.now(timezone.utc)
    rows = [
        # (id, last_seen_days_ago, is_active)
        ("fresh-1",    0,  1),
        ("fresh-2",    5,  1),
        ("borderline", 20, 1),
        ("stale-1",    22, 1),
        ("stale-2",    60, 1),
        ("inactive",   90, 0),  # already inactive — should NOT count again
    ]
    for rid, days_ago, active in rows:
        seen = (now - timedelta(days=days_ago)).isoformat()
        conn.execute("""
            INSERT INTO listings (id, source, url, url_hash, price_eur,
                                  scraped_at, last_seen_at, is_active)
            VALUES (?, 'test', ?, ?, 100000, ?, ?, ?)
        """, (rid, f"http://x/{rid}", rid, seen, seen, active))
    conn.commit()
    conn.close()

    # Patch database.get_conn to return a connection to our temp file
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)

    yield path
    os.unlink(path)


def _count_active(path):
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active=1").fetchone()[0]
    conn.close()
    return n


def _count_active_by_id(path, ids):
    conn = sqlite3.connect(path)
    ph = ",".join("?" * len(ids))
    n = conn.execute(
        f"SELECT COUNT(*) FROM listings WHERE is_active=1 AND id IN ({ph})",
        ids,
    ).fetchone()[0]
    conn.close()
    return n


def test_deactivates_only_stale(temp_db):
    from database import deactivate_stale_listings
    assert _count_active(temp_db) == 5
    n = deactivate_stale_listings(days=21)
    # Should deactivate "stale-1" (22d) and "stale-2" (60d), not the rest
    assert n == 2
    assert _count_active(temp_db) == 3


def test_borderline_kept_active(temp_db):
    # 20 days old is younger than 21-day cutoff → still active
    from database import deactivate_stale_listings
    deactivate_stale_listings(days=21)
    assert _count_active_by_id(temp_db, ["borderline"]) == 1


def test_does_not_touch_already_inactive(temp_db):
    # Row already at is_active=0 shouldn't be counted as "deactivated"
    from database import deactivate_stale_listings
    n = deactivate_stale_listings(days=21)
    assert n == 2  # only the two newly-stale rows, not the already-inactive one


def test_custom_cutoff(temp_db):
    # A 7-day cutoff should also catch the borderline 20-day row
    from database import deactivate_stale_listings
    n = deactivate_stale_listings(days=7)
    assert n == 3  # borderline + stale-1 + stale-2


def test_no_stale_returns_zero(temp_db):
    # Running twice should leave nothing to deactivate on the second call
    from database import deactivate_stale_listings
    deactivate_stale_listings(days=21)
    n = deactivate_stale_listings(days=21)
    assert n == 0

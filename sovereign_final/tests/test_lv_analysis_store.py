"""Tests for database.set_lv_analysis — persisting modules/debt_bot's Claude
analyze_lv read (risk level + summary) onto the listing row so the dashboard can
surface it. The column migration runs inside the helper, so a DB predating the
lv_* columns still works."""

import os
import sqlite3
import sys
import tempfile

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    # Minimal listings table WITHOUT the lv_* columns — exercises the migration.
    conn.execute("""
        CREATE TABLE listings (
            id TEXT PRIMARY KEY, source TEXT, url TEXT UNIQUE,
            lv_status TEXT DEFAULT 'PENDING'
        )
    """)
    conn.execute("INSERT INTO listings (id, source, url) VALUES ('l1','t','http://x/l1')")
    conn.commit()
    conn.close()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _conn)
    yield path
    os.unlink(path)


def test_adds_columns_and_persists(temp_db):
    from database import set_lv_analysis
    set_lv_analysis("l1", "HIGH", "Exekúcia registered on title.")
    conn = sqlite3.connect(temp_db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(listings)")]
    row = conn.execute(
        "SELECT lv_risk_level, lv_summary FROM listings WHERE id='l1'"
    ).fetchone()
    conn.close()
    assert "lv_risk_level" in cols and "lv_summary" in cols
    assert row[0] == "HIGH"
    assert "Exekúcia" in row[1]


def test_empty_values_store_null(temp_db):
    from database import set_lv_analysis
    set_lv_analysis("l1", "", "")
    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        "SELECT lv_risk_level, lv_summary FROM listings WHERE id='l1'"
    ).fetchone()
    conn.close()
    assert row[0] is None and row[1] is None


def test_summary_truncated(temp_db):
    from database import set_lv_analysis
    set_lv_analysis("l1", "LOW", "x" * 5000)
    conn = sqlite3.connect(temp_db)
    row = conn.execute("SELECT lv_summary FROM listings WHERE id='l1'").fetchone()
    conn.close()
    assert len(row[0]) == 1000

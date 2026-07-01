"""Tests for the LV debt-filter fabrication fix.

The old demo mode invented "[DEMO]" liens for listings without a cadastral
parcel number — and since scrapers never provide one, every listing shared the
same fallback hash seed and one run REJECTED them all, emptying the dashboard.

Covers: the unverified-PASS path in query_lv_api, reset_demo_rejections()
healing fabricated rejections, and a run_debt_filter integration pass over a
temp DB (heals, passes unverified, persists no fabricated rejections)."""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

import modules.debt_bot as debt_bot


class TestUnverifiedPass:
    def test_no_key_passes_unverified(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "CADASTRAL_API_KEY", "")
        res = debt_bot.query_lv_api("123/4")
        assert res["status"] == "PASS"
        assert res["unverified"] is True
        assert "unverified" in res["detail"].lower()
        assert res["raw"] == {}  # nothing for _decide_lv / Claude to read

    def test_no_parcel_passes_unverified_even_with_key(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "CADASTRAL_API_KEY", "real-key")
        for missing in ("", None):
            res = debt_bot.query_lv_api(missing)
            assert res["status"] == "PASS" and res.get("unverified")

    def test_two_listings_get_identical_honest_result(self, monkeypatch):
        # Regression: the old code hashed a shared fallback seed, so verdicts
        # were fabricated-but-identical. Now both are the same *honest* PASS.
        monkeypatch.setattr(debt_bot, "CADASTRAL_API_KEY", "")
        a = debt_bot.query_lv_api("")
        b = debt_bot.query_lv_api("999/1")
        assert a["status"] == b["status"] == "PASS"


@pytest.fixture
def temp_db(monkeypatch):
    """listings + rejections_log with two [DEMO]-rejected rows, one real
    rejection, and one pending row; database.get_conn patched to it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id TEXT PRIMARY KEY, source TEXT, url TEXT UNIQUE,
            address_raw TEXT DEFAULT '', cadastral_number TEXT,
            cadastral_area TEXT, lv_status TEXT DEFAULT 'PENDING',
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE rejections_log (
            id TEXT PRIMARY KEY, listing_id TEXT, reason TEXT,
            detail TEXT, module TEXT, flagged_at TEXT
        )
    """)
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        ("demo1", "REJECTED", "[DEMO] Non-bank lien detected — private creditor"),
        ("demo2", "REJECTED", "[DEMO] Court execution order registered on title"),
        ("real1", "REJECTED", "LV encumbrance detected: 'exekúcia'"),
        ("fresh", "PENDING",  None),
    ]
    for rid, status, detail in rows:
        conn.execute(
            "INSERT INTO listings (id, source, url, lv_status) VALUES (?,?,?,?)",
            (rid, "test", f"http://x/{rid}", status))
        if detail:
            conn.execute(
                "INSERT INTO rejections_log VALUES (?,?,?,?,?,?)",
                (f"r-{rid}", rid, "flag", detail, "debt_bot", now))
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


class TestResetDemoRejections:
    def test_heals_demo_rows_only(self, temp_db):
        from database import reset_demo_rejections
        healed = reset_demo_rejections()
        assert healed == 2
        conn = sqlite3.connect(temp_db)
        status = dict(conn.execute("SELECT id, lv_status FROM listings"))
        details = [r[0] for r in conn.execute("SELECT detail FROM rejections_log")]
        conn.close()
        assert status["demo1"] == "PENDING" and status["demo2"] == "PENDING"
        assert status["real1"] == "REJECTED"          # real rejection untouched
        assert all("[DEMO]" not in d for d in details)  # fabricated log rows gone
        assert any("exekúcia" in d for d in details)    # real log row kept

    def test_idempotent_on_clean_db(self, temp_db):
        from database import reset_demo_rejections
        reset_demo_rejections()
        assert reset_demo_rejections() == 0


class TestRunDebtFilterIntegration:
    def test_heals_then_passes_unverified(self, temp_db, monkeypatch):
        # No cadastral key, Claude disabled → every checkable row should end
        # PASS (unverified), never REJECTED, and demo rows must be healed.
        monkeypatch.setattr(debt_bot, "CADASTRAL_API_KEY", "")
        monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)

        passed, rejected = debt_bot.run_debt_filter()
        assert rejected == 0
        assert passed == 3  # demo1, demo2 (healed) + fresh; real1 stays REJECTED

        conn = sqlite3.connect(temp_db)
        status = dict(conn.execute("SELECT id, lv_status FROM listings"))
        conn.close()
        assert status["demo1"] == status["demo2"] == status["fresh"] == "PASS"
        assert status["real1"] == "REJECTED"

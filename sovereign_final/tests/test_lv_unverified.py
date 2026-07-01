"""Tests for the LV debt-filter's honest-verdict behaviour.

The old demo mode invented "[DEMO]" liens for listings without a cadastral
parcel number — and since scrapers never provide one, every listing shared the
same fallback hash seed and one run REJECTED them all, emptying the dashboard.

query_lv_api now fetches real LV text through the unofficial skgeodesy.sk
scraper (kataster_scraper.enrich_parcel — no API key exists). Covers: the
unverified-PASS paths (no parcel data, scraper failure/not-found), the real
scan paths (clean LV passes, exekúcia rejects, raw text flows to Claude),
reset_demo_rejections() healing fabricated rejections, and a run_debt_filter
integration pass over a temp DB."""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

import modules.debt_bot as debt_bot


def _scraper_result(status="OK", detail="", lv_text=None, lv_no=4321):
    """Shape returned by kataster_scraper.enrich_parcel."""
    return {
        "status": status, "detail": detail, "source": "live",
        "query": {}, "cadastral_unit": {"code": 1, "name": "X"},
        "parcel": {"no": "1/1"}, "lv": {"no": lv_no} if lv_no else None,
        "owners": [], "lv_text": lv_text, "risk_flags": [],
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }


class TestUnverifiedPass:
    def test_no_parcel_or_area_passes_unverified(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: pytest.fail("scraper must not run"))
        for cid, area in (("", "Nitra"), (None, "Nitra"),
                          ("123/4", ""), ("", "")):
            res = debt_bot.query_lv_api(cid, area)
            assert res["status"] == "PASS"
            assert res["unverified"] is True
            assert "unverified" in res["detail"].lower()
            assert res["raw"] == {}  # nothing for _decide_lv / Claude to read

    def test_scraper_error_passes_unverified(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "enrich_parcel", lambda *a, **k:
                            _scraper_result("ERROR", "portal unreachable"))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "PASS" and res["unverified"] is True
        assert "portal unreachable" in res["detail"]

    def test_parcel_not_found_passes_unverified(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "enrich_parcel", lambda *a, **k:
                            _scraper_result("NOT_FOUND", "parcel '123/4' not found"))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "PASS" and res["unverified"] is True
        assert "not found" in res["detail"]

    def test_no_lv_text_passes_unverified(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "enrich_parcel", lambda *a, **k:
                            _scraper_result("OK", "parcel found (no LV)",
                                            lv_text=None, lv_no=None))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "PASS" and res["unverified"] is True

    def test_two_listings_get_identical_honest_result(self, monkeypatch):
        # Regression: the old code hashed a shared fallback seed, so verdicts
        # were fabricated-but-identical. Now both are the same *honest* PASS.
        a = debt_bot.query_lv_api("", "")
        b = debt_bot.query_lv_api("999/1", "")
        assert a["status"] == b["status"] == "PASS"


class TestRealLvScan:
    def test_clean_lv_passes_with_text_for_claude(self, monkeypatch):
        text = "Výpis z LV 4321. Časť C: Bez tiarch."
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: _scraper_result(lv_text=text))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "PASS"
        assert not res.get("unverified")
        assert res["raw"] == text          # real LV text flows to _decide_lv
        assert res["detail"].startswith("LV 4321:")

    def test_exekucia_rejects(self, monkeypatch):
        text = "Časť C ŤARCHY: Exekúcia EX 55/2021 na podiel vlastníka."
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: _scraper_result(lv_text=text))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "REJECT"
        assert res["flag"] == "exekúcia"
        assert res["raw"] == text

    def test_bank_lien_passes_substring_scan(self, monkeypatch):
        text = "Ťarchy: Záložné právo v prospech Tatra banka, a.s."
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: _scraper_result(lv_text=text))
        res = debt_bot.query_lv_api("123/4", "Nitra")
        assert res["status"] == "PASS"


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
        # No cadastral parcel data on any listing, Claude disabled → every
        # checkable row should end PASS (unverified), never REJECTED, the
        # scraper must never fire, and demo rows must be healed.
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: pytest.fail("scraper must not run"))
        monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)

        passed, rejected = debt_bot.run_debt_filter()
        assert rejected == 0
        assert passed == 3  # demo1, demo2 (healed) + fresh; real1 stays REJECTED

        conn = sqlite3.connect(temp_db)
        status = dict(conn.execute("SELECT id, lv_status FROM listings"))
        conn.close()
        assert status["demo1"] == status["demo2"] == status["fresh"] == "PASS"
        assert status["real1"] == "REJECTED"

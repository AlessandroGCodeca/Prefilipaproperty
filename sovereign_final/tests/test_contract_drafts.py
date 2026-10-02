"""Tests for database.save_contract_draft / get_contract_drafts — keeping the
drafts the ONE-CLICK CLOSE tab generates. The contract_drafts table existed but
nothing wrote to it, so a draft was gone as soon as the page reloaded."""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from database import get_contract_drafts, save_contract_draft  # noqa: E402


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(database.SQLITE_SCHEMA)
    conn.commit()
    conn.close()

    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(database, "get_conn", _temp_conn)

    yield path
    os.unlink(path)


def test_saved_draft_comes_back(temp_db):
    draft_id = save_contract_draft(
        "listing-1", "s.r.o.", 168000, "Moja s.r.o.", "12345678",
        "JUDr. Novák", "KÚPNA ZMLUVA — DRAFT ...")
    [d] = get_contract_drafts("listing-1")
    assert d["id"] == draft_id
    assert d["ownership_type"] == "s.r.o."
    assert d["agreed_price"] == 168000
    assert d["buyer_name"] == "Moja s.r.o."
    assert d["buyer_ico"] == "12345678"
    assert d["notary_name"] == "JUDr. Novák"
    assert d["draft_text"] == "KÚPNA ZMLUVA — DRAFT ..."
    assert d["status"] == "DRAFT"
    assert d["generated_at"]


def test_blank_optional_fields_stored_as_null(temp_db):
    save_contract_draft("listing-1", "Personal", 98000, "Ján Kováč", "", "", "text")
    [d] = get_contract_drafts("listing-1")
    assert d["buyer_ico"] is None
    assert d["notary_name"] is None


def test_newest_first_and_only_that_listing(temp_db, monkeypatch):
    stamps = iter(["2026-10-01T09:00:00+00:00", "2026-10-02T09:00:00+00:00",
                   "2026-10-03T09:00:00+00:00"])

    class _Clock:
        @staticmethod
        def now(tz=None):
            class _T:
                def isoformat(self):
                    return next(stamps)
            return _T()
    monkeypatch.setattr(database, "datetime", _Clock)

    first = save_contract_draft("listing-1", "Personal", 1, "A", "", "", "v1")
    save_contract_draft("listing-2", "Personal", 1, "B", "", "", "other")
    second = save_contract_draft("listing-1", "Personal", 1, "A", "", "", "v2")

    assert [d["id"] for d in get_contract_drafts("listing-1")] == [second, first]
    assert get_contract_drafts("listing-3") == []

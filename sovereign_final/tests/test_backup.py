"""modules/backup (audit O5): the whole database lived on one Docker volume
with no copy, so `docker compose down -v` deleted the deal pipeline, notes
and contract drafts."""

import json
import os
import sqlite3
from datetime import date

import pytest

from modules import backup
from tests.conftest import make_listing


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "backups"


@pytest.fixture
def db(full_db):
    import database
    database.upsert_listing(make_listing("a1", title="Tracked flat"))
    database.upsert_listing(make_listing("a2", title="LV entered"))
    database.upsert_listing(make_listing("a3", title="Untouched"))
    database.set_deal_stage("a1", "OFFER", "offered 95k")
    database.add_annotation("a1", "quiet street", 8)
    database.set_flat_lv("a2", "4321", "Petržalka")
    database.save_contract_draft("a1", "personal", 95_000, "Ján Kupec", "", "", "text")
    return database


def test_copy_is_a_full_database(db, dirs):
    path, written = backup.backup_database(date(2026, 10, 8))
    assert written and os.path.basename(path) == "sovereign-2026-10-08.db"
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 3
    assert conn.execute("SELECT stage FROM deal_stages").fetchone()[0] == "OFFER"
    conn.close()
    assert [p.name for p in dirs.iterdir()] == ["sovereign-2026-10-08.db"]   # no .part left


def test_a_days_first_copy_is_kept(db, dirs):
    backup.backup_database(date(2026, 10, 8))
    db.set_deal_stage("a1", "PASSED", "")
    _, written = backup.backup_database(date(2026, 10, 8))
    assert not written
    conn = sqlite3.connect(dirs / "sovereign-2026-10-08.db")
    assert conn.execute("SELECT stage FROM deal_stages").fetchone()[0] == "OFFER"
    conn.close()


def test_export_holds_what_you_typed_and_the_listings_it_refers_to(db, dirs):
    path = backup.export_user_data(date(2026, 10, 8))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["deal_stages"][0]["note"] == "offered 95k"
    assert data["annotations"][0]["vibe_score"] == 8
    assert data["contract_drafts"][0]["buyer_name"] == "Ján Kupec"
    assert len(data["deal_stage_history"]) == 1
    listed = {r["id"]: r for r in data["listings"]}
    assert set(listed) == {"a1", "a2"}
    assert listed["a2"]["lv_number"] == "4321"


def test_prune_keeps_the_newest(dirs):
    dirs.mkdir()
    for d in range(1, 6):
        (dirs / f"sovereign-2026-10-0{d}.db").write_text("x")
        (dirs / f"your-data-2026-10-0{d}.json").write_text("{}")
    assert backup.prune(keep=2) == 6
    assert sorted(p.name for p in dirs.iterdir()) == [
        "sovereign-2026-10-04.db", "sovereign-2026-10-05.db",
        "your-data-2026-10-04.json", "your-data-2026-10-05.json"]


def test_restore_puts_the_copy_back(db, dirs):
    path, _ = backup.backup_database(date(2026, 10, 8))
    db.set_deal_stage("a1", "PASSED", "")
    backup.restore_database(path)
    assert db.get_deal_stages()["a1"]["stage"] == "OFFER"


def test_restore_refuses_a_missing_file(db, dirs):
    with pytest.raises(FileNotFoundError):
        backup.restore_database(str(dirs / "nope.db"))

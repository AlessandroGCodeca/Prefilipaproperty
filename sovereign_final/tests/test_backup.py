"""modules/backup (audit O5): the whole database lived on one Docker volume
with no copy, so `docker compose down -v` deleted the deal pipeline, notes
and contract drafts."""

import gzip
import json
import os
import sqlite3
from datetime import date, timedelta

import pytest

from modules import backup
from tests.conftest import make_listing


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "backups"


def _db_file(db) -> str:
    """The file behind the test's database connection."""
    conn = db.get_conn()
    try:
        return conn.execute("PRAGMA database_list").fetchone()[2]
    finally:
        conn.close()


def _open(path):
    """A connection to a compressed backup, through a plain copy beside it."""
    plain = str(path) + ".plain"
    with gzip.open(path, "rb") as src, open(plain, "wb") as dst:
        dst.write(src.read())
    return sqlite3.connect(plain)


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
    assert written and os.path.basename(path) == "sovereign-2026-10-08.db.gz"
    assert [p.name for p in dirs.iterdir()] == ["sovereign-2026-10-08.db.gz"]  # no .part left
    conn = _open(path)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 3
    assert conn.execute("SELECT stage FROM deal_stages").fetchone()[0] == "OFFER"
    conn.close()


def test_the_copy_is_compressed(db, dirs):
    """The point of EF5: the same database in a fraction of the room."""
    conn = db.get_conn()
    conn.executemany("INSERT INTO annotations (id, listing_id, note, vibe_score, created_at) "
                     "VALUES (?, 'a1', ?, 5, '2026-10-08')",
                     [(f"n{i}", f"Byt 3+1 na Obchodnej ulici, tehla, balkón, pivnica {i}")
                      for i in range(3000)])
    conn.commit()
    conn.close()
    path, _ = backup.backup_database(date(2026, 10, 8))
    assert os.path.getsize(path) * 3 < os.path.getsize(_db_file(db))


def test_a_days_first_copy_is_kept(db, dirs):
    backup.backup_database(date(2026, 10, 8))
    db.set_deal_stage("a1", "PASSED", "")
    _, written = backup.backup_database(date(2026, 10, 8))
    assert not written
    conn = _open(dirs / "sovereign-2026-10-08.db.gz")
    assert conn.execute("SELECT stage FROM deal_stages").fetchone()[0] == "OFFER"
    conn.close()


def test_a_days_plain_copy_from_before_compression_counts_too(db, dirs):
    dirs.mkdir()
    (dirs / "sovereign-2026-10-08.db").write_bytes(b"older copy")
    path, written = backup.backup_database(date(2026, 10, 8))
    assert not written and path.endswith("sovereign-2026-10-08.db")


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


def test_seven_days_four_weeks_six_months_are_kept():
    days = [date(2026, 11, 25) - timedelta(days=n) for n in range(400)]
    kept = sorted(backup.keep_days(days, daily=7, weekly=4, monthly=6))
    assert kept == [date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
                    date(2026, 9, 30), date(2026, 10, 31),               # monthly
                    date(2026, 11, 8), date(2026, 11, 15),               # weekly
                    *[date(2026, 11, d) for d in range(19, 26)]]         # daily
    assert backup.keep_days(days, daily=3, weekly=0, monthly=0) == set(days[:3])


def test_prune_keeps_those_days_of_each_kind_old_plain_copies_too(dirs, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_KEEP_DAILY", 2)
    monkeypatch.setattr(backup, "BACKUP_KEEP_WEEKLY", 0)
    monkeypatch.setattr(backup, "BACKUP_KEEP_MONTHLY", 2)
    dirs.mkdir()
    for d in ("2026-09-10", "2026-09-30", "2026-10-03", "2026-10-04", "2026-10-05"):
        (dirs / f"sovereign-{d}.db{'' if d < '2026-10-04' else '.gz'}").write_text("x")
        (dirs / f"your-data-{d}.json").write_text("{}")
    (dirs / "notes.txt").write_text("not a backup")
    assert backup.prune() == 4
    assert sorted(p.name for p in dirs.iterdir()) == [
        "notes.txt",
        "sovereign-2026-09-30.db", "sovereign-2026-10-04.db.gz", "sovereign-2026-10-05.db.gz",
        "your-data-2026-09-30.json", "your-data-2026-10-04.json", "your-data-2026-10-05.json"]


def test_copies_saved_before_a_restore_keep_their_own_count(dirs, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_KEEP", 2)
    dirs.mkdir()
    for n in range(4):
        (dirs / f"{backup.PRE_RESTORE_PREFIX}2026-10-0{n + 1}_120000.db").write_text("x")
    assert backup.prune() == 2
    assert len(list(dirs.iterdir())) == 2


def test_the_privacy_notice_says_how_far_back_the_backups_reach(monkeypatch):
    from dashboard import legal
    monkeypatch.setattr(backup, "BACKUP_KEEP_MONTHLY", 6)
    assert "about 6 months" in legal.privacy_md()
    monkeypatch.setattr(backup, "BACKUP_KEEP_MONTHLY", 0)
    monkeypatch.setattr(backup, "BACKUP_KEEP_WEEKLY", 0)
    monkeypatch.setattr(backup, "BACKUP_KEEP_DAILY", 14)
    assert "up to 14 days old" in legal.privacy_md()


def test_restore_puts_the_copy_back(db, dirs):
    path, _ = backup.backup_database(date(2026, 10, 8))
    db.set_deal_stage("a1", "PASSED", "")
    backup.restore_database(path)
    assert db.get_deal_stages()["a1"]["stage"] == "OFFER"


def test_a_compressed_copy_that_is_cut_short_is_not_restored(db, dirs):
    path, _ = backup.backup_database(date(2026, 10, 8))
    with open(path, "rb") as f:
        head = f.read(200)
    with open(path, "wb") as f:
        f.write(head)
    assert backup.integrity_problem(path)
    with pytest.raises(backup.BackupError):
        backup.restore_database(path)
    assert db.get_deal_stages()["a1"]["stage"] == "OFFER"
    assert not [p for p in os.listdir(backup.DATA_DIR) if p.startswith(".unpacked")]


def test_restore_refuses_a_missing_file(db, dirs):
    with pytest.raises(FileNotFoundError):
        backup.restore_database(str(dirs / "nope.db"))


def test_restore_brings_an_old_backups_schema_up_to_date(db, dirs, tmp_path):
    # The dashboard runs init_db() once per process, so a restored backup that
    # predates a column must get it from the restore itself.
    path, _ = backup.backup_database(date(2026, 10, 8))
    old = _open(path)
    old.execute("ALTER TABLE listings DROP COLUMN lv_number")
    old.commit()
    old.close()
    plain = path + ".plain"          # an older, uncompressed backup
    backup.restore_database(plain)
    conn = db.get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    conn.close()
    assert "lv_number" in cols


# ── A copy off this disk (BACKUP_COPY_DIR) ───────────────────────────────────
def test_the_backups_are_copied_to_the_folder_you_set(db, dirs, tmp_path, monkeypatch):
    dest = tmp_path / "icloud"
    monkeypatch.setenv("BACKUP_COPY_DIR", str(dest))
    summary = backup.run_backup(date(2026, 10, 8))
    assert "2 file(s) copied" in summary
    assert sorted(p.name for p in dest.iterdir()) == ["sovereign-2026-10-08.db.gz",
                                                      "your-data-2026-10-08.json"]
    assert backup.integrity_problem(str(dest / "sovereign-2026-10-08.db.gz")) is None
    # Nothing new, nothing copied again.
    assert backup.copy_off_site() == f"0 file(s) copied to {dest}"


def test_the_copy_keeps_only_the_newest_and_leaves_pre_restore_files_out(db, dirs, tmp_path,
                                                                         monkeypatch):
    dest = tmp_path / "usb"
    monkeypatch.setattr(backup, "BACKUP_KEEP_DAILY", 2)
    monkeypatch.setattr(backup, "BACKUP_KEEP_WEEKLY", 0)
    monkeypatch.setattr(backup, "BACKUP_KEEP_MONTHLY", 0)
    for d in range(1, 5):
        backup.backup_database(date(2026, 10, d))
    (dirs / f"{backup.PRE_RESTORE_PREFIX}x.db").write_bytes(b"x")
    backup.copy_off_site(str(dest))
    assert sorted(p.name for p in dest.iterdir()) == ["sovereign-2026-10-03.db.gz",
                                                      "sovereign-2026-10-04.db.gz"]


def test_no_folder_no_copy_and_a_failure_never_fails_the_run(db, dirs, tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_COPY_DIR", raising=False)
    assert backup.copy_off_site() == ""
    assert "off-site" not in backup.run_backup(date(2026, 10, 8))
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("BACKUP_COPY_DIR", str(blocker / "inside"))
    summary = backup.run_backup(date(2026, 10, 9))
    assert "off-site copy skipped" in summary
    assert (dirs / "sovereign-2026-10-09.db.gz").exists()


# ── Upkeep (EF6) ─────────────────────────────────────────────────────────────
def test_the_first_run_compacts_and_a_month_later_again(db, dirs):
    conn = db.get_conn()
    conn.executemany("INSERT INTO annotations (id, listing_id, note, vibe_score, created_at) "
                     "VALUES (?, 'a1', ?, 5, '2026-10-01')",
                     [(f"v{i}", "x" * 500) for i in range(2000)])
    conn.commit()
    conn.execute("DELETE FROM annotations WHERE created_at = '2026-10-01'")
    conn.commit()
    conn.close()
    before = os.path.getsize(_db_file(db))
    assert "database compacted" in backup.run_backup(date(2026, 10, 1))
    assert os.path.getsize(_db_file(db)) < before
    assert backup.upkeep(date(2026, 10, 20)) == ""                 # not a month yet
    assert "compacted" in backup.upkeep(date(2026, 10, 31))
    assert db.get_deal_stages()["a1"]["stage"] == "OFFER"          # nothing lost


def test_a_busy_database_only_postpones_the_vacuum(db, dirs):
    other = sqlite3.connect(_db_file(db), timeout=0.1)
    other.execute("BEGIN IMMEDIATE")            # the dashboard mid-write
    try:
        import modules.backup as b
        real = db.get_conn

        def quick():
            c = real()
            c.execute("PRAGMA busy_timeout = 100")
            return c
        b.database.get_conn, saved = quick, b.database.get_conn
        try:
            said = backup.upkeep(date(2026, 10, 1))
        finally:
            b.database.get_conn = saved
    finally:
        other.rollback()
        other.close()
    assert "postponed" in said
    assert "compacted" in backup.upkeep(date(2026, 10, 2))       # the next run does it


def test_an_upkeep_failure_never_fails_the_backup(db, dirs, monkeypatch):
    def broken(day=None):
        raise sqlite3.DatabaseError("disk I/O error")
    monkeypatch.setattr(backup, "upkeep", broken)
    summary = backup.run_backup(date(2026, 10, 8))
    assert "written and checked" in summary and "upkeep skipped" in summary

"""
modules/backup.py — a daily copy of the database, and a plain export of what
you typed into it.

Everything lives in one SQLite file, in Docker on a named volume, so
`docker compose down -v` (or a broken volume) took the deal pipeline, notes
and contract drafts with it. Before each scheduled run this writes

  backups/sovereign-YYYY-MM-DD.db     a full, consistent copy (SQLite's online
                                      backup — safe while the dashboard writes)
  backups/your-data-YYYY-MM-DD.json   deal stages and their history, notes and
                                      vibe scores, contract drafts, and the flat
                                      LV numbers you entered — readable without
                                      the app

and keeps the newest BACKUP_KEEP of each. In Docker, backups/ is a folder on
this computer (docker-compose.yml), outside the volume.

  python -m modules.backup                       back up now
  python -m modules.backup restore <file.db>     put a copy back (the live
                                                 database is saved first as
                                                 backups/pre-restore-<time>.db)
  python -m modules.backup check <file.db>       is a copy a sound database?

Every new copy is opened and checked (SQLite's quick_check) before it counts.

Off the disk: set BACKUP_COPY_DIR in .env to a synced folder (on a Mac,
~/Library/Mobile Documents/com~apple~CloudDocs/Sovereign-backups is iCloud
Drive) and each run copies the new backups there too. Keep it private: the
backups hold title-deed texts with owners' names.

In Docker: `docker compose stop scheduler`, then
`docker compose exec dashboard python -m modules.backup restore backups/<file>.db`,
then `docker compose start scheduler`. Restoring goes through SQLite, not a
file copy, so a write-ahead log left beside the live file can't corrupt it.
"""

import glob
import json
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
from config import BACKUP_DIR, BACKUP_KEEP, DATA_DIR

DB_PREFIX, DATA_PREFIX = "sovereign-", "your-data-"
# The live database as it was just before a restore wrote over it.
PRE_RESTORE_PREFIX = "pre-restore-"


class BackupError(Exception):
    pass


def _private(path: str) -> None:
    """Readable and writable by this computer's user only: a backup holds the
    deeds' texts with owners' names, deal files and your notes. Ignored where
    the system has no such permissions (Windows) or refuses."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def integrity_problem(path: str) -> str | None:
    """None when SQLite reads the file at `path` as a sound database
    (PRAGMA quick_check); else what is wrong with it."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()]
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return f"{type(e).__name__}: {e}"
    return None if rows == ["ok"] else "; ".join(rows[:3])

# What a person typed or decided — the part of the database no scrape can
# rebuild.
_USER_TABLES = {
    "deal_stages":        "SELECT * FROM deal_stages ORDER BY listing_id",
    "deal_stage_history": "SELECT * FROM deal_stage_history ORDER BY changed_at",
    "annotations":        "SELECT * FROM annotations ORDER BY created_at",
    "contract_drafts":    "SELECT * FROM contract_drafts ORDER BY generated_at",
    # The due-diligence checklist, and which documents a deal has (their
    # contents are in the .db copy, not in this readable export).
    "deal_checklist":     "SELECT * FROM deal_checklist ORDER BY listing_id, item",
    "building_facts":     "SELECT * FROM building_facts ORDER BY listing_id",
    "owned_flats":        "SELECT * FROM owned_flats ORDER BY id",
    "owned_ledger":       "SELECT * FROM owned_ledger ORDER BY flat_id, month",
    "sold_prices":        "SELECT * FROM sold_prices ORDER BY id",
    "deal_files":         "SELECT id, listing_id, kind, name, mime, size, uploaded_at "
                          "FROM deal_files ORDER BY uploaded_at",
    "alert_rules":        "SELECT * FROM alert_rules ORDER BY position",
}


def backup_database(day: date | None = None) -> tuple[str, bool]:
    """Copy the database to backups/sovereign-<day>.db. Returns (path,
    written). A day's first copy is kept: it is the state before that day's
    first run, and a retry later that day must not overwrite it."""
    day = day or date.today()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    target = os.path.join(BACKUP_DIR, f"{DB_PREFIX}{day.isoformat()}.db")
    if os.path.exists(target):
        return target, False
    # Build the copy beside the live database, then move the finished file
    # across: a half-written backup never sits in backups/ under its real
    # name, and SQLite only ever writes to the volume it already works on.
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = os.path.join(DATA_DIR, f".backup-{day.isoformat()}.tmp")
    if os.path.exists(tmp):             # left by a run that died mid-copy
        os.remove(tmp)
    src = database.get_conn()
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    # Opened and checked before it counts as a backup: a copy that can't be
    # read would only be found out on the day it is needed.
    problem = integrity_problem(tmp)
    if problem:
        os.remove(tmp)
        raise BackupError(f"the copy of the database failed SQLite's check ({problem}) — "
                          f"no backup was written; the live database may be damaged")
    # An older backup may predate columns the code now expects. The dashboard
    # only runs init_db() once per process, so bring the schema up to date here.
    database.init_db()
    part = target + ".part"
    shutil.copyfile(tmp, part)
    os.replace(part, target)
    _private(target)
    os.remove(tmp)
    return target, True


def export_user_data(day: date | None = None) -> str:
    """Write deal stages, notes, contract drafts and entered LV numbers to
    backups/your-data-<day>.json (overwritten by later runs that day)."""
    day = day or date.today()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    conn = database.get_conn()
    try:
        out = {"exported_at": datetime.now(timezone.utc).isoformat()}
        for name, sql in _USER_TABLES.items():
            out[name] = ([dict(r) for r in conn.execute(sql).fetchall()]
                         if database._has_table(conn, name) else [])
        # Enough of each listing those rows refer to (and of every flat whose
        # own LV you entered) to find it again without the database.
        ids = {r["listing_id"] for name in _USER_TABLES for r in out[name]}
        rows = conn.execute(
            "SELECT id, url, title, district, price_eur, size_m2, lv_number, "
            "cadastral_area, lv_status, is_active FROM listings "
            "WHERE COALESCE(lv_number, '') != '' OR id IN (SELECT value FROM json_each(?)) "
            "ORDER BY id", (json.dumps(sorted(ids)),)).fetchall()
        out["listings"] = [dict(r) for r in rows]
    finally:
        conn.close()
    path = os.path.join(BACKUP_DIR, f"{DATA_PREFIX}{day.isoformat()}.json")
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)
    _private(path)
    return path


def prune(keep: int = BACKUP_KEEP) -> int:
    """Delete all but the newest `keep` backups of each kind. Returns how many
    went. Names sort by date, so the newest sort last."""
    gone = 0
    for pattern in (f"{DB_PREFIX}*.db", f"{DATA_PREFIX}*.json", f"{PRE_RESTORE_PREFIX}*.db"):
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, pattern)))
        for old in files[:-keep] if keep > 0 else []:
            os.remove(old)
            gone += 1
    return gone


def copy_off_site(dest: str | None = None) -> str:
    """Copy backups/ into `dest` (BACKUP_COPY_DIR: an iCloud Drive or other
    synced folder, or a USB disk), so a disk failure or theft doesn't take the
    only copies with the database. Only the newest BACKUP_KEEP of each kind
    are kept there too. Returns a summary; "" when no folder is set. A failure
    (the disk isn't plugged in, iCloud refuses) raises BackupError and never
    touches the local backups."""
    dest = os.path.expanduser((dest or os.getenv("BACKUP_COPY_DIR") or "").strip())
    if not dest:
        return ""
    try:
        os.makedirs(dest, exist_ok=True)
        copied = 0
        for path in sorted(glob.glob(os.path.join(BACKUP_DIR, "*"))):
            name = os.path.basename(path)
            if not os.path.isfile(path) or name.endswith(".part") or name.startswith(
                    PRE_RESTORE_PREFIX):
                continue
            target = os.path.join(dest, name)
            if (not os.path.exists(target)
                    or os.path.getsize(target) != os.path.getsize(path)):
                shutil.copy2(path, target + ".part")
                os.replace(target + ".part", target)
                _private(target)
                copied += 1
        for prefix in (DB_PREFIX, DATA_PREFIX):
            old = sorted(glob.glob(os.path.join(dest, f"{prefix}*")))[:-BACKUP_KEEP]
            for path in old:
                os.remove(path)
    except OSError as e:
        raise BackupError(f"the copy to {dest} failed: {e}") from e
    return f"{copied} file(s) copied to {dest}"


def run_backup(day: date | None = None) -> str:
    """The scheduler's backup step: copy, export, prune, and — with
    BACKUP_COPY_DIR set — a copy off this disk. Returns a summary."""
    path, written = backup_database(day)
    export_user_data(day)
    pruned = prune()
    name = os.path.basename(path)
    summary = (f"{name} {'written and checked' if written else 'already there (kept)'}, "
               f"data exported"
               + (f", {pruned} old backup(s) removed" if pruned else ""))
    # A failed off-site copy never fails the run: the local backup stands.
    try:
        off = copy_off_site()
        if off:
            summary += f", {off}"
    except BackupError as e:
        summary += f", ⚠ off-site copy skipped ({e})"
    return summary


def save_live_copy() -> str | None:
    """Copy the live database to backups/pre-restore-<time>.db (SQLite's
    online backup) and return its path; None when it holds nothing yet.

    It asks the database the app uses (database.get_conn) rather than looking
    for config.SQLITE_PATH on disk: that is the one the restore overwrites."""
    src = database.get_conn()
    try:
        if not src.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        target = os.path.join(BACKUP_DIR, f"{PRE_RESTORE_PREFIX}{stamp}.db")
        dst = sqlite3.connect(target + ".part")
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(target + ".part", target)
    _private(target)
    return target


def restore_database(path: str) -> str | None:
    """Replace the live database's contents with the backup at `path`. Stop
    the scheduler first: a run in progress would keep writing over it.

    The backup is checked before anything is touched, and the live database
    is first saved as backups/pre-restore-<time>.db, so restoring the wrong
    file can be undone by restoring that one. Returns its path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    problem = integrity_problem(path)
    if problem:
        raise BackupError(f"{path} is not a sound database ({problem}) — nothing was restored")
    saved = save_live_copy()
    src = sqlite3.connect(path)
    try:
        dst = database.get_conn()
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    # An older backup may predate columns the code now expects. The dashboard
    # only runs init_db() once per process, so bring the schema up to date here.
    database.init_db()
    return saved


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["restore"] and len(args) == 2:
        saved = restore_database(args[1])
        print(f"Restored {args[1]} into {database.SQLITE_PATH}."
              + (f"\nThe database as it was before is saved as {saved} — restore that "
                 f"file to undo this." if saved else ""))
    elif args[:1] == ["check"] and len(args) == 2:
        problem = integrity_problem(args[1])
        print("OK — a sound database." if not problem else f"NOT SOUND: {problem}")
        sys.exit(1 if problem else 0)
    elif not args:
        print(run_backup())
    else:
        sys.exit("usage: python -m modules.backup [restore <backup.db> | check <backup.db>]")

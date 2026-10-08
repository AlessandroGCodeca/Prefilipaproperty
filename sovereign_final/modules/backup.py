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
  python -m modules.backup restore <file.db>     put a copy back

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

# What a person typed or decided — the part of the database no scrape can
# rebuild.
_USER_TABLES = {
    "deal_stages":        "SELECT * FROM deal_stages ORDER BY listing_id",
    "deal_stage_history": "SELECT * FROM deal_stage_history ORDER BY changed_at",
    "annotations":        "SELECT * FROM annotations ORDER BY created_at",
    "contract_drafts":    "SELECT * FROM contract_drafts ORDER BY generated_at",
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
    part = target + ".part"
    shutil.copyfile(tmp, part)
    os.replace(part, target)
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
    return path


def prune(keep: int = BACKUP_KEEP) -> int:
    """Delete all but the newest `keep` backups of each kind. Returns how many
    went. Names sort by date, so the newest sort last."""
    gone = 0
    for pattern in (f"{DB_PREFIX}*.db", f"{DATA_PREFIX}*.json"):
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, pattern)))
        for old in files[:-keep] if keep > 0 else []:
            os.remove(old)
            gone += 1
    return gone


def run_backup(day: date | None = None) -> str:
    """The scheduler's backup step: copy, export, prune. Returns a summary."""
    path, written = backup_database(day)
    export_user_data(day)
    pruned = prune()
    name = os.path.basename(path)
    return (f"{name} {'written' if written else 'already there (kept)'}, data exported"
            + (f", {pruned} old backup(s) removed" if pruned else ""))


def restore_database(path: str) -> None:
    """Replace the live database's contents with the backup at `path`. Stop
    the scheduler first: a run in progress would keep writing over it."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    src = sqlite3.connect(path)
    try:
        dst = database.get_conn()
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["restore"] and len(args) == 2:
        restore_database(args[1])
        print(f"Restored {args[1]} into {database.SQLITE_PATH}.")
    elif not args:
        print(run_backup())
    else:
        sys.exit("usage: python -m modules.backup [restore <backup.db>]")

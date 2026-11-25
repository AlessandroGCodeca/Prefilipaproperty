"""
modules/backup.py — a daily copy of the database, and a plain export of what
you typed into it.

Everything lives in one SQLite file, in Docker on a named volume, so
`docker compose down -v` (or a broken volume) took the deal pipeline, notes
and contract drafts with it. Before each scheduled run this writes

  backups/sovereign-YYYY-MM-DD.db.gz  a full, consistent copy (SQLite's online
                                      backup — safe while the dashboard writes),
                                      gzip-compressed: a database file shrinks
                                      several times
  backups/your-data-YYYY-MM-DD.json   deal stages and their history, notes and
                                      vibe scores, contract drafts, and the flat
                                      LV numbers you entered — readable without
                                      the app

and keeps, of each kind, the newest BACKUP_KEEP_DAILY (7) days, the newest
copy of each of the last BACKUP_KEEP_WEEKLY (4) weeks and of each of the last
BACKUP_KEEP_MONTHLY (6) months: half a year back in less room than two weeks
of plain daily copies took. Older plain .db backups are still read, restored
and pruned the same way. In Docker, backups/ is a folder on this computer
(docker-compose.yml), outside the volume.

  python -m modules.backup                          back up now
  python -m modules.backup restore <file.db[.gz]>   put a copy back (the live
                                                    database is saved first as
                                                    backups/pre-restore-<time>.db)
  python -m modules.backup check <file.db[.gz]>     is a copy a sound database?

Every new copy is opened and checked (SQLite's quick_check) before it counts.
After it, the database gets its upkeep (upkeep()): fresh query statistics on
every run, and once a month a VACUUM, which gives back the room deleted rows
left (deed texts past LV_TEXT_RETENTION_DAYS, old price history).

Off the disk: set BACKUP_COPY_DIR in .env to a synced folder (on a Mac,
~/Library/Mobile Documents/com~apple~CloudDocs/Sovereign-backups is iCloud
Drive) and each run copies the new backups there too. Keep it private: the
backups hold title-deed texts with owners' names.

In Docker: `docker compose stop scheduler`, then
`docker compose exec dashboard python -m modules.backup restore backups/<file>.db`,
then `docker compose start scheduler`. Restoring goes through SQLite, not a
file copy, so a write-ahead log left beside the live file can't corrupt it.
"""

import contextlib
import glob
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
from config import (BACKUP_DIR, BACKUP_KEEP, BACKUP_KEEP_DAILY, BACKUP_KEEP_MONTHLY,
                    BACKUP_KEEP_WEEKLY, DATA_DIR)

log = logging.getLogger("sovereign")

DB_PREFIX, DATA_PREFIX = "sovereign-", "your-data-"
DB_SUFFIX = ".db.gz"
# A dated backup's name: its kind, its day, and what it is (".db" is the
# plain copy older versions wrote).
_DATED = re.compile(r"^(sovereign-|your-data-)(\d{4}-\d{2}-\d{2})\.(db\.gz|db|json)$")
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


@contextlib.contextmanager
def _plain(path: str):
    """The backup at `path` as a plain database file: itself, or, for a .gz,
    a decompressed copy beside the live database that is deleted afterwards.
    Raises BackupError when a .gz can't be decompressed."""
    if not path.endswith(".gz"):
        yield path
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = os.path.join(DATA_DIR, f".unpacked-{os.getpid()}-{os.path.basename(path)[:-3]}")
    try:
        try:
            with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        except (OSError, EOFError) as e:      # not gzip, or cut short
            raise BackupError(f"{type(e).__name__}: {e}") from None
        _private(tmp)
        yield tmp
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def integrity_problem(path: str) -> str | None:
    """None when SQLite reads the file at `path` (a .db, or a .db.gz) as a
    sound database (PRAGMA quick_check); else what is wrong with it."""
    try:
        with _plain(path) as plain:
            conn = sqlite3.connect(f"file:{plain}?mode=ro", uri=True)
            try:
                rows = [r[0] for r in conn.execute("PRAGMA quick_check").fetchall()]
                conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            finally:
                conn.close()
    except BackupError as e:
        return str(e)
    except sqlite3.DatabaseError as e:
        return f"{type(e).__name__}: {e}"
    return None if rows == ["ok"] else "; ".join(rows[:3])


def keep_days(days, daily: int = None, weekly: int = None, monthly: int = None) -> set:
    """Of the days that have a backup, the ones to keep: the newest `daily`
    days, and the newest day of each of the newest `weekly` ISO weeks and of
    each of the newest `monthly` months."""
    daily = BACKUP_KEEP_DAILY if daily is None else daily
    weekly = BACKUP_KEEP_WEEKLY if weekly is None else weekly
    monthly = BACKUP_KEEP_MONTHLY if monthly is None else monthly
    newest_first = sorted(set(days), reverse=True)
    keep = set(newest_first[:max(daily, 0)])
    for count, bucket in ((weekly, lambda d: d.isocalendar()[:2]),
                          (monthly, lambda d: (d.year, d.month))):
        seen = set()
        for d in newest_first:
            b = bucket(d)
            if b in seen:
                continue
            if len(seen) >= count:
                break
            seen.add(b)
            keep.add(d)
    return keep


def _prune_dated(folder: str) -> int:
    """Delete the dated backups in `folder` that keep_days() lets go, each kind
    on its own. Returns how many went."""
    kinds: dict[str, dict[date, list[str]]] = {}
    for path in glob.glob(os.path.join(folder, "*")):
        m = _DATED.match(os.path.basename(path))
        if m and os.path.isfile(path):
            day = date.fromisoformat(m.group(2))
            kinds.setdefault(m.group(1), {}).setdefault(day, []).append(path)
    gone = 0
    for by_day in kinds.values():
        keep = keep_days(by_day)
        for day, paths in by_day.items():
            if day not in keep:
                for path in paths:
                    os.remove(path)
                    gone += 1
    return gone


def retention_text() -> str:
    """How far back the backups reach, for the privacy notice and the erase
    button: what an erased owner's data may still sit in."""
    parts = [f"the newest {BACKUP_KEEP_DAILY} days"]
    if BACKUP_KEEP_WEEKLY > 0:
        parts.append(f"one a week for {BACKUP_KEEP_WEEKLY} weeks")
    if BACKUP_KEEP_MONTHLY > 0:
        parts.append(f"one a month for {BACKUP_KEEP_MONTHLY} months")
    reach = (f"about {BACKUP_KEEP_MONTHLY} months" if BACKUP_KEEP_MONTHLY > 0 else
             f"about {BACKUP_KEEP_WEEKLY} weeks" if BACKUP_KEEP_WEEKLY > 0 else
             f"{BACKUP_KEEP_DAILY} days")
    return (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) \
        + f", so the oldest is up to {reach} old"

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
    "starred":            "SELECT * FROM starred ORDER BY starred_at",
    "viewing":            "SELECT * FROM viewing ORDER BY listing_id",          # UX4
    "saved_searches":     "SELECT * FROM saved_searches ORDER BY name",         # UX1
}


def backup_database(day: date | None = None) -> tuple[str, bool]:
    """Copy the database to backups/sovereign-<day>.db.gz. Returns (path,
    written). A day's first copy is kept: it is the state before that day's
    first run, and a retry later that day must not overwrite it (a plain .db
    of that day, from before the backups were compressed, counts too)."""
    day = day or date.today()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    target = os.path.join(BACKUP_DIR, f"{DB_PREFIX}{day.isoformat()}{DB_SUFFIX}")
    for existing in (target, target[:-3]):
        if os.path.exists(existing):
            return existing, False
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
    with open(tmp, "rb") as src, gzip.open(part, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
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
        # Not every table is about one listing (alert rules, saved searches,
        # your own flats): a row without a listing_id names none.
        ids = {r.get("listing_id") for name in _USER_TABLES for r in out[name]} - {None}
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


def prune() -> int:
    """Delete the database copies and data exports keep_days() lets go, and
    all but the newest BACKUP_KEEP copies saved before a restore. Returns how
    many went."""
    gone = _prune_dated(BACKUP_DIR)
    saved = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{PRE_RESTORE_PREFIX}*.db")))
    for old in saved[:-BACKUP_KEEP] if BACKUP_KEEP > 0 else []:
        os.remove(old)
        gone += 1
    return gone


def copy_off_site(dest: str | None = None) -> str:
    """Copy backups/ into `dest` (BACKUP_COPY_DIR: an iCloud Drive or other
    synced folder, or a USB disk), so a disk failure or theft doesn't take the
    only copies with the database. The same days are kept there as here
    (keep_days). Returns a summary; "" when no folder is set. A failure
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
        _prune_dated(dest)
    except OSError as e:
        raise BackupError(f"the copy to {dest} failed: {e}") from e
    return f"{copied} file(s) copied to {dest}"


# ── Upkeep (EF6) ─────────────────────────────────────────────────────────────
# A VACUUM rewrites the whole file to give back the room deleted rows left;
# once a month is enough for a database that mostly grows.
VACUUM_EVERY_DAYS = 30


def _db_mb(path: str) -> float:
    """The database's size on disk, its write-ahead log included."""
    total = 0
    for p in (path, path + "-wal"):
        with contextlib.suppress(OSError):
            total += os.path.getsize(p)
    return total / 1e6


def upkeep(day: date | None = None) -> str:
    """Every run: PRAGMA optimize, so SQLite's query planner works from fresh
    statistics. When the last VACUUM is VACUUM_EVERY_DAYS old (or there never
    was one): VACUUM, then empty the write-ahead log it filled. Run after the
    day's backup. A busy database only postpones the VACUUM to the next run.
    The day of the last VACUUM is kept in the database itself (table upkeep).
    Returns a summary for the run's log ("" when there is nothing to say)."""
    day = day or date.today()
    conn = database.get_conn()
    conn.isolation_level = None              # VACUUM can't run in a transaction
    try:
        path = conn.execute("PRAGMA database_list").fetchone()[2] or ""
        # Every step below can meet the dashboard mid-write ("database is
        # locked"): the whole upkeep then waits for the next run.
        conn.execute("CREATE TABLE IF NOT EXISTS upkeep (name TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM upkeep WHERE name = 'last_vacuum'").fetchone()
        try:
            last = date.fromisoformat(row[0]) if row else None
        except (TypeError, ValueError):
            last = None
        conn.execute("PRAGMA optimize")
        if last and (day - last).days < VACUUM_EVERY_DAYS:
            return ""
        before = _db_mb(path)
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("INSERT OR REPLACE INTO upkeep (name, value) VALUES ('last_vacuum', ?)",
                     (day.isoformat(),))
    except sqlite3.OperationalError as e:
        log.warning(f"Upkeep: postponed ({e})")
        return "⚠ database upkeep postponed to the next run (it was busy)"
    finally:
        conn.close()
    return f"database compacted ({before:.1f} → {_db_mb(path):.1f} MB)"


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
    # After the copy, never before it: a VACUUM rewrites the whole file. Its
    # failure never fails the run: the backup above stands.
    try:
        done = upkeep(day)
    except sqlite3.Error as e:
        done = f"⚠ database upkeep skipped ({type(e).__name__}: {e})"
    if done:
        summary += f", {done}"
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
    """Replace the live database's contents with the backup at `path` (a .db
    or a .db.gz). Stop the scheduler first: a run in progress would keep
    writing over it.

    The backup is checked before anything is touched, and the live database
    is first saved as backups/pre-restore-<time>.db, so restoring the wrong
    file can be undone by restoring that one. Returns its path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    problem = integrity_problem(path)
    if problem:
        raise BackupError(f"{path} is not a sound database ({problem}) — nothing was restored")
    saved = save_live_copy()
    with _plain(path) as plain:
        src = sqlite3.connect(plain)
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
        sys.exit("usage: python -m modules.backup [restore <backup.db[.gz]> | "
                 "check <backup.db[.gz]>]")

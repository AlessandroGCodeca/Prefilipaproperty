"""
database/portal_runs.py — how many listings each portal returned on each run.

The stale check retires a listing its portal has not shown for 21 days. A
portal that is blocked, or whose page layout changed so the parser finds
nothing, shows none of its listings: without a record of what each portal
returned, its listings were retired with the rest and nothing said the
portal had gone quiet. Each scrape — the pipeline's and a sidebar button's —
records here what its portal returned. The stale check retires only the
listings of portals that returned some this run, and the dashboard flags a
portal whose last QUIET_RUNS runs returned none or failed.

What a portal "returned" is counted from the listings themselves: those of
its source seen (upserted or touched) since the scrape began. A scraper's
own return value counts only the listings it upserted on some portals — a
run where every listing was already fresh returns 0 and still saw them all.
"""

from datetime import datetime, timedelta, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import _ensure_market_columns

# Runs in a row with no listings (or an error) before the dashboard flags a
# portal: one bad run is often a portal's passing hiccup.
QUIET_RUNS = 2
# How long the run log is kept.
KEEP_DAYS = 90

_DDL = """
    CREATE TABLE IF NOT EXISTS portal_runs (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        market    TEXT NOT NULL,
        source    TEXT NOT NULL,
        run_at    TEXT NOT NULL,
        listings  INTEGER NOT NULL DEFAULT 0,
        error     TEXT NOT NULL DEFAULT ''
    )"""


def _ensure_portal_runs(conn) -> None:
    """The table on a database that hasn't been through init_db since it was
    added (a scraper subprocess, an old file). Idempotent and cheap."""
    conn.execute(_DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_portal_runs_source "
                 "ON portal_runs(market, source, run_at)")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_seen_since(source: str, market: str, since: str) -> int:
    """Listings of `source` (in `market`) seen at or after `since` (UTC ISO)."""
    import markets
    conn = _db.get_conn()
    try:
        _ensure_market_columns(conn)
        return conn.execute(
            "SELECT COUNT(*) FROM listings WHERE source = ? AND market = ? "
            "AND last_seen_at >= ?", (source, markets.normalize(market), since)).fetchone()[0]
    finally:
        conn.close()


def record_portal_run(market: str, source: str, started: str, returned: int | None = 0,
                      error: str = "") -> int:
    """Record one scrape of `source`, begun at `started`: the listings it
    returned are the larger of what the scraper said (`returned`) and the
    listings of its source seen since `started`. Returns that count."""
    import markets
    market = markets.normalize(market)
    listings = max(int(returned or 0), count_seen_since(source, market, started))
    when = now_iso()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_portal_runs(conn)
        conn.execute("INSERT INTO portal_runs (market, source, run_at, listings, error) "
                     "VALUES (?,?,?,?,?)", (market, source, when, listings, (error or "")[:300]))
        conn.execute("DELETE FROM portal_runs WHERE run_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
    return listings


def portal_runs(market: str | None = None, last: int = QUIET_RUNS) -> dict[tuple, list[dict]]:
    """{(market, source): its `last` runs, newest first} — each run
    {"run_at", "listings", "error"}."""
    conn = _db.get_conn()
    try:
        _ensure_portal_runs(conn)
        where, params = ("WHERE market = ?", (market,)) if market else ("", ())
        rows = conn.execute(
            f"SELECT market, source, run_at, listings, error FROM portal_runs {where} "
            "ORDER BY run_at DESC, id DESC", params).fetchall()
    finally:
        conn.close()
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        runs = out.setdefault((r["market"], r["source"]), [])
        if len(runs) < last:
            runs.append({"run_at": r["run_at"], "listings": r["listings"], "error": r["error"]})
    return out


def _bad(run: dict) -> bool:
    return not run["listings"] or bool(run["error"])


def quiet_portals(market: str | None = None, runs: int = QUIET_RUNS) -> list[dict]:
    """The portals whose last `runs` runs each returned no listings or
    failed: [{"market", "source", "runs": newest first, "last_good_at"}].
    A portal with fewer runs on record is not flagged yet."""
    history = portal_runs(market, last=runs)
    quiet = [{"market": m, "source": s, "runs": rs}
             for (m, s), rs in sorted(history.items())
             if len(rs) >= runs and all(_bad(r) for r in rs)]
    if quiet:
        conn = _db.get_conn()
        try:
            for q in quiet:
                row = conn.execute(
                    "SELECT MAX(run_at) FROM portal_runs WHERE market = ? AND source = ? "
                    "AND listings > 0 AND error = ''", (q["market"], q["source"])).fetchone()
                q["last_good_at"] = row[0] if row else None
        finally:
            conn.close()
    return quiet


def portal_health(days: int = 7, now: datetime | None = None) -> dict[tuple, dict]:
    """Each portal's record over the last `days` days, for the dashboard's
    health strip: {(market, source): {"daily": the most listings a run
    returned on each day, oldest first (None: no run that day), "last": its
    latest run {"run_at", "listings", "error"}, "last_good_at": its latest
    run that returned listings without an error, or None}}. Days are UTC."""
    now = now or datetime.now(timezone.utc)
    first_day = (now - timedelta(days=days - 1)).date()
    conn = _db.get_conn()
    try:
        _ensure_portal_runs(conn)
        rows = conn.execute(
            "SELECT market, source, run_at, listings, error FROM portal_runs "
            "ORDER BY run_at, id").fetchall()
    finally:
        conn.close()
    out: dict[tuple, dict] = {}
    for r in rows:
        h = out.setdefault((r["market"], r["source"]),
                           {"daily": [None] * days, "last": None, "last_good_at": None})
        run = {"run_at": r["run_at"], "listings": r["listings"], "error": r["error"]}
        h["last"] = run                                   # rows come oldest first
        if not _bad(run):
            h["last_good_at"] = r["run_at"]
        try:
            i = (datetime.fromisoformat(r["run_at"]).date() - first_day).days
        except ValueError:
            continue
        if 0 <= i < days:
            h["daily"][i] = max(h["daily"][i] or 0, 0 if _bad(run) else r["listings"])
    return out

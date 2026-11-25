"""
database/starred.py — the flats you starred (D10): "look at this again",
lighter than a deal stage. The TODAY view lists them first.
"""

from datetime import datetime, timezone

import database as _db


def _ensure(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS starred ("
                 "listing_id TEXT PRIMARY KEY, starred_at TEXT NOT NULL)")


def set_starred(listing_id: str, on: bool) -> None:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        if on:
            conn.execute("INSERT OR IGNORE INTO starred (listing_id, starred_at) VALUES (?, ?)",
                         (listing_id, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM starred WHERE listing_id = ?", (listing_id,))
        conn.commit()
    finally:
        conn.close()


def get_starred() -> set[str]:
    """The ids of the starred flats."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        return {r[0] for r in conn.execute("SELECT listing_id FROM starred")}
    finally:
        conn.close()


# Deal stages after which a flat is no longer followed.
DONE_STAGES = ("CLOSED", "PASSED")


def get_followed() -> list[dict]:
    """The flats you follow, active or not: the starred ones and the ones in
    a deal stage that isn't CLOSED or PASSED. With "stage" (or None) and
    "starred" (0/1)."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        staged = _db._has_table(conn, "deal_stages")
        stage_col = "d.stage" if staged else "NULL"
        join = "LEFT JOIN deal_stages d ON d.listing_id = l.id" if staged else ""
        open_stage = (f"OR (d.stage IS NOT NULL AND d.stage NOT IN "
                      f"({','.join('?' * len(DONE_STAGES))}))" if staged else "")
        rows = conn.execute(f"""
            SELECT l.id, l.title, l.district, l.url, l.price_eur, l.scraped_at, l.last_seen_at,
                   l.is_active, COALESCE(l.market, 'sk') AS market, l.currency,
                   {stage_col} AS stage, (s.listing_id IS NOT NULL) AS starred
            FROM listings l
            LEFT JOIN starred s ON s.listing_id = l.id
            {join}
            WHERE s.listing_id IS NOT NULL {open_stage}""",
            DONE_STAGES if staged else ()).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

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

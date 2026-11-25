"""
database/viewing.py — what you saw at a viewing (UX4): the condition you
found the flat in, and the problems ticked on the viewing checklist, each
with a note. The condition seen replaces the ad's in the renovation estimate
(dashboard/building_view.py). Photos taken there are deal files (kind
"Photo", database/deal_docs.py); your impression is a vibe note.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import database as _db

CONDITIONS = ("new", "renovated", "good", "original", "poor")


def _ensure(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS viewing (listing_id TEXT PRIMARY KEY, "
                 "condition TEXT, problems TEXT NOT NULL DEFAULT '{}', updated_at TEXT)")


def get_viewing(listing_id: str) -> dict:
    """{"condition": str | None, "problems": {item: note}, "updated_at": str | None}."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        row = conn.execute("SELECT condition, problems, updated_at FROM viewing "
                           "WHERE listing_id = ?", (listing_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {"condition": None, "problems": {}, "updated_at": None}
    try:
        problems = json.loads(row["problems"] or "{}")
    except ValueError:
        problems = {}
    return {"condition": row["condition"] if row["condition"] in CONDITIONS else None,
            "problems": problems if isinstance(problems, dict) else {},
            "updated_at": row["updated_at"]}


def set_viewing(listing_id: str, condition: str | None, problems: dict) -> None:
    """Store what you saw. An unknown condition is kept as none; notes are
    cut to 300 characters."""
    clean = {str(k)[:40]: str(v or "")[:300] for k, v in (problems or {}).items()}
    conn = _db.get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO viewing (listing_id, condition, problems, "
                     "updated_at) VALUES (?, ?, ?, ?)",
                     (listing_id, condition if condition in CONDITIONS else None,
                      json.dumps(clean, ensure_ascii=False),
                      datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()

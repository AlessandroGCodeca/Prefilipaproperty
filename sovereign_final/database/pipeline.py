"""
database/pipeline.py — The pipeline lock (modules/pipeline_state): one pipeline run at a time
across the dashboard and the scheduler.
"""

from datetime import datetime, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import _has_table


# ── Pipeline lock (modules/pipeline_state) ────────────────────────────────────
def try_lock_pipeline(holder: str, token: str, stale_after_s: float) -> dict | None:
    """Take the pipeline lock as `holder` (shown to the user) under `token`
    (unique to this attempt). Returns None when taken, else the row of whoever
    holds it. A row whose heartbeat is older than stale_after_s is taken over:
    the process that held it is gone."""
    now = datetime.now(timezone.utc)
    conn = _db.get_conn()
    try:
        # IMMEDIATE takes the write lock up front, so two processes can't
        # both read "free" and both insert.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT holder, token, acquired_at, heartbeat_at FROM pipeline_lock WHERE id=1"
        ).fetchone()
        if row:
            try:
                age = (now - datetime.fromisoformat(row["heartbeat_at"])).total_seconds()
            except (TypeError, ValueError):
                age = stale_after_s
            if age < stale_after_s:
                conn.rollback()
                return dict(row)
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_lock (id, holder, token, acquired_at, heartbeat_at) "
            "VALUES (1, ?, ?, ?, ?)", (holder, token, now.isoformat(), now.isoformat()))
        conn.commit()
        return None
    finally:
        conn.close()


def heartbeat_pipeline_lock(token: str) -> bool:
    """Refresh the lock's heartbeat. False when this token no longer holds it."""
    conn = _db.get_conn()
    try:
        n = conn.execute("UPDATE pipeline_lock SET heartbeat_at=? WHERE token=?",
                         (datetime.now(timezone.utc).isoformat(), token)).rowcount
        conn.commit()
    finally:
        conn.close()
    return n > 0


def unlock_pipeline(token: str) -> None:
    conn = _db.get_conn()
    try:
        conn.execute("DELETE FROM pipeline_lock WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


def get_pipeline_lock() -> dict | None:
    """The lock row (holder, acquired_at, heartbeat_at), or None when free."""
    conn = _db.get_conn()
    try:
        if not _has_table(conn, "pipeline_lock"):
            return None
        row = conn.execute(
            "SELECT holder, acquired_at, heartbeat_at FROM pipeline_lock WHERE id=1"
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None

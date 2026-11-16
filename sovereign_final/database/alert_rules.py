"""
database/alert_rules.py — the saved searches a Telegram alert is sent for
(modules/alerts): each a name and what a listing must be to match it.

No row at all means the built-in rule from .env (ALERT_CLASSES, ALERT_GRADES,
ALERT_MIN_SURPLUS); the first rule saved from the dashboard's ALERTS tab
replaces it.
"""

import uuid
from datetime import datetime, timezone

import database as _db

CLASSES = ("GREEN", "YELLOW", "WHITE")
GRADES = ("A", "B", "C", "D")
# A rule's fields, as the dashboard edits them and modules/alerts reads them.
FIELDS = ("name", "enabled", "market", "classes", "grades", "district",
          "min_size", "max_price_eur", "min_surplus")


def _ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            market        TEXT NOT NULL DEFAULT '',
            classes       TEXT NOT NULL DEFAULT '',
            grades        TEXT NOT NULL DEFAULT '',
            district      TEXT NOT NULL DEFAULT '',
            min_size      REAL,
            max_price_eur REAL,
            min_surplus   REAL,
            position      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        )""")


def _csv(value, allowed) -> str:
    """"green, B ,x" → "GREEN" for classes: the allowed ones, upper-cased, in
    their own order, comma-separated. A list is taken as it is."""
    parts = value if isinstance(value, (list, tuple, set)) else str(value or "").replace(";", ",").split(",")
    wanted = {str(p).strip().upper() for p in parts}
    return ",".join(a for a in allowed if a in wanted)


def _num(value):
    """A number, or None for blank / not a number / NaN."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def clean_rule(row: dict) -> dict | None:
    """One rule as stored: its text trimmed, its lists cut to the known
    classes and grades, its numbers numbers. None for a row with no name
    (an empty line in the editor)."""
    name = str(row.get("name") or "").strip()[:60]
    if not name:
        return None
    market = str(row.get("market") or "").strip().lower()
    return {
        "name": name,
        "enabled": 1 if row.get("enabled", True) not in (False, 0, "0", None) else 0,
        "market": market if market in ("sk", "cz") else "",
        "classes": _csv(row.get("classes"), CLASSES),
        "grades": _csv(row.get("grades"), GRADES),
        "district": str(row.get("district") or "").strip()[:60],
        "min_size": _num(row.get("min_size")),
        "max_price_eur": _num(row.get("max_price_eur")),
        "min_surplus": _num(row.get("min_surplus")),
    }


def get_alert_rules() -> list[dict]:
    """The saved rules, in the order they were saved. [] when none was."""
    conn = _db.get_conn()
    try:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT id, name, enabled, market, classes, grades, district, min_size, "
            "max_price_eur, min_surplus FROM alert_rules ORDER BY position, created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def save_alert_rules(rows) -> int:
    """Replace the saved rules with `rows` (dicts with FIELDS; a row without
    a name is dropped). Returns how many were stored."""
    rules = [r for r in (clean_rule(row) for row in rows or []) if r]
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM alert_rules")
        conn.executemany(
            "INSERT INTO alert_rules (id, name, enabled, market, classes, grades, district, "
            "min_size, max_price_eur, min_surplus, position, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(str(uuid.uuid4()), r["name"], r["enabled"], r["market"], r["classes"],
              r["grades"], r["district"], r["min_size"], r["max_price_eur"],
              r["min_surplus"], i, now) for i, r in enumerate(rules)])
        conn.commit()
    finally:
        conn.close()
    return len(rules)

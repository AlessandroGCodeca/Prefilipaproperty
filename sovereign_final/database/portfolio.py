"""
database/portfolio.py — the flats you own (PORTFOLIO tab): what you paid,
the loan, the rent and costs you planned, and month by month what the flat
really brought in and cost (the ledger).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import database as _db

FLAT_FIELDS = (
    "name", "market", "district", "size_m2", "rooms", "bought_on", "price", "buying_costs",
    "structure", "loan_principal", "loan_rate", "loan_years", "loan_start", "fixation_years",
    "reset_rate", "rent_monthly", "hoa_monthly", "other_costs_monthly", "value_estimate",
    "listing_id", "notes",
)
_REAL = {"size_m2", "price", "buying_costs", "loan_principal", "loan_rate", "reset_rate",
         "rent_monthly", "hoa_monthly", "other_costs_monthly", "value_estimate"}
_INT = {"rooms", "loan_years", "fixation_years"}


def _ensure(conn) -> None:
    cols = ", ".join(f"{c} {'REAL' if c in _REAL else 'INTEGER' if c in _INT else 'TEXT'}"
                     for c in FLAT_FIELDS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS owned_flats (id TEXT PRIMARY KEY, {cols}, "
                 f"created_at TEXT, updated_at TEXT)")
    conn.execute("""CREATE TABLE IF NOT EXISTS owned_ledger (
        flat_id TEXT NOT NULL, month TEXT NOT NULL, rent_received REAL, costs REAL,
        vacant_days INTEGER, note TEXT, PRIMARY KEY (flat_id, month))""")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _typed(values: dict) -> dict:
    out = {}
    for k in FLAT_FIELDS:
        v = values.get(k)
        if v in ("", None):
            out[k] = None
        elif k in _REAL:
            out[k] = float(v)
        elif k in _INT:
            out[k] = int(float(v))
        else:
            out[k] = str(v).strip()[:300]
    out["market"] = out["market"] if out["market"] in ("sk", "cz") else "sk"
    out["structure"] = out["structure"] if out["structure"] in ("personal", "sro") else "personal"
    return out


def save_owned_flat(values: dict, flat_id: str | None = None) -> str:
    """Add a flat (no id) or replace one's fields. Returns its id."""
    if not (values.get("name") or "").strip():
        raise ValueError("a flat needs a name")
    data = _typed(values)
    conn = _db.get_conn()
    try:
        _ensure(conn)
        if flat_id:
            conn.execute(f"UPDATE owned_flats SET {', '.join(f'{k}=?' for k in data)}, "
                         f"updated_at=? WHERE id=?", [*data.values(), _now(), flat_id])
        else:
            flat_id = uuid.uuid4().hex[:12]
            conn.execute(f"INSERT INTO owned_flats (id, {', '.join(data)}, created_at, updated_at) "
                         f"VALUES (?, {', '.join('?' for _ in data)}, ?, ?)",
                         [flat_id, *data.values(), _now(), _now()])
        conn.commit()
    finally:
        conn.close()
    return flat_id


def get_owned_flats() -> list[dict]:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM owned_flats ORDER BY bought_on, name").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_owned_flat(flat_id: str) -> None:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        conn.execute("DELETE FROM owned_flats WHERE id=?", (flat_id,))
        conn.execute("DELETE FROM owned_ledger WHERE flat_id=?", (flat_id,))
        conn.commit()
    finally:
        conn.close()


def set_ledger_month(flat_id: str, month: str, rent_received: float | None,
                     costs: float | None, vacant_days: int | None = 0, note: str = "") -> None:
    """One month's actuals ("YYYY-MM")."""
    if len(month) != 7 or month[4] != "-":
        raise ValueError("month must be YYYY-MM")
    conn = _db.get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO owned_ledger VALUES (?,?,?,?,?,?)",
                     (flat_id, month, rent_received, costs, vacant_days or 0, note or ""))
        conn.commit()
    finally:
        conn.close()


def get_ledger(flat_id: str | None = None) -> list[dict]:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM owned_ledger" + (" WHERE flat_id=?" if flat_id else "")
                            + " ORDER BY month", (flat_id,) if flat_id else ()).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

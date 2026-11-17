"""
database/auctions.py — Slovak real-estate auctions read from the notaries'
central register (Notársky centrálny register dražieb, modules/auctions_sk):
one row per announced auction, with what its announcement says once read.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import database as _db

_COLUMNS = (
    "act_id", "ncr_no", "act_type", "auction_date", "opens_at", "auctioneer",
    "auctioneer_ico", "proposer", "subject_kind", "venue", "doc_url", "doc_name",
    "municipality", "address", "is_flat", "size_m2", "rooms", "min_bid_eur",
    "valuation_eur", "deposit_eur", "lv_number", "cadastral_area", "inspection", "notes",
    "read_at", "first_seen_at", "updated_at",
)
_NUMERIC = {"is_flat", "size_m2", "rooms", "min_bid_eur", "valuation_eur", "deposit_eur"}


def _ensure(conn) -> None:
    cols = ",\n".join(f"{c} {'REAL' if c in _NUMERIC else 'TEXT'}"
                      + (" PRIMARY KEY" if c == "act_id" else "") for c in _COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS auctions ({cols})")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_auction(row: dict) -> bool:
    """Store what the register says (keeping what an announcement read
    added). True when the auction is new."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        known = conn.execute("SELECT 1 FROM auctions WHERE act_id=?", (row["act_id"],)).fetchone()
        given = {k: v for k, v in row.items() if k in _COLUMNS and v not in (None, "")}
        if known:
            sets = ", ".join(f"{k}=?" for k in given if k != "act_id")
            if sets:
                conn.execute(f"UPDATE auctions SET {sets}, updated_at=? WHERE act_id=?",
                             [v for k, v in given.items() if k != "act_id"]
                             + [_now(), row["act_id"]])
        else:
            given.update(first_seen_at=_now(), updated_at=_now())
            conn.execute(f"INSERT INTO auctions ({', '.join(given)}) VALUES "
                         f"({', '.join('?' for _ in given)})", list(given.values()))
        conn.commit()
        return not known
    finally:
        conn.close()


def get_auctions(upcoming_only: bool = True, today: date | None = None) -> list[dict]:
    """The auctions on record, soonest first; real estate only."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM auctions ORDER BY auction_date, act_id").fetchall()
    finally:
        conn.close()
    cut = (today or date.today()).isoformat()
    out = [dict(r) for r in rows]
    out = [r for r in out if (r.get("subject_kind") or "Nehnuteľná vec").startswith("Nehnuteľn")]
    if upcoming_only:
        out = [r for r in out if (r.get("auction_date") or "9999") >= cut]
    return out


def get_auction(act_id: str) -> dict | None:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM auctions WHERE act_id=?", (act_id,)).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def auctions_without_detail(limit: int) -> list[str]:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT act_id FROM auctions WHERE subject_kind IS NULL "
                            "AND auction_date >= ? ORDER BY auction_date LIMIT ?",
                            (date.today().isoformat(), limit)).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]

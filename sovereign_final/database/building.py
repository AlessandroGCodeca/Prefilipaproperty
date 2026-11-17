"""
database/building.py — the building's own facts as you learned them (the
správca's answer to the letter, the viewing, the energy certificate): what
it is built of, when, whether it has been insulated, how it is heated, and
the real monthly fee the owner pays (správa + fond opráv).

The real fee replaces the size-band estimate in the score (engine/financial
hoa_override); saving facts drops the flat's score so the next scoring run
redoes it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import database as _db

FIELDS = ("construction", "year_built", "insulated", "heating", "hoa_monthly", "notes")
CONSTRUCTIONS = ("", "panel", "brick", "skeleton", "wood", "other")
HEATING = ("", "district", "gas boiler (building)", "gas boiler (flat)", "heat pump",
           "electric", "other")


def _ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS building_facts (
        listing_id  TEXT PRIMARY KEY,
        construction TEXT, year_built INTEGER, insulated INTEGER, heating TEXT,
        hoa_monthly REAL, notes TEXT, updated_at TEXT)""")


def get_building_facts(listing_id: str) -> dict:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        r = conn.execute("SELECT * FROM building_facts WHERE listing_id=?", (listing_id,)).fetchone()
    finally:
        conn.close()
    return dict(r) if r else {}


def building_facts_map() -> dict[str, dict]:
    """Every flat's facts, for the scoring run."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM building_facts").fetchall()
    finally:
        conn.close()
    return {r["listing_id"]: dict(r) for r in rows}


def clean(values: dict) -> dict:
    """The known fields, each of its type; an empty one is None."""
    out = {}
    for k in FIELDS:
        v = values.get(k)
        if v in ("", None):
            out[k] = None
        elif k == "year_built":
            y = int(float(v))
            out[k] = y if 1800 <= y <= datetime.now().year + 3 else None
        elif k == "insulated":
            out[k] = 1 if v in (True, 1, "1", "yes") else 0 if v in (False, 0, "0", "no") else None
        elif k == "hoa_monthly":
            f = float(v)
            out[k] = f if 0 < f < 100_000 else None
        else:
            out[k] = str(v).strip()[:500] or None
    return out


def set_building_facts(listing_id: str, values: dict) -> dict:
    """Store the facts and drop the flat's score, so the next scoring run
    redoes it on them. Returns what was stored."""
    facts = clean(values)
    conn = _db.get_conn()
    try:
        _ensure(conn)
        conn.execute(
            "INSERT OR REPLACE INTO building_facts (listing_id, construction, year_built, "
            "insulated, heating, hoa_monthly, notes, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (listing_id, facts["construction"], facts["year_built"], facts["insulated"],
             facts["heating"], facts["hoa_monthly"], facts["notes"],
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        from database.scores import _drop_cashflow_score
        _drop_cashflow_score(conn, listing_id)
        conn.commit()
    finally:
        conn.close()
    return facts

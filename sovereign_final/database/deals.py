"""
database/deals.py — The user's own tracking: deal stages and their history, vibe notes, and
saved contract drafts.
"""

from datetime import datetime, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import _ensure_enrichment_columns, _ensure_market_columns


# ── Deal stages ──────────────────────────────────────────────────────────────
DEAL_STAGES = [
    "NEW", "WATCHING", "VIEWING", "OFFER", "NEGOTIATING",
    "DUE DILIGENCE", "NOTARY", "CLOSED", "PASSED",
]


def set_deal_stage(listing_id: str, stage: str, note: str = "") -> None:
    """Move a listing to `stage` and log the move."""
    stage = (stage or "").upper()
    if stage not in DEAL_STAGES:
        raise ValueError(f"unknown deal stage {stage!r}")
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.get_conn()
    try:
        conn.execute("""
            INSERT INTO deal_stages (listing_id, stage, note, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(listing_id) DO UPDATE SET
                stage=excluded.stage, note=excluded.note, updated_at=excluded.updated_at
        """, (listing_id, stage, note or None, now))
        conn.execute("""
            INSERT INTO deal_stage_history (listing_id, stage, note, changed_at)
            VALUES (?,?,?,?)
        """, (listing_id, stage, note or None, now))
        conn.commit()
    finally:
        conn.close()


def get_deal_stages() -> dict:
    """{listing_id: {stage, note, updated_at}} for every tracked listing."""
    conn = _db.get_conn()
    try:
        rows = conn.execute(
            "SELECT listing_id, stage, note, updated_at FROM deal_stages").fetchall()
    finally:
        conn.close()
    return {r["listing_id"]: dict(r) for r in rows}


def get_deal_stage_history(listing_id: str) -> list[dict]:
    conn = _db.get_conn()
    try:
        rows = conn.execute("""
            SELECT stage, note, changed_at FROM deal_stage_history
            WHERE listing_id=? ORDER BY changed_at DESC, id DESC
        """, (listing_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_tracked_listings() -> list[dict]:
    """Every listing with a deal stage, active or not — a deal under offer
    stays on the board even after the portal pulls the ad."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.url, l.source, l.price_eur,
                   l.size_m2, l.is_active, l.scraped_at, l.lv_status,
                   l.market, l.currency,
                   c.classification AS cf_class, c.surplus_sro,
                   c.max_price_yellow, c.max_price_green,
                   d.stage, d.note, d.updated_at
            FROM deal_stages d
            JOIN listings l ON l.id = d.listing_id
            LEFT JOIN cashflow_scores c ON c.listing_id = l.id
            ORDER BY d.updated_at DESC
        """).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Vibe notes (annotations) ─────────────────────────────────────────────────
def add_annotation(listing_id: str, note: str, vibe_score: int | None) -> None:
    import uuid
    conn = _db.get_conn()
    try:
        conn.execute(
            "INSERT INTO annotations (id, listing_id, note, vibe_score, created_at) "
            "VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), listing_id, note or "", vibe_score,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def get_annotations(listing_id: str | None = None) -> list[dict]:
    """Saved vibe checks, newest first — for one listing or all of them."""
    conn = _db.get_conn()
    try:
        if listing_id:
            rows = conn.execute(
                "SELECT * FROM annotations WHERE listing_id=? "
                "ORDER BY created_at DESC", (listing_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM annotations ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def latest_vibes() -> dict:
    """{listing_id: (latest vibe score, latest note, number of notes)}."""
    out: dict = {}
    for a in get_annotations():            # newest first
        lid = a["listing_id"]
        if lid in out:
            score, note, n = out[lid]
            out[lid] = (score, note, n + 1)
        else:
            out[lid] = (a.get("vibe_score"), a.get("note") or "", 1)
    return out


def save_contract_draft(listing_id: str, ownership_type: str, agreed_price: float,
                        buyer_name: str, buyer_ico: str, notary_name: str,
                        draft_text: str) -> str:
    """Keep a generated contract draft, so the text sent to the notár can be
    found again after the page reloads. Returns the new draft's id."""
    import uuid
    draft_id = str(uuid.uuid4())
    conn = _db.get_conn()
    try:
        conn.execute("""
            INSERT INTO contract_drafts
            (id, listing_id, ownership_type, agreed_price, buyer_name, buyer_ico,
             notary_name, draft_text, generated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (draft_id, listing_id, ownership_type, float(agreed_price),
              buyer_name, buyer_ico or None, notary_name or None, draft_text,
              datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return draft_id


def get_contract_drafts(listing_id: str) -> list[dict]:
    """Saved contract drafts for one listing, newest first."""
    conn = _db.get_conn()
    try:
        rows = conn.execute("""
            SELECT id, ownership_type, agreed_price, buyer_name, buyer_ico,
                   notary_name, draft_text, generated_at, status
            FROM contract_drafts WHERE listing_id=?
            ORDER BY generated_at DESC
        """, (listing_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

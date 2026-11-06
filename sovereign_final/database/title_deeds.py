"""
database/title_deeds.py — Title deeds (LV, list vlastníctva): check status, the stored deed text,
parcel data, and the dashboard's LV to-do list.
"""

from datetime import datetime, timedelta, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import (
    _ensure_enrichment_columns, _ensure_market_columns, _has_table, _market_sql,
)


def set_lv_status(listing_id: str, status: str, reason: str = "", detail: str = "",
                  module: str = "debt_bot", soft_flags: str | None = None):
    """Record an LV check. status: PASS (the flat's own LV was read and is
    clean), UNVERIFIED (no title deed of this flat was read — lv_detail says
    why), or REJECTED (the flat's LV carries a blocking encumbrance).
    soft_flags: what the flat's own LV carries that is flagged, not blocking
    (modules/lv_screen tiers); each check replaces the last one's."""
    import uuid
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute(
            "UPDATE listings SET lv_status=?, lv_detail=?, lv_checked_at=?, "
            "lv_soft_flags=? WHERE id=?",
            (status, (detail or "")[:1000] or None,
             datetime.now(timezone.utc).isoformat(),
             (soft_flags or "")[:1000] or None, listing_id))
        if status == "REJECTED":
            conn.execute("""
                INSERT INTO rejections_log (id, listing_id, reason, detail, module, flagged_at)
                VALUES (?,?,?,?,?,?)
            """, (str(uuid.uuid4()), listing_id, reason, detail, module,
                  datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def reset_demo_rejections() -> int:
    """Undo rejections fabricated by the old demo LV mode.

    Before modules/debt_bot stopped inventing verdicts, listings without a
    cadastral parcel number (i.e. all of them) were REJECTED with invented
    "[DEMO] ..." liens — every one sharing the same hash seed — which hid the
    entire dashboard. Flip those rows back to PENDING and drop their fabricated
    rejection-log entries so the next debt-filter run re-checks them honestly.
    Real rejections (no [DEMO] marker) are untouched. Returns rows healed.
    """
    conn = _db.get_conn()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT listing_id FROM rejections_log WHERE detail LIKE '%[DEMO]%'"
        )]
        if not ids:
            return 0
        ph = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE listings SET lv_status='PENDING' "
            f"WHERE id IN ({ph}) AND lv_status='REJECTED'", ids)
        conn.execute(
            f"DELETE FROM rejections_log WHERE detail LIKE '%[DEMO]%' "
            f"AND listing_id IN ({ph})", ids)
        conn.commit()
    finally:
        conn.close()
    return len(ids)


def set_lv_analysis(listing_id: str, risk_level: str, summary: str = ""):
    """Persist Claude's analyze_lv read (modules/debt_bot._decide_lv) so the
    dashboard can show the title-deed risk level and rationale. Previously this
    was computed and discarded. No-op-safe on older DBs via the column migration."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute(
            "UPDATE listings SET lv_risk_level=?, lv_summary=? WHERE id=?",
            (risk_level or None, (summary or "")[:1000] or None, listing_id),
        )
        conn.commit()
    finally:
        conn.close()


_LV_ROW_COLUMNS = """
    id, address_raw, district, lat, lng, coords_source,
    cadastral_area, cadastral_number, cadastral_unit_code,
    plot_lv_number, lv_number, market
"""


def get_pending_lv(recheck_days: int = 7, market: str | None = None):
    """Listings the LV debt filter should (re)check: every PENDING one, and an
    UNVERIFIED one that has something new to check with — a portal map pin or
    a flat LV number — once its last check is `recheck_days` old (a portal
    outage or a pin off the building shouldn't park it forever). `market`
    keeps one market's; None returns all, each row carrying its market."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=recheck_days)).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market)
        rows = conn.execute(f"""
            SELECT {_LV_ROW_COLUMNS}
            FROM listings
            WHERE is_active=1 AND (
                lv_status='PENDING'
                OR (lv_status='UNVERIFIED'
                    AND (coords_source='listing' OR COALESCE(lv_number, '') != '')
                    AND (lv_checked_at IS NULL OR lv_checked_at < ?))
            ){only}
        """, (cutoff, *params)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_lv_row(listing_id: str) -> dict | None:
    """One listing's LV inputs, shaped like a get_pending_lv() row."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        row = conn.execute(
            f"SELECT {_LV_ROW_COLUMNS} FROM listings WHERE id=?", (listing_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def set_parcel_data(listing_id: str, cadastral_area: str, parcel_no: str,
                    ku_code=None, plot_lv=None):
    """Store the building parcel found under a listing's map pin."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute(
            "UPDATE listings SET cadastral_area=?, cadastral_number=?, "
            "cadastral_unit_code=?, plot_lv_number=? WHERE id=?",
            (cadastral_area, parcel_no,
             str(ku_code) if ku_code is not None else None,
             str(plot_lv) if plot_lv is not None else None, listing_id))
        conn.commit()
    finally:
        conn.close()


def _ensure_lv_documents_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS lv_documents ("
                 "listing_id TEXT PRIMARY KEY, lv_text TEXT NOT NULL, "
                 "added_at TEXT NOT NULL)")


def set_lv_document(listing_id: str, lv_text: str) -> None:
    """Store the pasted text of a flat's výpis z LV; blank removes it. Kept
    composed (NFC): text copied from a PDF may come decomposed."""
    import unicodedata
    text = unicodedata.normalize("NFC", lv_text or "").strip()
    conn = _db.get_conn()
    try:
        _ensure_lv_documents_table(conn)
        if text:
            conn.execute(
                "INSERT INTO lv_documents (listing_id, lv_text, added_at) VALUES (?,?,?) "
                "ON CONFLICT(listing_id) DO UPDATE SET lv_text=excluded.lv_text, "
                "added_at=excluded.added_at",
                (listing_id, text, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM lv_documents WHERE listing_id=?", (listing_id,))
        conn.commit()
    finally:
        conn.close()


def get_lv_documents(listing_ids=None) -> dict[str, str]:
    """{listing id: pasted LV text} — for `listing_ids`, or every one."""
    conn = _db.get_conn()
    try:
        _ensure_lv_documents_table(conn)
        if listing_ids is None:
            rows = conn.execute("SELECT listing_id, lv_text FROM lv_documents").fetchall()
        else:
            ids = list(listing_ids)
            rows = []
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                rows += conn.execute(
                    f"SELECT listing_id, lv_text FROM lv_documents WHERE listing_id IN "
                    f"({','.join('?' * len(chunk))})", chunk).fetchall()
    finally:
        conn.close()
    return {r[0]: r[1] for r in rows}


def get_lv_document(listing_id: str) -> str | None:
    return get_lv_documents([listing_id]).get(listing_id)


def set_flat_lv(listing_id: str, lv_number: str, cadastral_area: str = ""):
    """Store the flat's own LV number — typed in from the seller's papers or
    the agent; blank clears it. A katastrálne územie that differs from the
    stored one replaces it, and drops the plot data found under the map pin
    (its parcel number belongs to the old unit; the next check re-finds it)."""
    lv_number = (lv_number or "").strip() or None
    area = (cadastral_area or "").strip()
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute("UPDATE listings SET lv_number=? WHERE id=?",
                     (lv_number, listing_id))
        if area:
            conn.execute(
                "UPDATE listings SET cadastral_area=?, cadastral_unit_code=NULL, "
                "cadastral_number=NULL, plot_lv_number=NULL "
                "WHERE id=? AND COALESCE(cadastral_area, '') != ?",
                (area, listing_id, area))
        conn.commit()
    finally:
        conn.close()


def get_lv_todo() -> list[dict]:
    """The LV to-do queue: active GREEN and YELLOW listings whose title deed
    is not verified yet, best deal first. The debt filter can verify a flat
    only through its own LV number, which comes from the seller's papers or
    the agent — never from the map pin, whose plot LV is a different one — so
    almost every listing starts here as UNVERIFIED."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        if not _has_table(conn, "cashflow_scores"):
            return []
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.address_raw, l.url, l.source,
                   l.price_eur, l.size_m2, l.lv_status, l.lv_number,
                   l.market, l.currency,
                   l.cadastral_area, l.cadastral_unit_code, l.cadastral_number,
                   l.plot_lv_number, l.lv_detail, l.lv_checked_at,
                   c.classification AS cf_class, c.market_discount
            FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE l.is_active = 1
              AND COALESCE(l.lv_status, 'PENDING') NOT IN ('PASS', 'CLEAN', 'REJECTED')
              AND c.classification IN ('GREEN', 'YELLOW')
            ORDER BY CASE c.classification WHEN 'GREEN' THEN 0 ELSE 1 END,
                     c.market_discount DESC
        """).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def queue_lv_check(listing_id: str) -> None:
    """Have the next LV debt-filter run check this listing whatever its last
    check's age — for an LV number typed in without verifying it now."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute("UPDATE listings SET lv_checked_at=NULL "
                     "WHERE id=? AND lv_status='UNVERIFIED'", (listing_id,))
        conn.commit()
    finally:
        conn.close()

"""
database/enrichment.py — Description and address enrichment: the queues the parsers work through
and the fields they write back onto a listing.
"""

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.scores import _drop_cashflow_score
from database.schema import (
    _ensure_enrichment_columns, _ensure_market_columns, _market_sql,
)


def get_listing_description(listing_id: str) -> str:
    conn = _db.get_conn()
    try:
        row = conn.execute("SELECT description FROM listings WHERE id=?",
                           (listing_id,)).fetchone()
    finally:
        conn.close()
    return (row[0] if row else "") or ""


def get_unparsed_descriptions(limit: int = 200, market: str | None = None):
    """Active listings with a stored free-text description that hasn't been
    parsed into structured features yet. desc_parsed stays 0 until a successful
    parse, so transient enrichment failures get retried on a later run.
    `market` keeps one market's (None: all)."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market)
        rows = conn.execute(f"""
            SELECT id, description, market
            FROM listings
            WHERE is_active=1
              AND description IS NOT NULL AND description != ''
              AND (desc_parsed IS NULL OR desc_parsed = 0){only}
            ORDER BY scraped_at DESC
            LIMIT ?
        """, (*params, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_description_features(listing_id: str, features: dict):
    """Persist parsed description features and mark the row parsed.
    `features` keys: has_parking, has_balcony, furnished, condition, the
    building facts (has_elevator, has_cellar, has_terrace, has_loggia,
    building_floors) and optionally rooms / floor — which only fill in when
    the listing has none yet (structured scraper data outranks the
    description's phrasing)."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        # What the rent estimate reads: when the parse changes it, the score
        # made without it is dropped and redone by the scoring that follows.
        def rent_inputs():
            r = conn.execute("SELECT has_parking, has_balcony, furnished, rooms FROM listings "
                             "WHERE id = ?", (listing_id,)).fetchone()
            if not r:
                return None
            furn = (r["furnished"] or "").lower()
            return (bool(r["has_parking"]), bool(r["has_balcony"]),
                    furn if furn in ("furnished", "semi") else "", r["rooms"])
        before = rent_inputs()
        conn.execute("""
            UPDATE listings SET
                has_parking = ?, has_balcony = ?,
                furnished   = ?, condition   = ?,
                has_elevator = ?, has_cellar = ?,
                has_terrace  = ?, has_loggia = ?,
                building_floors = COALESCE(?, building_floors),
                rooms       = COALESCE(rooms, ?),
                floor       = COALESCE(floor, ?),
                desc_parsed = 1
            WHERE id = ?
        """, (
            features.get("has_parking"),
            features.get("has_balcony"),
            features.get("furnished"),
            features.get("condition"),
            features.get("has_elevator"),
            features.get("has_cellar"),
            features.get("has_terrace"),
            features.get("has_loggia"),
            features.get("building_floors"),
            features.get("rooms"),
            features.get("floor"),
            listing_id,
        ))
        if before is not None and rent_inputs() != before:
            _drop_cashflow_score(conn, listing_id)
        conn.commit()
    finally:
        conn.close()


def requeue_descriptions_missing_extras() -> int:
    """Send listings parsed before the building facts (elevator, cellar,
    terrace, floors) were kept back through description enrichment once. The
    parse already returned those facts; they were discarded at the time.
    Returns the number of rows re-queued."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        n = conn.execute("""
            UPDATE listings SET desc_parsed = 0
            WHERE is_active = 1 AND desc_parsed = 1 AND has_elevator IS NULL
              AND description IS NOT NULL AND description != ''
        """).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def get_unnormalized_addresses(limit: int = 200, market: str | None = None):
    """Active listings that have a raw address but a blank district (so the rent
    estimate falls to the €6.50/m² default) and haven't been normalized yet.
    addr_normalized stays 0 until a normalize_address() call returns (success or
    a definitive empty result), so only transient failures get retried."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market)
        rows = conn.execute(f"""
            SELECT id, address_raw, market
            FROM listings
            WHERE is_active=1
              AND address_raw IS NOT NULL AND address_raw != ''
              AND (district IS NULL OR district = '')
              AND (addr_normalized IS NULL OR addr_normalized = 0){only}
            ORDER BY scraped_at DESC
            LIMIT ?
        """, (*params, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_address(listing_id: str, district: str, city: str):
    """Persist a normalized district/city and mark the row normalized.

    Only fills blanks: district is set when a non-empty value was resolved; city
    is set only when it was previously blank — so a good scraped city is never
    clobbered. addr_normalized is set regardless (even on an empty resolution)
    so an unresolvable address isn't re-sent to the LLM every run. A resolved
    district drops the score worked out without it (_drop_cashflow_score).
    """
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute("""
            UPDATE listings SET
                district = CASE WHEN ? != '' THEN ? ELSE district END,
                city = CASE WHEN (city IS NULL OR city = '') AND ? != ''
                            THEN ? ELSE city END,
                addr_normalized = 1
            WHERE id = ?
        """, (district, district, city, city, listing_id))
        if district:
            _drop_cashflow_score(conn, listing_id)
        conn.commit()
    finally:
        conn.close()

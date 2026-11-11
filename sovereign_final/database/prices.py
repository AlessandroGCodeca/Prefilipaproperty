"""
database/prices.py — Price history: every asking price a listing has shown, price cuts, and
days on market.
"""

from datetime import datetime, timedelta, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import _ensure_market_columns


# ── Price history ─────────────────────────────────────────────────────────────
def _ensure_price_history(conn):
    """price_history on a DB that hasn't been through init_db since it was
    added (a scraper subprocess, an old file). Idempotent and cheap."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id  TEXT NOT NULL,
            price_eur   REAL NOT NULL,
            observed_at TEXT NOT NULL
        )""")


def _record_price(conn, listing_id: str, price_eur: float, when: str | None = None):
    conn.execute(
        "INSERT INTO price_history (listing_id, price_eur, observed_at) VALUES (?,?,?)",
        (listing_id, float(price_eur),
         when or datetime.now(timezone.utc).isoformat()),
    )


def _has_price_history(conn, listing_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM price_history WHERE listing_id=? LIMIT 1", (listing_id,)
    ).fetchone() is not None


def forget_price(conn, listing_id: str, price_eur: float) -> int:
    """Remove a misread price (a neighbouring listing's, or a deposit) from a
    listing's history, keeping the prices recorded around it. Takes the
    caller's connection; the caller commits."""
    return conn.execute(
        "DELETE FROM price_history WHERE listing_id=? AND price_eur=?",
        (listing_id, float(price_eur)),
    ).rowcount


def summarize_price_history(rows, now: datetime | None = None) -> dict:
    """Fold price_history rows (listing_id, price_eur, observed_at — oldest
    first per listing) into one summary per listing:

      first_price, last_price, change_pct (last vs first, negative = cut),
      last_change_at, last_change_pct, n_changes, history [(when, price)].

    A row repeating the price before it is not a change. Only listings whose
    price actually moved are returned.
    """
    by_listing: dict[str, list] = {}
    for lid, price, when in rows:
        hist = by_listing.setdefault(lid, [])
        if not hist or hist[-1][1] != price:
            hist.append((when, price))
    out = {}
    for lid, hist in by_listing.items():
        if len(hist) < 2:
            continue
        first, last, prev = hist[0][1], hist[-1][1], hist[-2][1]
        out[lid] = {
            "first_price":     first,
            "last_price":      last,
            "change_pct":      round(last / first - 1, 4) if first else None,
            "last_change_at":  hist[-1][0],
            "last_change_pct": round(last / prev - 1, 4) if prev else None,
            "n_changes":       len(hist) - 1,
            "history":         hist,
        }
    return out


_IN_CHUNK = 500


def get_price_history(listing_ids=None) -> dict:
    """summarize_price_history for every listing (or just `listing_ids`)."""
    conn = _db.get_conn()
    try:
        _ensure_price_history(conn)
        if listing_ids:
            # In chunks, as title_deeds.get_lv_documents does: SQLite caps the
            # parameters of one query. Each listing's rows stay in one chunk,
            # in order.
            ids = list(dict.fromkeys(listing_ids))
            rows = []
            for i in range(0, len(ids), _IN_CHUNK):
                chunk = ids[i:i + _IN_CHUNK]
                rows += conn.execute(
                    f"SELECT listing_id, price_eur, observed_at FROM price_history "
                    f"WHERE listing_id IN ({','.join('?' * len(chunk))}) "
                    f"ORDER BY listing_id, observed_at, id", chunk).fetchall()
        else:
            rows = conn.execute(
                "SELECT listing_id, price_eur, observed_at FROM price_history "
                "ORDER BY listing_id, observed_at, id").fetchall()
    finally:
        conn.close()
    return summarize_price_history([tuple(r) for r in rows])


def get_price_drops(days: int = 14, min_drop: float = 0.02,
                    max_drop: float = 0.40) -> list[dict]:
    """Active listings whose latest price change was a cut of at least
    `min_drop`, made within `days`. Cuts deeper than `max_drop` are left out:
    a 60% "cut" is a misread being corrected, not a motivated seller."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    hist = get_price_history()
    if not hist:
        return []
    conn = _db.get_conn()
    try:
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.url, l.source, l.price_eur,
                   l.size_m2, l.rooms, l.scraped_at, c.classification AS cf_class,
                   c.max_price_yellow, c.max_price_green, l.market, l.currency
            FROM listings l LEFT JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE l.is_active = 1 AND l.lv_status != 'REJECTED'
        """).fetchall()
    finally:
        conn.close()
    drops = []
    for r in rows:
        h = hist.get(r["id"])
        if not h or h["last_change_at"] < cutoff:
            continue
        pct = h["last_change_pct"]
        if pct is None or not (-max_drop <= pct <= -min_drop):
            continue
        drops.append({**dict(r), **{k: h[k] for k in
                     ("first_price", "last_change_at", "last_change_pct",
                      "change_pct", "n_changes")}})
    drops.sort(key=lambda d: d["last_change_at"], reverse=True)
    return drops


def days_on_market(scraped_at: str | None, until: str | None = None) -> int | None:
    """Whole days since we first saw the listing (scraped_at is set on insert
    and never updated, so it is first-seen). `until` defaults to now."""
    if not scraped_at:
        return None
    try:
        start = datetime.fromisoformat(scraped_at)
        end = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end - start).days, 0)

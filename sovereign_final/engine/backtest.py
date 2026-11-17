"""
engine/backtest.py — does GREEN mean cheap? The market's own answer: flats
that really are cheap go fast. Of the flats that were GREEN (or YELLOW,
WHITE) a month or two ago, how many have gone, how fast, and after what
price cuts — and the same for the other classes, to compare.

The class a flat had on each day comes from class_snapshots, written after
every daily run (take_snapshot). Before snapshots reach back far enough, a
cohort is the flats first seen in the window with the class they have now —
marked approximate.

Sold prices (M6): no free register publishes them for Slovakia or Czechia.
Two stand-ins: the last asking price of flats that left the portals (most
sold, some were withdrawn), and the sold prices you enter yourself (from an
agent, a notary, your own purchases) — each compared with the asking median
of the flats still listed.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

import database as _db

GONE_AFTER_DAYS = 3          # unseen this long before the newest sighting: gone
KEEP_SNAPSHOT_DAYS = 400


def _ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS class_snapshots (
        day TEXT NOT NULL, listing_id TEXT NOT NULL, classification TEXT, price REAL,
        PRIMARY KEY (day, listing_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sold_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT, district TEXT, size_m2 REAL,
        rooms INTEGER, price REAL, sold_on TEXT, source TEXT, note TEXT)""")


def take_snapshot(day: date | None = None) -> int:
    """Each active scored listing's class and price today. Returns rows."""
    day = (day or date.today()).isoformat()
    conn = _db.get_conn()
    try:
        _ensure(conn)
        if not _db._has_table(conn, "cashflow_scores"):
            return 0
        n = conn.execute("""
            INSERT OR REPLACE INTO class_snapshots (day, listing_id, classification, price)
            SELECT ?, l.id, c.classification, l.price_eur
            FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE l.is_active = 1""", (day,)).rowcount
        cut = (date.fromisoformat(day) - timedelta(days=KEEP_SNAPSHOT_DAYS)).isoformat()
        conn.execute("DELETE FROM class_snapshots WHERE day < ?", (cut,))
        conn.commit()
    finally:
        conn.close()
    return n


def _parse(iso: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None
    return d.replace(tzinfo=d.tzinfo or timezone.utc) if d else None


def cohort(start: date, end: date, market: str | None = None) -> tuple[dict[str, str], bool]:
    """({listing id: class on its first snapshot in [start, end]}, exact).
    Without snapshots in the window: listings first seen in it, with their
    class now — exact=False."""
    conn = _db.get_conn()
    try:
        _ensure(conn)
        mk = " AND l.market = ?" if market else ""
        args = (start.isoformat(), end.isoformat()) + ((market,) if market else ())
        rows = conn.execute(f"""
            SELECT s.listing_id, s.classification FROM class_snapshots s
            JOIN listings l ON l.id = s.listing_id
            WHERE s.day BETWEEN ? AND ?{mk} ORDER BY s.day DESC""", args).fetchall()
        if rows:
            out = {}
            for r in rows:                       # oldest last: it wins
                out[r[0]] = r[1]
            return out, True
        if not _db._has_table(conn, "cashflow_scores"):
            return {}, False
        rows = conn.execute(f"""
            SELECT l.id, c.classification FROM listings l
            JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE substr(l.scraped_at, 1, 10) BETWEEN ? AND ?{mk}""", args).fetchall()
        return {r[0]: r[1] for r in rows}, False
    finally:
        conn.close()


def outcomes(ids, today: datetime | None = None) -> dict[str, dict]:
    """{id: {gone, days_listed, cuts, cut_pct}} — gone: inactive, or unseen
    for GONE_AFTER_DAYS before the newest sighting of its market."""
    ids = list(ids)
    if not ids:
        return {}
    conn = _db.get_conn()
    try:
        newest = _parse(conn.execute("SELECT MAX(last_seen_at) FROM listings").fetchone()[0])
        rows, hist = [], {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            rows += conn.execute(f"SELECT id, scraped_at, last_seen_at, is_active FROM listings "
                                 f"WHERE id IN ({q})", chunk).fetchall()
            if _db._has_table(conn, "price_history"):
                for r in conn.execute(f"SELECT listing_id, price_eur FROM price_history WHERE "
                                      f"listing_id IN ({q}) ORDER BY observed_at", chunk):
                    hist.setdefault(r[0], []).append(r[1])
    finally:
        conn.close()
    newest = newest or today or datetime.now(timezone.utc)
    out = {}
    for r in rows:
        first, last = _parse(r[1]), _parse(r[2])
        if not first or not last:
            continue
        gone = not r[3] or (newest - last).days >= GONE_AFTER_DAYS
        prices = hist.get(r[0], [])
        cuts = sum(1 for a, b in zip(prices, prices[1:]) if b < a)
        out[r[0]] = {"gone": gone, "days_listed": max((last - first).days, 0), "cuts": cuts,
                     "cut_pct": (prices[-1] / prices[0] - 1) if len(prices) > 1 and prices[0] else 0.0}
    return out


def summary(classes: dict[str, str], results: dict[str, dict]) -> list[dict]:
    """One row a class: how many, how many gone, how fast, after what cuts."""
    rows = []
    for cls in ("GREEN", "YELLOW", "WHITE"):
        ids = [i for i, c in classes.items() if c == cls and i in results]
        if not ids:
            continue
        gone = [results[i] for i in ids if results[i]["gone"]]
        rows.append({
            "Class": cls, "Flats": len(ids),
            "Gone %": round(100 * len(gone) / len(ids), 1),
            "Gone within 30 days %": round(100 * sum(1 for g in gone if g["days_listed"] <= 30)
                                           / len(ids), 1),
            "Median days to go": statistics.median([g["days_listed"] for g in gone]) if gone else None,
            "Cut before going %": round(100 * sum(1 for g in gone if g["cuts"]) / len(gone), 1)
            if gone else None,
            "Median cut %": round(100 * statistics.median([g["cut_pct"] for g in gone if g["cuts"]]), 1)
            if any(g["cuts"] for g in gone) else None,
        })
    return rows


def run(days_back_from: int = 60, days_back_to: int = 30, market: str | None = None,
        today: date | None = None) -> tuple[list[dict], bool]:
    """summary() for the flats of the window [today − from, today − to]."""
    today = today or date.today()
    classes, exact = cohort(today - timedelta(days=days_back_from),
                            today - timedelta(days=days_back_to), market)
    return summary(classes, outcomes(classes)), exact


# ── Sold prices (M6) ──────────────────────────────────────────────────────────
def add_sold_price(market: str, district: str, size_m2: float, price: float, sold_on: str = "",
                   rooms: int | None = None, source: str = "", note: str = "") -> None:
    if not (district or "").strip() or not size_m2 or not price:
        raise ValueError("a sold price needs a district, a size and a price")
    conn = _db.get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT INTO sold_prices (market, district, size_m2, rooms, price, sold_on, "
                     "source, note) VALUES (?,?,?,?,?,?,?,?)",
                     (market or "sk", district.strip(), float(size_m2), rooms, float(price),
                      sold_on, source, note))
        conn.commit()
    finally:
        conn.close()


def sold_prices() -> list[dict]:
    conn = _db.get_conn()
    try:
        _ensure(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM sold_prices ORDER BY sold_on DESC")]
    finally:
        conn.close()


def asking_vs(market: str = "sk", days: int = 90) -> list[dict]:
    """Per district key: the asking €/m² of listed flats, the last asking
    €/m² of flats that left in the last `days`, and the €/m² of sold prices
    you entered — each a median, with the gap to the asking median."""
    from engine.financial import match_rent_key
    conn = _db.get_conn()
    try:
        _ensure(conn)
        newest = _parse(conn.execute("SELECT MAX(last_seen_at) FROM listings").fetchone()[0])
        rows = conn.execute("SELECT district, price_eur, size_m2, last_seen_at, is_active, market "
                            "FROM listings WHERE price_eur > 0 AND size_m2 > 0").fetchall()
        sold = conn.execute("SELECT district, price, size_m2, market FROM sold_prices").fetchall()
    finally:
        conn.close()
    if not newest:
        return []
    cutoff = newest - timedelta(days=days)
    groups: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        if (r[5] or "sk") != market:
            continue
        key = match_rent_key(r[0] or "", market=market)
        last = _parse(r[3])
        gone = not r[4] or (last and (newest - last).days >= GONE_AFTER_DAYS)
        bucket = "left" if gone and last and last >= cutoff else "listed" if not gone else None
        if bucket:
            groups.setdefault(key, {}).setdefault(bucket, []).append(r[1] / r[2])
    for r in sold:
        if (r[3] or "sk") == market:
            key = match_rent_key(r[0] or "", market=market)
            groups.setdefault(key, {}).setdefault("sold", []).append(r[1] / r[2])
    out = []
    for key, g in sorted(groups.items()):
        listed = statistics.median(g["listed"]) if g.get("listed") else None
        row = {"District key": key, "Listed": len(g.get("listed", [])),
               "Asking €/m²": round(listed) if listed else None}
        for name, label in (("left", "Last asking of flats that left"), ("sold", "Sold (yours)")):
            vals = g.get(name) or []
            med = statistics.median(vals) if vals else None
            row[f"{label} €/m²"] = round(med) if med else None
            row[f"{label} n"] = len(vals)
            row[f"{label} vs asking %"] = round((med / listed - 1) * 100, 1) if med and listed else None
        out.append(row)
    return out

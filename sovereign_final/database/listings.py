"""
database/listings.py — Sale listings: the scrapers' upserts, the dashboard's active and rejected
lists, cross-portal duplicates, staleness, and developer-project flags.
"""

import re
from datetime import datetime, timedelta, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.prices import (
    _ensure_price_history, _has_price_history, _record_price, forget_price,
)
from database.schema import (
    _ensure_dev_project_column, _ensure_enrichment_columns, _ensure_market_columns,
    _market_sql,
)
from database.scores import _drop_cashflow_score, _drop_location_score


# Detect dev-project listings (multi-unit projects, not individual buyable
# apartments). Their "price" field is typically the cheapest unit's starting
# price ("od €X") rather than a real sale price, so they distort GREEN/YELLOW
# classification. Detection is conservative — we'd rather miss a few than
# false-positive on a real apartment.
_DEV_PROJECT_URL_MARKERS = (
    "/detail/developersky-projekt/",   # nehnutelnosti explicit dev project path
    "developersky-projekt",            # other portals occasionally use this slug
)


_DEV_PROJECT_TITLE_MARKERS = (
    "developersky projekt", "developerský projekt",
    "novy projekt", "nový projekt",
    "novostavba",
    "1. fáza", "2. fáza", "3. fáza", "1. etapa", "2. etapa", "i. etapa", "ii. etapa",
    " od €", " od eur",   # "Predaj bytov od €145 900" pattern — only with leading space
)


# A Czech project's title says "1. fáze" / "2. etapa" or quotes a starting
# price in crowns ("Byty od 3 990 000 Kč"); the Slovak markers above apply too.
_DEV_PROJECT_TITLE_MARKERS_CZ = ("1. fáze", "2. fáze", "3. fáze", "developerský projekt")


_DEV_PROJECT_FROM_CZK_RE = re.compile(r"(?<!\w)od\s+\d[\d\s\xa0.]*(?:,-)?\s*(?:kč|czk)")


def detect_dev_project(url: str, title: str, market: str = "sk") -> int:
    """Return 1 if URL or title indicates this is a multi-unit dev project,
    else 0. Conservative: returns 0 on ambiguous input rather than risk
    false-positives on real apartments. A Czech listing also matches the
    Czech markers."""
    u = (url or "").lower()
    if any(marker in u for marker in _DEV_PROJECT_URL_MARKERS):
        return 1
    t = (title or "").lower()
    if any(marker in t for marker in _DEV_PROJECT_TITLE_MARKERS):
        return 1
    if market != "sk" and (any(m in t for m in _DEV_PROJECT_TITLE_MARKERS_CZ)
                           or _DEV_PROJECT_FROM_CZK_RE.search(t)):
        return 1
    return 0


def backfill_dev_project_flags() -> int:
    """Run detect_dev_project on every active listing and update is_dev_project.
    Returns the number of rows newly flagged as dev projects."""
    conn = _db.get_conn()
    try:
        _ensure_dev_project_column(conn)
        _ensure_market_columns(conn)
        rows = conn.execute(
            "SELECT id, url, title, market FROM listings WHERE is_dev_project=0"
        ).fetchall()
        flagged = []
        for r in rows:
            if detect_dev_project(r[1] or "", r[2] or "", r[3] or "sk"):
                flagged.append(r[0])
        if flagged:
            ph = ",".join("?" * len(flagged))
            conn.execute(
                f"UPDATE listings SET is_dev_project=1 WHERE id IN ({ph})",
                flagged,
            )
            conn.commit()
    finally:
        conn.close()
    return len(flagged)


# ── Query Helpers ─────────────────────────────────────────────────────────────
def get_all_active(rejected: bool = False, market: str | None = None):
    """Active listings with their cashflow and location scores, best discount
    first. LV-rejected listings never reach the deal lists, so they are left
    out — or, with rejected=True, they are all that comes back (the
    dashboard's Rejected tile counts them against the same filters).
    `market` keeps one market's listings; None (default) returns all."""
    conn = _db.get_conn()
    try:
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.*,
                   c.classification        AS cf_class,
                   c.surplus_personal,     c.surplus_sro,
                   c.ratio_personal,       c.ratio_sro,
                   c.cash_on_cash,         c.net_rental_yield,
                   c.gross_yield,          c.optimal_structure,
                   c.noi_monthly,          c.cap_rate,
                   c.principal_paydown_monthly, c.total_return_annual,
                   c.total_roi,            c.total_cash_invested,
                   c.market_discount,      c.regional_median_m2,
                   c.estimated_rent_eur,   c.total_costs_personal,
                   c.total_costs_sro,      c.annual_sro_saving,
                   c.sro_break_even_months,
                   c.mortgage_monthly,     c.hoa_monthly,
                   c.property_tax_monthly, c.vacancy_cost,
                   c.maintenance_monthly,  c.management_monthly,
                   c.income_tax_personal,
                   c.health_levy_personal, c.income_tax_sro,
                   c.acquisition_costs,
                   c.mortgage_rate_used,   c.ltv_used, c.loan_term_years,
                   c.max_price_green,      c.max_price_yellow,
                   c.stress_surplus_sro,   c.stress_ratio_sro,
                   c.irr_sro,              c.irr_personal, c.rent_source,
                   c.sro_rate_used,        c.sro_ltv_used,
                   c.mortgage_monthly_sro, c.total_cash_invested_sro,
                   c.sro_running_cost_monthly, c.rent_key, c.tax_year,
                   lc.location_score,      lc.location_tier,
                   lc.nearest_transit_m,   lc.walkability_score,
                   lc.industrial_zone,     lc.construction_risk,
                   lc.noise_flag,          lc.amenity_count,
                   lc.flood_zone,          lc.construction_detail,
                   lc.noise_detail,        lc.flood_detail,
                   lc.geo_precision
            FROM listings l
            LEFT JOIN cashflow_scores c  ON l.id = c.listing_id
            LEFT JOIN location_scores lc ON l.id = lc.listing_id
            WHERE l.is_active = 1 AND l.lv_status {'=' if rejected else '!='} 'REJECTED'{only}
            ORDER BY c.market_discount DESC NULLS LAST
        """, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_rejected():
    """Every LV rejection with its reason, newest first. A listing re-verified
    and rejected twice appears twice — each row is one decision."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.address_raw, l.url, l.source,
                   l.price_eur, l.size_m2, l.scraped_at, l.is_active,
                   l.lv_status, l.lv_risk_level, l.lv_summary,
                   l.market, l.currency,
                   r.reason, r.detail, r.module, r.flagged_at
            FROM listings l
            JOIN rejections_log r ON l.id = r.listing_id
            ORDER BY r.flagged_at DESC
        """).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Cross-portal duplicates ──────────────────────────────────────────────────
def mark_duplicates(market: str | None = None) -> int:
    """Group copies of the same flat across portals (engine.duplicates) and
    store each member's primary id in listings.dup_group. Re-run from scratch
    every time, so a copy that went inactive or changed price leaves its
    group. Returns the number of listings that are part of a group.

    Copies are only ever matched within one market. `market` regroups that
    market alone (its pipeline run), leaving the other's groups as they are;
    None regroups every market.

    LV-rejected copies take part in the matching but never in a group: the
    dashboard hides them, so a group is only the copies it shows. What they
    do leave is dup_lv_failed on every shown copy of the same flat — the
    title deed that failed is that flat's, whichever portal carried it."""
    from engine.duplicates import group_duplicates
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market)
        rows = [dict(r) for r in conn.execute(f"""
            SELECT id, url, source, district, size_m2, price_eur, rooms, floor,
                   scraped_at, lv_status, market
            FROM listings
            WHERE is_active = 1
              AND price_eur > 0 AND size_m2 > 0
              AND (is_dev_project IS NULL OR is_dev_project = 0){only}
        """, params).fetchall()]
        rejected = {r["id"] for r in rows if r["lv_status"] == "REJECTED"}
        members: dict[str, list[str]] = {}
        for lid, primary in group_duplicates(rows).items():
            members.setdefault(primary, []).append(lid)
        conn.execute("UPDATE listings SET dup_group = NULL, dup_lv_failed = NULL "
                     f"WHERE (dup_group IS NOT NULL OR dup_lv_failed IS NOT NULL){only}",
                     params)
        grouped = 0
        for primary, ids in members.items():
            shown = [i for i in ids if i not in rejected]
            # A rejected copy ranks last, so with any shown copy the primary
            # is one of them.
            if len(shown) >= 2:
                conn.executemany("UPDATE listings SET dup_group=? WHERE id=?",
                                 [(primary, i) for i in shown])
                grouped += len(shown)
            if len(shown) < len(ids):
                conn.executemany("UPDATE listings SET dup_lv_failed=1 WHERE id=?",
                                 [(i,) for i in shown])
        conn.commit()
    finally:
        conn.close()
    return grouped


# ── Rental listings (live rent comps) ────────────────────────────────────────
def upsert_rental(data: dict) -> None:
    """Store one prenájom listing for engine/rent_comps. Keyed on url; a
    re-seen rental refreshes its rent and last_seen_at. `rent_eur` is the
    rent in the rental's own currency (`currency`: EUR for a Slovak one, CZK
    for a Czech one); `market` defaults to 'sk'."""
    import markets
    market = markets.normalize(data.get("market"))
    data = {**data, "market": market,
            "currency": data.get("currency") or markets.get(market).currency}
    conn = _db.get_conn()
    try:
        _ensure_market_columns(conn)
        conn.execute("""
            INSERT INTO rental_listings
            (id, source, url, title, rent_eur, size_m2, rooms, district, rent_key,
             energies_included, furnished, scraped_at, last_seen_at, is_active,
             market, currency)
            VALUES
            (:id,:source,:url,:title,:rent_eur,:size_m2,:rooms,:district,:rent_key,
             :energies_included,:furnished,:scraped_at,:last_seen_at,1,
             :market,:currency)
            ON CONFLICT(url) DO UPDATE SET
                rent_eur=excluded.rent_eur, size_m2=excluded.size_m2,
                rooms=COALESCE(excluded.rooms, rooms),
                district=CASE WHEN excluded.district != '' THEN excluded.district ELSE district END,
                rent_key=excluded.rent_key,
                energies_included=excluded.energies_included,
                furnished=excluded.furnished,
                last_seen_at=excluded.last_seen_at, is_active=1
        """, data)
        conn.commit()
    finally:
        conn.close()


def get_stats(market: str | None = None):
    """Active listings by class. An LV-rejected listing is counted as
    rejected only — it keeps the class it had (often PENDING), and counting
    it there too made the classes add up to more than the total. `market`
    counts one market's listings; None counts all."""
    conn = _db.get_conn()
    try:
        only, params = _market_sql(conn, market)
        r = conn.execute(f"""
            SELECT
                COUNT(*)                                       AS total,
                COALESCE(SUM(CASE WHEN NOT rej AND classification='GREEN'   THEN 1 ELSE 0 END), 0) AS green,
                COALESCE(SUM(CASE WHEN NOT rej AND classification='YELLOW'  THEN 1 ELSE 0 END), 0) AS yellow,
                COALESCE(SUM(CASE WHEN NOT rej AND classification='WHITE'   THEN 1 ELSE 0 END), 0) AS white,
                COALESCE(SUM(CASE WHEN rej                                  THEN 1 ELSE 0 END), 0) AS rejected,
                COALESCE(SUM(CASE WHEN NOT rej AND classification='PENDING' THEN 1 ELSE 0 END), 0) AS pending
            FROM (SELECT classification, COALESCE(lv_status, '') = 'REJECTED' AS rej
                  FROM listings WHERE is_active=1{only})
        """, params).fetchone()
    finally:
        conn.close()
    return dict(r) if r else {"total":0,"green":0,"yellow":0,"white":0,"rejected":0,"pending":0}


def get_active_sources() -> list[str]:
    """Every source active listings came from — the portals, and 'sample' for
    the rows seed_market_data.py writes. The dashboard's Source filter offers
    these, so no source is hidden by a filter that cannot select it."""
    conn = _db.get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT source FROM listings "
            "WHERE is_active=1 AND COALESCE(source, '') != '' ORDER BY source"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def deactivate_stale_listings(days: int = 21, market: str | None = None,
                              sources=None, exclude_sources=()) -> int:
    """Mark listings as inactive when last_seen_at is older than `days` days.

    Each scraper run touches last_seen_at on every listing it sees, so any
    listing not re-seen for ~3 weeks has likely been removed from the source
    site (sold, withdrawn, or expired). Keeping them active inflates GREEN
    counts and shows the user listings that no longer exist.

    `market` limits it to one market — a pipeline run whose own portals
    couldn't be read skips its market's check, not the other's. None (the
    default) checks every market.

    `sources`, when given, limits it to those portals' listings: the pipeline
    passes the portals that returned listings this run, so a blocked or
    broken portal's listings are kept, not retired for not being seen (an
    empty `sources` retires nothing). `exclude_sources` leaves those
    portals' listings out.

    Returns the number of rows deactivated.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if sources is not None:
        sources = [s for s in sources if s]
        if not sources:
            return 0
    exclude = [s for s in (exclude_sources or ()) if s]
    conn = _db.get_conn()
    try:
        only, params = _market_sql(conn, market)
        if sources is not None:
            only += f" AND source IN ({','.join('?' * len(sources))})"
            params = (*params, *sources)
        if exclude:
            only += f" AND source NOT IN ({','.join('?' * len(exclude))})"
            params = (*params, *exclude)
        n = conn.execute(
            "UPDATE listings SET is_active=0 "
            f"WHERE is_active=1 AND last_seen_at < ?{only}",
            (cutoff, *params),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def mark_details_enriched(listing_ids, when: str = "") -> int:
    """Stamp `detail_enriched_at` on listings whose detail page was just scraped.

    Called by the scrapers after a successful detail-page visit. The stamp is
    what get_fresh_detail_urls() reads back on the next run to decide the page
    doesn't need re-opening. Returns the number of rows stamped.
    """
    ids = [i for i in (listing_ids or []) if i]
    if not ids:
        return 0
    stamp = when or datetime.now(timezone.utc).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        n = 0
        for listing_id in ids:
            n += conn.execute(
                "UPDATE listings SET detail_enriched_at=? WHERE id=?",
                (stamp, listing_id),
            ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def touch_listings(urls) -> int:
    """Bump last_seen_at (and re-activate) rows a scraper saw but chose not to
    re-fetch, so deactivate_stale_listings doesn't retire a listing that is
    still very much on the source site. Returns the number of rows touched.
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.get_conn()
    try:
        n = 0
        for url in urls:
            n += conn.execute(
                "UPDATE listings SET last_seen_at=?, is_active=1 WHERE url=?",
                (now, url),
            ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def deactivate_listings(urls) -> int:
    """Retire listings whose own page says they are gone, without waiting the
    three weeks deactivate_stale_listings needs to reach the same answer.

    A removed nehnutelnosti listing's URL still loads, but shows a grid of
    similar listings where the listing was (see
    scraper.nehnutelnosti._is_similar_listings_page). Keyed on url like
    touch_listings; the row keeps its data and comes back if an upsert sees
    the listing again. Returns the number of rows deactivated.
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return 0
    conn = _db.get_conn()
    try:
        n = 0
        for url in urls:
            n += conn.execute(
                "UPDATE listings SET is_active=0 WHERE url=? AND is_active=1",
                (url,),
            ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def set_listing_price(listing_id: str, price_eur: float) -> bool:
    """Overwrite a listing's price outright — including back down to 0.

    upsert_listing deliberately never lowers a price to 0, because a scrape
    that simply failed to read one must not wipe a good value. Repairing a
    price that was read off the wrong listing needs exactly that, so it goes
    through here instead.

    Clearing a price also resets the row to PENDING and drops
    detail_enriched_at, so get_fresh_detail_urls() stops treating the row as
    complete and the next scrape reads its detail page again.
    """
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_price_history(conn)
        old = conn.execute(
            "SELECT price_eur FROM listings WHERE id=?", (listing_id,)).fetchone()
        old_price = (old[0] or 0) if old else 0
        misread_at = None
        if old_price and old_price != (price_eur or 0):
            # A repair corrects a misread, so the misread was never an asking
            # price: it leaves the history, rather than the correction being
            # reported as a price cut. Prices seen before the misread stay, so
            # a genuine earlier cut is still one. The score worked out at the
            # misread goes too, so the corrected price gets scored.
            #
            # The corrected price takes the misread's date: it is what was on
            # offer then. Dated now, a repair to below the price seen before
            # the misread showed up as a cut made today.
            misread_at = conn.execute(
                "SELECT MAX(observed_at) FROM price_history "
                "WHERE listing_id=? AND price_eur=?",
                (listing_id, float(old_price)),
            ).fetchone()[0]
            forget_price(conn, listing_id, old_price)
            _drop_cashflow_score(conn, listing_id)
        if price_eur and price_eur > 0:
            n = conn.execute(
                "UPDATE listings SET price_eur=? WHERE id=?",
                (float(price_eur), listing_id),
            ).rowcount
            if n:
                _record_price(conn, listing_id, float(price_eur), misread_at)
        else:
            n = conn.execute(
                "UPDATE listings SET price_eur=0, classification='PENDING', "
                "detail_enriched_at=NULL WHERE id=?",
                (listing_id,),
            ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n > 0


def get_shared_price_listings(source: str, min_distinct_sizes: int = 2,
                              limit: int = 200) -> list[dict]:
    """Listings whose price is also carried by other listings of a DIFFERENT
    size — the signature of a price read off a neighbouring listing.

    One agency's €1,250,000 property ended up on seven of its unrelated flats,
    and €1,399,000 on three more of 200, 188 and 114 m². Sizes differ because
    the listings are genuinely different properties; only the price was shared.

    Round asking prices do repeat legitimately (€259,000 across nine unrelated
    flats is ordinary market clustering), so this over-reports. That is the
    right way round for its purpose: the caller re-reads the page, which costs
    one visit and confirms a genuine price as easily as it corrects a wrong one.
    """
    conn = _db.get_conn()
    try:
        rows = conn.execute("""
            SELECT id, source, url, price_eur, size_m2, district, title
            FROM listings
            WHERE source=? AND is_active=1 AND price_eur > 0 AND size_m2 > 0
              AND price_eur IN (
                  SELECT price_eur FROM listings
                  WHERE source=? AND is_active=1 AND price_eur > 0 AND size_m2 > 0
                  GROUP BY price_eur
                  HAVING COUNT(DISTINCT size_m2) >= ?
              )
            ORDER BY price_eur DESC
            LIMIT ?
        """, (source, source, min_distinct_sizes, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_fresh_detail_urls(source: str, max_age_days: int = 7) -> set[str]:
    """URLs whose detail page was scraped within `max_age_days` AND already has
    both a price and a size.

    Opening a detail page is by far the most expensive step in a scrape run —
    one full browser navigation each. A listing we already hold complete, recent
    data for gains nothing from being re-opened, so the scrapers skip these and
    just touch last_seen_at (which keeps deactivate_stale_listings happy).

    The window matters: listings do get price cuts, so anything older than
    `max_age_days` is re-opened to pick up changes. Rows missing a price or size
    are never skipped — those are exactly the ones a re-visit might fix.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = conn.execute(
            "SELECT url FROM listings "
            "WHERE source=? AND is_active=1 "
            "  AND price_eur > 0 AND size_m2 > 0 "
            "  AND detail_enriched_at IS NOT NULL AND detail_enriched_at >= ?",
            (source, cutoff),
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows if r[0]}


def fill_blank_district(conn, listing_id: str, district: str,
                        address_raw: str | None = None) -> bool:
    """Set a district on a row that has none, and drop the score worked out
    without it (see _drop_cashflow_score). A row that already has a district
    is left alone. `address_raw`, when given, is written alongside.

    Takes the caller's connection so a backfill loop stays one transaction;
    the caller commits. Returns True when the row was filled.
    """
    if not district:
        return False
    sets, params = "district=?", [district]
    if address_raw is not None:
        sets += ", address_raw=?"
        params.append(address_raw)
    n = conn.execute(
        f"UPDATE listings SET {sets} "
        "WHERE id=? AND (district IS NULL OR district='')",
        (*params, listing_id),
    ).rowcount
    if n:
        _drop_cashflow_score(conn, listing_id)
    return n > 0


# A pin that moves further than this (~20–25 m) points at another building.
_PIN_MOVE_DEG = 0.0002


# The row upsert_listing finds for a listing it is about to write. _pin_moved
# reads lat/lng/coords_source at 2–4; the price history reads 5–6.
_EXISTING_COLS = "id, district, lat, lng, coords_source, price_eur, scraped_at"


def _pin_moved(existing, lat, lng) -> bool:
    """`existing` is upsert_listing's _EXISTING_COLS row."""
    old_lat, old_lng, source = existing[2], existing[3], existing[4]
    if source != "listing" or old_lat is None:
        return True
    return (abs(old_lat - lat) > _PIN_MOVE_DEG
            or abs(old_lng - lng) > _PIN_MOVE_DEG)


_SCHEMA_CHECKED: set = set()


def upsert_listing(data: dict):
    """Insert or refresh a scraped listing. `lat`/`lng`, when present, are the
    portal's own map pin; they outrank geocoded coordinates, and a new or
    moved pin sends an UNVERIFIED LV check back to PENDING so the debt filter
    looks up the building parcel under it.

    `market` ('sk' when absent) and `currency` (the market's own when absent)
    are set on insert and never changed after; `price_eur` is the asking price
    in that currency — EUR for a Slovak listing, CZK for a Czech one."""
    import markets
    lat, lng = data.get("lat"), data.get("lng")
    has_pin = lat is not None and lng is not None
    market = markets.normalize(data.get("market"))
    data = {**data, "lat": lat if has_pin else None, "lng": lng if has_pin else None,
            "coords_source": "listing" if has_pin else None,
            "market": market,
            "currency": data.get("currency") or markets.get(market).currency}
    conn = _db.get_conn()
    try:
        # The schema checks once per database per process, not per listing:
        # a scrape saves thousands. Keyed by the connection function too, so
        # a test that swaps in its own database is checked again.
        schema_key = (_db.SQLITE_PATH, _db.get_conn)
        if schema_key not in _SCHEMA_CHECKED:
            _ensure_enrichment_columns(conn)
            _ensure_market_columns(conn)
            _ensure_price_history(conn)
            _SCHEMA_CHECKED.add(schema_key)
        # If a row already exists with this URL (e.g. a prior slug-URL variant
        # that _dedupe_canonical_urls rewrote to the canonical form), reuse its
        # id so ON CONFLICT(id) fires instead of hitting the url UNIQUE constraint.
        existing = conn.execute(
            f"SELECT {_EXISTING_COLS} FROM listings WHERE url=?",
            (data["url"],)
        ).fetchone()
        if existing is None:
            existing = conn.execute(
                f"SELECT {_EXISTING_COLS} FROM listings WHERE id=?",
                (data["id"],)
            ).fetchone()
        if existing and existing[0] != data["id"]:
            data = {**data, "id": existing[0], "url_hash": existing[0]}
        # Auto-detect dev-project listings from URL + title at insert time.
        data = {**data, "is_dev_project": detect_dev_project(
            data.get("url", ""), data.get("title", ""), market,
        )}
        conn.execute("""
            INSERT INTO listings
            (id, source, url, url_hash, title, description, price_eur, size_m2,
             rooms, floor, year_built, energy_class, address_raw, district, city,
             primary_image_url, image_urls, classification, lv_status, scraped_at,
             last_seen_at, is_dev_project, lat, lng, coords_source, market, currency)
            VALUES
            (:id,:source,:url,:url_hash,:title,:description,:price_eur,:size_m2,
             :rooms,:floor,:year_built,:energy_class,:address_raw,:district,:city,
             :primary_image_url,:image_urls,:classification,:lv_status,:scraped_at,
             :last_seen_at,:is_dev_project,:lat,:lng,:coords_source,:market,:currency)
            ON CONFLICT(id) DO UPDATE SET
                last_seen_at=excluded.last_seen_at,
                title=CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,
                description=CASE WHEN excluded.description IS NOT NULL AND excluded.description != ''
                                 THEN excluded.description ELSE description END,
                price_eur=CASE WHEN excluded.price_eur > 0 THEN excluded.price_eur ELSE price_eur END,
                size_m2=CASE WHEN excluded.size_m2 > 0 THEN excluded.size_m2 ELSE size_m2 END,
                rooms=COALESCE(excluded.rooms, rooms),
                floor=COALESCE(excluded.floor, floor),
                year_built=COALESCE(excluded.year_built, year_built),
                energy_class=CASE WHEN excluded.energy_class != 'UNKNOWN' AND excluded.energy_class != ''
                                  THEN excluded.energy_class ELSE energy_class END,
                address_raw=CASE WHEN excluded.address_raw != '' THEN excluded.address_raw ELSE address_raw END,
                district=CASE WHEN excluded.district != '' THEN excluded.district ELSE district END,
                city=CASE WHEN excluded.city != '' THEN excluded.city ELSE city END,
                primary_image_url=CASE WHEN excluded.primary_image_url != ''
                                       THEN excluded.primary_image_url ELSE primary_image_url END,
                image_urls=CASE WHEN excluded.image_urls != '' THEN excluded.image_urls ELSE image_urls END,
                is_active=1,
                is_dev_project=CASE WHEN excluded.is_dev_project=1 THEN 1 ELSE is_dev_project END,
                lat=CASE WHEN excluded.lat IS NOT NULL THEN excluded.lat ELSE lat END,
                lng=CASE WHEN excluded.lat IS NOT NULL THEN excluded.lng ELSE lng END,
                coords_source=CASE WHEN excluded.lat IS NOT NULL THEN 'listing'
                                   ELSE coords_source END
        """, data)
        # A new or moved pin: the parcel found under the old one (if any) is
        # stale, and an UNVERIFIED check can now get further.
        if existing and has_pin and _pin_moved(existing, lat, lng):
            conn.execute(
                "UPDATE listings SET cadastral_area=NULL, cadastral_number=NULL, "
                "cadastral_unit_code=NULL, plot_lv_number=NULL "
                "WHERE id=? AND (lv_number IS NULL OR lv_number='')",
                (data["id"],))
            conn.execute(
                "UPDATE listings SET lv_status='PENDING' "
                "WHERE id=? AND lv_status='UNVERIFIED'", (data["id"],))
            # Location IQ judged transit, amenities and risk at the old
            # coordinates (a geocode, often just a district centroid, or the
            # pin before it moved): score it again at the pin.
            _drop_location_score(conn, data["id"])
            # A pin needs no geocode: back to the front of Location IQ's queue.
            conn.execute("UPDATE listings SET location_tried_at=NULL WHERE id=?",
                         (data["id"],))
        # A district arriving for a row that had none: its score is stale.
        if (existing and not (existing[1] or "").strip()
                and (data.get("district") or "").strip()):
            _drop_cashflow_score(conn, data["id"])
        # A new asking price: log it, and re-score at the new price (a cut
        # can turn a WHITE into a YELLOW — that is the alert worth having).
        new_price = data.get("price_eur") or 0
        old_price = (existing[5] or 0) if existing else 0
        if new_price > 0 and new_price != old_price:
            if existing and old_price > 0 and not _has_price_history(conn, data["id"]):
                # Rows from before price history existed: the price being
                # replaced is the first one we ever saw, as of first sight.
                _record_price(conn, data["id"], old_price, existing[6])
            _record_price(conn, data["id"], new_price,
                          data.get("last_seen_at") or data.get("scraped_at"))
            # Also when the old price was 0: a price a cleanup zeroed may
            # still have the score worked out at the misread.
            if existing:
                _drop_cashflow_score(conn, data["id"])
        conn.commit()
    finally:
        conn.close()

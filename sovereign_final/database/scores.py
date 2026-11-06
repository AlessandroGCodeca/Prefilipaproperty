"""
database/scores.py — Cashflow and location scores: writing them, the queues of listings still
to score, and the requeue rules that send a stale score back.
"""

from datetime import datetime, timezone

import database as _db  # get_conn through the package: tests swap database.get_conn
from database.schema import (
    _CASHFLOW_NEW_COLUMNS, _LOCATION_NEW_COLUMNS, _ensure_cashflow_columns,
    _ensure_enrichment_columns, _ensure_location_columns, _ensure_market_columns,
    _has_table, _market_kw, _market_sql,
)


def clear_cashflow_scores() -> int:
    """Delete all cashflow scores and reset scored listings back to PENDING so
    the next 💰 CASHFLOW SCORE run re-scores every listing from scratch.

    Needed whenever the engine's assumptions change (RENT_PER_M2, tax rates,
    mortgage rate, cost model) — get_unscored_cashflow() only picks up listings
    with no existing score, so without this the updated figures never reach
    already-scored rows. Returns the number of score rows removed.
    """
    conn = _db.get_conn()
    try:
        n = conn.execute("DELETE FROM cashflow_scores").rowcount
        conn.execute(
            "UPDATE listings SET classification='PENDING' "
            "WHERE classification IN ('GREEN','YELLOW','WHITE')"
        )
        conn.commit()
    finally:
        conn.close()
    return n


def _drop_cashflow_score(conn, listing_id: str) -> bool:
    """Discard one listing's cashflow score so the next scoring run redoes it.

    A score worked out while the district was blank used the €6.50/m² default
    rent — about half what a Bratislava flat earns. get_unscored_cashflow()
    only picks up rows with no score, so filling the district alone would
    leave that wrong score in place for good. Classification goes back to
    PENDING only when it came from the score being dropped.
    """
    if not _has_table(conn, "cashflow_scores"):
        return False     # a DB (or test fixture) that never scored anything
    n = conn.execute(
        "DELETE FROM cashflow_scores WHERE listing_id=?", (listing_id,)
    ).rowcount
    if n:
        conn.execute(
            "UPDATE listings SET classification='PENDING' "
            "WHERE id=? AND classification IN ('GREEN','YELLOW','WHITE')",
            (listing_id,),
        )
    return n > 0


def _drop_location_score(conn, listing_id: str) -> bool:
    """Discard one listing's location row so the next Location IQ run scores
    it again (get_unscored_location only picks up rows with none)."""
    if not _has_table(conn, "location_scores"):
        return False
    return conn.execute(
        "DELETE FROM location_scores WHERE listing_id=?", (listing_id,)
    ).rowcount > 0


def requeue_scores_without_benchmark(market: str | None = None) -> int:
    """Drop the scores worked out with no regional median for a district that
    has one now, so the next scoring run classifies them against it.

    A district engine.regional_prices didn't know scored WHITE ("no regional
    price benchmark"), and get_unscored_cashflow() never looks at a scored row
    again — so a town added to the price tables later would stay WHITE for
    good. `market` keeps it to one market's listings (None: all) — a run
    scoped to one market must not drop another's scores it won't redo.
    Returns the number of scores dropped."""
    from engine.regional_prices import regional_median_price
    conn = _db.get_conn()
    try:
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.id, l.district, l.market FROM listings l
            JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE c.regional_median_m2 IS NULL AND l.is_active = 1{only}
        """, params).fetchall()
        n = sum(_drop_cashflow_score(conn, r["id"]) for r in rows
                if regional_median_price(r["district"] or "",
                                         **_market_kw(r["market"])) is not None)
        conn.commit()
    finally:
        conn.close()
    return n


def requeue_scores_with_stale_class(market: str | None = None) -> int:
    """Drop the scores whose class or max offers no longer match what the
    engine gives for the listing's price, size and district today — a
    regional median that moved, or a class rule that changed (classify()
    judging at 4 decimals, so a flat exactly 20% under the median is GREEN
    now, not YELLOW). get_unscored_cashflow() never looks at a scored row
    again, so without this they would keep the old answer for good.
    `market` keeps it to one market's listings (None: all). Returns the
    number of scores dropped."""
    from engine.financial import class_at_price, max_offer_price
    conn = _db.get_conn()
    try:
        if not _has_table(conn, "cashflow_scores"):
            return 0
        _ensure_cashflow_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.id, l.price_eur, l.size_m2, l.district, l.rooms, l.market,
                   c.classification, c.max_price_green, c.max_price_yellow
            FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
            -- Only what get_unscored_cashflow() would score again.
            WHERE l.is_active = 1 AND l.price_eur > 0 AND l.size_m2 > 0
              AND l.lv_status != 'REJECTED'{only}
        """, params).fetchall()
        stale = [
            r["id"] for r in rows
            if (class_at_price(r["price_eur"], r["size_m2"], r["district"] or "",
                               r["rooms"], **_market_kw(r["market"]))
                != r["classification"]
                or max_offer_price(r["size_m2"], r["district"] or "", "GREEN",
                                   rooms=r["rooms"], **_market_kw(r["market"]))
                != r["max_price_green"]
                or max_offer_price(r["size_m2"], r["district"] or "", "YELLOW",
                                   rooms=r["rooms"], **_market_kw(r["market"]))
                != r["max_price_yellow"])
        ]
        n = sum(_drop_cashflow_score(conn, lid) for lid in stale)
        conn.commit()
    finally:
        conn.close()
    return n


def requeue_scores_with_stale_property_tax(market: str = "sk") -> int:
    """Drop the scores of `market` whose property tax is no longer what the
    engine charges — a rate or coefficient was updated from the official
    sources (modules/tax_rates, modules/tax_rates_cz) — so the next scoring
    run redoes them. Compares each score's stored property_tax_monthly with
    the tax at today's figures, so it drops only the listings the change
    reaches. Returns how many it dropped."""
    from engine.financial import property_tax_annual
    conn = _db.get_conn()
    try:
        if not _has_table(conn, "cashflow_scores"):
            return 0
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.id, l.price_eur, l.size_m2, l.district, c.property_tax_monthly
            FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
            WHERE l.is_active = 1 AND l.price_eur > 0 AND l.size_m2 > 0
              AND l.lv_status != 'REJECTED'{only}
        """, params).fetchall()
        n = 0
        for r in rows:
            now = round(property_tax_annual(r["price_eur"], r["size_m2"], r["district"] or "",
                                            market=market) / 12, 2)
            if r["property_tax_monthly"] is None or abs(now - r["property_tax_monthly"]) > 0.011:
                n += _drop_cashflow_score(conn, r["id"])
        conn.commit()
    finally:
        conn.close()
    return n


def requeue_scores_from_older_model(market: str | None = None) -> int:
    """Drop the scores worked out by an older version of the engine
    (engine.financial.SCORING_MODEL_VERSION) or under another year's tax
    table than the one scoring uses now (config.tax_rules), so the next
    scoring run redoes them. A new tax year's table, or a change to how the
    figures are worked out, would otherwise reach only listings scored after
    it. `market` keeps it to one market's listings (None: all). Returns the
    number of scores dropped."""
    import markets
    from engine.financial import SCORING_MODEL_VERSION
    conn = _db.get_conn()
    try:
        if not _has_table(conn, "cashflow_scores"):
            return 0
        _ensure_cashflow_columns(conn)
        _ensure_market_columns(conn)
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.id, l.market, c.model_version, c.tax_year, c.ltv_used
            FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
            -- Only what get_unscored_cashflow() would score again.
            WHERE l.is_active = 1 AND l.price_eur > 0 AND l.size_m2 > 0
              AND l.lv_status != 'REJECTED'{only}
        """, params).fetchall()
        # Each market has its own tax tables, so its own current year.
        years: dict[str, int | None] = {}

        def tax_year(market):
            m = markets.normalize(market)
            if m not in years:
                try:
                    years[m] = markets.tax_rules(market=m)["year"]
                except LookupError:          # no table yet: nothing to compare
                    years[m] = None
            return years[m]
        # ... and the LTV a bank lends at today: it moves with the date (the
        # investor cap from INVESTOR_LTV_FROM) and with PROPERTIES_OWNED.
        ltvs: dict[str, float | None] = {}

        def ltv_now(market):
            from engine.financial import default_ltv
            m = markets.normalize(market)
            if m not in ltvs:
                try:
                    ltvs[m] = default_ltv(**_market_kw(m))
                except LookupError:
                    ltvs[m] = None
            return ltvs[m]
        n = sum(_drop_cashflow_score(conn, r["id"]) for r in rows
                if r["model_version"] is None
                or r["model_version"] != SCORING_MODEL_VERSION
                or r["tax_year"] is None or r["tax_year"] != tax_year(r["market"])
                or (ltv_now(r["market"]) is not None
                    and (r["ltv_used"] is None
                         or abs(r["ltv_used"] - ltv_now(r["market"])) > 1e-9)))
        conn.commit()
    finally:
        conn.close()
    return n


def upsert_cashflow(data: dict):
    """Store one listing's score. Columns added after the first schema
    (_CASHFLOW_NEW_COLUMNS) default to NULL when the caller leaves them out."""
    conn = _db.get_conn()
    try:
        _ensure_cashflow_columns(conn)
        conn.execute("""
            INSERT OR REPLACE INTO cashflow_scores
            (listing_id, estimated_rent_eur, mortgage_monthly, hoa_monthly,
             property_tax_monthly, vacancy_cost, maintenance_monthly, management_monthly,
             income_tax_personal, health_levy_personal, total_costs_personal,
             surplus_personal, ratio_personal,
             income_tax_sro, health_levy_sro, total_costs_sro,
             surplus_sro, ratio_sro,
             noi_monthly, cap_rate,
             cash_on_cash, net_rental_yield, gross_yield,
             principal_paydown_monthly, total_return_annual, total_roi,
             regional_median_m2, market_discount,
             acquisition_costs, total_cash_invested,
             optimal_structure, classification,
             annual_sro_saving, sro_break_even_months,
             scored_at, mortgage_rate_used, ltv_used, loan_term_years,
             max_price_green, max_price_yellow,
             stress_surplus_sro, stress_ratio_sro,
             irr_sro, irr_personal, rent_source,
             sro_rate_used, sro_ltv_used, mortgage_monthly_sro,
             total_cash_invested_sro, sro_running_cost_monthly, rent_key,
             tax_year, model_version)
            VALUES
            (:listing_id,:estimated_rent_eur,:mortgage_monthly,:hoa_monthly,
             :property_tax_monthly,:vacancy_cost,:maintenance_monthly,:management_monthly,
             :income_tax_personal,:health_levy_personal,:total_costs_personal,
             :surplus_personal,:ratio_personal,
             :income_tax_sro,:health_levy_sro,:total_costs_sro,
             :surplus_sro,:ratio_sro,
             :noi_monthly,:cap_rate,
             :cash_on_cash,:net_rental_yield,:gross_yield,
             :principal_paydown_monthly,:total_return_annual,:total_roi,
             :regional_median_m2,:market_discount,
             :acquisition_costs,:total_cash_invested,
             :optimal_structure,:classification,
             :annual_sro_saving,:sro_break_even_months,
             :scored_at,:mortgage_rate_used,:ltv_used,:loan_term_years,
             :max_price_green,:max_price_yellow,
             :stress_surplus_sro,:stress_ratio_sro,
             :irr_sro,:irr_personal,:rent_source,
             :sro_rate_used,:sro_ltv_used,:mortgage_monthly_sro,
             :total_cash_invested_sro,:sro_running_cost_monthly,:rent_key,
             :tax_year,:model_version)
        """, {**dict.fromkeys(_CASHFLOW_NEW_COLUMNS), **data})
        conn.execute(
            "UPDATE listings SET classification=? WHERE id=?",
            (data["classification"], data["listing_id"])
        )
        conn.commit()
    finally:
        conn.close()


def upsert_location(data: dict):
    conn = _db.get_conn()
    try:
        _ensure_location_columns(conn)
        conn.execute("""
            INSERT OR REPLACE INTO location_scores
            (listing_id, lat, lng, nearest_transit_m, amenity_count,
             grocery_count, pharmacy_count, school_count,
             construction_risk, noise_flag, flood_zone,
             walkability_score, industrial_zone, industrial_zone_name,
             location_score, location_tier, scored_at,
             construction_detail, noise_detail, flood_detail,
             geo_precision, risk_checked_at)
            VALUES
            (:listing_id,:lat,:lng,:nearest_transit_m,:amenity_count,
             :grocery_count,:pharmacy_count,:school_count,
             :construction_risk,:noise_flag,:flood_zone,
             :walkability_score,:industrial_zone,:industrial_zone_name,
             :location_score,:location_tier,:scored_at,
             :construction_detail,:noise_detail,:flood_detail,
             :geo_precision,:risk_checked_at)
        """, {**dict.fromkeys(_LOCATION_NEW_COLUMNS), **data})
        # Mirror coordinates onto the listing row — the dashboard (satellite view,
        # MAPS buttons) reads l["lat"]/l["lng"] via get_all_active's l.*, and
        # location_scores' lat/lng are not part of that select. A portal's own pin
        # is never overwritten by a geocode.
        if data.get("lat") is not None and data.get("lng") is not None:
            _ensure_enrichment_columns(conn)
            conn.execute(
                "UPDATE listings SET lat=:lat, lng=:lng, coords_source='geocode' "
                "WHERE id=:listing_id "
                "  AND (coords_source IS NULL OR coords_source != 'listing')", data)
        conn.commit()
    finally:
        conn.close()


def get_location_rows_missing_risk(limit: int = 100) -> list[dict]:
    """Location rows written before real risk data existed (risk_checked_at
    NULL) for active listings the location step scores — LV PASS and
    UNVERIFIED, as in get_unscored_location. Carries the listing's own map pin
    (listing_lat/listing_lng, coords_source) and the stored transit and
    amenity facts, so the score can be recomputed with the new flags."""
    conn = _db.get_conn()
    try:
        _ensure_location_columns(conn)
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT lc.listing_id, lc.lat, lc.lng,
                   lc.nearest_transit_m, lc.amenity_count,
                   l.address_raw, l.district, l.energy_class,
                   l.lat AS listing_lat, l.lng AS listing_lng, l.coords_source,
                   l.market
            FROM location_scores lc JOIN listings l ON l.id = lc.listing_id
            WHERE lc.risk_checked_at IS NULL AND l.is_active = 1
              AND l.lv_status IN ('PASS', 'UNVERIFIED')
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_location_risk(listing_id: str, risk: dict) -> None:
    """Write construction / noise / flood answers (and the geocode precision
    they were judged at) onto an existing location row. lat/lng, and the
    location score and tier recomputed from the new flags, are written when
    given and kept otherwise."""
    conn = _db.get_conn()
    try:
        _ensure_location_columns(conn)
        conn.execute("""
            UPDATE location_scores SET
                construction_risk=:construction_risk,
                construction_detail=:construction_detail,
                noise_flag=:noise_flag, noise_detail=:noise_detail,
                flood_zone=:flood_zone, flood_detail=:flood_detail,
                geo_precision=:geo_precision, risk_checked_at=:risk_checked_at,
                lat=COALESCE(:lat, lat), lng=COALESCE(:lng, lng),
                location_score=COALESCE(:location_score, location_score),
                location_tier=COALESCE(:location_tier, location_tier),
                walkability_score=COALESCE(:walkability_score, walkability_score)
            WHERE listing_id=:listing_id
        """, {"lat": None, "lng": None, "location_score": None,
              "location_tier": None, "walkability_score": None,
              **risk, "listing_id": listing_id,
              "risk_checked_at": datetime.now(timezone.utc).isoformat()})
        conn.commit()
    finally:
        conn.close()


def get_unscored_cashflow(market: str | None = None):
    # SELECT l.* (not an explicit column list) so optional enrichment columns
    # like has_parking / furnished flow through to the scorer when present,
    # without a column-list edit each time the schema grows. Each row carries
    # its market; `market` keeps one market's (None: all).
    conn = _db.get_conn()
    try:
        only, params = _market_sql(conn, market, "l.")
        rows = conn.execute(f"""
            SELECT l.*
            FROM listings l
            LEFT JOIN cashflow_scores c ON l.id = c.listing_id
            WHERE l.lv_status != 'REJECTED' AND c.listing_id IS NULL
              AND l.price_eur > 0 AND l.size_m2 > 0 AND l.is_active=1{only}
        """, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_unscored_location():
    """The listings Location IQ still has to locate: listings never tried
    first (oldest first, as before), then the ones whose geocode failed,
    least recently tried first. Without that order the same listings that
    never geocode came first on every run and filled its per-run limit, and
    the listings behind them were never located."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_market_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.address_raw, l.energy_class, l.district,
                   l.lat, l.lng, l.coords_source, l.market
            FROM listings l
            LEFT JOIN location_scores lc ON l.id = lc.listing_id
            WHERE l.lv_status IN ('PASS', 'UNVERIFIED')
              AND lc.listing_id IS NULL AND l.is_active=1
            ORDER BY l.location_tried_at IS NOT NULL, l.location_tried_at, l.rowid
        """).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_location_tried(listing_id: str) -> None:
    """Record that Location IQ could not geocode the listing just now, so the
    next run tries it after every listing not yet tried."""
    conn = _db.get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute("UPDATE listings SET location_tried_at=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(), listing_id))
        conn.commit()
    finally:
        conn.close()

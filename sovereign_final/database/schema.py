"""
database/schema.py — The SQLite schema, the column migrations init_db runs on an older file,
and the small query helpers every topic shares (market filter, table check).
"""

import logging

import database as _db  # get_conn through the package: tests swap database.get_conn

log = logging.getLogger(__name__)


# ── Schema Init ───────────────────────────────────────────────────────────────
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id                TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    url               TEXT NOT NULL UNIQUE,
    url_hash          TEXT UNIQUE,
    title             TEXT,
    description       TEXT,
    price_eur         REAL NOT NULL,
    size_m2           REAL,
    rooms             REAL,
    floor             INTEGER,
    year_built        INTEGER,
    energy_class      TEXT DEFAULT 'UNKNOWN',
    address_raw       TEXT,
    district          TEXT,
    city              TEXT,
    cadastral_area    TEXT,
    cadastral_number  TEXT,
    lat               REAL,
    lng               REAL,
    primary_image_url TEXT,
    image_urls        TEXT,
    classification    TEXT DEFAULT 'PENDING',
    lv_status         TEXT DEFAULT 'PENDING',
    llm_sentiment     REAL,
    llm_risk_flags    TEXT,
    scraped_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    is_active         INTEGER DEFAULT 1,
    is_dev_project    INTEGER DEFAULT 0,
    has_parking       INTEGER,
    has_balcony       INTEGER,
    furnished         TEXT,
    condition         TEXT,
    desc_parsed       INTEGER DEFAULT 0,
    addr_normalized   INTEGER DEFAULT 0,
    lv_risk_level     TEXT,
    lv_summary        TEXT,
    coords_source     TEXT,
    cadastral_unit_code TEXT,
    plot_lv_number    TEXT,
    lv_number         TEXT,
    lv_detail         TEXT,
    lv_checked_at     TEXT,
    notes             TEXT,
    market            TEXT NOT NULL DEFAULT 'sk',
    currency          TEXT NOT NULL DEFAULT 'EUR'
);

CREATE TABLE IF NOT EXISTS cashflow_scores (
    listing_id            TEXT PRIMARY KEY,
    estimated_rent_eur    REAL,
    mortgage_monthly      REAL,
    hoa_monthly           REAL,
    property_tax_monthly  REAL,
    vacancy_cost          REAL,
    maintenance_monthly   REAL,
    management_monthly    REAL,
    income_tax_personal   REAL,
    health_levy_personal  REAL,
    total_costs_personal  REAL,
    surplus_personal      REAL,
    ratio_personal        REAL,
    income_tax_sro        REAL,
    health_levy_sro       REAL,
    total_costs_sro       REAL,
    surplus_sro           REAL,
    ratio_sro             REAL,
    noi_monthly           REAL,
    cap_rate              REAL,
    cash_on_cash          REAL,
    net_rental_yield      REAL,
    gross_yield           REAL,
    principal_paydown_monthly REAL,
    total_return_annual   REAL,
    total_roi             REAL,
    regional_median_m2    REAL,
    market_discount       REAL,
    acquisition_costs     REAL,
    total_cash_invested   REAL,
    optimal_structure     TEXT,
    classification        TEXT,
    annual_sro_saving     REAL,
    sro_break_even_months INTEGER,
    scored_at             TEXT,
    mortgage_rate_used    REAL,
    ltv_used              REAL,
    loan_term_years       INTEGER,
    tax_year              INTEGER DEFAULT 2026,
    max_price_green       REAL,
    max_price_yellow      REAL,
    stress_surplus_sro    REAL,
    stress_ratio_sro      REAL,
    irr_sro               REAL,
    irr_personal          REAL,
    rent_source           TEXT,
    sro_rate_used         REAL,
    sro_ltv_used          REAL,
    mortgage_monthly_sro  REAL,
    total_cash_invested_sro REAL,
    sro_running_cost_monthly REAL,
    rent_key              TEXT,
    model_version         INTEGER
);

CREATE TABLE IF NOT EXISTS location_scores (
    listing_id            TEXT PRIMARY KEY,
    lat                   REAL,
    lng                   REAL,
    nearest_transit_m     REAL,
    amenity_count         INTEGER DEFAULT 0,
    grocery_count         INTEGER DEFAULT 0,
    pharmacy_count        INTEGER DEFAULT 0,
    school_count          INTEGER DEFAULT 0,
    construction_risk     INTEGER DEFAULT 0,
    construction_detail   TEXT,
    noise_flag            INTEGER DEFAULT 0,
    flood_zone            INTEGER DEFAULT 0,
    walkability_score     INTEGER,
    industrial_zone       INTEGER DEFAULT 0,
    industrial_zone_name  TEXT,
    location_score        INTEGER,
    location_tier         TEXT,
    scored_at             TEXT
);

CREATE TABLE IF NOT EXISTS lv_checks (
    id                    TEXT PRIMARY KEY,
    listing_id            TEXT NOT NULL,
    cadastral_area        TEXT,
    parcel_number         TEXT,
    zalozne_pravo_flag    INTEGER DEFAULT 0,
    zalozne_pravo_detail  TEXT,
    exekucia_flag         INTEGER DEFAULT 0,
    exekucia_detail       TEXT,
    sudny_spor_flag       INTEGER DEFAULT 0,
    sudny_spor_detail     TEXT,
    predkupne_pravo_flag  INTEGER DEFAULT 0,
    bank_mortgage_flag    INTEGER DEFAULT 0,
    bank_name             TEXT,
    llm_analysis          TEXT,
    llm_risk_level        TEXT,
    lv_status             TEXT NOT NULL,
    rejection_reason      TEXT,
    checked_at            TEXT,
    raw_response          TEXT
);

CREATE TABLE IF NOT EXISTS rejections_log (
    id          TEXT PRIMARY KEY,
    listing_id  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    detail      TEXT,
    module      TEXT,
    flagged_at  TEXT
);

CREATE TABLE IF NOT EXISTS rent_comps (
    id              TEXT PRIMARY KEY,
    district        TEXT NOT NULL,
    city            TEXT,
    size_band       TEXT NOT NULL,
    avg_rent_eur    REAL,
    median_rent_eur REAL,
    sample_count    INTEGER,
    source          TEXT,
    updated_at      TEXT,
    eur_per_m2      REAL,
    market          TEXT NOT NULL DEFAULT 'sk',
    UNIQUE(market, district, size_band)
);

CREATE TABLE IF NOT EXISTS rental_listings (
    id                TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    url               TEXT NOT NULL UNIQUE,
    title             TEXT,
    rent_eur          REAL NOT NULL,
    size_m2           REAL NOT NULL,
    rooms             REAL,
    district          TEXT,
    rent_key          TEXT,
    energies_included INTEGER DEFAULT 0,
    furnished         TEXT,
    scraped_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    is_active         INTEGER DEFAULT 1,
    market            TEXT NOT NULL DEFAULT 'sk',
    currency          TEXT NOT NULL DEFAULT 'EUR'
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  TEXT NOT NULL,
    price_eur   REAL NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_listing
    ON price_history(listing_id, observed_at);

CREATE TABLE IF NOT EXISTS deal_stages (
    listing_id  TEXT PRIMARY KEY,
    stage       TEXT NOT NULL,
    note        TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deal_stage_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  TEXT NOT NULL,
    stage       TEXT NOT NULL,
    note        TEXT,
    changed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contract_drafts (
    id              TEXT PRIMARY KEY,
    listing_id      TEXT NOT NULL,
    ownership_type  TEXT NOT NULL,
    agreed_price    REAL,
    buyer_name      TEXT,
    buyer_ico       TEXT,
    seller_name     TEXT,
    notary_name     TEXT,
    draft_text      TEXT,
    generated_at    TEXT,
    status          TEXT DEFAULT 'DRAFT'
);

CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    listing_id  TEXT NOT NULL,
    note        TEXT NOT NULL,
    vibe_score  INTEGER,
    created_at  TEXT
);

-- One row while pipeline work runs — the scheduler's daily run or a dashboard
-- button — so the two never scrape or check LVs at the same time. The holder
-- refreshes heartbeat_at while it works; a row whose heartbeat has stopped
-- belonged to a process that died and is taken over. See
-- modules/pipeline_state.
CREATE TABLE IF NOT EXISTS pipeline_lock (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    holder        TEXT NOT NULL,
    token         TEXT NOT NULL,
    acquired_at   TEXT NOT NULL,
    heartbeat_at  TEXT NOT NULL
);

-- The text of a flat's výpis z LV, pasted on its card (a Czech listing: the
-- cadastre's free services don't give an LV's contents to a program — see
-- modules/lv_cz). One per listing; the LV check screens it.
CREATE TABLE IF NOT EXISTS lv_documents (
    listing_id    TEXT PRIMARY KEY,
    lv_text       TEXT NOT NULL,
    added_at      TEXT NOT NULL
);

-- Flat rates (daň z bytov, €/m² a year) read from the towns' own sites by the
-- dashboard's update button (modules/tax_rates). engine/property_tax_sk uses
-- them on top of its table. One per town and first tax year it applies to.
CREATE TABLE IF NOT EXISTS property_tax_rates (
    town          TEXT NOT NULL,       -- folded: 'banska bystrica'
    name          TEXT NOT NULL,       -- 'Banská Bystrica'
    tax_year      INTEGER NOT NULL,
    rate          REAL NOT NULL,
    source_url    TEXT,
    document      TEXT,
    excerpt       TEXT,                -- the words the rate was read from
    origin        TEXT NOT NULL,       -- scraped / accepted / upload
    saved_at      TEXT NOT NULL,
    PRIMARY KEY (town, tax_year)
);

-- The last check of each town: what its site said and what was done with it.
CREATE TABLE IF NOT EXISTS property_tax_checks (
    town          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL,       -- confirmed / applied / upcoming / new / review /
                                       -- kept / not_found / blocked
    message       TEXT,
    rates         TEXT,                -- JSON list: the flat rates the source states
    tax_year      INTEGER,
    source_url    TEXT,
    document      TEXT,
    excerpt       TEXT,
    detail        TEXT,                -- JSON: problems, pages read, an upcoming rate
    checked_at    TEXT NOT NULL
);

-- Every Slovak municipality with its official website (Wikidata), for the
-- rates of the ones not in TOWNS — refreshed once a month.
CREATE TABLE IF NOT EXISTS sk_municipalities (
    key           TEXT PRIMARY KEY,    -- its name, or "Porúbka (okres Žilina)" when shared
    name          TEXT NOT NULL,
    okres         TEXT,
    web           TEXT,
    population    INTEGER,
    refreshed_at  TEXT NOT NULL
);

-- Towns a user added, with the page the search starts from.
CREATE TABLE IF NOT EXISTS property_tax_sources (
    name          TEXT PRIMARY KEY,
    start_url     TEXT NOT NULL,
    added_at      TEXT NOT NULL
);

-- Czechia (modules/tax_rates_cz): every municipality's population on
-- 1 January (Czech Statistical Office), …
CREATE TABLE IF NOT EXISTS cz_population (
    code          TEXT NOT NULL,       -- kód obce
    year          INTEGER NOT NULL,
    name          TEXT NOT NULL,
    okres         TEXT,                -- its district: tells same-named ones apart
    population    INTEGER NOT NULL,
    PRIMARY KEY (code, year)
);

-- … each ordinance on the coefficients read from sbirkapp.gov.cz once (a
-- published ordinance never changes), …
CREATE TABLE IF NOT EXISTS cz_ordinances (
    id            TEXT PRIMARY KEY,    -- the collection's id, SPP…
    ico           TEXT,
    publisher     TEXT,
    number        TEXT,
    title         TEXT,
    published     TEXT,
    effective     TEXT,
    parsed        TEXT,                -- JSON: what it sets for flats
    problem       TEXT,                -- why it couldn't be read
    fetched_at    TEXT NOT NULL
);

-- … the municipality behind each publisher's IČO (ARES), …
CREATE TABLE IF NOT EXISTS cz_ico (
    ico           TEXT PRIMARY KEY,
    code          TEXT,
    name          TEXT,
    district      TEXT
);

-- … and what a flat pays there: the size and local coefficients by area
-- ("" for the municipality's main part), per tax year.
CREATE TABLE IF NOT EXISTS property_tax_cz (
    code          TEXT NOT NULL,
    tax_year      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    okres         TEXT,
    population    INTEGER,
    size          TEXT NOT NULL,       -- JSON {area: coefficient}
    local         TEXT NOT NULL,       -- JSON {area: coefficient}
    sources       TEXT,                -- JSON list of the ordinances used
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (code, tax_year)
);
"""


def _ensure_dev_project_column(conn):
    """Add is_dev_project column to existing DBs that pre-date this column.
    Safe no-op when the column already exists."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(listings)")]
    if "is_dev_project" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN is_dev_project INTEGER DEFAULT 0")
        conn.commit()


# New cashflow_scores columns added with the P1 model overhaul (NOI/cap rate,
# amortization split, total return, acquisition costs). ALTER existing DBs so
# upsert_cashflow's INSERT doesn't fail on a missing column.
_CASHFLOW_NEW_COLUMNS = {
    "management_monthly":        "REAL",
    "noi_monthly":               "REAL",
    "cap_rate":                  "REAL",
    "principal_paydown_monthly": "REAL",
    "total_return_annual":       "REAL",
    "total_roi":                 "REAL",
    "acquisition_costs":         "REAL",
    "total_cash_invested":       "REAL",
    "regional_median_m2":        "REAL",
    "market_discount":           "REAL",
    # Deal extras (engine.financial.deal_extras) and the rent's provenance.
    "max_price_green":           "REAL",
    "max_price_yellow":          "REAL",
    "stress_surplus_sro":        "REAL",
    "stress_ratio_sro":          "REAL",
    "irr_sro":                   "REAL",
    "irr_personal":              "REAL",
    "rent_source":               "TEXT",
    # The s.r.o.'s own loan and running cost (engine.financial.sro_financing),
    # the rent key the estimate came from (a kraj fallback or "default" is
    # flagged on the card), the tax table and the model the score was worked
    # out with (requeue_scores_from_older_model).
    "sro_rate_used":             "REAL",
    "sro_ltv_used":              "REAL",
    "mortgage_monthly_sro":      "REAL",
    "total_cash_invested_sro":   "REAL",
    "sro_running_cost_monthly":  "REAL",
    "rent_key":                  "TEXT",
    "tax_year":                  "INTEGER",
    "model_version":             "INTEGER",
}


def _ensure_cashflow_columns(conn):
    """Add P1 cashflow_scores columns to pre-existing DBs. No-op when present.

    A DB that predates market_discount holds classes from the old
    self-funding-ratio rule (see config.py, Classification Thresholds), so its
    scores are dropped once, when the column arrives; the next 💰 CASHFLOW
    SCORE run reclassifies every listing against the regional median."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(cashflow_scores)")]
    for name, sqltype in _CASHFLOW_NEW_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE cashflow_scores ADD COLUMN {name} {sqltype}")
    if cols and "market_discount" not in cols:
        n = conn.execute("DELETE FROM cashflow_scores").rowcount
        conn.execute(
            "UPDATE listings SET classification='PENDING' "
            "WHERE classification IN ('GREEN','YELLOW','WHITE')")
        if n:
            log.info(f"♻️  Cleared {n} cashflow scores classed by the old self-funding "
                     f"rule — run 💰 CASHFLOW SCORE to reclassify against the "
                     f"regional median.")
    elif cols and any(c not in cols for c in _DEAL_EXTRA_COLUMNS):
        # Scores from before max offer, the rate-shock stress test and IRR
        # existed. get_unscored_cashflow() never looks at a scored row again,
        # so without this they would show blanks for those figures for good.
        # Dropped once: the columns exist from here on.
        n = conn.execute("DELETE FROM cashflow_scores").rowcount
        conn.execute(
            "UPDATE listings SET classification='PENDING' "
            "WHERE classification IN ('GREEN','YELLOW','WHITE')")
        if n:
            log.info(f"♻️  Cleared {n} cashflow scores from before max offer, stress "
                     f"test and IRR — run 💰 CASHFLOW SCORE to fill them in.")
    conn.commit()


# The deal extras (engine.financial.deal_extras). A score row without them
# predates them; see _ensure_cashflow_columns.
_DEAL_EXTRA_COLUMNS = ("max_price_green", "max_price_yellow",
                       "stress_surplus_sro", "stress_ratio_sro",
                       "irr_sro", "irr_personal")


# Optional LLM-enrichment columns on `listings` (modules/llm_enrichment via the
# modules/*_enrichment runners and modules/debt_bot). Each *_parsed/*_normalized
# flag gates the LLM so it's called at most once per listing:
#   - has_parking + furnished feed the rent premium in engine/financial;
#     desc_parsed gates parse_description().
#   - addr_normalized gates normalize_address(), which fills a blank district/
#     city so the rent estimate stops defaulting to the €6.50/m² floor.
#   - lv_risk_level + lv_summary persist modules/debt_bot's Claude analyze_lv
#     read so the dashboard can show WHY a title deed passed/failed.
#   - detail_enriched_at records when a scraper last opened the listing's own
#     detail page. Scrapers read it back via get_fresh_detail_urls() to skip
#     re-opening pages they already have full data for (see that docstring).
#   - coords_source says where lat/lng came from: 'listing' (the portal's own
#     map pin, which modules/debt_bot resolves to a building parcel) or
#     'geocode' (Google's guess from the address — a street or district
#     centroid, never good enough to pick a parcel).
#   - cadastral_unit_code / plot_lv_number: the katastrálne územie code and
#     the LV of the building plot found under the map pin. The plot's LV is
#     NOT the flat's title deed; lv_number is the flat's own LV, entered by
#     hand, and the only thing that can verify a flat.
#   - lv_detail / lv_checked_at: the last LV check's reason and time.
_ENRICHMENT_COLUMNS = {
    "has_parking":        "INTEGER",
    "has_balcony":        "INTEGER",
    "furnished":          "TEXT",
    "condition":          "TEXT",
    "desc_parsed":        "INTEGER DEFAULT 0",
    "addr_normalized":    "INTEGER DEFAULT 0",
    "lv_risk_level":      "TEXT",
    "lv_summary":         "TEXT",
    "detail_enriched_at": "TEXT",
    "coords_source":      "TEXT",
    "cadastral_unit_code": "TEXT",
    "plot_lv_number":     "TEXT",
    "lv_number":          "TEXT",
    "lv_detail":          "TEXT",
    "lv_checked_at":      "TEXT",
    # Further description facts (modules/description_enrichment). floor
    # already exists and is filled only when the scraper left it empty.
    "building_floors":    "INTEGER",
    "has_elevator":       "INTEGER",
    "has_cellar":         "INTEGER",
    "has_terrace":        "INTEGER",
    "has_loggia":         "INTEGER",
    # Cross-portal duplicates (mark_duplicates): every member of a group
    # carries the id of the group's primary listing; singletons stay NULL.
    # dup_lv_failed marks a listing whose copy on another portal (or under
    # another agency) was LV-rejected.
    "dup_group":          "TEXT",
    "dup_lv_failed":      "INTEGER",
    # The soft flags (utility easement, a municipality's pre-emption right)
    # on the flat's own LV at its last check — shown, not rejected.
    "lv_soft_flags":      "TEXT",
    # When Location IQ last failed to geocode the listing (no row written):
    # get_unscored_location puts it behind every listing not yet tried.
    "location_tried_at":  "TEXT",
}


def _ensure_enrichment_columns(conn):
    """Add optional LLM-enrichment columns to pre-existing DBs. No-op when present."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(listings)")]
    for name, sqltype in _ENRICHMENT_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {name} {sqltype}")
    conn.commit()


# Location-risk provenance (modules/risk_data). construction_detail is in the
# original schema; the rest arrived with the real noise/flood/construction data.
_LOCATION_NEW_COLUMNS = {
    "construction_detail": "TEXT",
    "noise_detail":        "TEXT",
    "flood_detail":        "TEXT",
    "geo_precision":       "TEXT",
    "risk_checked_at":     "TEXT",
}


def _ensure_location_columns(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(location_scores)")]
    for name, sqltype in _LOCATION_NEW_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE location_scores ADD COLUMN {name} {sqltype}")
    conn.commit()


def _ensure_rent_comps_columns(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(rent_comps)")]
    if "eur_per_m2" not in cols:
        conn.execute("ALTER TABLE rent_comps ADD COLUMN eur_per_m2 REAL")
    conn.commit()
    if cols and "market" not in cols:
        _rebuild_rent_comps_with_market(conn)


_RENT_COMPS_COLS = ("id, district, city, size_band, avg_rent_eur, median_rent_eur, "
                    "sample_count, source, updated_at, eur_per_m2")


def _rebuild_rent_comps_with_market(conn):
    """rent_comps was unique per (district, size band); with two markets it
    is unique per (market, district, size band), and SQLite can't widen a
    UNIQUE constraint in place. The table is recreated and every row copied
    across as Slovak — every comp before the Czech market was one."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(rent_comps)")]
        if "market" in cols:            # another process got here first
            conn.rollback()
            return
        conn.execute("ALTER TABLE rent_comps RENAME TO rent_comps_pre_market")
        conn.execute("""
            CREATE TABLE rent_comps (
                id              TEXT PRIMARY KEY,
                district        TEXT NOT NULL,
                city            TEXT,
                size_band       TEXT NOT NULL,
                avg_rent_eur    REAL,
                median_rent_eur REAL,
                sample_count    INTEGER,
                source          TEXT,
                updated_at      TEXT,
                eur_per_m2      REAL,
                market          TEXT NOT NULL DEFAULT 'sk',
                UNIQUE(market, district, size_band)
            )""")
        conn.execute(f"INSERT INTO rent_comps ({_RENT_COMPS_COLS}, market) "
                     f"SELECT {_RENT_COMPS_COLS}, 'sk' FROM rent_comps_pre_market")
        conn.execute("DROP TABLE rent_comps_pre_market")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


# ── Markets (markets.py) ──────────────────────────────────────────────────────
# Every listing and rental belongs to one market. Rows from before the Czech
# market have none, and the migration gives them 'sk' (and 'EUR'): they were
# all Slovak, and nothing else about them changes.
_MARKET_COLUMNS = {
    "market":   "TEXT NOT NULL DEFAULT 'sk'",
    "currency": "TEXT NOT NULL DEFAULT 'EUR'",
}


def _ensure_market_columns(conn):
    """Add market / currency to listings and rental_listings on a database
    that predates them. Idempotent; every existing row keeps its data and
    reads as Slovak (EUR)."""
    for table in ("listings", "rental_listings"):
        if not _has_table(conn, table):
            continue
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        for name, sqltype in _MARKET_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}")
    conn.commit()


def _market_sql(conn, market, alias: str = "") -> tuple[str, tuple]:
    """(" AND <alias>market = ?", (market,)) to keep a query to one market,
    or ("", ()) for all of them (market None). A table without the column
    holds only Slovak rows — the column is added when the filter needs it."""
    if market is None:
        return "", ()
    _ensure_market_columns(conn)
    import markets
    return f" AND {alias}market = ?", (markets.normalize(market),)


def _market_kw(market) -> dict:
    """{"market": m} for an engine call about a row of another market than
    Slovakia, {} for a Slovak one — the engine's own default — so a Slovak
    row makes exactly the call it always did."""
    import markets
    m = markets.normalize(market)
    return {} if m == "sk" else {"market": m}


def _backfill_listing_coords(conn):
    """One-time repair: copy lat/lng from existing location_scores rows onto
    their listings. upsert_location now mirrors coordinates as it writes, but
    rows scored before that fix left listings.lat/lng NULL — and the satellite
    view / MAPS buttons read the listing columns. Idempotent (fills NULLs only).
    Those coordinates were geocoded from the address, so they're marked so."""
    _ensure_enrichment_columns(conn)
    conn.execute("""
        UPDATE listings SET
            lat = (SELECT lc.lat FROM location_scores lc WHERE lc.listing_id = listings.id),
            lng = (SELECT lc.lng FROM location_scores lc WHERE lc.listing_id = listings.id),
            coords_source = 'geocode'
        WHERE lat IS NULL
          AND EXISTS (SELECT 1 FROM location_scores lc
                      WHERE lc.listing_id = listings.id AND lc.lat IS NOT NULL)
    """)
    conn.commit()


def _mark_legacy_lv_passes_unverified(conn) -> int:
    """Relabel LV 'PASS' rows written before UNVERIFIED existed.

    The debt filter used to store PASS for every listing it could not check —
    which was every listing, since none carried parcel data — and the
    dashboard showed each as ✅ CLEAN. A PASS now always comes with an
    lv_checked_at stamp, so an unstamped one is one of those. Idempotent.
    """
    n = conn.execute(
        "UPDATE listings SET lv_status='UNVERIFIED', "
        "lv_detail=COALESCE(lv_detail, 'No title deed was read (checked before "
        "parcel lookup existed).') "
        "WHERE lv_status IN ('PASS', 'CLEAN') AND lv_checked_at IS NULL"
    ).rowcount
    conn.commit()
    return n


def _rescreen_lv_passes(conn) -> int:
    """Send the Slovak LV verdicts an older version of the rules could have
    got wrong back to the LV check, once per new rules version
    (modules.lv_screen.RULES_VERSION). Each keeps its flat LV number, so the
    next LV DEBT FILTER reads it again. Idempotent.

    - version 2 added transfer bans, which the screen used to pass as clean:
      every PASS is checked again;
    - version 3 made the owners' statutory lien (§ 15 of Act 182/1993) a soft
      flag: every flat rejected on a lien is checked again."""
    from modules.lv_screen import RULES_VERSION
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
    row = conn.execute("SELECT value FROM app_state WHERE key = 'lv_rules_sk'").fetchone()
    stored = int(row[0]) if row else 0
    if stored >= RULES_VERSION:
        return 0
    n = 0
    if stored < 2:
        n += conn.execute(
            "UPDATE listings SET lv_status = 'PENDING', "
            "lv_detail = 'Checked again under updated LV rules (transfer bans).' "
            "WHERE lv_status IN ('PASS', 'CLEAN') AND COALESCE(market, 'sk') = 'sk'"
        ).rowcount
    if stored < 3 and _has_table(conn, "rejections_log"):
        n += conn.execute(
            "UPDATE listings SET lv_status = 'PENDING', "
            "lv_detail = 'Checked again under updated LV rules (the owners'' statutory "
            "lien no longer rejects).' "
            "WHERE lv_status = 'REJECTED' AND COALESCE(market, 'sk') = 'sk' "
            "AND id IN (SELECT listing_id FROM rejections_log WHERE reason = 'záložné právo')"
        ).rowcount
    conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('lv_rules_sk', ?)",
                 (str(RULES_VERSION),))
    return n


def init_db():
    conn = _db.get_conn()
    try:
        conn.executescript(SQLITE_SCHEMA)
        _ensure_dev_project_column(conn)
        _ensure_cashflow_columns(conn)
        _ensure_enrichment_columns(conn)
        _ensure_location_columns(conn)
        _ensure_rent_comps_columns(conn)
        _ensure_market_columns(conn)
        from database.portal_runs import _ensure_portal_runs
        _ensure_portal_runs(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_market "
                     "ON listings(market, is_active)")
        _backfill_listing_coords(conn)
        _mark_legacy_lv_passes_unverified(conn)
        _rescreen_lv_passes(conn)
        # rent_comps used to be seeded with hand-typed 'baseline_2026' rows
        # (invented sample counts, never read). The table now holds only live
        # comps built from scraped rentals (engine/rent_comps), so the seed rows
        # go — anything in it is real.
        conn.execute("DELETE FROM rent_comps WHERE source='baseline_2026'")
        conn.commit()
    finally:
        conn.close()
    log.debug("✅ Database ready.")   # the dashboard calls this on every rerun


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None

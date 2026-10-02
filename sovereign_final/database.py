"""
database.py — Sovereign Investor Dashboard
Handles both PostgreSQL (Docker) and SQLite (local fallback).
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from config import DATABASE_URL, USE_SQLITE_FALLBACK, SQLITE_PATH


# ── Connection ────────────────────────────────────────────────────────────────
def get_conn():
    if USE_SQLITE_FALLBACK:
        os.makedirs("data", exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    else:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn


def is_postgres():
    return not USE_SQLITE_FALLBACK


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
    notes             TEXT
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
    market_value_eur      REAL,
    discount_to_market    REAL,
    stress_surplus_sro    REAL,
    stress_ratio_sro      REAL,
    stress_classification TEXT,
    irr_sro               REAL,
    irr_personal          REAL,
    rent_source           TEXT
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
    UNIQUE(district, size_band)
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
    is_active         INTEGER DEFAULT 1
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
    pdf_path        TEXT,
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
"""

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


def detect_dev_project(url: str, title: str) -> int:
    """Return 1 if URL or title indicates this is a multi-unit dev project,
    else 0. Conservative: returns 0 on ambiguous input rather than risk
    false-positives on real apartments."""
    u = (url or "").lower()
    if any(marker in u for marker in _DEV_PROJECT_URL_MARKERS):
        return 1
    t = (title or "").lower()
    if any(marker in t for marker in _DEV_PROJECT_TITLE_MARKERS):
        return 1
    return 0


def _ensure_dev_project_column(conn):
    """Add is_dev_project column to existing DBs that pre-date this column.
    Safe no-op when the column already exists."""
    if not USE_SQLITE_FALLBACK:
        return
    cols = [row[1] for row in conn.execute("PRAGMA table_info(listings)")]
    if "is_dev_project" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN is_dev_project INTEGER DEFAULT 0")
        conn.commit()


def backfill_dev_project_flags() -> int:
    """Run detect_dev_project on every active listing and update is_dev_project.
    Returns the number of rows newly flagged as dev projects."""
    conn = get_conn()
    try:
        _ensure_dev_project_column(conn)
        rows = conn.execute(
            "SELECT id, url, title FROM listings WHERE is_dev_project=0"
        ).fetchall()
        flagged = []
        for r in rows:
            if detect_dev_project(r[1] or "", r[2] or ""):
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
    # Deal extras (engine.financial.deal_extras) and the rent's provenance.
    "max_price_green":           "REAL",
    "max_price_yellow":          "REAL",
    "market_value_eur":          "REAL",
    "discount_to_market":        "REAL",
    "stress_surplus_sro":        "REAL",
    "stress_ratio_sro":          "REAL",
    "stress_classification":     "TEXT",
    "irr_sro":                   "REAL",
    "irr_personal":              "REAL",
    "rent_source":               "TEXT",
}


def _ensure_cashflow_columns(conn):
    """Add P1 cashflow_scores columns to pre-existing DBs. No-op when present."""
    if not USE_SQLITE_FALLBACK:
        return
    cols = [row[1] for row in conn.execute("PRAGMA table_info(cashflow_scores)")]
    for name, sqltype in _CASHFLOW_NEW_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE cashflow_scores ADD COLUMN {name} {sqltype}")
    conn.commit()


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
    # Further description facts (modules/description_enrichment). floor
    # already exists and is filled only when the scraper left it empty.
    "building_floors":    "INTEGER",
    "has_elevator":       "INTEGER",
    "has_cellar":         "INTEGER",
    "has_terrace":        "INTEGER",
    "has_loggia":         "INTEGER",
    # Cross-portal duplicates (mark_duplicates): every member of a group
    # carries the id of the group's primary listing; singletons stay NULL.
    "dup_group":          "TEXT",
}


def _ensure_enrichment_columns(conn):
    """Add optional LLM-enrichment columns to pre-existing DBs. No-op when present."""
    if not USE_SQLITE_FALLBACK:
        return
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
    if not USE_SQLITE_FALLBACK:
        return
    cols = [row[1] for row in conn.execute("PRAGMA table_info(location_scores)")]
    for name, sqltype in _LOCATION_NEW_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE location_scores ADD COLUMN {name} {sqltype}")
    conn.commit()


def _ensure_rent_comps_columns(conn):
    if not USE_SQLITE_FALLBACK:
        return
    cols = [row[1] for row in conn.execute("PRAGMA table_info(rent_comps)")]
    if "eur_per_m2" not in cols:
        conn.execute("ALTER TABLE rent_comps ADD COLUMN eur_per_m2 REAL")
    conn.commit()


def _backfill_listing_coords(conn):
    """One-time repair: copy lat/lng from existing location_scores rows onto
    their listings. upsert_location now mirrors coordinates as it writes, but
    rows scored before that fix left listings.lat/lng NULL — and the satellite
    view / MAPS buttons read the listing columns. Idempotent (fills NULLs only)."""
    conn.execute("""
        UPDATE listings SET
            lat = (SELECT lc.lat FROM location_scores lc WHERE lc.listing_id = listings.id),
            lng = (SELECT lc.lng FROM location_scores lc WHERE lc.listing_id = listings.id)
        WHERE lat IS NULL
          AND EXISTS (SELECT 1 FROM location_scores lc
                      WHERE lc.listing_id = listings.id AND lc.lat IS NOT NULL)
    """)
    conn.commit()


def init_db():
    conn = get_conn()
    if USE_SQLITE_FALLBACK:
        conn.executescript(SQLITE_SCHEMA)
        _ensure_dev_project_column(conn)
        _ensure_cashflow_columns(conn)
        _ensure_enrichment_columns(conn)
        _ensure_location_columns(conn)
        _ensure_rent_comps_columns(conn)
        _backfill_listing_coords(conn)
        # rent_comps used to be seeded with hand-typed 'baseline_2026' rows
        # (invented sample counts, never read). The table now holds only live
        # comps built from scraped rentals (engine/rent_comps), so the seed
        # rows go — anything in it is real.
        conn.execute("DELETE FROM rent_comps WHERE source='baseline_2026'")
        conn.commit()
    else:
        # PostgreSQL — schema already applied via docker-entrypoint
        pass
    conn.close()
    print("✅ Database ready.")


# ── Query Helpers ─────────────────────────────────────────────────────────────
def get_all_active():
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.*,
               c.classification        AS cf_class,
               c.surplus_personal,     c.surplus_sro,
               c.ratio_personal,       c.ratio_sro,
               c.cash_on_cash,         c.net_rental_yield,
               c.gross_yield,          c.optimal_structure,
               c.noi_monthly,          c.cap_rate,
               c.principal_paydown_monthly, c.total_return_annual,
               c.total_roi,            c.total_cash_invested,
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
               c.market_value_eur,     c.discount_to_market,
               c.stress_surplus_sro,   c.stress_ratio_sro,
               c.stress_classification,
               c.irr_sro,              c.irr_personal, c.rent_source,
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
        WHERE l.is_active = 1 AND l.lv_status != 'REJECTED'
        ORDER BY c.surplus_sro DESC NULLS LAST
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rejected():
    """Every LV rejection with its reason, newest first. A listing re-verified
    and rejected twice appears twice — each row is one decision."""
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.address_raw, l.url, l.source,
                   l.price_eur, l.size_m2, l.scraped_at, l.is_active,
                   l.lv_status, l.lv_risk_level, l.lv_summary,
                   r.reason, r.detail, r.module, r.flagged_at
            FROM listings l
            JOIN rejections_log r ON l.id = r.listing_id
            ORDER BY r.flagged_at DESC
        """).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ── Cross-portal duplicates ──────────────────────────────────────────────────
def mark_duplicates() -> int:
    """Group copies of the same flat across portals (engine.duplicates) and
    store each member's primary id in listings.dup_group. Re-run from scratch
    every time, so a copy that went inactive or changed price leaves its
    group. Returns the number of listings that are part of a group."""
    from engine.duplicates import group_duplicates
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = [dict(r) for r in conn.execute("""
            SELECT id, url, source, district, size_m2, price_eur, rooms, floor,
                   scraped_at
            FROM listings
            WHERE is_active = 1 AND lv_status != 'REJECTED'
              AND price_eur > 0 AND size_m2 > 0
              AND (is_dev_project IS NULL OR is_dev_project = 0)
        """).fetchall()]
        groups = group_duplicates(rows)
        conn.execute("UPDATE listings SET dup_group = NULL WHERE dup_group IS NOT NULL")
        for lid, primary in groups.items():
            conn.execute("UPDATE listings SET dup_group=? WHERE id=?", (primary, lid))
        conn.commit()
    finally:
        conn.close()
    return len(groups)


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
    conn = get_conn()
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
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT listing_id, stage, note, updated_at FROM deal_stages").fetchall()
    finally:
        conn.close()
    return {r["listing_id"]: dict(r) for r in rows}


def get_deal_stage_history(listing_id: str) -> list[dict]:
    conn = get_conn()
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
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.url, l.source, l.price_eur,
                   l.size_m2, l.is_active, l.scraped_at,
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
    conn = get_conn()
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
    conn = get_conn()
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


# ── Rental listings (live rent comps) ────────────────────────────────────────
def upsert_rental(data: dict) -> None:
    """Store one prenájom listing for engine/rent_comps. Keyed on url; a
    re-seen rental refreshes its rent and last_seen_at."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO rental_listings
            (id, source, url, title, rent_eur, size_m2, rooms, district, rent_key,
             energies_included, furnished, scraped_at, last_seen_at, is_active)
            VALUES
            (:id,:source,:url,:title,:rent_eur,:size_m2,:rooms,:district,:rent_key,
             :energies_included,:furnished,:scraped_at,:last_seen_at,1)
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


def get_stats():
    conn = get_conn()
    r = conn.execute("""
        SELECT
            COUNT(*)                                       AS total,
            SUM(CASE WHEN classification='GREEN'    THEN 1 ELSE 0 END) AS green,
            SUM(CASE WHEN classification='YELLOW'   THEN 1 ELSE 0 END) AS yellow,
            SUM(CASE WHEN classification='WHITE'    THEN 1 ELSE 0 END) AS white,
            SUM(CASE WHEN lv_status='REJECTED'      THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN classification='PENDING'  THEN 1 ELSE 0 END) AS pending
        FROM listings WHERE is_active=1
    """).fetchone()
    conn.close()
    return dict(r) if r else {"total":0,"green":0,"yellow":0,"white":0,"rejected":0,"pending":0}


def deactivate_stale_listings(days: int = 21) -> int:
    """Mark listings as inactive when last_seen_at is older than `days` days.

    Each scraper run touches last_seen_at on every listing it sees, so any
    listing not re-seen for ~3 weeks has likely been removed from the source
    site (sold, withdrawn, or expired). Keeping them active inflates GREEN
    counts and shows the user listings that no longer exist.

    Returns the number of rows deactivated.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_conn()
    try:
        n = conn.execute(
            "UPDATE listings SET is_active=0 "
            "WHERE is_active=1 AND last_seen_at < ?",
            (cutoff,),
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
    conn = get_conn()
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
    conn = get_conn()
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
    conn = get_conn()
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
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        _ensure_price_history(conn)
        # A repair corrects a misread, so the misread was never an asking
        # price: the history restarts from the corrected value (or empties),
        # instead of reporting the correction as a price cut.
        clear_price_history(conn, [listing_id])
        if price_eur and price_eur > 0:
            n = conn.execute(
                "UPDATE listings SET price_eur=? WHERE id=?",
                (float(price_eur), listing_id),
            ).rowcount
            if n:
                _record_price(conn, listing_id, float(price_eur))
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
    conn = get_conn()
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
    conn = get_conn()
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


def clear_cashflow_scores() -> int:
    """Delete all cashflow scores and reset scored listings back to PENDING so
    the next 💰 CASHFLOW SCORE run re-scores every listing from scratch.

    Needed whenever the engine's assumptions change (RENT_PER_M2, tax rates,
    mortgage rate, cost model) — get_unscored_cashflow() only picks up listings
    with no existing score, so without this the updated figures never reach
    already-scored rows. Returns the number of score rows removed.
    """
    conn = get_conn()
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


def clear_price_history(conn, listing_ids) -> int:
    """Forget the recorded prices of listings whose price turned out to be a
    misread (a neighbouring listing's, or a deposit). Takes the caller's
    connection; the caller commits."""
    ids = [i for i in (listing_ids or []) if i]
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    return conn.execute(
        f"DELETE FROM price_history WHERE listing_id IN ({ph})", ids
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


def get_price_history(listing_ids=None) -> dict:
    """summarize_price_history for every listing (or just `listing_ids`)."""
    conn = get_conn()
    try:
        _ensure_price_history(conn)
        if listing_ids:
            ids = list(listing_ids)
            ph = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT listing_id, price_eur, observed_at FROM price_history "
                f"WHERE listing_id IN ({ph}) ORDER BY listing_id, observed_at, id",
                ids).fetchall()
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
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT l.id, l.title, l.district, l.url, l.source, l.price_eur,
                   l.size_m2, l.scraped_at, c.classification AS cf_class,
                   c.max_price_yellow, c.max_price_green
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


def upsert_listing(data: dict):
    conn = get_conn()
    try:
        _ensure_price_history(conn)
        # If a row already exists with this URL (e.g. a prior slug-URL variant
        # that _dedupe_canonical_urls rewrote to the canonical form), reuse its
        # id so ON CONFLICT(id) fires instead of hitting the url UNIQUE constraint.
        existing = conn.execute(
            "SELECT id, district, price_eur, scraped_at FROM listings WHERE url=?",
            (data["url"],)
        ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id, district, price_eur, scraped_at FROM listings WHERE id=?",
                (data["id"],)
            ).fetchone()
        if existing and existing[0] != data["id"]:
            data = {**data, "id": existing[0], "url_hash": existing[0]}
        # Auto-detect dev-project listings from URL + title at insert time.
        data = {**data, "is_dev_project": detect_dev_project(
            data.get("url", ""), data.get("title", ""),
        )}
        conn.execute("""
            INSERT INTO listings
            (id, source, url, url_hash, title, description, price_eur, size_m2,
             rooms, floor, year_built, energy_class, address_raw, district, city,
             primary_image_url, image_urls, classification, lv_status, scraped_at,
             last_seen_at, is_dev_project)
            VALUES
            (:id,:source,:url,:url_hash,:title,:description,:price_eur,:size_m2,
             :rooms,:floor,:year_built,:energy_class,:address_raw,:district,:city,
             :primary_image_url,:image_urls,:classification,:lv_status,:scraped_at,
             :last_seen_at,:is_dev_project)
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
                is_dev_project=CASE WHEN excluded.is_dev_project=1 THEN 1 ELSE is_dev_project END
        """, data)
        # A district arriving for a row that had none: its score is stale.
        if (existing and not (existing[1] or "").strip()
                and (data.get("district") or "").strip()):
            _drop_cashflow_score(conn, data["id"])
        # A new asking price: log it, and re-score at the new price (a cut
        # can turn a WHITE into a YELLOW — that is the alert worth having).
        new_price = data.get("price_eur") or 0
        old_price = (existing[2] or 0) if existing else 0
        if new_price > 0 and new_price != old_price:
            if existing and old_price > 0 and not _has_price_history(conn, data["id"]):
                # Rows from before price history existed: the price being
                # replaced is the first one we ever saw, as of first sight.
                _record_price(conn, data["id"], old_price, existing[3])
            _record_price(conn, data["id"], new_price,
                          data.get("last_seen_at") or data.get("scraped_at"))
            if existing and old_price > 0:
                _drop_cashflow_score(conn, data["id"])
        conn.commit()
    finally:
        conn.close()


def upsert_cashflow(data: dict):
    """Store one listing's score. Columns added after the first schema
    (_CASHFLOW_NEW_COLUMNS) default to NULL when the caller leaves them out."""
    conn = get_conn()
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
         acquisition_costs, total_cash_invested,
         optimal_structure, classification,
         annual_sro_saving, sro_break_even_months,
         scored_at, mortgage_rate_used, ltv_used, loan_term_years,
         max_price_green, max_price_yellow, market_value_eur, discount_to_market,
         stress_surplus_sro, stress_ratio_sro, stress_classification,
         irr_sro, irr_personal, rent_source)
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
         :acquisition_costs,:total_cash_invested,
         :optimal_structure,:classification,
         :annual_sro_saving,:sro_break_even_months,
         :scored_at,:mortgage_rate_used,:ltv_used,:loan_term_years,
         :max_price_green,:max_price_yellow,:market_value_eur,:discount_to_market,
         :stress_surplus_sro,:stress_ratio_sro,:stress_classification,
         :irr_sro,:irr_personal,:rent_source)
    """, {**dict.fromkeys(_CASHFLOW_NEW_COLUMNS), **data})
    conn.execute(
        "UPDATE listings SET classification=? WHERE id=?",
        (data["classification"], data["listing_id"])
    )
    conn.commit()
    conn.close()


def upsert_location(data: dict):
    conn = get_conn()
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
    # location_scores' lat/lng are not part of that select.
    if data.get("lat") is not None and data.get("lng") is not None:
        conn.execute(
            "UPDATE listings SET lat=:lat, lng=:lng WHERE id=:listing_id", data)
    conn.commit()
    conn.close()


def get_location_rows_missing_risk(limit: int = 100) -> list[dict]:
    """Location rows written before real risk data existed (risk_checked_at
    NULL) for listings still active and LV-clean."""
    conn = get_conn()
    try:
        _ensure_location_columns(conn)
        rows = conn.execute("""
            SELECT lc.listing_id, lc.lat, lc.lng, l.address_raw, l.district
            FROM location_scores lc JOIN listings l ON l.id = lc.listing_id
            WHERE lc.risk_checked_at IS NULL AND l.is_active = 1
              AND l.lv_status = 'PASS'
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_location_risk(listing_id: str, risk: dict) -> None:
    """Write construction / noise / flood answers (and the geocode precision
    they were judged at) onto an existing location row."""
    conn = get_conn()
    try:
        _ensure_location_columns(conn)
        conn.execute("""
            UPDATE location_scores SET
                construction_risk=:construction_risk,
                construction_detail=:construction_detail,
                noise_flag=:noise_flag, noise_detail=:noise_detail,
                flood_zone=:flood_zone, flood_detail=:flood_detail,
                geo_precision=:geo_precision, risk_checked_at=:risk_checked_at
            WHERE listing_id=:listing_id
        """, {**risk, "listing_id": listing_id,
              "risk_checked_at": datetime.now(timezone.utc).isoformat()})
        conn.commit()
    finally:
        conn.close()


def set_lv_status(listing_id: str, status: str, reason: str = "", detail: str = "", module: str = "debt_bot"):
    import uuid
    conn = get_conn()
    conn.execute("UPDATE listings SET lv_status=? WHERE id=?", (status, listing_id))
    if status == "REJECTED":
        conn.execute("""
            INSERT INTO rejections_log (id, listing_id, reason, detail, module, flagged_at)
            VALUES (?,?,?,?,?,?)
        """, (str(uuid.uuid4()), listing_id, reason, detail, module,
              datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def reset_demo_rejections() -> int:
    """Undo rejections fabricated by the old demo LV mode.

    Before the fix in modules/debt_bot.query_lv_api, listings without a
    cadastral parcel number (i.e. all of them) were REJECTED with invented
    "[DEMO] ..." liens — every one sharing the same hash seed — which hid the
    entire dashboard. Flip those rows back to PENDING and drop their fabricated
    rejection-log entries so the next debt-filter run re-checks them honestly.
    Real rejections (no [DEMO] marker) are untouched. Returns rows healed.
    """
    conn = get_conn()
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
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute(
            "UPDATE listings SET lv_risk_level=?, lv_summary=? WHERE id=?",
            (risk_level or None, (summary or "")[:1000] or None, listing_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_lv():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, cadastral_number, cadastral_area, address_raw
        FROM listings WHERE lv_status='PENDING' AND is_active=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unscored_cashflow():
    # SELECT l.* (not an explicit column list) so optional enrichment columns
    # like has_parking / furnished flow through to the scorer when present,
    # without a column-list edit each time the schema grows.
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.*
        FROM listings l
        LEFT JOIN cashflow_scores c ON l.id = c.listing_id
        WHERE l.lv_status != 'REJECTED' AND c.listing_id IS NULL
          AND l.price_eur > 0 AND l.size_m2 > 0 AND l.is_active=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unparsed_descriptions(limit: int = 200):
    """Active listings with a stored free-text description that hasn't been
    parsed into structured features yet. desc_parsed stays 0 until a successful
    parse, so transient enrichment failures get retried on a later run."""
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = conn.execute("""
            SELECT id, description
            FROM listings
            WHERE is_active=1
              AND description IS NOT NULL AND description != ''
              AND (desc_parsed IS NULL OR desc_parsed = 0)
            ORDER BY scraped_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
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
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
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
        conn.commit()
    finally:
        conn.close()


def requeue_descriptions_missing_extras() -> int:
    """Send listings parsed before the building facts (elevator, cellar,
    terrace, floors) were kept back through description enrichment once. The
    parse already returned those facts; they were discarded at the time.
    Returns the number of rows re-queued."""
    conn = get_conn()
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


def get_unnormalized_addresses(limit: int = 200):
    """Active listings that have a raw address but a blank district (so the rent
    estimate falls to the €6.50/m² default) and haven't been normalized yet.
    addr_normalized stays 0 until a normalize_address() call returns (success or
    a definitive empty result), so only transient failures get retried."""
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        rows = conn.execute("""
            SELECT id, address_raw
            FROM listings
            WHERE is_active=1
              AND address_raw IS NOT NULL AND address_raw != ''
              AND (district IS NULL OR district = '')
              AND (addr_normalized IS NULL OR addr_normalized = 0)
            ORDER BY scraped_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
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
    conn = get_conn()
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


def get_unscored_location():
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.id, l.address_raw, l.energy_class, l.district
        FROM listings l
        LEFT JOIN location_scores lc ON l.id = lc.listing_id
        WHERE l.lv_status='PASS' AND lc.listing_id IS NULL AND l.is_active=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()

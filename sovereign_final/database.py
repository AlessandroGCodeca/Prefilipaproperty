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
    tax_year              INTEGER DEFAULT 2026
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
    UNIQUE(district, size_band)
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

RENT_COMPS_SEED = [
    ("bratislava-i-small",   "Bratislava I",   "Bratislava", "small",  850,  820,  312),
    ("bratislava-i-medium",  "Bratislava I",   "Bratislava", "medium", 1150, 1100, 284),
    ("bratislava-i-large",   "Bratislava I",   "Bratislava", "large",  1600, 1500, 189),
    ("bratislava-ii-small",  "Bratislava II",  "Bratislava", "small",  680,  660,  421),
    ("bratislava-ii-medium", "Bratislava II",  "Bratislava", "medium", 900,  880,  389),
    ("bratislava-iii-small", "Bratislava III", "Bratislava", "small",  640,  620,  298),
    ("bratislava-iv-small",  "Bratislava IV",  "Bratislava", "small",  600,  580,  312),
    ("bratislava-iv-medium", "Bratislava IV",  "Bratislava", "medium", 790,  760,  289),
    ("bratislava-v-small",   "Bratislava V",   "Bratislava", "small",  620,  600,  278),
    ("kosice-i-small",       "Košice I",       "Košice",     "small",  480,  460,  412),
    ("kosice-i-medium",      "Košice I",       "Košice",     "medium", 640,  620,  389),
    ("zilina-small",         "Žilina",         "Žilina",     "small",  460,  440,  312),
    ("zilina-medium",        "Žilina",         "Žilina",     "medium", 610,  590,  289),
    ("nitra-small",          "Nitra",          "Nitra",      "small",  420,  400,  289),
    ("nitra-medium",         "Nitra",          "Nitra",      "medium", 560,  540,  267),
    ("trnava-small",         "Trnava",         "Trnava",     "small",  480,  460,  298),
    ("trnava-medium",        "Trnava",         "Trnava",     "medium", 640,  620,  278),
    ("presov-small",         "Prešov",         "Prešov",     "small",  380,  360,  312),
    ("banska-small",         "Banská Bystrica","BB",         "small",  360,  340,  278),
    ("trencin-small",        "Trenčín",        "Trenčín",    "small",  380,  360,  234),
    ("martin-small",         "Martin",         "Martin",     "small",  350,  330,  198),
    ("poprad-small",         "Poprad",         "Poprad",     "small",  340,  320,  187),
]


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
_ENRICHMENT_COLUMNS = {
    "has_parking":     "INTEGER",
    "has_balcony":     "INTEGER",
    "furnished":       "TEXT",
    "condition":       "TEXT",
    "desc_parsed":     "INTEGER DEFAULT 0",
    "addr_normalized": "INTEGER DEFAULT 0",
    "lv_risk_level":   "TEXT",
    "lv_summary":      "TEXT",
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
        _backfill_listing_coords(conn)
        now = datetime.now(timezone.utc).isoformat()
        for row in RENT_COMPS_SEED:
            conn.execute("""
                INSERT OR IGNORE INTO rent_comps
                (id, district, city, size_band, avg_rent_eur, median_rent_eur, sample_count, source, updated_at)
                VALUES (?,?,?,?,?,?,?,'baseline_2026',?)
            """, (*row, now))
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
               lc.location_score,      lc.location_tier,
               lc.nearest_transit_m,   lc.walkability_score,
               lc.industrial_zone,     lc.construction_risk,
               lc.noise_flag,          lc.amenity_count
        FROM listings l
        LEFT JOIN cashflow_scores c  ON l.id = c.listing_id
        LEFT JOIN location_scores lc ON l.id = lc.listing_id
        WHERE l.is_active = 1 AND l.lv_status != 'REJECTED'
        ORDER BY c.surplus_sro DESC NULLS LAST
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rejected():
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.id, l.address_raw, l.url, l.price_eur, l.scraped_at,
               r.reason, r.detail, r.flagged_at
        FROM listings l
        JOIN rejections_log r ON l.id = r.listing_id
        ORDER BY r.flagged_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def upsert_listing(data: dict):
    conn = get_conn()
    try:
        # If a row already exists with this URL (e.g. a prior slug-URL variant
        # that _dedupe_canonical_urls rewrote to the canonical form), reuse its
        # id so ON CONFLICT(id) fires instead of hitting the url UNIQUE constraint.
        existing = conn.execute(
            "SELECT id FROM listings WHERE url=?", (data["url"],)
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
        conn.commit()
    finally:
        conn.close()


def upsert_cashflow(data: dict):
    conn = get_conn()
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
         scored_at, mortgage_rate_used, ltv_used, loan_term_years)
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
         :scored_at,:mortgage_rate_used,:ltv_used,:loan_term_years)
    """, data)
    conn.execute(
        "UPDATE listings SET classification=? WHERE id=?",
        (data["classification"], data["listing_id"])
    )
    conn.commit()
    conn.close()


def upsert_location(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO location_scores
        (listing_id, lat, lng, nearest_transit_m, amenity_count,
         grocery_count, pharmacy_count, school_count,
         construction_risk, noise_flag, flood_zone,
         walkability_score, industrial_zone, industrial_zone_name,
         location_score, location_tier, scored_at)
        VALUES
        (:listing_id,:lat,:lng,:nearest_transit_m,:amenity_count,
         :grocery_count,:pharmacy_count,:school_count,
         :construction_risk,:noise_flag,:flood_zone,
         :walkability_score,:industrial_zone,:industrial_zone_name,
         :location_score,:location_tier,:scored_at)
    """, data)
    # Mirror coordinates onto the listing row — the dashboard (satellite view,
    # MAPS buttons) reads l["lat"]/l["lng"] via get_all_active's l.*, and
    # location_scores' lat/lng are not part of that select.
    if data.get("lat") is not None and data.get("lng") is not None:
        conn.execute(
            "UPDATE listings SET lat=:lat, lng=:lng WHERE id=:listing_id", data)
    conn.commit()
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
    `features` keys: has_parking, has_balcony, furnished, condition, and
    optionally rooms — which only fills in when the listing has none yet
    (structured scraper data outranks the description's phrasing)."""
    conn = get_conn()
    try:
        _ensure_enrichment_columns(conn)
        conn.execute("""
            UPDATE listings SET
                has_parking = ?, has_balcony = ?,
                furnished   = ?, condition   = ?,
                rooms       = COALESCE(rooms, ?),
                desc_parsed = 1
            WHERE id = ?
        """, (
            features.get("has_parking"),
            features.get("has_balcony"),
            features.get("furnished"),
            features.get("condition"),
            features.get("rooms"),
            listing_id,
        ))
        conn.commit()
    finally:
        conn.close()


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
    so an unresolvable address isn't re-sent to the LLM every run.
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

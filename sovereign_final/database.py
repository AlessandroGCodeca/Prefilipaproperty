"""
database.py — Sovereign Investor Dashboard
Handles both PostgreSQL (Docker) and SQLite (local fallback).
"""

import os
import sqlite3
import json
from datetime import datetime, timezone
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
    cash_on_cash          REAL,
    net_rental_yield      REAL,
    gross_yield           REAL,
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


def init_db():
    conn = get_conn()
    if USE_SQLITE_FALLBACK:
        conn.executescript(SQLITE_SCHEMA)
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
               c.estimated_rent_eur,   c.total_costs_personal,
               c.total_costs_sro,      c.annual_sro_saving,
               c.sro_break_even_months,
               c.mortgage_monthly,     c.hoa_monthly,
               c.property_tax_monthly, c.vacancy_cost,
               c.maintenance_monthly,  c.income_tax_personal,
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


def upsert_listing(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO listings
        (id, source, url, url_hash, title, description, price_eur, size_m2,
         rooms, floor, year_built, energy_class, address_raw, district, city,
         primary_image_url, image_urls, classification, lv_status, scraped_at, last_seen_at)
        VALUES
        (:id,:source,:url,:url_hash,:title,:description,:price_eur,:size_m2,
         :rooms,:floor,:year_built,:energy_class,:address_raw,:district,:city,
         :primary_image_url,:image_urls,:classification,:lv_status,:scraped_at,:last_seen_at)
        ON CONFLICT(id) DO UPDATE SET
            last_seen_at=excluded.last_seen_at,
            title=CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,
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
            is_active=1
    """, data)
    conn.commit()
    conn.close()


def upsert_cashflow(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO cashflow_scores
        (listing_id, estimated_rent_eur, mortgage_monthly, hoa_monthly,
         property_tax_monthly, vacancy_cost, maintenance_monthly,
         income_tax_personal, health_levy_personal, total_costs_personal,
         surplus_personal, ratio_personal,
         income_tax_sro, health_levy_sro, total_costs_sro,
         surplus_sro, ratio_sro,
         cash_on_cash, net_rental_yield, gross_yield,
         optimal_structure, classification,
         annual_sro_saving, sro_break_even_months,
         scored_at, mortgage_rate_used, ltv_used, loan_term_years)
        VALUES
        (:listing_id,:estimated_rent_eur,:mortgage_monthly,:hoa_monthly,
         :property_tax_monthly,:vacancy_cost,:maintenance_monthly,
         :income_tax_personal,:health_levy_personal,:total_costs_personal,
         :surplus_personal,:ratio_personal,
         :income_tax_sro,:health_levy_sro,:total_costs_sro,
         :surplus_sro,:ratio_sro,
         :cash_on_cash,:net_rental_yield,:gross_yield,
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


def get_pending_lv():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, cadastral_number, cadastral_area, address_raw
        FROM listings WHERE lv_status='PENDING' AND is_active=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unscored_cashflow():
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.id, l.price_eur, l.size_m2, l.district, l.energy_class
        FROM listings l
        LEFT JOIN cashflow_scores c ON l.id = c.listing_id
        WHERE l.lv_status != 'REJECTED' AND c.listing_id IS NULL
          AND l.price_eur > 0 AND l.size_m2 > 0 AND l.is_active=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

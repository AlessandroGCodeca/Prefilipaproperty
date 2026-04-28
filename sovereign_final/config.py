"""
config.py — Sovereign Investor Dashboard
All tunable constants. Review every January.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_SQLITE_FALLBACK = not DATABASE_URL  # True when no Postgres available

# ── 2026 Slovak Financial Rates ───────────────────────────────────────────────
MORTGAGE_RATE_PA       = 0.034   # 3.4% per annum — NBS average Q1 2026
LOAN_TERM_YEARS        = 25
LTV_RATIO              = 0.80    # 80% financing assumed

# Income tax — Fyzická osoba (personal)
TAX_RATE_PERSONAL_LOW  = 0.19   # 19% up to threshold
TAX_RATE_PERSONAL_HIGH = 0.25   # 25% above threshold
TAX_THRESHOLD_PERSONAL = 41_445 # Annual € threshold 2026

# Income tax — s.r.o.
TAX_RATE_SRO           = 0.21   # 21% corporate flat rate

# Health insurance levy
HEALTH_LEVY_PERSONAL   = 0.16   # 16% on net rental income (FO)
HEALTH_LEVY_SRO        = 0.00   # 0% — company exempt

# Property tax
PROPERTY_TAX_RATE_PA   = 0.004  # ~0.4% of value annually

# Operating cost estimates
HOA_SMALL              = 35     # < 40 m²
HOA_MEDIUM             = 60     # 40–70 m²
HOA_LARGE              = 90     # > 70 m²
HOA_PREMIUM            = 130    # > 120 m²
VACANCY_RATE           = 0.05   # 5%
MAINTENANCE_RATE       = 0.01   # 1% of value annually

# ── Classification Thresholds ─────────────────────────────────────────────────
GREEN_RATIO            = 1.15   # Rent >= 115% of costs
YELLOW_RATIO           = 1.05   # Rent >= 105% of costs

# ── Location Scoring ──────────────────────────────────────────────────────────
TRANSIT_WALK_METERS    = 560    # 7 min walk at 80m/min
AMENITY_RADIUS_METERS  = 800
NOISE_LIMIT_DB         = 65
CONSTRUCTION_RADIUS_M  = 300

POINTS_TRANSIT         = 30
POINTS_AMENITIES       = 20
POINTS_CONSTRUCTION    = 20
POINTS_NOISE           = 20
POINTS_ENERGY          = 10

PRIME_THRESHOLD        = 75
SOLID_THRESHOLD        = 45

# ── Industrial Zones (worker demand premium) ──────────────────────────────────
INDUSTRIAL_ZONES = [
    "žilina", "nitra", "trnava", "voderady", "šurany",
    "bytča", "kysucké nové mesto", "nové mesto nad váhom",
    "košice", "prešov",
]
INDUSTRIAL_RENT_PREMIUM = 1.12  # 12% above base comps

# ── APIs ──────────────────────────────────────────────────────────────────────
GOOGLE_API_KEY    = os.getenv("GOOGLE_PLACES_API_KEY", "")
CADASTRAL_API_KEY = os.getenv("CADASTRAL_API_KEY", "")
FINSTAT_API_KEY   = os.getenv("FINSTAT_API_KEY", "")
DMR_ENDPOINT      = os.getenv("DMR_ENDPOINT", "http://localhost:12434/v1")
LLM_MODEL         = os.getenv("LLM_MODEL", "mistral:7b-instruct-q4_k_m")

# ── Scraper ───────────────────────────────────────────────────────────────────
SCRAPE_DELAY_SEC       = 2.5
CADASTRAL_DELAY_SEC    = 1.5
CADASTRAL_BACKOFF_MAX  = 60

# ── LV Rejection Keywords ─────────────────────────────────────────────────────
LV_REJECT_FLAGS = [
    "záložné právo", "exekúcia", "súdny spor",
    "vecné bremeno", "predkupné právo", "konkurz",
    "zabezpečovacie prevodné právo",
]
LV_BANK_NAMES = [
    "slovenská sporiteľňa", "vúb", "tatra banka", "čsob",
    "prima banka", "unicredit", "oberbank", "hypotekárna banka",
    "365 bank", "mbank",
]

# ── Rent Comps: €/m²/month by district (2026 baseline) ───────────────────────
RENT_PER_M2 = {
    "bratislava i":    14.5,
    "bratislava ii":   11.8,
    "bratislava iii":  11.2,
    "bratislava iv":   10.5,
    "bratislava v":    10.8,
    "košice i":         8.2,
    "košice ii":        7.8,
    "žilina":           7.8,
    "nitra":            7.2,
    "trnava":           8.5,
    "trenčín":          6.8,
    "prešov":           7.0,
    "banská bystrica":  6.8,
    "martin":           6.5,
    "poprad":           6.2,
    "ružomberok":       6.0,
    "liptovský mikuláš":5.8,
    "default":          6.0,
}

# ── s.r.o. Setup Cost Estimate ────────────────────────────────────────────────
SRO_SETUP_COST = 2_500  # Notary + registry + first year accounting

# ── Paths ─────────────────────────────────────────────────────────────────────
SQLITE_PATH    = "data/sovereign.db"
CONTRACTS_DIR  = "contracts"
LOGS_DIR       = "logs"

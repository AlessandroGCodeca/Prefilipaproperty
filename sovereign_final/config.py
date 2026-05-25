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
# ScraperAPI key — bypasses IP blocks on nehnutelnosti/bazos when running
# from a server/cloud environment. Free tier: https://www.scraperapi.com
SCRAPER_API_KEY   = os.getenv("SCRAPER_API_KEY", "")

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
# engine/financial.py uses fuzzy substring matching so partial names resolve:
# "Bratislava - Rača" → "bratislava iv", "okres Žilina" → "žilina" etc.
RENT_PER_M2 = {
    # Bratislava — city-only fallback (used when no district number is known)
    "bratislava":           11.5,   # weighted average across BA I–V
    # Bratislava — administrative districts (override city-only above via exact match)
    "bratislava i":         14.5,
    "bratislava ii":        11.8,
    "bratislava iii":       11.2,
    "bratislava iv":        10.5,
    "bratislava v":         10.8,
    # Bratislava — city parts / suburbs (map to nearest district rate)
    "staré mesto":          13.5,   # BA I
    "ružinov":              11.5,   # BA II
    "vrakuňa":               9.2,   # BA II
    "podunajské":            9.0,   # BA II
    "vajnory":               9.5,   # BA II
    "nové mesto":           10.8,   # BA III (Bratislava Nové Mesto)
    "rača":                 10.0,   # BA III
    "vajnory":               9.5,   # BA III
    "dúbravka":             10.0,   # BA IV
    "karlova ves":          11.0,   # BA IV
    "lamač":                 9.8,   # BA IV
    "záhorská":              9.0,   # BA IV
    "devínska":              9.5,   # BA IV
    "petržalka":            10.5,   # BA V
    "rusovce":               9.2,   # BA V
    "jarovce":               9.0,   # BA V
    "čunovo":                8.8,   # BA V
    # Bratislava-okolie (suburbs)
    "senec":                 8.5,
    "pezinok":               8.8,
    "malacky":               7.5,
    "stupava":               8.0,
    "modra":                 8.0,
    # Trnava region
    "trnava":                8.5,
    "dunajská streda":       7.0,
    "galanta":               6.5,
    "hlohovec":              6.5,
    "piešťany":              7.5,
    "senica":                6.0,
    "skalica":               6.2,
    # Trenčín region
    "trenčín":               7.2,
    "bánovce":               5.8,
    "ilava":                 6.2,
    "myjava":                5.5,
    "nové mesto nad váhom":  6.5,
    "partizánske":           5.8,
    "považská bystrica":     6.5,
    "púchov":                6.5,
    # Nitra region
    "nitra":                 7.2,
    "komárno":               6.2,
    "levice":                6.0,
    "nové zámky":            6.2,
    "šaľa":                  6.2,
    "topoľčany":             5.8,
    "zlaté moravce":         5.8,
    "vráble":                5.5,
    # Žilina region
    "žilina":                8.0,
    "bytča":                 6.5,
    "čadca":                 6.2,
    "kysucké nové mesto":    6.5,
    "liptovský mikuláš":     6.2,
    "námestovo":             5.8,
    "ružomberok":            6.5,
    "turčianske teplice":    5.8,
    "tvrdošín":              5.8,
    # Banská Bystrica region
    "banská bystrica":       7.0,
    "brezno":                5.8,
    "detva":                 5.2,
    "lučenec":               5.8,
    "revúca":                5.2,
    "rimavská sobota":       5.2,
    "veľký krtíš":           5.2,
    "zvolen":                6.5,
    "žiar nad hronom":       6.2,
    "zvolenská":             6.0,
    # Prešov region
    "prešov":                7.2,
    "bardejov":              5.8,
    "humenné":               5.8,
    "kežmarok":              6.0,
    "levoča":                5.8,
    "medzilaborce":          4.8,
    "poprad":                6.5,
    "sabinov":               5.8,
    "snina":                 5.2,
    "stará ľubovňa":         5.8,
    "stropkov":              5.2,
    "vranov nad topľou":     5.8,
    # Košice — city-only fallback
    "košice":                8.0,
    # Košice region
    "košice i":              8.5,
    "košice ii":             8.0,
    "košice iii":            7.8,
    "košice iv":             7.5,
    "košice-okolie":         7.0,
    "gelnica":               5.2,
    "michalovce":            6.2,
    "rožňava":               5.8,
    "sobrance":              5.0,
    "spišská nová ves":      6.2,
    "trebišov":              5.5,
    # Martin area
    "martin":                6.8,
    "turčianske":            6.0,
    # Default — smaller towns not listed above
    "default":               6.0,
}

# ── s.r.o. Setup Cost Estimate ────────────────────────────────────────────────
SRO_SETUP_COST = 2_500  # Notary + registry + first year accounting

# ── Paths ─────────────────────────────────────────────────────────────────────
SQLITE_PATH    = "data/sovereign.db"
CONTRACTS_DIR  = "contracts"
LOGS_DIR       = "logs"

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
# Sources (updated April–May 2026):
#   - Deloitte Rent Index Q4 2025 (via SME/Pravda) — city-level + BA districts
#   - Bencont Group Q1 2026 — Bratislava 17.26 €/m²/mo incl. energies
#   - Pravda Realitný report Feb 2026 — BA city-parts breakdown
#   - Government ASPNB 2026 — regulated rent ceilings per kraj (lower bound check)
#   - trh.sk + nehnutelnosti.sk inzertné štatistiky
#
# Values represent BARE rent (without energies) — what the landlord actually
# receives as income. Lower bound of published ranges to stay conservative for
# cashflow analysis. With-energies figures run ~3–5 €/m²/mo higher.
#
# engine/financial.py uses fuzzy substring matching so partial names resolve:
# "Bratislava - Rača" → "bratislava iv", "okres Žilina" → "žilina" etc.
RENT_PER_M2 = {
    # Bratislava — city-only fallback (used when no district number is known)
    "bratislava":           12.5,   # weighted average across BA I–V
    # Bratislava — administrative districts (override city-only above via exact match)
    "bratislava i":         14.5,   # Staré Mesto
    "bratislava ii":        12.0,   # Ružinov, Vrakuňa, Podunajské Biskupice
    "bratislava iii":       12.0,   # Nové Mesto, Rača, Vajnory
    "bratislava iv":        11.0,   # Karlova Ves, Dúbravka, Devínska, Lamač
    "bratislava v":         11.5,   # Petržalka, Rusovce, Jarovce, Čunovo
    # Bratislava — city parts / suburbs (Q2 2026 lower-bound rates)
    "staré mesto":          14.5,   # BA I — 15–19 €/m² range
    "ružinov":              13.5,   # BA II — 14–17 €/m² range
    "vrakuňa":              10.0,   # BA II — 10–12 €/m² range
    "podunajské":           10.0,   # BA II — 10–12 €/m² range
    "vajnory":              10.0,   # BA III
    "nové mesto":           13.0,   # BA III — 13–16 €/m² range
    "rača":                 11.0,   # BA III — 11–13 €/m² range
    "dúbravka":             11.5,   # BA IV — 11–14 €/m² range
    "karlova ves":          12.0,   # BA IV — 12–14 €/m² range
    "lamač":                10.5,   # BA IV
    "záhorská":             10.0,   # BA IV
    "devínska":             10.0,   # BA IV — 10–12 €/m² range
    "petržalka":            12.0,   # BA V — 12–15 €/m² range
    "rusovce":              10.0,   # BA V
    "jarovce":              10.0,   # BA V
    "čunovo":                9.5,   # BA V
    # Bratislava-okolie (suburbs)
    "senec":                 9.5,   # Top-10 growth city
    "pezinok":               9.5,   # Top-10 growth city
    "malacky":               7.5,
    "stupava":               8.5,
    "modra":                 8.0,
    # Trnava region — Q2 2026: 9–11 €/m²
    "trnava":               10.0,
    "dunajská streda":       7.5,
    "galanta":               7.0,
    "hlohovec":              7.0,
    "piešťany":              8.0,
    "senica":                6.5,
    "skalica":               6.5,
    # Trenčín region — Q2 2026: 7–9 €/m²
    "trenčín":               8.0,
    "bánovce":               6.0,
    "ilava":                 6.2,
    "myjava":                5.8,
    "nové mesto nad váhom":  6.8,
    "partizánske":           6.0,
    "považská bystrica":     6.8,
    "púchov":                6.8,
    # Nitra region — Q2 2026: 8–10 €/m², Jaguar Land Rover demand
    "nitra":                 8.5,
    "komárno":               6.5,
    "levice":                6.2,
    "nové zámky":            6.5,
    "šaľa":                  6.5,
    "topoľčany":             6.0,
    "zlaté moravce":         6.0,
    "vráble":                5.8,
    # Žilina region — Q2 2026: 9–12 €/m², strongest yield-per-cost in SR
    "žilina":               10.0,
    "bytča":                 7.0,
    "čadca":                 6.5,
    "kysucké nové mesto":    7.0,
    "liptovský mikuláš":     8.0,   # Top-10 growth city
    "námestovo":             6.0,
    "ružomberok":            7.0,
    "turčianske teplice":    6.0,
    "tvrdošín":              6.0,
    # Banská Bystrica region — Q2 2026: 8–10 €/m²
    "banská bystrica":       8.5,
    "brezno":                6.0,
    "detva":                 5.5,
    "lučenec":               6.0,
    "revúca":                5.5,
    "rimavská sobota":       5.5,
    "veľký krtíš":           5.5,
    "zvolen":                7.0,
    "žiar nad hronom":       6.5,
    "zvolenská":             6.2,
    # Prešov region — Q2 2026: 8–10 €/m², +12% YoY rent growth (highest in SR)
    "prešov":                8.5,
    "bardejov":              6.0,
    "humenné":               6.0,
    "kežmarok":              6.5,
    "levoča":                6.0,
    "medzilaborce":          5.0,
    "poprad":                9.5,   # Top-10 growth city, Tatry Airbnb premium
    "sabinov":               6.0,
    "snina":                 5.5,
    "stará ľubovňa":         6.0,
    "stropkov":              5.5,
    "vranov nad topľou":     6.0,
    # Košice — Q2 2026: 10–13 €/m² (#2 market after BA, +7% YoY)
    "košice":               10.5,
    # Košice — mestské obvody (data: Košice I 13.5–15, II 12–13, III 10.5–11.8, IV 11.5–12.8)
    "košice i":             13.5,   # Staré Mesto, Sever
    "košice ii":            12.0,   # Terasa, Juh, Západ
    "košice iii":           10.5,   # Dargovských hrdinov, Nad Jazerom
    "košice iv":            11.5,   # Vyšné Opátske, Barca
    "košice-okolie":         7.5,
    "gelnica":               5.5,
    "michalovce":            6.5,
    "rožňava":               6.0,
    "sobrance":              5.2,
    "spišská nová ves":      6.5,
    "trebišov":              5.8,
    # Martin area
    "martin":                7.5,
    "turčianske":            6.5,
    # Default — smaller towns not listed above
    "default":               6.5,
}

# ── s.r.o. Setup Cost Estimate ────────────────────────────────────────────────
SRO_SETUP_COST = 2_500  # Notary + registry + first year accounting

# ── Paths ─────────────────────────────────────────────────────────────────────
SQLITE_PATH    = "data/sovereign.db"
CONTRACTS_DIR  = "contracts"
LOGS_DIR       = "logs"

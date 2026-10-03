"""
config.py — Sovereign Investor Dashboard
All tunable constants. Review every January.
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
# SQLite only — see SQLITE_PATH below. DATABASE_URL is ignored: the old
# PostgreSQL mode never worked (see the database.py docstring).

# ── 2026 Slovak Financial Rates ───────────────────────────────────────────────
# Mortgage: NBS new-housing-loan average sat ~3.5% in 2026, bank offers ~3.4–4.0%
# (sources: NBS avg lending rates; financnykompas.sk; finsider.sk). 3.8% is a
# representative mid-market figure for a well-qualified borrower at ≤80% LTV.
MORTGAGE_RATE_PA       = 0.038   # 3.8% per annum — NBS-consistent 2026 average
LOAN_TERM_YEARS        = 25      # conservative; 30y is the more common max (NBS cap)
LTV_RATIO              = 0.80    # 80% standard NBS cap for owner-occupied/1st-2nd
# From 1 Oct 2026 NBS tightens the LTV cap to 70% for a 3rd-and-subsequent
# residential property (i.e. most pure investors). Use this when modelling an
# investor who already owns ≥2 properties.
LTV_RATIO_INVESTOR     = 0.70
INVESTOR_LTV_FROM      = "2026-10-01"   # date the 70% cap takes effect
# How many residential properties you already own. At 2 or more, the next
# purchase is your 3rd+, so scoring uses LTV_RATIO_INVESTOR instead of
# LTV_RATIO (see engine.financial.default_ltv). Set in .env.
PROPERTIES_OWNED       = int(os.getenv("PROPERTIES_OWNED", "0") or 0)

# Rate-shock stress test. NBS makes banks test affordability (DSTI) at the
# offered rate + 2 percentage points; a fixation ending in a higher-rate market
# does the same thing to a rental's cashflow. The engine re-runs each deal at
# MORTGAGE_RATE_PA + RATE_SHOCK_PP and reports whether it still pays for itself.
RATE_SHOCK_PP          = 0.02

# ── Hold-period IRR (engine.financial.project_irr) ───────────────────────────
# Assumptions for the multi-year return, including selling at the end. All
# conservative and editable. Appreciation and rent growth are nominal.
HOLD_YEARS             = 10
APPRECIATION_RATE      = 0.03   # price growth p.a. (SK long-run nominal ~4–6%)
RENT_GROWTH_RATE       = 0.025  # rent growth p.a.
COST_INFLATION_RATE    = 0.025  # HOA / fond opráv growth p.a.
# Selling costs as a fraction of the sale price: agent commission (~3%, paid by
# the seller when you are the seller) plus legal/cadastre.
EXIT_COST_RATE         = 0.035
# §9 ods. 1 písm. b) ZDP: an individual's gain on a flat held ≥5 years is
# exempt. Sold sooner, the gain is taxed at the personal income-tax rate. An
# s.r.o. pays corporate + dividend tax on the gain whenever it sells.
PERSONAL_CGT_EXEMPT_YEARS = 5

# Income tax — Fyzická osoba (personal), passive rental under §6 ods. 3
TAX_RATE_PERSONAL_LOW  = 0.19   # 19% up to threshold
TAX_RATE_PERSONAL_HIGH = 0.25   # 25% above threshold
TAX_THRESHOLD_PERSONAL = 41_445 # Annual € threshold 2026 (verify each January)
# §9 ods. 1 písm. g): the first €500 of rental income is exempt; expenses are
# reduced proportionally. Modelled here as a flat €500 deduction from the base.
RENTAL_INCOME_EXEMPTION = 500

# Income tax — s.r.o. (corporate)
TAX_RATE_SRO           = 0.21   # 21% standard corporate rate
# Reduced rate for small companies whose taxable revenue is under the limit.
# A single rental's gross rent is far below the limit, so this rate normally
# applies. (2026 figures — verify with an účtovník; rates shifted under the
# consolidation package.)
TAX_RATE_SRO_REDUCED       = 0.10
SRO_REDUCED_REVENUE_LIMIT  = 100_000
# Withholding tax on dividends when company profit is distributed to the owner.
# This is what creates s.r.o. double taxation (corporate tax + dividend tax).
DIVIDEND_TAX_RATE      = 0.10

# Health insurance levy.
# IMPORTANT: passive rental income under §6 ods. 3 of zákon 595/2003 is NOT
# subject to health (zdravotné odvody) or social contributions for an
# individual without a živnosť — so the personal levy is 0, not 16%. The old
# 16% figure structurally over-recommended the s.r.o. route. (Confirm with an
# účtovník for your specific situation.)
HEALTH_LEVY_PERSONAL   = 0.00   # passive rental: exempt from zdravotné odvody
HEALTH_LEVY_SRO        = 0.00   # company exempt

# Property tax
PROPERTY_TAX_RATE_PA   = 0.004  # ~0.4% of value annually

# Operating cost estimates.
# HOA = správa + fond opráv. By Act 182/1993 §10 the fond opráv already funds
# the building shell (roof, facade, elevator, risers, renovation), so we do NOT
# also charge a value-based building-maintenance reserve on top (that would
# double-count). Instead OWNER_RESERVE_RATE covers only the owner's in-flat
# capex (appliances, interior fittings, flooring, paint).
HOA_SMALL              = 35     # < 40 m²
HOA_MEDIUM             = 60     # 40–70 m²
HOA_LARGE              = 90     # > 70 m²
HOA_PREMIUM            = 130    # > 120 m²
VACANCY_RATE           = 0.05   # 5% (≈18 days/yr; conservative — BA runs 2–4%)
OWNER_RESERVE_RATE     = 0.05   # 5% of rent — in-flat capex/appliance reserve
# Property management fee if the unit is NOT self-managed (~8–10% of rent in SK,
# plus a ~1-month finder fee). Default 0 = self-managed.
PROPERTY_MGMT_RATE     = 0.00
# One-off buyer acquisition costs as a fraction of price, added to the cash
# invested for an honest cash-on-cash. Slovakia has NO transfer tax; buyer pays
# cadastre (€50–100), legal/contract (€150–400), valuation (€150–300) and any
# mortgage fee → ~1% all-in. Agent commission (~2–5%) is normally seller-paid/
# embedded in the price, so it is not added here by default.
ACQUISITION_COST_RATE  = 0.01

# ── Classification Thresholds ─────────────────────────────────────────────────
# Classes measure how far the asking €/m² sits below the region's median
# (engine/regional_prices — Realitná únia / NBS). They used to be the s.r.o.
# self-funding ratio: GREEN at rent ≥ 115% of all costs including the
# mortgage, YELLOW at ≥ 105%. At 3.8% over 25 years and 80% LTV that needs a
# ~7% gross yield, which no region reaches below ~50% of its median price —
# exactly where the sanity floor (REGIONAL_PRICE_FLOOR_RATIO) zeroes prices as
# data errors. At the median the ratio is 0.60–0.75 everywhere. So GREEN was
# unreachable for any real listing, and YELLOW only reachable at the floor.
# These thresholds sit well clear of it: GREEN is 20–50% below the median.
GREEN_DISCOUNT         = 0.20   # asking €/m² ≥ 20% below the regional median
YELLOW_DISCOUNT        = 0.10   # ≥ 10% below
# A GREEN this close to the floor (≥ 40% below the median) gets a warning: the
# price may be a deposit, an "od €X" starting price, or another listing's.
NEAR_FLOOR_DISCOUNT    = 0.40

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

# ── Location risk data (modules/risk_data.py) ─────────────────────────────────
# Open data, no keys. OpenStreetMap via Overpass for construction sites, noise
# sources, transit and amenities; Nominatim geocodes when there is no Google
# key; SVP's flood-hazard map service for the Q100 flood area.
OVERPASS_URL      = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NOMINATIM_URL     = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
# Nominatim's usage policy asks for a contact address in the request.
NOMINATIM_EMAIL   = os.getenv("NOMINATIM_EMAIL", "")
# SVP (Slovenský vodohospodársky podnik) flood hazard maps, cycle II —
# "Hranica záplavy Q100" (the 100-year flood extent). An ArcGIS MapServer
# identify endpoint plus the layer id(s) to test. Override if SVP moves it.
FLOOD_IDENTIFY_URL = os.getenv(
    "FLOOD_IDENTIFY_URL",
    "https://mpt.svp.sk/server/rest/services/MPOMPR_II/Op_Ohrozenie_Q/MapServer/identify",
)
FLOOD_LAYER_IDS   = os.getenv("FLOOD_LAYER_IDS", "24")
# Noise proxy: EU strategic noise maps put ≥65 dB Lden (NOISE_LIMIT_DB) along
# exactly these sources. Within these distances of one, flag the flat.
NOISE_MAJOR_ROAD_M = 150   # motorway / trunk (diaľnica, rýchlostná cesta)
NOISE_PRIMARY_M    = 30    # primary road (cesta I. triedy, city arterial)
NOISE_RAIL_M       = 80    # main-line railway (not sidings, not trams)
NOISE_AIRPORT_M    = 1500  # an airport with an IATA code

# ── Industrial Zones (worker demand premium) ──────────────────────────────────
# Only smaller towns built around a single large employer go here. The big
# cities (Žilina, Nitra, Trnava, Košice, Prešov) were removed: their RENT_PER_M2
# base rates already reflect local industrial demand, so applying the premium on
# top double-counted it.
INDUSTRIAL_ZONES = [
    "voderady", "šurany", "bytča",
    "kysucké nové mesto", "nové mesto nad váhom",
]
INDUSTRIAL_RENT_PREMIUM = 1.12  # 12% above base comps

# ── Description-derived rent premiums ─────────────────────────────────────────
# Features parsed out of the free-text listing description by
# modules/llm_enrichment.parse_description() that materially raise achievable
# rent. Conservative, multiplicative on top of the base €/m² rate, and applied
# only when the description was actually parsed (otherwise neutral). Sources:
# Bencont/Deloitte rent splits showing dedicated parking and furnished units
# rent at a premium across Slovak cities.
PARKING_RENT_PREMIUM    = 1.05   # garage / dedicated parking spot: +5%
FURNISHED_RENT_PREMIUM  = 1.10   # fully furnished: +10%
SEMI_FURNISHED_PREMIUM  = 1.05   # partially furnished: +5%
BALCONY_RENT_PREMIUM    = 1.03   # balcony / loggia / terrace: +3% (common, modest)

# ── APIs ──────────────────────────────────────────────────────────────────────
GOOGLE_API_KEY    = os.getenv("GOOGLE_PLACES_API_KEY", "")
# NOTE: there is no CADASTRAL_API_KEY — ÚGKK SR has no public API or keys.
# LV checks scrape kataster.skgeodesy.sk directly via kataster_scraper.py.
DMR_ENDPOINT      = os.getenv("DMR_ENDPOINT", "http://localhost:12434/v1")
LLM_MODEL         = os.getenv("LLM_MODEL", "mistral:7b-instruct-q4_k_m")
# ScraperAPI key — bypasses IP blocks on nehnutelnosti/bazos when running
# from a server/cloud environment. Free tier: https://www.scraperapi.com
SCRAPER_API_KEY   = os.getenv("SCRAPER_API_KEY", "")

# Anthropic Claude — optional cloud LLM for listing enrichment (parsing Slovak
# free-text descriptions, normalising blank districts, structured LV analysis).
# NEVER hard-code the key here. It is read from the .env file (gitignored), so
# the secret never lands in the repository. Leave blank to disable — every
# enrichment helper degrades gracefully when no key is set.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Sonnet is the cost-appropriate default for high-volume enrichment; override
# via the ANTHROPIC_MODEL env var if you want a different tier.
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ── Scraper ───────────────────────────────────────────────────────────────────
SCRAPE_DELAY_SEC       = 2.5
# How long a listing's detail-page scrape stays good for. Opening a detail page
# is the most expensive step in a run (one navigation/fetch each), so a listing
# already scraped within this window — and already holding a price and size —
# is skipped and only has its last_seen_at touched. Listings do get price cuts,
# so anything older than this is re-read. Lower it to catch price moves sooner
# at the cost of a slower run.
DETAIL_REFRESH_DAYS    = 7
CADASTRAL_DELAY_SEC    = 1.5
CADASTRAL_BACKOFF_MAX  = 60
# An UNVERIFIED LV check that has something to check with (a portal map pin or
# the flat's LV number) is retried after this many days — portal outages and
# approximate pins shouldn't park a listing for good.
LV_RECHECK_DAYS        = 7

# ── LV screening ──────────────────────────────────────────────────────────────
# The encumbrances the LV debt filter rejects on (záložné právo, exekúcia,
# konkurz, súdny spor, vecné bremeno, predkupné právo, zabezpečovacie prevodné
# právo) and how each is matched live in modules/lv_screen.py.
#
# A lien is ordinary housing finance — and doesn't reject — only when ITS OWN
# creditor is one of these. Any creditor whose name contains "banka"/"bank" or
# "sporiteľňa" already counts (Slovak law reserves "banka" for licensed banks);
# this list adds names and abbreviations that don't. ŠFRB (the state housing
# fund) lends against flats the way a bank does.
LV_BANK_NAMES = [
    "vúb", "čsob", "unicredit", "oberbank", "mbank", "365.bank",
    "štátny fond rozvoja bývania", "šfrb",
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

# ── Live rent comps (engine/rent_comps.py) ────────────────────────────────────
# The table above is a published-report baseline. scraper/rentals.py reads real
# "prenájom" listings and engine/rent_comps.py turns them into a live €/m² per
# RENT_PER_M2 key, which then replaces the baseline for that key.
#
# Asking rents run above what a flat actually lets for; this haircut brings a
# live median back towards achieved rent (and towards the table's conservative
# lower-bound convention).
RENT_COMP_ASKING_HAIRCUT = 0.95
# A district needs this many rentals before its live figure is used at all...
RENT_COMP_MIN_SAMPLE     = 5
# ...and even then it is blended with the baseline, which counts as this many
# comps: rate = (n·live + k·baseline) / (n + k). Five rentals move the rate a
# third of the way; forty move it 80%.
RENT_COMP_PRIOR_WEIGHT   = 10
# Rentals not seen for this long drop out of the comps.
RENT_COMP_MAX_AGE_DAYS   = 60
# Plausible long-term monthly rent for a flat. Outside it is a sale price, a
# per-night rate or a typo.
RENT_MIN_EUR             = 150
RENT_MAX_EUR             = 6_000

# ── s.r.o. Setup Cost Estimate ────────────────────────────────────────────────
SRO_SETUP_COST = 2_500  # Notary + registry + first year accounting

# ── Paths ─────────────────────────────────────────────────────────────────────
SQLITE_PATH    = "data/sovereign.db"
CONTRACTS_DIR  = "contracts"
LOGS_DIR       = "logs"

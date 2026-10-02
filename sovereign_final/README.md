# 🏛 SOVEREIGN INVESTOR DASHBOARD
**Private Slovak Real Estate Engine — 2026**

---

## Quick Start (Windows + Docker)

```
1. Install Docker Desktop  →  docker.com/products/docker-desktop
2. Unzip this folder anywhere (e.g. C:\Users\Filip\sovereign)
3. Copy .env.example → .env  (edit DB_PASSWORD if you want)
4. Double-click START.bat
5. Dashboard opens at http://localhost:8501
```

That's it.

---

## Tests

CI runs on every PR. To run locally from `sovereign_final/`:

```
python3 -m pytest tests/
```

Expected: ~680 passing, 1 xfailed (known Slovak-declension limitation).

---

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (9 tabs)
├── scheduler.py              ← Daily 06:00 CET automation
├── config.py                 ← All 2026 Slovak tax rates
├── database.py               ← PostgreSQL + SQLite fallback
├── enrich_pending.py         ← Re-read listings missing a price, size or district
├── repair_prices.py          ← Re-read listings whose price looks borrowed
├── repair_districts.py       ← Fix towns misread as Bratislava, then rescore
├── diagnose.py               ← Data-quality report (coverage, classification)
├── START.bat                 ← Windows one-click launcher
├── docker-compose.yml        ← 4 Docker containers
├── docker/Dockerfile         ← App image
├── requirements.txt
├── .env.example              ← Copy to .env
├── scraper/
│   ├── nehnutelnosti.py      ← Nehnutelnosti.sk scraper (Playwright)
│   ├── bazos.py              ← Bazos.sk scraper
│   ├── topreality.py         ← Topreality.sk scraper
│   └── rentals.py            ← Prenájom (to-let) listings for live rent comps
├── engine/
│   ├── financial.py          ← 2026 Slovak tax + cashflow engine, max offer,
│   │                           rate shock, hold-period IRR
│   ├── regional_prices.py    ← Sale-price medians, floor + ceiling filters
│   ├── rent_comps.py         ← Live €/m² rents from scraped rentals
│   └── duplicates.py         ← Same flat listed on several portals
├── modules/
│   ├── debt_bot.py           ← LV title deed checker + Mistral LLM
│   ├── cashflow_runner.py    ← Financial scoring runner
│   ├── location_iq.py        ← Location scorer (Google, or OpenStreetMap)
│   ├── risk_data.py          ← Real noise / flood / construction data
│   └── memo.py               ← PDF investment memo
└── dev/                      ← One-off debug/exploration scripts (not runtime)
```

---

## Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| TRIAGE TABLE | Flat, sortable view of every scored listing — grade, price, **max offer** (🟡/🟢), ask vs max offer, **vs market**, rent, surplus, **+2 pp stress**, cap rate, **IRR**, **days listed**, **price change**, **portals**, deal stage, vibe |
| ACTIVE SNAG LIST | 🟢🟡 deal cards: cost breakdown, financing stress (+2 pp, 70% LTV), location risk with sources, price history, other portals' copies, deal stage, vibe notes, **PDF memo**, LV re-verify |
| MAP | Every listing with coordinates, coloured by class (faded = area-level geocode) |
| WHAT-IF / TAX | The tax toggle calculator: any listing (or a custom one) re-run with your own price, rate, LTV, term, rent, hold period, growth and exit costs — personal vs s.r.o. side by side, rate-shock table, IRR, max offer |
| DEAL PIPELINE | Board of the deals you're working: WATCHING → VIEWING → OFFER → NEGOTIATING → DUE DILIGENCE → NOTARY → CLOSED / PASSED, with a timeline per deal |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score, and every note saved for the listing |
| REJECTED | Every LV rejection with its reason, detail and LV risk read; re-verify from here |
| RENT COMPS | Live €/m² per district from prenájom listings vs the baseline table |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download |

A 🔻 banner above the tabs lists price cuts from the last 14 days, and says
whether the new price now sits inside the max YELLOW offer.

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + self-funding ratio), location, energy class and risk flags — so a
GREEN deal in a poor location doesn't outrank a genuinely solid one.

---

## Pipeline (Sidebar Buttons)

```
NEHNUT → BAZOS → TOPREAL → RENT COMPS → housekeeping → LV DEBT FILTER
       → NORM ADDR → PARSE DESC → CASHFLOW SCORE → LOCATION IQ → RISK BACKFILL
       → MERGE PORTAL COPIES
```

Housekeeping = deactivate stale listings (>21d unseen) + flag dev projects.
A nehnutelnosti listing is deactivated sooner, the moment any read of its page
finds a grid of similar listings where the listing was — that is what a
removed listing's URL serves.
Runs automatically every morning at 06:00 CET via scheduler container.
Or click buttons in sidebar to run manually anytime.

Changed the rent/tax assumptions in `config.py`? Click **♻️ RESCORE ALL** to
clear existing scores and re-run scoring (the plain CASHFLOW SCORE button only
processes listings that have never been scored). A listing whose asking price
changes, or whose district's live rent moves, is re-scored automatically.

---

## What each score carries

- **Max offer 🟡 / 🟢** — the highest price at which the deal still scores
  YELLOW / GREEN, found by solving the engine itself (`max_offer_price`).
  "Ask vs 🟡" is the discount you need to negotiate.
- **vs Market** — asking vs the regional median €/m² × size
  (`regional_prices.regional_median_price`; medians are for older 3-room flats).
- **+2 pp** — the s.r.o. surplus at the mortgage rate + 2 percentage points (the
  NBS affordability stress).
- **IRR** — 10-year return on the cash put in: rent growth, appreciation,
  amortisation, selling costs and tax on the sale (a personal sale is exempt
  after 5 years; an s.r.o. sale is revenue and usually costs the 10% rate).
  Assumptions in `config.py` (`HOLD_YEARS`, `APPRECIATION_RATE`, …).
- **Rent source** — live prenájom comps when the district has enough of them,
  else the `RENT_PER_M2` baseline.

Set `PROPERTIES_OWNED` in `.env`: at 2 or more, the next purchase is a 3rd+
property, NBS caps the loan at **70% LTV** (from 1 Oct 2026), and scoring uses
that instead of 80%.

## Live rent comps

`scraper/rentals.py` reads prenájom listings from bazos and topreality into
`rental_listings` (never into `listings` — they are evidence, not deals).
`engine/rent_comps.py` drops ads with energies in the price, restates each
rent as a bare, unfurnished 2-izb flat's €/m², takes the median per
`RENT_PER_M2` key, cuts it 5% (asking → achieved) and blends it with the
baseline by sample size. Needs 5+ rentals per district. The rental-page
parsing mirrors the sale scrapers' selectors; check the 🏘️ RENT COMPS output
after the first run.

## Location risk data

`modules/risk_data.py` replaces the old always-"clear" stubs with open data —
no keys needed:

| Flag | Source |
|------|--------|
| Construction | OpenStreetMap `landuse/building=construction` within 300 m |
| Noise | OpenStreetMap: motorway/trunk ≤150 m, primary road ≤30 m, main railway ≤80 m, airport ≤1.5 km — a proxy for the ≥65 dB Lden zones of the EU strategic noise maps |
| Flood | SVP flood hazard maps — inside the mapped Q100 extent (`FLOOD_IDENTIFY_URL`) |

A flag nobody could determine (service down, or an address that only geocodes
to a district centroid) is stored as unknown and costs nothing. Without a
Google key, Location IQ now geocodes with Nominatim and counts transit and
amenities from OpenStreetMap instead of skipping.

---

## Classification

| Class | Condition |
|-------|-----------|
| 🟢 GREEN | s.r.o. ratio ≥ 115% — self-funding, hold 20+ years |
| 🟡 YELLOW | s.r.o. ratio ≥ 105% — solid yield play |
| ⚪ WHITE | Below threshold — flip/arbitrage only |
| ❌ REJECTED | Any LV debt flag — hard stop, never pursue |

---

## 2026 Slovak Tax Rates (config.py)

| | Personal (FO) | s.r.o. |
|--|---------|--------|
| Income Tax | 19% / 25% | 10% reduced (≤€100k rev) / 21% |
| Health Levy | **0%** — passive §6(3) rental is exempt from zdravotné odvody | 0% |
| Dividend tax on distribution | n/a | 10% (→ effective double taxation) |
| Mortgage | 3.8% p.a. | 3.8% p.a. |

> The personal health levy was previously modelled at 16%, which wrongly
> over-favoured the s.r.o. route. Passive rental income under §6 ods. 3 of zákon
> 595/2003 is exempt from health/social contributions; the first €500 is also
> tax-exempt. s.r.o. deducts mortgage interest (personal §6(3) does not) but
> pays corporate **and** dividend tax. Confirm specifics with an účtovník.

**Update `config.py` every January.**

---

## API Keys (all optional — demo mode without them)

| Key | Where | Enables |
|-----|-------|---------|
| GOOGLE_PLACES_API_KEY | console.cloud.google.com | Google geocoding/places + inline satellite view (OpenStreetMap is used without it) |
| FINSTAT_API_KEY | finstat.sk/api | Company owner lookup |

> LV debt checking needs **no key**: ÚGKK SR has no public API, so
> `kataster_scraper.py` scrapes kataster.skgeodesy.sk directly (unofficial —
> may break if the portal changes; listings without parcel data pass
> "unverified").

---

## Docker Commands (PowerShell)

```powershell
docker compose up -d        # Start everything
docker compose down         # Stop everything
docker compose logs -f      # Live logs
docker compose ps           # Container status
docker compose restart      # Restart all
```

---

## Legal

- Contract drafts are **DRAFT ONLY** — no legal validity
- Always use **Notárska úschova** for fund transfers
- Re-verify LV **48 hours before signing** — titles change
- s.r.o. structuring requires a licensed Slovak **účtovník**
- This tool provides data scoring only — not investment advice

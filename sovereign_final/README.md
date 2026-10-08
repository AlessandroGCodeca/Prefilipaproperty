# 🏛 SOVEREIGN INVESTOR DASHBOARD
**Private Slovak Real Estate Engine — 2026**

---

## Quick Start (Windows + Docker)

```
1. Install Docker Desktop  →  docker.com/products/docker-desktop
2. Unzip this folder anywhere (e.g. C:\Users\Filip\sovereign)
3. Copy .env.example → .env  (API keys are optional)
4. Double-click START.bat
5. Dashboard opens at http://localhost:8501
```

That's it.

Storage is one SQLite file, `data/sovereign.db` inside this folder (whatever
directory a script is started from) — locally, and in Docker on
the `sovereign_data` volume shared by the dashboard and the scheduler. (The
old PostgreSQL mode never worked and is gone; a `DATABASE_URL` left in an old
`.env` is ignored.) To carry a local database into Docker:

```
docker compose cp data/sovereign.db dashboard:/app/data/sovereign.db
docker compose restart
```

---

## Tests

CI runs on every PR. To run locally from `sovereign_final/`:

```
python3 -m pytest tests/
```

Expected: ~1,045 passing (the dashboard smoke test in `tests/test_app_smoke.py` needs `streamlit` installed and is skipped without it).

---

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (9 tabs)
├── scheduler.py              ← Daily 06:00 CET automation
├── config.py                 ← All 2026 Slovak tax rates
├── database.py               ← SQLite storage
├── enrich_pending.py         ← Re-read listings missing a price, size or district
├── repair_prices.py          ← Re-read listings whose price looks borrowed
├── repair_districts.py       ← Fix towns misread as Bratislava, then rescore
├── diagnose.py               ← Data-quality report (coverage, classification)
├── START.bat                 ← Windows one-click launcher
├── docker-compose.yml        ← dashboard + scheduler + local LLM
├── docker/Dockerfile         ← App image
├── requirements.txt
├── .env.example              ← Copy to .env
├── scraper/
│   ├── nehnutelnosti.py      ← Nehnutelnosti.sk scraper (Playwright)
│   ├── bazos.py              ← Bazos.sk scraper
│   ├── topreality.py         ← Topreality.sk scraper
│   ├── geo.py                ← A listing's own map pin (JSON-LD / API / meta)
│   ├── slovak_cases.py       ← Locative place names ("v Nitre", "v Košiciach")
│   └── rentals.py            ← Prenájom (to-let) listings for live rent comps
├── engine/
│   ├── financial.py          ← 2026 Slovak tax + cashflow engine, max offer,
│   │                           rate shock, hold-period IRR
│   ├── regional_prices.py    ← Sale-price medians, floor + ceiling filters
│   ├── rent_comps.py         ← Live €/m² rents from scraped rentals
│   └── duplicates.py         ← Same flat listed on several portals
├── modules/
│   ├── debt_bot.py           ← LV title deed checker (PASS / UNVERIFIED / REJECTED)
│   ├── lv_screen.py          ← Entry-by-entry LV encumbrance screen
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
| TRIAGE TABLE | Flat, sortable view of every scored listing — grade, price, **max offer** (🟡/🟢), ask vs max offer, below-market %, rent, surplus, **+2 pp stress**, gross yield, cap rate, **IRR**, **days tracked** (since the first scrape — not the portal's posting date), **price change**, **portals**, deal stage, vibe, LV status, **⛔ cash-flow negative** |
| ACTIVE SNAG LIST | 🟢🟡 deal cards: cost breakdown (the s.r.o.'s own loan and running cost), financing stress (+2 pp, 70% LTV), location risk with sources, price history, other portals' copies, deal stage, vibe notes, **PDF memo**, LV status and flat-LV verify; a ⛔ CASH-FLOW NEGATIVE badge and a ⚠ rent-fallback warning where they apply |
| MAP | Every listing with coordinates, coloured by class (faded = area-level geocode) |
| WHAT-IF / TAX | The tax toggle calculator: any listing (or a custom one) re-run with your own price, rate, LTV, term, rent, hold period, growth and exit costs, and the s.r.o.'s loan premium, LTV and running cost — personal vs s.r.o. side by side, rate-shock table, IRR, max offer |
| DEAL PIPELINE | Board of the deals you're working: WATCHING → VIEWING → OFFER → NEGOTIATING → DUE DILIGENCE → NOTARY → CLOSED / PASSED, with a timeline per deal |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score, and every note saved for the listing |
| REJECTED | Every LV rejection with its reason, detail and LV risk read; re-verify from here |
| LV TO-DO | Every GREEN / YELLOW deal whose title deed isn't verified, with what the plot check found; type the flats' own LV numbers in bulk, then save (checked on the next LV run) or save & verify now |
| RENT COMPS | Live €/m² per district from prenájom listings vs the baseline table |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download |

A 🔻 banner above the tabs lists price cuts from the last 14 days, and says
whether the new price now sits inside the max YELLOW offer.

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + discount to the regional median), location, energy class,
condition and risk flags — so a GREEN deal in a poor location doesn't outrank
a genuinely solid one. An LV that is verified clean scores above an unverified one.

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
Runs automatically every morning at 06:00 CET via scheduler container. When
the scheduler starts it runs the pipeline only if none has finished since the
last 06:00 (first start, or the PC was off at 06:00) — restarting Docker or
the PC does not re-scrape a day that is already done. Or click buttons in
sidebar to run manually anytime.

Changed the rent/tax assumptions in `config.py`? Click **♻️ RESCORE ALL** to
clear existing scores and re-run scoring (the plain CASHFLOW SCORE button only
processes listings that have never been scored). A listing whose asking price
changes, or whose district's live rent moves, is re-scored automatically.

---

## What each score carries

- **Max offer 🟡 / 🟢** — the highest price at which the listing still scores
  YELLOW / GREEN: the regional median €/m² × size × (1 − 10% / 20%), checked
  against `analyse()` itself (`max_offer_price`). Financing doesn't move it —
  the class is the discount to the median. "Ask vs 🟡" is the discount you
  need to negotiate.
- **Below%** — asking €/m² vs the regional median
  (`regional_prices.regional_median_price`; medians are for older 3-room flats).
- **+2 pp** — the s.r.o. surplus and self-funding ratio at the mortgage rate
  + 2 percentage points (the NBS affordability stress).
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

Classes compare the asking €/m² with the region's median
(`engine/regional_prices.py` — Realitná únia / NBS), and the GREEN / YELLOW
lists rank by that discount, then gross yield.

- **Room count.** The medians are for older 3-room flats; a listing is judged
  against its region's median × `MEDIAN_ROOMS_MULTIPLIER` (1-room ×1.15,
  2-room ×1.07, 4+ ×0.95 — estimates to replace with Realitná únia's
  per-category medians). An unknown room count keeps the 3-room figure.
- **Bratislava.** A city part with its own median uses it. "Bratislava I"–"V"
  with no city part named use their okres's median, weighted by the
  population of its city parts; Lamač, Vajnory, Rusovce, Jarovce, Čunovo,
  Devín and Záhorská Bystrica, which have no median of their own, use their
  okres's. Plain "Bratislava" is still the city-wide figure. The card's
  "vs Market" tooltip says which benchmark was used.
- **Class is not cash flow.** At the median the rent covers only 60–75% of
  all costs, so most GREEN flats still cost money every month. A flat whose
  surplus is below `CASHFLOW_MIN_SURPLUS` (default €0/mo) carries a
  ⛔ CASH-FLOW NEGATIVE badge, the snag-list headings count them, and the
  sidebar's 💶 Cash-flow positive only filter hides them.

| Class | Condition |
|-------|-----------|
| 🟢 GREEN | 20–50% below the regional median €/m² |
| 🟡 YELLOW | 10–20% below |
| ⚪ WHITE | Less than 10% below, above the median, no regional benchmark — or more than 50% below, which is the sanity floor (a deposit, an "od €X" price, another listing's price) |
| ❌ REJECTED | The flat's own LV carries a blocking encumbrance — hard stop |

The classes used to be the s.r.o. self-funding ratio (GREEN at rent ≥ 115% of
all costs). At 3.8% / 25 years / 80% LTV that needs a ~7% gross yield, which
no region reaches above ~50% of its median price — the sanity floor below
which prices are zeroed as data errors. No real listing could be GREEN. The
ratio is still computed and shown ("Self-Fund"). A GREEN ≥ 40% below the
median carries a warning: that close to the floor, check the price is the
flat's own.

Existing scores from the old rule are cleared once on upgrade — run
💰 CASHFLOW SCORE (or wait for 06:00) to reclassify.

---

## LV debt filter

| LV status | Meaning |
|-----------|---------|
| ✅ CLEAN | The flat's **own** LV was read and nothing on it blocks |
| ⚠ UNVERIFIED | No LV of this flat was read — the card says how far the check got |
| ❌ REJECTED | The flat's own LV has a non-bank lien, exekúcia, konkurz, súdny spor, vecné bremeno or predkupné právo |

How a check runs:

1. **Building plot.** When the portal ships the listing's own map pin, the
   filter resolves it to the built-up parcel under it (`kataster_scraper.parcel_at`)
   and stores the parcel, its cadastral unit and the plot's LV. A pin off any
   building, or in another town than the listing, is not used. Geocoded
   addresses never are — they land on a street or district centroid.
2. **That is still UNVERIFIED.** A flat in a bytový dom has its own LV entry,
   often on another LV than its plot, sometimes on one LV shared by the whole
   building — so a clean plot LV says nothing about the flat, and a lien on it
   may be a neighbour's. The card shows the plot and anything its LV lists.
3. **The flat's own LV verifies it.** Type the flat's LV number (from the
   seller's papers or the agent) and its katastrálne územie into the card and
   press RE-VERIFY LV — or enter many at once in the **LV TO-DO** tab, which
   lists every GREEN / YELLOW deal still waiting for one. A shared LV with a
   flag on it stays UNVERIFIED until you've checked part C against the flat's
   number.

So the filter does not, on its own, keep debt-laden flats off the lists: it
rejects a flat only once its own LV has been read. Until then the flat is
⚠ UNVERIFIED — shown, never called clean.

The screen (`modules/lv_screen.py`) reads each encumbrance separately: a lien
passes only when its **own** creditor ("v prospech …") is a bank or ŠFRB, and
an exekúcia / konkurz / súdny spor never passes — not even when the optional
Claude read says otherwise. Matching is inflection-aware ("začatie exekúcie",
"záložným právom").

To check the filter against a flat whose výpis you hold:

```
python3 dev/lv_known_flat.py LAT LNG --lv 4321 --area Petržalka
```

It prints the parcels at the pin, the plot LV and the flat LV, what the screen
reads out of each, and the verdicts the filter would store. Run it from a
Slovak IP — skgeodesy.sk geo-blocks many foreign ones.

---

## 2026 Slovak Tax Rates (config.py)

| | Personal (FO) | s.r.o. |
|--|---------|--------|
| Income Tax | 19% / 25% | 10% reduced (≤€100k rev) / 21% |
| Health Levy | **0%** — passive §6(3) rental is exempt from zdravotné odvody | 0% |
| Dividend tax on distribution | n/a | 10% (→ effective double taxation) |
| Loan | hypotéka 3.8% p.a., 80% LTV (70% for a 3rd+ flat) | company loan: rate + `SRO_RATE_PREMIUM_PP` (1 pp), at most `SRO_LTV_RATIO` (70%) |
| Running cost | — | `SRO_ANNUAL_RUNNING_COST` €1,200/yr (bookkeeping, accounts, office), deductible |

The s.r.o. is recommended only when it nets more than personal ownership
after its running cost and loan terms **and** that gain repays
`SRO_SETUP_COST` within `HOLD_YEARS`. The company-loan terms and the running
cost are estimates — set them from a bank's quote and your účtovník's (all
three are `.env` settings).

> The personal health levy was previously modelled at 16%, which wrongly
> over-favoured the s.r.o. route. Passive rental income under §6 ods. 3 of zákon
> 595/2003 is exempt from health/social contributions; the first €500 is also
> tax-exempt. s.r.o. deducts mortgage interest (personal §6(3) does not) but
> pays corporate **and** dividend tax. Confirm specifics with an účtovník.

The tax figures live in `TAX_YEAR_RULES` in `config.py`, one table per tax
year with its source and the date it was last checked; the sidebar shows
which table scoring uses. A year with no table of its own falls back to the
latest one and the sidebar warns. Scores worked out under another year's table
(or by an older version of the engine) are redone on the next scoring run.

**Every January, add the new year to `TAX_YEAR_RULES`.** The 2026 personal
threshold (€41,445) is the 2023 figure carried over — it is 176.8 × the
životné minimum, so recompute it.

---

## API Keys (all optional — demo mode without them)

| Key | Where | Enables |
|-----|-------|---------|
| GOOGLE_PLACES_API_KEY | console.cloud.google.com | Google geocoding/places + inline satellite view (OpenStreetMap is used without it) |

> LV debt checking needs **no key**: ÚGKK SR has no public API, so
> `kataster_scraper.py` scrapes kataster.skgeodesy.sk directly (unofficial —
> may break if the portal changes). Listings it cannot verify are stored and
> shown as ⚠ UNVERIFIED, never as clean.

---

## Docker Commands (PowerShell)

```powershell
docker compose up -d --build   # Start everything (rebuilds after a code update)
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

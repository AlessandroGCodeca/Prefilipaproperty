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

That's it. Edit `.env` later and run `docker compose up -d` (or START.bat) to
apply it — no rebuild.

## Quick Start (Mac, without Docker)

```
1. Install Python 3.13  →  python.org/downloads/macos
   (the "macOS 64-bit universal2 installer" under a 3.13.x release)
2. Unzip this folder anywhere
3. Copy .env.example → .env  (optional — API keys)
4. Double-click "Start Sovereign.command" in sovereign_final/
5. Dashboard opens in Chrome at http://localhost:8501
```

Python 3.11–3.14 work. **3.15 does not** — Streamlit needs a pyarrow that has
no 3.15 build, so the install fails; the start file says so and looks for an
older Python beside it.

The first start installs the libraries and the scrapers' browser (Chromium)
into `.venv/` — a few minutes; later starts take seconds, and a newer
`requirements.txt` is installed on the next start. Keep the Terminal window it
opens: closing it (or Ctrl+C) stops the dashboard. Double-clicking the file
while the dashboard runs just opens the page again.

If macOS won't open the file ("Apple could not verify…", usual for a
downloaded file), click **Open Anyway** in System Settings → Privacy &
Security, or start it once from Terminal in `sovereign_final/`:

```
bash "Start Sovereign.command"
```

No scheduler runs without Docker: click **▶ RUN EVERYTHING** in the sidebar to
refresh everything (or run `python scheduler.py` in a second Terminal window,
from `sovereign_final/` with `.venv/bin/activate` sourced, for the daily 06:00
run).

The start file serves the dashboard to this Mac only (`--server.address
127.0.0.1`), as `docker-compose.yml` does. A bare `streamlit run app.py`
listens on every network, so anyone on the same Wi-Fi could open it — see
below.

Moving to a newer download of the project: copy the `data/` folder (the
database: listings, deal stages, notes) and `.env` from the old folder into
the new one before the first start.

### Who can open it

The dashboard listens on **this computer only** (`127.0.0.1:8501` in
`docker-compose.yml`). It has no login unless `DASHBOARD_PASSWORD` is set in
`.env`, and anyone who can open it can press buttons that spend your paid API
credits and read your deal notes and contract drafts (buyer names). To use it
from a phone or another PC:

1. set `DASHBOARD_PASSWORD` in `.env`;
2. change the dashboard's port in `docker-compose.yml` from
   `"127.0.0.1:8501:8501"` to `"8501:8501"`;
3. `docker compose up -d`.

Over the internet, put it behind a reverse proxy with HTTPS (Caddy, Cloudflare
Tunnel, Tailscale) — the password alone travels in the clear over plain HTTP.

API keys live in `.env`, which Docker hands to the containers when they start
(`env_file`). `.dockerignore` keeps it out of the image, so the keys are never
baked into an image layer.

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

Everything should pass (about 1,500 tests; the dashboard tests in
`tests/test_app_smoke.py` need `streamlit` installed and are skipped without
it). CI also runs `ruff check . --select=E9,F` and runs the suite on Windows.

Dependencies are pinned to exact versions in `requirements.txt`, so a Docker
rebuild installs what the tests last passed with. Dependabot opens a PR each
week with upgrades, and CI tests them before they land.

---

## Markets: Slovakia and Czechia

Both markets run in the same app, side by side. Slovakia works exactly as
before; Czechia is added next to it.

- **Market selector** at the top of the page: *All markets* (default),
  🇸🇰 Slovakia or 🇨🇿 Czechia. It filters every tab. Cards and tables carry
  a market badge.
- **Currency**: a listing keeps its own currency (EUR or CZK) on its card and
  in its own market's view. The combined view and the *Max Price €* filter
  convert CZK at one rate, `CZK_PER_EUR`, labelled with its date
  (`FX_RATE_DATE`). Czech cards use Czech labels and Czech number formatting
  (`4 500 000 Kč`).
- **Pipelines**: each market has its own steps, status line, success record
  and retries. Both run one after the other under the one pipeline lock, and
  a failure in one never stops the other (`scheduler.run_all_markets`).

### Czech sources

| What | Source | State |
|---|---|---|
| Listings | Bezrealitky.cz (website sitemap + listing pages; never api.bezrealitky.cz, which robots.txt closes), Reality.iDNES.cz, Bazoš (reality.bazos.cz) | read when robots.txt allows; each fails soft |
| Listings | **Sreality.cz — left out**: its robots.txt gives every crawler but the named search engines `Disallow: /` | parser kept (`scraper/sreality.py`); 🔗 TEST CZ SITES re-checks |
| Rentals (comps) | Bazoš `/pronajmu/byt/`, Bezrealitky rental pages | `scraper/rentals_cz.py` → `engine/rent_comps_cz.py` |
| Rent baseline | Deloitte Rent Index Q2 2026: Praha 462, Praha 7 493, Brno 390, Hradec Králové 318, Pardubice 314, Jihlava 257, Ostrava 254, Ústí nad Labem 221 Kč/m² | other towns: live comps only, or not scored |
| Sale-price medians | none could be read whole — **the table is empty**, so every Czech listing is WHITE; `data/cz_regional_prices.csv` fills it (format in `engine/regional_prices_cz.py`) | gap |
| Title deed (LV) | the flat's **výpis z LV, pasted on its card** (or, once rejected, in the REJECTED tab), screened with Czech vocabulary — PASS / REJECTED / UNVERIFIED as in Slovakia. PASS needs part C in the text and the výpis to run on to part E (so a page cut off inside C or D can't pass), the flat's unit in part B, every entry of parts C–D to be one the screen knows, the LV number and k.ú. to match the card's, and a výpis no older than `CZ_LV_MAX_VYPIS_AGE_DAYS` (30 days, read from its "stav evidovaný k datu" line); the building's own LV (the number the card shows for the plot, with no units) is never taken as the flat's; a cooperative flat (its ad, or a družstvo owning it in part A) is never PASS | ČÚZK's free services give no LV contents to a program; nahlížení is CAPTCHA-guarded |
| Cadastre lookups | ČÚZK API KN (free key: `CZ_CUZK_API_KEY`) + RÚIAN address points: the building under the pin, its LV and pending proceedings | never PASS on its own |
| Flood | ÚÚR national map, VÚV T. G. M. Q100 flood areas (indicative) | `modules/risk_data_cz.py` |
| Noise | OpenStreetMap proxy + 2022 strategic noise map of main roads (MZ ČR) | ≥65 dB flags the flat |
| Place names | RÚIAN okres names, Prague 1–22, Brno's districts; Czech locatives ("v Praze 2", "ve Zlíně"); every obec when `data/cz_obce.csv` (a RÚIAN export) is present | `scraper/czech_cases.py` |
| Tax, mortgage, costs | ZDP 2026, ČNB limits (LTV 80 % / 70 % for investment mortgages from 1 Apr 2026), Swiss Life Hypoindex rate, SVJ fond oprav, daň z nemovitých věcí, katastr fee | `markets.py`, each with its source and date |
| Contract | a Czech **kupní smlouva NÁVRH** for a Czech advokát or notář to review — not legal advice | `modules/contract_draft_cz.py` |

No Czech host could be reached from the container this was built in. Every
endpoint, page shape and figure above came from published documentation, open-source
collectors and web search, and each scraper checks robots.txt live before it
reads anything.

### UNVERIFIED — figures and endpoints that could not be confirmed

Each is marked `UNVERIFIED` in its own source / checked field. The env settings
named here override them.

1. Czech sale-price medians: none (table empty); the rooms multiplier for them is 1.0.
2. Deloitte Rent Index: whether its figures are asking or achieved rents.
3. Property tax: each municipality's local coefficient (1.0, `CZ_PROPERTY_TAX_LOCAL_COEF`) and the size coefficient outside Prague (3.5, the upper bound).
4. Personal tax: whether an SVJ fond oprav payment is deductible when paid (modelled) or only when spent; the 40 mil. Kč cap on an exempt sale (not modelled).
5. Lending: a ČNB stress add-on (the engine's +2 pp is used).
6. SVJ správa fee per flat (0, `CZ_SVJ_SPRAVA_PER_UNIT`); fond oprav 20 Kč/m² (`CZ_SVJ_FOND_OPRAV_PER_M2`).
7. Legal fees on a purchase: 1 % of the price, carried over from Slovakia (`CZ_ACQUISITION_COST_RATE`).
8. s.r.o. setup and running costs: Slovak estimates converted (`CZ_SRO_SETUP_COST`, `CZ_SRO_ANNUAL_RUNNING_COST`).
9. Parking, furnished and balcony rent premiums, and the hold assumptions (price and rent growth, cost inflation, exit costs): carried over from Slovakia.
10. ČÚZK API KN paths and fields (from its OpenAPI document as copied in January 2025) and the RÚIAN address layer (layer 1, field `kod`).
11. The ÚÚR flood layer (82) and the noise map's REST path and value encoding.
12. The výpis z LV layout the Czech screen reads (part headings, "Oprávnění pro", the "o" entry bullet, the V-/Z-/POLVZ/PV register numbers, the "Kat.území" line); without a part C heading it reads the whole text and never calls the title clean.
13. Portal page shapes: Sreality's v1 API, Bezrealitky's sitemap and `__NEXT_DATA__` advert, iDNES's country-wide search and parameter list, Bazoš CZ's cards (taken as the Slovak site's).
14. Each portal's robots.txt, as captured by an open-source collector on 2026-09-15 — the scrapers read it live, keeping a copy a day at most (a missing one an hour).

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (9 tabs)
├── scheduler.py              ← Daily 06:00 CET automation, retries a failed run
├── config.py                 ← All 2026 Slovak tax rates
├── markets.py                ← Market registry: the SK and CZ profiles
├── database.py               ← SQLite storage
├── enrich_pending.py         ← Re-read listings missing a price, size or district
│                               (🔎 FILL MISSING DETAILS)
├── repair_prices.py          ← Re-read listings whose price looks borrowed
├── repair_districts.py       ← Fix towns misread as Bratislava, then rescore
├── diagnose.py               ← Data-quality report (coverage, classification)
├── START.bat                 ← Windows one-click launcher
├── Start Sovereign.command   ← macOS one-click launcher (no Docker)
├── restart.sh                ← Restart the dashboard outside Docker
├── docker-compose.yml        ← dashboard + scheduler
├── docker/Dockerfile         ← App image
├── requirements.txt
├── .env.example              ← Copy to .env
├── scraper/
│   ├── nehnutelnosti.py      ← Nehnutelnosti.sk scraper (Playwright)
│   ├── bazos.py              ← Bazos.sk scraper
│   ├── topreality.py         ← Topreality.sk scraper
│   ├── geo.py                ← A listing's own map pin (JSON-LD / API / meta)
│   ├── slovak_cases.py       ← Locative place names ("v Nitre", "v Košiciach")
│   ├── rentals.py            ← Prenájom (to-let) listings for live rent comps
│   ├── cz_common.py          ← Czech scrapers' shared parts: robots.txt, Kč, places
│   ├── bezrealitky.py        ← Bezrealitky.cz (sitemap + listing pages)
│   ├── idnes.py              ← Reality.iDNES.cz
│   ├── bazos_cz.py           ← Bazoš (reality.bazos.cz)
│   ├── sreality.py           ← Sreality.cz parser — not run: robots.txt disallows
│   ├── czech_cases.py        ← Czech locatives ("v Praze", "ve Zlíně")
│   └── rentals_cz.py         ← Pronájem listings for Czech rent comps
├── engine/
│   ├── financial.py          ← 2026 Slovak tax + cashflow engine, max offer,
│   │                           rate shock, hold-period IRR
│   ├── regional_prices.py    ← Sale-price medians, floor + ceiling filters
│   ├── rent_comps.py         ← Live €/m² rents from scraped rentals
│   ├── regional_prices_cz.py ← Czech kraj / okres / Prague / Brno lookup (medians empty)
│   ├── rent_cz.py            ← Czech rent baseline (Deloitte Rent Index Q2 2026)
│   ├── rent_comps_cz.py      ← Live Kč/m² rents from Czech rentals
│   ├── property_tax_cz.py    ← Daň z nemovitých věcí on a flat
│   └── duplicates.py         ← Same flat listed on several portals
├── modules/
│   ├── debt_bot.py           ← LV title deed checker (PASS / UNVERIFIED / REJECTED)
│   ├── lv_screen.py          ← Entry-by-entry LV encumbrance screen
│   ├── lv_cz.py              ← Czech LV check (pasted výpis; ČÚZK API KN)
│   ├── lv_screen_cz.py       ← The screen in the Czech register's words
│   ├── cuzk_cz.py            ← ČÚZK API KN + RÚIAN client
│   ├── risk_data_cz.py       ← Czech flood and noise maps
│   ├── contract_draft_cz.py  ← Czech kupní smlouva draft (for a Czech advokát)
│   ├── cashflow_runner.py    ← Financial scoring runner
│   ├── location_iq.py        ← Location scorer (Google, or OpenStreetMap)
│   ├── risk_data.py          ← Real noise / flood / construction data
│   ├── memo.py               ← PDF investment memo
│   ├── contract_draft.py     ← ONE-CLICK CLOSE contract draft + internal analysis
│   ├── pipeline_state.py     ← Pipeline lock + last full run's status
│   ├── jobs.py               ← Runs the sidebar buttons in the background
│   └── backup.py             ← Daily database copy + export of your data
└── dev/                      ← Debug probes: LV check, nehnutelnosti, topreality
```

---

## Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| TRIAGE TABLE | Flat, sortable view of every scored listing — grade, price, **max offer** (🟡/🟢), ask vs max offer, below-market %, rent, surplus, **+2 pp stress**, gross yield, cap rate, **IRR**, **days tracked** (since the first scrape — not the portal's posting date), **price change**, **portals**, deal stage, vibe, LV status, **⛔ cash-flow negative** |
| ACTIVE SNAG LIST | 🟢🟡 deal cards, 25 a page per class, each built when you open it: cost breakdown (the s.r.o.'s own loan and running cost), financing stress (+2 pp, 70% LTV), location risk with sources, price history, other portals' copies, deal stage, vibe notes, **PDF memo**, LV status and flat-LV verify; a ⛔ CASH-FLOW NEGATIVE badge and a ⚠ rent-fallback warning where they apply |
| MAP | Every listing with coordinates, coloured by class (faded = area-level geocode) |
| WHAT-IF / TAX | The tax toggle calculator: any listing (or a custom one) re-run with your own price, rate, LTV, term, rent, hold period, growth and exit costs, and the s.r.o.'s loan premium, LTV and running cost — personal vs s.r.o. side by side, rate-shock table, IRR, max offer |
| DEAL PIPELINE | Board of the deals you're working: WATCHING → VIEWING → OFFER → NEGOTIATING → DUE DILIGENCE → NOTARY → CLOSED / PASSED, with a timeline per deal |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score, and every note saved for the listing |
| REJECTED | Every LV rejection with its reason, detail and LV risk read; re-verify from here |
| LV TO-DO | Every GREEN / YELLOW deal whose title deed isn't verified, with what the plot check found; type the flats' own LV numbers in bulk, then save (checked on the next LV run) or save & verify now (in the background, like the pipeline buttons) |
| RENT COMPS | Live €/m² per district from prenájom listings vs the baseline table |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download; the deal's numbers are a separate download, not part of the draft |

A 🔻 banner above the tabs lists price cuts from the last 14 days, and says
whether the new price now sits inside the max YELLOW offer.

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + discount to the regional median), location, energy class,
condition and risk flags — so a GREEN deal in a poor location doesn't outrank
a genuinely solid one. An LV that is verified clean scores above an unverified one.
A price below the sanity floor gets no grade ("—"): it is a data error, not a deal.

---

## Pipeline (Sidebar Buttons)

```
NEHNUT → BAZOS → TOPREAL → FILL MISSING DETAILS → RENT COMPS → housekeeping
       → LV DEBT FILTER → NORM ADDR → PARSE DESC → CASHFLOW SCORE
       → LOCATION IQ → RISK BACKFILL → MERGE PORTAL COPIES
```

**▶ RUN EVERYTHING** at the top of the sidebar runs that whole chain — the
same run the scheduler makes at 06:00, recorded the same way — for when no
scheduler runs (the Mac start above) or you want fresh data now. It takes a
while (each portal can take up to 30 minutes); the page stays usable.

**🔎 FILL MISSING DETAILS** re-reads nehnutelnosti listings saved without a
price, a size or a district (`enrich_pending.py`), retires the ones taken
down, and scores what it filled in. A listing with no price or size can't be
scored, and the daily scrape doesn't open its page again, so without this it
stays PENDING. The pipeline does it for up to 100 listings a run — and skips
it when nehnutelnosti blocked that run's scrape, as every read would only time
out — the button for up to 200. Bazos and Topreality listings aren't re-read.

Housekeeping = deactivate stale listings (>21d unseen) + flag dev projects.
(Skipped on a day no portal could be read: "unseen" then says nothing.)
A nehnutelnosti listing is deactivated sooner, the moment any read of its page
finds a grid of similar listings where the listing was — that is what a
removed listing's URL serves.
Runs automatically every morning at 06:00 CET via scheduler container. When
the scheduler starts it runs the pipeline only if none has succeeded since the
last 06:00 (first start, the PC was off at 06:00, or the run failed) —
restarting Docker or the PC does not re-scrape a day that is already done. Or
click buttons in sidebar to run manually anytime.

A run **succeeds** when at least one portal was read. When all three scrapers
fail (blocked, offline) the run is not counted as done: it is retried an hour
later, up to three times that day, and the dashboard says so — in red at the
top of the page, and on the status line under PIPELINE in the sidebar, which
always shows when the last full run (scheduled or ▶ RUN EVERYTHING) finished,
what it found, and which steps failed. The details are in
`logs/scheduler.log`. After a failed ▶ RUN EVERYTHING the status line says to
click it again — only a running scheduler retries on its own.

A sidebar button runs its step **in the background**: the page stays usable,
a progress bar shows under PIPELINE, and the result stays there until the next
step. The pipeline buttons are greyed out while a step runs. The scheduler and
the buttons share one lock, so a button pressed during the 06:00 run says the
scheduler is busy instead of running the same step twice — and the 06:00 run
waits (up to an hour) for a step you started.

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
  The s.r.o. also pays `SRO_SETUP_COST` once, in year 0.
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
  okres's. A city part named on its own ("Ružinov", without "Bratislava")
  uses its own median too. Plain "Bratislava" is still the city-wide figure. The card's
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
| ❌ REJECTED | The flat's own LV has a non-bank lien, exekúcia, konkurz, súdny spor, a lifetime right to use or live in the flat, a private person's or company's predkupné právo, or a vecné bremeno of a kind the screen can't read |
| ⚑ soft flag | Shown on a CLEAN (or rejected) flat, not a reason to reject: a utility / access vecné bremeno (lines, pipes, right of way) or a predkupné právo of the state or a municipality. `LV_SOFT_FLAGS_REJECT=1` rejects these too — a judgement call for you or your lawyer |

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
Claude read says otherwise. A report with no part C, or one cut short at
the reader's length cap (`LV_TEXT_MAX_CHARS` in `kataster_scraper.py`), is
never called clean: it stays UNVERIFIED. Matching is inflection-aware ("začatie exekúcie",
"záložným právom"). An easement is read within its own entry (up to the next
entry number), so a neighbouring entry's wording can't soften it.

The optional Claude read (`ANTHROPIC_MODEL_LV`, default `claude-opus-5-5`, high
effort, server-side refusal fallback) is sent **part C whole** — parts A and B
are shortened on a long LV, never part C. It used to see only the first 6,000
characters, which on a long LV stopped before the encumbrances. Its "safe" can
clear a lien the screen couldn't attribute; it cannot clear distress, nor any
hit on an LV the cadastre report was cut short on. Description parsing and
address normalisation use `ANTHROPIC_MODEL_BULK` (default `claude-haiku-5-5`,
low effort).

The screen's rules were written without live LV reports to check them
against. `tests/fixtures/lv/` holds LV texts with their expected verdicts — so
far only **synthetic** ones. Add real, anonymised LVs with
`dev/capture_lv_fixture.py` (from a Slovak IP; see the README there) and each
becomes a regression test.

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
| CZ_CUZK_API_KEY | registrace.cuzk.gov.cz (free) | Czech LV check: the building under a listing's pin, its LV and pending proceedings |

> LV debt checking needs **no key**: ÚGKK SR has no public API, so
> `kataster_scraper.py` scrapes kataster.skgeodesy.sk directly (unofficial —
> may break if the portal changes). Listings it cannot verify are stored and
> shown as ⚠ UNVERIFIED, never as clean.

---

## Backups

Before each scheduled run, the scheduler writes to `backups/` in this folder
(on your computer, outside Docker's volume — `docker compose down -v` can't
delete it):

- `sovereign-YYYY-MM-DD.db` — a full copy of the database, as it was before
  that day's first run;
- `your-data-YYYY-MM-DD.json` — what you typed: deal stages and their
  history, notes and vibe scores, contract drafts, the flat LV numbers you
  entered, and enough of each listing to find it again. Readable without the
  app.

The newest 14 of each are kept (`BACKUP_KEEP` in `.env`). Back up now, or put
a copy back:

```powershell
docker compose exec dashboard python -m modules.backup
docker compose stop scheduler
docker compose exec dashboard python -m modules.backup restore backups/sovereign-2026-10-08.db
docker compose start scheduler
```

Restore goes through SQLite rather than copying the file over, so a leftover
write-ahead log can't corrupt the restored database.

---

## Docker Commands (PowerShell)

```powershell
docker compose up -d --build --remove-orphans   # Start everything (rebuilds after a code update)
docker compose down         # Stop everything (keeps the database; `down -v` deletes it)
docker compose logs -f      # Live logs
docker compose ps           # Container status
docker compose restart      # Restart all
```

The local Mistral model (`model-runner`) is gone: nothing used it. If an older
setup pulled it, reclaim the space with
`docker image rm ai/mistral:7b-instruct-q4_k_m` and `docker volume rm` on the
volume `docker volume ls` lists as `<this folder's name>_model_cache`.

---

## Legal

- Contract drafts are **DRAFT ONLY** — no legal validity
- Always use **Notárska úschova** for fund transfers
- Re-verify LV **48 hours before signing** — titles change
- s.r.o. structuring requires a licensed Slovak **účtovník**
- This tool provides data scoring only — not investment advice

### Before this becomes a product

The tool is built for one person's own purchases. Selling access to its feed
(the €500/month subscription idea) or assigning deals for a fee changes the
legal position, and needs advice from a Slovak lawyer **before** it starts:

- **Portal terms.** nehnutelnosti.sk is read through a real browser to get
  past its WAF; bazos.sk and topreality.sk are scraped too. Their terms of use
  and database rights govern reusing — let alone reselling — that data.
- **The cadastre.** `kataster_scraper.py` scrapes kataster.skgeodesy.sk
  unofficially; ÚGKK offers no API or licence for it, and the site geo-blocks
  many foreign IPs.
- **Personal data (GDPR).** The `cadastre_cache` table keeps owner names,
  registered addresses and full LV texts; listings and notes can name sellers
  and agents; contract drafts name buyers. Using that beyond your own
  purchases needs a legal basis, a retention limit and a privacy notice.
- **Brokerage.** Arranging sales between other people for a fee is
  real-estate brokerage: it needs the right trade licence, and estate agents
  carry anti-money-laundering duties.
- **Investment advice.** A paid feed that ranks properties as "deals" may be
  read as advice; the "not investment advice" line above is not enough on its
  own.

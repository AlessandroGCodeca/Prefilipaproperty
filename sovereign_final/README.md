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
below. `restart.sh` also serves it to this computer only.

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
it). CI also runs `ruff check .` (the rule set is in `pyproject.toml`) and
runs the suite on Python 3.11, 3.12 and 3.14, and on Windows.

`tests/test_nehnutelnosti_browser.py` runs the Nehnutelnosti.sk scraper in a
real Chromium against a fake site on 127.0.0.1, with no internet needed. It is
skipped unless Playwright and its browser are installed
(`playwright install chromium`). CI runs it in a job of its own, so a
Playwright or Chromium upgrade is tested too.

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
  convert CZK at one rate: the Czech National Bank's daily fixing, fetched
  before each scheduled run and at most hourly by the dashboard
  (`modules/fx_rate.py`, saved to `data/fx_rate.json`) and shown with its date
  in the sidebar. The sidebar warns when the rate is more than a week old.
  `CZK_PER_EUR` / `FX_RATE_DATE` in `config.py` are the fallback until the
  first fetch; setting `CZK_PER_EUR` in `.env` pins the rate by hand. Czech
  cards use Czech labels and Czech number formatting (`4 500 000 Kč`).
- **Pipelines**: each market has its own steps, status line, success record
  and retries. Both run one after the other under the one pipeline lock, and
  a failure in one never stops the other (`scheduler.run_all_markets`).

### Czech sources

| What | Source | State |
|---|---|---|
| Listings | Bezrealitky.cz (website sitemap + listing pages; never api.bezrealitky.cz, which robots.txt closes), Reality.iDNES.cz, Bazoš (reality.bazos.cz) | read when robots.txt allows; each fails soft |
| Listings | **Sreality.cz — left out**: its robots.txt gives every crawler but the named search engines `Disallow: /` | parser kept (`scraper/sreality.py`); 🔗 TEST CZ SITES re-checks |
| Rentals (comps) | Bazoš `/pronajmu/byt/`, Bezrealitky rental pages | `scraper/rentals_cz.py` → `engine/rent_comps_cz.py` |
| Rent baseline | Deloitte Rent Index Q2 2026 — asking rents of flats that let, as on the portals (the measure MF's official rent map uses), not contract rents: Praha 462 and Praha 1–10 (442–493), Brno 390, Hradec Králové 318, Pardubice 314, Plzeň 301, Olomouc 296, Liberec 289, Zlín 287, České Budějovice 283, Jihlava 257, Ostrava 254, Karlovy Vary 246, Ústí nad Labem 221 Kč/m² | other towns: live comps only, or not scored |
| Sale-price benchmark | ČSÚ open dataset **CEN0402** (Průměrné kupní ceny nemovitostí – data ČÚZK): the average purchase price per m² of flats in 2025 for all 14 kraje and 76 okresy, from the cadastre's record of each transfer with a stated price — e.g. Praha 131 520, Brno-město 99 713, Plzeň-město 73 399, Sokolov 33 203 Kč/m². Prague's and Brno's districts take their city's figure × how their listings' asking prices compare with the whole city's (`engine/price_comps_cz.py`, 8+ listings in the district, 30+ in the city); until then the city's figure, which the card says | `engine/cz_regional_prices.csv`, rebuilt by `dev/build_cz_regional_prices.py`; `data/cz_regional_prices.csv` overrides rows |
| Title deed (LV) | the flat's **výpis z LV, pasted on its card** (or, once rejected, in the REJECTED tab), screened with Czech vocabulary — PASS / REJECTED / UNVERIFIED as in Slovakia. PASS needs part C in the text and the výpis to run on to part E (so a page cut off inside C or D can't pass), the flat's unit in part B, every entry of parts C–D to be one the screen knows, the LV number and k.ú. to match the card's, and a výpis no older than `CZ_LV_MAX_VYPIS_AGE_DAYS` (30 days, read from its "stav evidovaný k datu" line); the building's own LV (the number the card shows for the plot, with no units) is never taken as the flat's; a cooperative flat (its ad, or a družstvo owning it in part A) is never PASS | ČÚZK's free services give no LV contents to a program; nahlížení is CAPTCHA-guarded |
| Cadastre lookups | ČÚZK API KN (free key: `CZ_CUZK_API_KEY`) + RÚIAN address points: the building under the pin, its LV and pending proceedings | never PASS on its own |
| Flood | ÚÚR national map, VÚV T. G. M. Q100 flood areas (indicative) | `modules/risk_data_cz.py` |
| Noise | OpenStreetMap proxy + 2022 strategic noise map of main roads (MZ ČR) | ≥65 dB flags the flat |
| Place names | RÚIAN okres names, Prague 1–22, Brno's districts; Czech locatives ("v Praze 2", "ve Zlíně"); every obec when `data/cz_obce.csv` (a RÚIAN export) is present | `scraper/czech_cases.py` |
| Tax, mortgage, costs | ZDP 2026, ČNB limits (LTV 80 % / 70 % for investment mortgages from 1 Apr 2026), Swiss Life Hypoindex rate, SVJ fond oprav, daň z nemovitých věcí (zákon 338/1992 Sb.; the coefficients of Prague, the 26 statutory cities and the 105 other towns over 10,000 people from their 2026 ordinances in sbirkapp.gov.cz; every municipality's size coefficient from its population, ČSÚ 1.1.2025; Prague quarters and postal districts, Ostrava quarters and city quarters' cadastral areas from ČÚZK RÚIAN — `dev/build_cz_property_tax_data.py` rebuilds `engine/property_tax_cz_data.json`), katastr fee | `markets.py`, `engine/property_tax_cz.py`, each with its source and date |
| Contract | a Czech **kupní smlouva NÁVRH** for a Czech advokát or notář to review — not legal advice | `modules/contract_draft_cz.py` |

No Czech host could be reached from the container most of this was built in.
Every endpoint, page shape and figure above came from published documentation,
open-source collectors and web search — except the sale-price benchmark, read
from ČSÚ's open-data download on 2026-11-06 — and each scraper checks
robots.txt live before it reads anything.

### UNVERIFIED — figures and endpoints that could not be confirmed

Each is marked `UNVERIFIED` in its own source / checked field. The env settings
named here override them. The cash-flow figures once on this list — the rent
index's measure, the ČNB stress add-on, the SVJ správa fee, purchase costs,
s.r.o. costs, the balcony and furnished premiums and exit costs — were checked
against a source on 2026-11-05; [docs/M1_VERIFICATION.md](docs/M1_VERIFICATION.md)
gives each source and what changed.

1. Czech sale-price benchmark: ČSÚ's figure is a mean of contract prices for 2025, judged against a listing's 2026 asking price — both differences make a Czech listing look dearer than it is, so fewer come out GREEN, never more. The rooms multiplier for it is 1.0 (ČSÚ gives no split by size). A Prague or Brno district without enough listings is judged against its whole city's figure.
2. Property tax in a Czech municipality outside the hand-checked tables (Prague, the statutory cities and the 105 other towns over 10,000, read from their 2026 ordinances: `engine/property_tax_cz.SOURCE`): its size coefficient follows its population, and its local coefficient is 1.0 (the law's when a municipality sets none, or `CZ_PROPERTY_TAX_LOCAL_COEF`) until 🏛️ UPDATE TAX RATES has read its ordinances (see "Czech property tax" below) — and after it where an ordinance couldn't be read (an old .doc file or a scan, listed on the TAX RATES tab) or was misread. A place that names no municipality is taxed at 3.5.
3. Personal tax: whether an SVJ fond oprav payment is deductible when paid (modelled) or only when spent; the 40 mil. Kč cap on an exempt sale (not modelled).
4. SVJ fond oprav 20 Kč/m² (`CZ_SVJ_FOND_OPRAV_PER_M2`): inside every published range (15–50), but no national statistic exists — the building's own předpis záloh is the real figure.
5. s.r.o. loan terms: +1 pp on the rate and 70 % LTV, carried over from Slovakia (`CZ_SRO_RATE_PREMIUM_PP`, `CZ_SRO_LTV_RATIO`).
6. The parking rent premium (+5 %): MF's rent map prices a garage at +13–25 % of its reference rent and an outdoor space at nothing measurable, and the description flag doesn't tell them apart. The semi-furnished premium (+5 %): MF has no such class.
7. Hold-period growth rates (price and rent growth, cost inflation): the Slovak profile's — forecasts, which no source can confirm (`CZ_APPRECIATION_RATE`, `CZ_RENT_GROWTH_RATE`, `CZ_COST_INFLATION_RATE`).
8. ČÚZK API KN paths and fields (from its OpenAPI document as copied in January 2025) and the RÚIAN address layer (layer 1, field `kod`).
9. The ÚÚR flood layer (82) and the noise map's REST path and value encoding.
10. The výpis z LV layout the Czech screen reads (part headings, "Oprávnění pro", the "o" entry bullet, the V-/Z-/POLVZ/PV register numbers, the "Kat.území" line); without a part C heading it reads the whole text and never calls the title clean.
11. Portal page shapes: Sreality's v1 API, Bezrealitky's sitemap and `__NEXT_DATA__` advert, iDNES's country-wide search and parameter list, Bazoš CZ's cards (taken as the Slovak site's).
12. Each portal's robots.txt, as captured by an open-source collector on 2026-09-15 — the scrapers read it live, keeping a copy a day at most (a missing one an hour).

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (11 tabs in 3 groups): the page, top to
│                               bottom; each part is drawn by dashboard/
├── dashboard/
│   ├── sidebar.py            ← Pipeline status, step buttons, filters
│   ├── actions.py            ← What each pipeline button runs (as a job)
│   ├── view.py               ← One run's page state: the market picked, the
│   │                           filtered listings, sorted by class
│   ├── overview.py           ← Banners, stats tiles, price cuts over the tabs
│   ├── listing_cache.py      ← The cached reads (listings, price history, stages, vibes, price cuts), and when they are cleared
│   ├── cards.py              ← The listing card and its memo button
│   ├── fmt.py                ← Money, badges, labels (Czech on a Czech card)
│   ├── diagnostics.py        ← 🔗 TEST SITES / TEST CZ SITES
│   ├── style.py, login.py, demo.py
│   └── tabs/                 ← One module per tab, each with render(view):
│                               triage, snag_list, map_view, what_if,
│                               deal_pipeline, satellite, rejected, lv_todo,
│                               rent_comps, tax_rates, close
├── scheduler.py              ← Daily 06:00 CET automation, retries a failed run
├── config.py                 ← All 2026 Slovak tax rates
├── markets.py                ← Market registry: the SK and CZ profiles
├── database/                 ← SQLite storage, one module per topic; `import
│   │                           database` re-exports every name
│   ├── __init__.py           ← get_conn (tests swap it here)
│   ├── schema.py             ← Schema, init_db and its column migrations
│   ├── listings.py           ← Sale listings: upserts, active/rejected, copies
│   ├── prices.py             ← Price history, cuts, days on market
│   ├── enrichment.py         ← Description and address parsing queues
│   ├── scores.py             ← Cashflow and location scores, requeue rules
│   ├── title_deeds.py        ← LV checks, deed text, parcels, LV to-do
│   ├── deals.py              ← Deal stages, vibe notes, contract drafts
│   └── pipeline.py           ← The pipeline lock
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
│   ├── property_tax_rates.py ← Each Slovak town's flat property-tax rate, read from
│   │                           its own ordinance or rate page (🏛️ UPDATE TAX RATES)
│   ├── tax_coefficients_cz.py ← Every Czech municipality's coefficients, from its
│   │                           ordinances in sbirkapp.gov.cz
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
│   ├── regional_prices_cz.py ← Czech kraj / okres / Prague / Brno lookup (ČSÚ CEN0402)
│   ├── cz_regional_prices.csv ← its shipped figures (dev/build_cz_regional_prices.py)
│   ├── price_comps_cz.py     ← Prague / Brno district levels from the listings
│   ├── rent_cz.py            ← Czech rent baseline (Deloitte Rent Index Q2 2026)
│   ├── rent_comps_cz.py      ← Live Kč/m² rents from Czech rentals
│   ├── property_tax_sk.py    ← Daň z bytov on a Slovak flat (€/m² by town)
│   ├── property_tax_cz.py    ← Daň z nemovitých věcí on a flat (every municipality's
│   │                           coefficients once 🏛️ UPDATE TAX RATES has read them)
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
│   ├── tax_rates.py          ← 🏛️ UPDATE TAX RATES (Slovakia): apply, confirm or review
│   ├── tax_rates_cz.py       ← 🏛️ UPDATE TAX RATES (Czechia): every municipality
│   └── backup.py             ← Daily database copy + export of your data
└── dev/                      ← Debug probes: LV check, nehnutelnosti, topreality
```

---

## Dashboard Tabs

The eleven tabs sit in three groups (one row of eleven overflowed at 1440 px):

- **🎯 DEALS** — TRIAGE TABLE, ACTIVE SNAG LIST, MAP, SATELLITE VIEWER
- **📊 ANALYSIS** — WHAT-IF / TAX, RENT COMPS, TAX RATES
- **🗂 WORKFLOW** — DEAL PIPELINE, LV TO-DO, REJECTED, ONE-CLICK CLOSE

| Tab | What it does |
|-----|-------------|
| TRIAGE TABLE | Flat, sortable view of every scored listing — grade, price, **max offer** (🟡/🟢), ask vs max offer, below-market %, rent, surplus, **+2 pp stress**, gross yield, cap rate, **IRR**, **days tracked** (since the first scrape — not the portal's posting date), **price change**, **portals**, deal stage, vibe, LV status, **⛔ cash-flow negative** |
| ACTIVE SNAG LIST | 🟢🟡 deal cards, 25 a page per class, each built when you open it (⚪ WHITE listings are one table, not cards): cost breakdown (the s.r.o.'s own loan and running cost), financing stress (+2 pp, 70% LTV), location risk with sources, price history, other portals' copies, deal stage, vibe notes, **PDF memo**, LV status and flat-LV verify; a ⛔ CASH-FLOW NEGATIVE badge and a ⚠ rent-fallback warning where they apply |
| MAP | Every listing with coordinates, coloured by class (faded = area-level geocode) |
| WHAT-IF / TAX | The tax toggle calculator: any listing (or a custom one) re-run with your own price, rate, LTV, term, rent, hold period, growth and exit costs, and the s.r.o.'s loan premium, LTV and running cost — personal vs s.r.o. side by side, rate-shock table, IRR, max offer |
| DEAL PIPELINE | Board of the deals you're working: WATCHING → VIEWING → OFFER → NEGOTIATING → DUE DILIGENCE → NOTARY → CLOSED / PASSED, with a timeline per deal |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score, and every note saved for the listing |
| REJECTED | Every LV rejection with its reason, detail and LV risk read; re-verify from here |
| LV TO-DO | Every GREEN / YELLOW deal whose title deed isn't verified, with what the plot check found; type the flats' own LV numbers in bulk, then save (checked on the next LV run) or save & verify now (in the background, like the pipeline buttons) |
| RENT COMPS | Live €/m² per district from prenájom listings vs the baseline table; in the Czech view, live Kč/m² per town vs the Deloitte Rent Index, and the Czech towns whose listings wait unscored for a rent figure |
| TAX RATES | Slovakia: each town's flat property-tax rate — what the engine charges, what the town's own site says, and the source; a doubtful reading waits here to be accepted or turned down, and a town whose site blocks automated requests takes an uploaded ordinance. Czechia: every municipality's size and local coefficients with the ordinances they come from, and a lookup by place. One click re-reads both countries |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download; the deal's numbers are a separate download, not part of the draft |

A 🔻 banner above the tabs lists price cuts from the last 14 days (the 50
latest, built when you open it), and says
whether the new price now sits inside the max YELLOW offer.

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + discount to the regional median), location, energy class,
condition and risk flags — so a GREEN deal in a poor location doesn't outrank
a genuinely solid one. An LV that is verified clean scores above an unverified one.
A listing with no regional median earns none of the discount points, so it
can't outrank one that is measured against its market.
A price below the sanity floor gets no grade ("—"): it is a data error, not a deal.

---

## Pipeline (Sidebar Buttons)

**▶ RUN EVERYTHING** sits at the top of the sidebar; the step buttons are in
three groups under it, each folded until you open it:

- **📅 DAILY RUN — step by step**: the steps of the daily run, in its order —
  each portal by its full name and flag (🇸🇰 Nehnutelnosti.sk, 🇸🇰 Bazos.sk,
  🇸🇰 Topreality.sk, 🇨🇿 Bezrealitky.cz, 🇨🇿 Reality.iDNES.cz, 🇨🇿 Bazos.cz),
  then 🔎 FILL MISSING DETAILS, 🏘️ RENT COMPS, 🔒 LV DEBT FILTER, 🗺️ NORMALIZE
  ADDRESSES, 📝 PARSE DESCRIPTIONS, 💰 CASHFLOW SCORE, 📍 LOCATION IQ,
  🌊 RISK BACKFILL, 📡 MERGE PORTAL COPIES
- **🔧 REPAIR DATA**: ♻️ RESCORE ALL, 📝 RE-PARSE (new fields), 🏛️ UPDATE TAX
  RATES, 🧹 CLEAN STALE (21d)
- **🩺 DIAGNOSTICS**: 🔗 TEST SITES, 🔗 TEST CZ SITES

```
portals → FILL MISSING DETAILS → RENT COMPS → housekeeping
        → LV DEBT FILTER → NORMALIZE ADDRESSES → PARSE DESCRIPTIONS → CASHFLOW SCORE
        → LOCATION IQ → RISK BACKFILL → MERGE PORTAL COPIES
```

**▶ RUN EVERYTHING** runs that whole chain for each market — the same run the
scheduler makes at 06:00, recorded the same way — for when no scheduler runs
(the Mac start above) or you want fresh data now. It takes a while (each
portal can take up to 30 minutes); the page stays usable.

**🔎 FILL MISSING DETAILS** re-reads nehnutelnosti listings saved without a
price, a size or a district (`enrich_pending.py`), retires the ones taken
down, and scores what it filled in. A listing with no price or size can't be
scored, and the daily scrape doesn't open its page again, so without this it
stays PENDING. The pipeline does it for up to 100 listings a run — and skips
it when nehnutelnosti blocked that run's scrape, as every read would only time
out — the button for up to 200. Bazos and Topreality listings aren't re-read.

**🏛️ UPDATE TAX RATES** re-reads every Slovak municipality's flat
property-tax rate from its own site and every Czech municipality's
coefficients from the official collection, and re-scores the listings whose
tax moved — see "Updating the rates with one click" and "Czech property tax"
below. It is not part of the daily run: rates change
once a year (most ordinances take effect on 1 January), so a click in December
or January, or after a town adopts a new ordinance, is enough.

Housekeeping = deactivate stale listings (>21d unseen) + flag dev projects.
The stale check runs per portal, and only for the portals that returned
listings this run: a portal that is blocked, or whose page layout changed so
the parser finds nothing, shows none of its listings, and "unseen" then says
nothing about them. A portal that runs without an error but returns no
listings fails its step, so the run reports it. Every scrape (the pipeline's
and a portal button's) records how many listings its portal returned
(`portal_runs`), and a portal with none, or a failure, on its last 2 runs gets
a ⚠ warning above the tabs until it returns listings again. 🧹 CLEAN STALE
leaves such a portal's listings alone too.
A nehnutelnosti listing is deactivated sooner, the moment any read of its page
finds a grid of similar listings where the listing was — that is what a
removed listing's URL serves.
Runs automatically every morning at 06:00 CET via scheduler container. When
the scheduler starts it runs the pipeline only if none has succeeded since the
last 06:00 (first start, the PC was off at 06:00, or the run failed) —
restarting Docker or the PC does not re-scrape a day that is already done. A
06:00 the computer slept through runs when it wakes, and a run that started
before 06:00 and ended after it is followed by the new day's run. Or click
buttons in sidebar to run manually anytime.

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

Czechia: `scraper/rentals_cz.py` reads pronájem listings from Bazoš and
Bezrealitky, and `engine/rent_comps_cz.py` builds Kč/m² per town the same
way. `engine/rent_cz.py` has the Deloitte Rent Index figures for Prague,
Praha 1–10 and the 13 regional capitals; a town outside it (Kladno, Opava,
Písek…) gets no borrowed rent, so its listings wait unscored until 5+ of its
rentals give it a live one. The Czech pipeline reads the rentals before it
scores; so do 🏘️ RENT COMPS (both countries) and a Czech portal's button
when no Czech rental was read in the last 20 hours. A line above the tabs
says how many Czech listings wait and in which towns; the RENT COMPS tab
lists them all, with the rentals each town has so far.

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
   lists every GREEN / YELLOW deal still waiting for one. RE-VERIFY LV reads
   the cadastre afresh; the daily run may use a copy read within
   `CADASTRE_CACHE_TTL_DAYS` (30). A shared LV with a
   flag on it stays UNVERIFIED until you've checked part C against the flat's
   number.

So the filter does not, on its own, keep debt-laden flats off the lists: it
rejects a flat only once its own LV has been read. Until then the flat is
⚠ UNVERIFIED — shown, never called clean.

The screen (`modules/lv_screen.py`) reads each encumbrance separately: a lien
passes only when its **own** creditor ("v prospech …") is a bank or ŠFRB, and
an exekúcia / konkurz / súdny spor — or a dražba (from part C on), výkon
záložného práva, predbežné opatrenie, zaistenie or a dispute over ownership —
never passes, not even when the optional Claude read says otherwise. A
leasing, insurance or factoring company of a banking group is not a bank. A report with no part C, or one cut short at
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

**Property tax** (daň z bytov, `engine/property_tax_sk.py`) is charged on the
flat's floor area, not its price: every started m² × the municipality's rate.
The act's default is 0.033 €/m² (zákon 582/2004 § 16), but each town sets its
own by VZN. The 2026 rates used:

| Place | €/m² a year |
|--|--|
| Bratislava, by pásmo | A 1.20 (Vajnory, Podunajské Biskupice, Vrakuňa, Devínska Nová Ves) · B 1.20 (Dúbravka, Karlova Ves, Lamač, Devín, Rača, Záhorská Bystrica, Jarovce, Rusovce, Čunovo) · C 1.25 (Nové Mesto, Petržalka) · D 1.35 (Staré Mesto; Ružinov, for its Nivy area) |
| Košice, by cadastral area | I 1.27 (Stredné Mesto) · II 1.207 (Terasa, Grunt, Furča, Južné Mesto, Nové Ťahanovce, Severné Mesto, …) · III 1.143 (Šaca, Myslava, Barca, Ťahanovce, Luník, Kavečany, …); a city part named without its area (Juh, Západ, KVP) 1.27 |
| Žilina, by cadastral area | 1.20 (Žilina, Závodie) · 1.10 (Bánová, Budatín, Žilinská Lehota and the other areas) |
| Liptovský Mikuláš, by cadastral area | 0.50 (Liptovský Mikuláš) · 0.45 (Bodice, Demänová, Liptovská Ondrašová, Okoličné, Palúdzka, Ráztoky) · 0.30 (Benice, Iľanovo, Ploštín, Svätý Štefan) |
| Zvolen, by zone | I 0.636 (the centre's streets) · II 0.588 (most other streets, listed one by one) · III 0.447 (Zolná, Lukové, Kráľová, Sekierska dolina, Bakova Jama); a listing that names no zone III part 0.636 |
| Čadca, by part | 0.40 (the town's streets) · 0.25 (the outlying settlements: Drahošanka, Čadečka, Podzávoz, Milošová, Vojty, Rieka, U Siheľníka) |
| Trnava · Banská Bystrica | 1.00 |
| Prešov | 0.953 |
| Trenčín | 0.88 |
| Nitra | 0.75 |
| Pezinok · Modra · Poprad | 1.00 |
| Piešťany | 0.75 |
| Trebišov | 0.71 |
| Dunajská Streda | 0.68 (Mliečany 0.61) |
| Prievidza | 0.675 |
| Malacky | 0.67 |
| Senec · Stupava · Michalovce · Bardejov | 0.60 |
| Ružomberok | 0.40 |
| Spišská Nová Ves | 0.398 |
| Humenné | 0.32 |
| anywhere else | 1.35 (UNVERIFIED: the highest rate above, not a legal ceiling) |

Martin, Považská Bystrica, Nové Zámky, Levice, Lučenec, Topoľčany and
Rimavská Sobota are not in the table: their sites block automated requests (a
CAPTCHA, a refused connection or "Access Forbidden") and they publish no
ordinance on CUET. Zvolen's site blocks them too, but Zvolen puts its
ordinances on CUET (cuet.slovensko.sk, the state's central official notice
board), where they were read. Komárno's current flat rate could not be pinned
to an adopted ordinance; Šamorín's (0.85) is added by the update below.

**Updating the rates with one click.** 🏛️ UPDATE TAX RATES (sidebar, or the
TAX RATES tab) reads every town's rate from its own site, in the background:
it starts at the town's tax page or list of ordinances
(`scraper/property_tax_rates.TOWNS`), follows the links to the property-tax
ordinance or rate sheet (skipping drafts, repealed ordinances and tax-return
forms), reads the PDF, Word file or page, and finds the flat rate — "0,60 € za
byty", "a) byty 0,675" under an "eur/m2" header, "… podlahovej plochy bytu
1,000 €" and the other ways towns write it — with the tax year it applies from
(the ordinance's účinnosť; a rate in force from any day but 1 January is first
charged the next year). What it does with a reading (`modules/tax_rates`):

| The site says | What happens |
|--|--|
| the rate the engine charges | ✅ confirmed |
| a new rate in a dated ordinance for a later year than the table's (2026) | 🔄 / 📅 stored, and charged from that year |
| a rate for a town the table lacks | ➕ stored and charged, instead of the 1.35 fallback |
| another rate for a year the table covers, several flat rates, two documents that disagree, an undated ordinance for a new town, or a newer ordinance about flats it can't read | ⚠️ waits on the TAX RATES tab: accept it (it is then charged even over the table) or keep the table's figure |
| a change in a town rated by area (Bratislava, Košice, Žilina, Dunajská Streda, Liptovský Mikuláš, Zvolen, Čadca) | ⚠️ review only — the areas are mapped by hand in `engine/property_tax_sk.py` |
| nothing readable, or the site refuses the request | ❔ / ⛔ with the reasons; save the ordinance in your browser and upload it on the tab. A town that publishes on CUET (Zvolen) is read from there instead |

Then the listings whose tax moved are re-scored; the others keep their score.
The stored rates live in `property_tax_rates` (with the document and the words
each was read from); ↩️ Undo on the tab forgets a town's and charges the table's
figure again, and ➕ Add a town adds any other town with the page its search
starts from.

Run from a data centre on 6 November 2026, it read every reachable town in
the table at the table's own rate — Liptovský Mikuláš and Čadca from their own
sites, Zvolen from CUET — and added Šamorín (0.85 €/m², VZN 7/2024; its
amendment 5/2025 changes only other taxes). Prešov, Považská Bystrica, Levice,
Lučenec, Topoľčany and Rimavská Sobota answer automated requests with a
CAPTCHA there, and Martin and Nové Zámky reset the connection — from a home
connection these usually open; if not, upload the ordinance. Bardejov's tax
pages answered 404 that day (the table keeps its checked 0.60). Stupava and
Komárno gave no readable current rate (their sites link older ordinances, or
none). A scanned PDF can't be read: Malacky's newest
consolidated text and Spišská Nová Ves's ordinance are scans (their tax pages
state the rate). `python -m scraper.property_tax_rates [town …] -v` prints
what it reads, page by page.

**Every other Slovak municipality.** Beyond those towns the button reads all
~2,900 Slovak municipalities, each from the home page of its official website
(the list and the sites come from Wikidata, refreshed monthly): it follows the
site's menu to its ordinances, the property-tax ordinance first, and stops at
the first dated rate. A municipality any listing is in is read on every click;
the others at most once a month, as many as fit in 25 minutes a click (the
never-read first) — the summary says how many are still due. Several
municipalities share a name (four Porúbkas): such a one is charged its rate
only when the listing names its district too. The first click, from a data
centre in November 2026, read 487 municipalities: 83 villages gained their own
rate (0.03–0.85 €/m², 0.16 on average, instead of the 1.35 fallback), 19 went
to review, 107 sites refused the request and 255 had no rate a program can
read — most often a scanned ordinance. A village that matters to you and isn't
read: upload its ordinance on the tab.

### Czech property tax

A Czech flat (a zdanitelná jednotka) pays floor area × 1.22 × 3.50 Kč × the
municipality's **size coefficient** × its **local coefficient** (zákon
338/1992 Sb., `engine/property_tax_cz.py`). The size coefficient follows the
population (§ 11 odst. 4: 1.0 / 1.4 / 1.6 / 2.0 / 2.5 / 3.5; every statutory
city and four spa towns 3.5; Prague 4.5), counted as in the Finance Ministry's
decree in force on 1 January (§ 12f), and an ordinance may raise it a step in
chosen cadastral areas or city parts (§ 11 odst. 5). The local coefficient
(0.5–5.0, § 12) is 1.0 unless an ordinance sets it — for the whole
municipality, a cadastral area or city part, or the group of flats.

Prague, the 26 statutory cities and the 105 other towns over 10,000 people
are charged from hand-checked tables of their ordinances in force for 2026
(`PRAHA_DISTRICTS`, `CITY_COEFFICIENTS`, `TOWN_COEFFICIENTS`), with ČÚZK's
RÚIAN telling which city part or cadastral area a quarter lies in ("Praha 9 -
Černý Most" is city part Praha 14). Every other municipality's size
coefficient follows its population (`engine/property_tax_cz_data.json`).

🏛️ UPDATE TAX RATES reads both coefficients for all 6,258 municipalities
(`modules/tax_rates_cz`, `scraper/tax_coefficients_cz`):

- the population of every municipality from the Czech Statistical Office's
  open data (once a year);
- every valid ordinance on the coefficients from the Sbírka právních předpisů
  územních samosprávných celků (sbirkapp.gov.cz), where every municipal
  ordinance since 2021 is published — each read once, since a published
  ordinance never changes;
- the municipality behind each ordinance's publisher (by IČO, from ARES).

It combines them as the act says: an ordinance counts for a tax year only if
it was published by 1 October before it and is in effect on 1 January (§ 16a);
a repealed one stops counting; an amendment's new annex replaces its
ordinance's; the group of flats or an area replaces the municipality's own
coefficient, and the higher of group and area counts (§ 12 odst. 5–8).

How the engine uses what it read:

| Place | 2026 | A later year |
|--|--|--|
| In the hand-checked tables | the table | the reading, if it differs from the same reading for 2026 (a new ordinance, a population band crossed); otherwise the table |
| Any other municipality | the reading | the reading |
| Not read yet | the size coefficient by population × local 1.0 (UNVERIFIED) | the same |

A listing is charged its city part's or area's coefficients where it names one
("Praha 3": size 5 × local 2 — 2,590 Kč a year on 60 m², against 1,749 Kč in
Praha 2), its city's highest where it names none, and a municipality whose
name several share by its district (the dearest of them where none is named).

The first run (3½ minutes; about a minute after that) read 2,147 ordinances of
1,775 municipalities — 772 set coefficients for 2026, the rest from 2027. 231
couldn't be read (an old .doc file or a scan); the tab lists them with links,
and those municipalities pay the act's figures. An ordinance from before 2021
that was never put in the collection isn't seen either. Checked against the
hand-checked tables, the reading gave the same coefficients for 101 of their
132 places. Where it read an ordinance, it was right for 63 of 73. Of the
other 31, most missed an ordinance's coefficients and fell back to the act's.
Against the act's local 1.0, it came closer to the table in 61 places, further in 2.

Each figure was read from the act and the city's own ordinance or tax page in
November 2026; `property_tax_sk.SOURCE` names each document. Prešov's comes
from its tax page as quoted by web search, because presov.sk answers automated
requests with a CAPTCHA. A 60 m² flat pays €19–81 a year at these rates; until
October 2026 the engine charged 0.4 % of the price, roughly ten times as much.

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

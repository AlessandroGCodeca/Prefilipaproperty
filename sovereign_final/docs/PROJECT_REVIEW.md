# Sovereign — Project Review

**5 November 2026 · `main` at commit 7ce45e9 · Slovakia and Czechia**

This review covers what the project does, what is wrong with it or missing, and
what to work on next, ranked by severity and impact. It ends with ideas for the
dashboard.

## 1. Summary

The code is in good shape. No crash, wrong-number or security bug turned up in
this pass. That is consistent with the six earlier audits, which fixed many
issues. One test-only bug was found and fixed: the test suite opened the real
database file (section 4).

| Check | Result |
|--|--|
| Test suite | 3,578 tests pass |
| Lint (CI's `ruff E9,F`) | clean |
| Every dashboard tab, clicked in a real browser | no errors |
| Financial engine, 3,000 random and extreme inputs in both markets | no crash, no NaN or infinite result |
| 20,000 listings in the database | the dashboard stays usable (about 1–2 s per click) |
| Network exposure | every launcher binds to `127.0.0.1` |
| Raw HTML in the dashboard | listing text is escaped |
| HTTP calls | every one has a timeout |

What needs work is mostly **coverage and data** rather than code:

- **The Czech market is only half-working.** No Czech listing can be graded
  green or yellow, and most Czech towns have no rent figure, so their listings
  are never scored (H1, H2).
- **A broken portal's listings disappear without a warning.** When one portal
  stops returning listings while another still works, the broken portal's
  listings are retired after 21 days, and the run still reports success (H3).
- **The tax tables expire on 1 January 2027.** That is eight weeks away (H4).

**The five things to do first:**

1. Load Czech sale-price medians (H1).
2. Add Czech rent figures, or make sure Czech rental comps run (H2).
3. Retire stale listings per portal and alert when a portal goes quiet (H3).
4. Add the 2027 tax tables before January (H4).
5. Test the browser scraper in CI (M3).

## 2. What the project does

Sovereign finds flats for sale in Slovakia and Czechia that are priced below
the market. It works out their cash flow under Slovak or Czech tax and lending
rules, screens their title deeds for debts, and tracks the ones worth pursuing
through to a purchase-contract draft.

It runs as two processes on one SQLite database (`data/sovereign.db`):

- **the dashboard** (Streamlit, `app.py`);
- **the scheduler** (`scheduler.py`), which runs the whole pipeline every day
  at 06:00 CET.

Docker runs both. On a Mac, `Start Sovereign.command` runs the dashboard
without Docker.

### 2.1 The daily pipeline

The Slovak pipeline has 14 steps and the Czech one has 13. Each step can also
be run from a sidebar button.

| Step | What it does |
|--|--|
| Backup | A daily copy of the database, plus a plain export of your notes, stages and drafts (`modules/backup.py`). |
| Scrape portals | **Slovakia:** Nehnutelnosti.sk (through a headless browser), Bazoš.sk, Topreality.sk. **Czechia:** Bezrealitky.cz, Reality.iDNES.cz, Bazoš.cz. Sreality.cz is left out on purpose: its robots.txt disallows crawlers. |
| Fill missing details | Re-reads Nehnutelnosti listings saved without a price, size or district, and retires those that are gone (`enrich_pending.py`). |
| Rent comps | Scrapes rental listings and builds live rent per m² for each district (`scraper/rentals*.py`, `engine/rent_comps*.py`). |
| Housekeeping | Retires listings not seen for 21 days and flags developer projects. |
| LV debt filter | Screens the title deed (list vlastníctva / vlastnictví) for liens and encumbrances. Each listing gets PASS, REJECTED or UNVERIFIED (`modules/debt_bot.py`, `lv_screen*.py`, `cuzk_cz.py`). |
| Address normalisation | Cleans the district and city of each listing. |
| Description enrichment | Reads the ad text for parking, balcony, furnishing, renovation and similar features (`scraper/textparse.py`; optional Claude enrichment in `llm_enrichment.py`). |
| Cash-flow scoring | Runs the financial engine on every unscored listing (`modules/cashflow_runner.py`). |
| Location IQ | Geocodes each listing and scores transit, amenities, flood, noise and construction risk (`location_iq.py`, `risk_data*.py`). |
| Risk backfill | Fills in risk flags for listings scored before those sources existed. |
| Merge portal copies | Links the same flat listed on several portals and shows one copy: the one whose title deed was verified, otherwise the cheapest (`engine/duplicates.py`). |

### 2.2 The financial engine (`engine/financial.py`)

For each listing the engine estimates:

- the rent;
- the mortgage, using the NBS or ČNB loan-to-value caps and a stress add-on;
- HOA or SVJ fees, property tax, vacancy, maintenance and management;
- income tax and health levies, worked out twice: as a private person and as an
  s.r.o. (company with dividend tax), with set-up and running costs and a
  break-even point.

It then grades each listing:

- **GREEN, YELLOW or WHITE** by how far the price per m² sits below the
  regional median;
- **a composite deal grade from A to D** that combines yield, discount to
  market, location, energy class, condition and risk.

The **property tax** is its own module for each country, and is worked out from
each town's ordinance:

- **Slovakia** (`property_tax_sk.py`): a rate per m², by town and, where a town
  sets one, by cadastral area.
- **Czechia** (`property_tax_cz.py`): the size coefficient for the
  municipality's population and the local coefficient, using the act's rounding
  (§ 11d).

The 🏛️ UPDATE TAX RATES button refreshes both from the towns' own documents.

### 2.3 The dashboard

A market switch at the top filters all of the following to Slovakia, Czechia or
both:

- the KPI tiles (total, green, yellow, white, rejected, pending);
- the 11 tabs.

| Tab | What it shows |
|--|--|
| TRIAGE TABLE | Every scored listing, sortable, ranked by deal grade, with price, discount, yield and cash flow. |
| ACTIVE SNAG LIST | Green and yellow deals as expandable cards: full cost breakdown, personal vs s.r.o., rent source, price history, portal copies, deal stage, LV re-check and a PDF memo. |
| MAP | The listings on a map. |
| WHAT-IF / TAX | Re-runs any listing, or a custom one, with your own price, financing, rent and hold assumptions, as a person or as an s.r.o. |
| DEAL PIPELINE | A board of tracked deals by stage, with notes and stage history. |
| SATELLITE VIEWER | An aerial view of a listing's location. |
| REJECTED | Listings rejected on their title deed, and why. |
| LV TO-DO | Green and yellow deals whose title deed hasn't been read yet, with an editor to fill in what the check needs. |
| RENT COMPS | The live rents per m² the scoring uses. |
| TAX RATES | The property-tax rate each town is charged, and the updater's findings to accept or keep. |
| ONE-CLICK CLOSE | A purchase-contract draft: a Slovak notary contract, or a Czech kupní smlouva for an advokát. |

The sidebar holds a ▶ RUN EVERYTHING button, one button per portal, one per
pipeline step, the filters, and 🔗 TEST SITES (which checks the portals can be
reached). A password gate (`DASHBOARD_PASSWORD`) protects the page when it is
reachable from a network.

### 2.4 Module map

| Area | Modules |
|--|--|
| Dashboard and automation | `app.py` (3,106 lines), `scheduler.py`, `modules/jobs.py`, `modules/pipeline_state.py` |
| Storage | `database.py` (SQLite, migrations, the lock shared by the dashboard and scheduler) |
| Configuration | `config.py` (Slovak tax and lending rules, all settings), `markets.py` (the Slovak and Czech profiles) |
| Engine | `financial.py`, `property_tax_sk.py`, `property_tax_cz.py`, `regional_prices*.py`, `rent_comps*.py`, `rent_cz.py`, `duplicates.py` |
| Scrapers | `nehnutelnosti`, `bazos`, `topreality` (Slovakia); `bezrealitky`, `idnes`, `bazos_cz`, `sreality` (Czechia, Sreality not run); `rentals*`, `property_tax_rates`, `tax_coefficients_cz`, `_http`, `cz_common`, `textparse`, `geo` |
| Title deeds | `debt_bot.py`, `lv_screen.py`, `lv_screen_cz.py`, `lv_cz.py`, `cuzk_cz.py`, `kataster_scraper.py` |
| Location | `location_iq.py`, `risk_data.py`, `risk_data_cz.py` |
| Documents | `memo.py` (PDF memo), `contract_draft.py`, `contract_draft_cz.py` |
| Maintenance scripts | `enrich_pending.py`, `repair_prices.py`, `repair_districts.py`, `backfill_enrichment.py`, `diagnose.py`, `seed_market_data.py`, `dev/` |

## 3. Issues, ranked

**Severity:**

- **High:** wrong or missing results in normal use, or data lost without
  notice.
- **Medium:** weaker results in some cases, a risk that grows over time, or
  code that makes fixes slow.
- **Low:** housekeeping or a rare edge case.

**Effort:** S is under half a day, M is a few days, L is a week or more.

### High

**H1 · No Czech listing can be graded green or yellow** · Impact: all Czech deal finding · Effort M

- **The problem:** the Czech sale-price median tables (`OKRES_MEDIAN`,
  `KRAJ_MEDIAN` in `engine/regional_prices_cz.py`) are empty. No figure was
  invented, which was the right call, but without a median a Czech listing has
  no discount to market. It always comes out WHITE.
- **Evidence:** on a test database, all 15 scored Czech listings were WHITE
  with no regional median, while Slovak listings split green 2,099, yellow 795,
  white 2,142. README item "UNVERIFIED 1" says the same.
- **Fix:** load okres and kraj medians from a published source into the CSV
  that `regional_prices_cz.load_medians()` already reads. Alternatively, build
  live medians from the scraped Czech sale listings, the way rent comps are
  built.

**H2 · Most Czech listings are never scored** · Impact: Czech coverage · Effort M

- **The problem:** the Czech rent table (`engine/rent_cz.py`) has figures for
  only eight places: Prague, Praha 7, Brno, Hradec Králové, Pardubice, Jihlava,
  Ostrava and Ústí nad Labem. A listing anywhere else waits unscored until live
  rental comps exist for its town.
- **Evidence:** 21 of 36 test Czech listings were not scored ("no rent figure
  for 'Olomouc' in engine/rent_cz.py yet"). That included Plzeň and Olomouc,
  two of the largest Czech cities.
- **Fix:**
    - Add sourced rents for the remaining regional capitals (Plzeň, Olomouc,
    Liberec, České Budějovice, Zlín, Karlovy Vary).
    - Make sure the Czech rental scrape runs before scoring.
    - Show on the dashboard how many listings wait, and for which towns.

**H3 · A broken portal's listings are retired without a warning** · Impact: data loss, wrong counts · Effort S–M

- **The problem:** the housekeeping step retires every listing in a market not
  seen for 21 days. It skips only when no portal at all was read. A portal that
  runs without error but finds nothing counts as read (`scheduler._run_steps`).
  So if one portal is blocked, or its page layout changes so the parser finds
  nothing, while another portal works:
    - every listing from the broken portal is retired after 21 days;
    - the run still reports success;
    - nothing on the dashboard says a portal has gone quiet.
- **Evidence:** the code path is
  `_run_steps` → `_market_steps("sk", scraped)` →
  `deactivate_stale_listings(days=21, market=...)`, which filters by market,
  not by source. README item 13 notes the scrapers depend on each portal's page
  shape, which changes from time to time.
- **Fix:**
    - Retire per source, and only for portals that returned listings this run.
    - Record each portal's count per run, and flag on the dashboard a portal that
    returned 0 or failed on two runs in a row.

**H4 · The tax tables expire on 1 January 2027** · Impact: every figure from January · Effort M, every year

- **The problem:** `config.TAX_YEAR` follows the calendar. From January,
  scoring falls back to the 2026 rules. The dashboard warns, but the figures go
  stale.
- **What needs a 2027 version:**
    - Slovak and Czech income tax and levies;
    - the Czech inflation coefficient (§ 11f: CPI May 2026 over May 2023, rounded
    down);
    - the hand-checked property-tax tables (`TABLE_YEAR = 2026` in both
    countries);
    - the NBS and ČNB lending limits;
    - mortgage rates.

- **Fix:**
    - Add the 2027 tables in December.
    - Run 🏛️ UPDATE TAX RATES in January.
    - Re-check the README's January list.

### Medium

**M1 · Unverified model inputs** · Impact: cash-flow accuracy · Effort varies

The README lists 14 figures that could not be confirmed. The ones that move
cash flow most:

- whether the Deloitte rent index gives asking or achieved rents;
- Czech SVJ fees (0 Kč správa, 20 Kč/m² fond oprav);
- s.r.o. costs converted from Slovak figures;
- legal fees at 1 %;
- the parking, balcony and furnished rent premiums and the hold assumptions,
  carried over from Slovakia;
- the ČNB +2 pp stress add-on.

Each can already be overridden in `.env`. Verify them one by one against a
source.

**M2 · Some property tax still relies on fallbacks** · Impact: tax in smaller towns · Effort S (operational)

- **Czechia:** municipalities under 10,000 people use local coefficient 1.0
  until 🏛️ UPDATE TAX RATES reads their ordinances.
- **Slovakia:** towns outside the table pay the 1.35 €/m² fallback until it
  runs.
- **Blocked sites:** ten Slovak town websites refuse automated reads (Martin,
  Zvolen, Liptovský Mikuláš, Považská Bystrica, Nové Zámky, Levice, Lučenec,
  Topoľčany, Čadca, Rimavská Sobota).
- **Fix:** run the update, and for the blocked towns upload their ordinance
  PDFs on the TAX RATES tab. The Czech Financial Administration's own
  coefficient lookup could cover every municipality, but it refused
  connections from the review machine.

**M3 · CI never runs the browser scraper** · Impact: Nehnutelnosti.sk can break unnoticed · Effort S

- **The problem:** `.github/workflows/test.yml` leaves Playwright out of the
  test install, so a Playwright or Chromium upgrade is untested. Each upgrade
  also needs its own `playwright install chromium`: build 1248 for Playwright
  1.64.1.
- **Fix:** add a CI job that installs Chromium and runs the scraper's browser
  code against a local fake site. That job needs no network; the review used
  exactly this test.

**M4 · Every dashboard click re-runs database set-up** · Impact: dashboard pauses while the pipeline runs · Effort S

- **The problem:** `app.py` calls `init_db()` at the top of the script, and
  Streamlit re-runs the whole script on every click. Each call:
    - re-applies the schema;
    - runs six column checks;
    - runs two backfill updates and a delete;
    - commits, which takes the database's write lock.

    It takes 8 ms normally. But while the scheduler is committing a large batch,
    a click can wait up to the 30-second lock timeout.

- **Fix:** run it once per process, for example with `st.cache_resource` keyed
  by the database path.

**M5 · Listing data is reloaded on every click** · Impact: speed as data grows · Effort S

- **The problem:** loading the active listings took 0.39 s for 5,000 listings
  and grows linearly. A full rerun at that size took 1.1–1.9 s.
- **Fix:** cache the load with `st.cache_data` and a short time limit, and
  clear it when a pipeline step finishes.
- **Done:** `app.py` caches the load for 60 s (`LISTINGS_TTL_S`). A cache
  hit takes 0.02 s at 5,000 listings, against 0.36 s for the query. The cache
  is cleared when a sidebar step finishes and after the page's own LV
  re-checks and saves. A scheduler run shows within the time limit.

**M6 · Some errors are swallowed without a trace** · Impact: hidden failures · Effort M

- **The problem:** there are 107 broad `except Exception` handlers, most of
  them deliberate "fail soft" guards. A few return a fallback without logging
  anything. Two examples:
    - `property_tax_cz._load()` returns `{}` on any database error, so the
    updater's readings are silently ignored;
    - `tax_rates._with_listings()` returns an empty set, so villages that have
    listings lose their priority.

- **Fix:** log each at warning level with the exception type, and narrow the
  exceptions where the error type is known.

**M7 · A few very large files** · Impact: slower, riskier changes · Effort L

- **The problem:** `app.py` (3,106 lines: all 11 tabs and the sidebar),
  `database.py` (2,611), `scraper/nehnutelnosti.py` (1,634) and
  `engine/financial.py` (1,367).
- **Fix:** split the dashboard into one module per tab, and the database layer
  by topic (listings, scores, title deeds, tax, pipeline).

### Low

**L1 · CI lint is minimal** · Effort S

- **The problem:** CI checks only syntax errors and unused or undefined names
  (`E9,F`). Bug-finding rule sets such as bugbear (`B`) and pylint warnings
  (`PLW`) are not enforced. Today they flag only false positives, but nothing
  stops new findings.
- **Fix:** add a `ruff` section to a `pyproject.toml` with a curated rule set.

**L2 · CI tests only Python 3.12** · Effort S

- **The problem:** the launchers accept Python 3.11–3.14.
- **Fix:** add 3.11 and 3.14 to the CI matrix.

**L3 · A pandas deprecation inside Streamlit** · Effort S

- **The problem:** Streamlit 1.66.1 uses `reset_index(inplace=True)`, which
  pandas 3.1 deprecates (292 warnings per test run). It will break under
  pandas 4.
- **Fix:** don't accept pandas 4 until Streamlit supports it.

**L4 · Code kept only for its tests** · Effort S

- **The problem:** `location_iq.check_construction`, `location_iq.check_noise`
  and `bezrealitky.sale_flat_url` are called only by tests.
- **Fix:** delete them with their tests, or wire them in.

**L5 · Five old branches with unmerged work** · Effort S–M

- **The problem:** five branches from April to June hold 60 unmerged commits:
    - `fix-listings-scraping-2llB0` (34)
    - `polish-scoring-and-filters` (13)
    - `tests-and-sortable-table` (7)
    - `sidebar-filters` (3)
    - `rent-rooms-stale-devproj` (3)

    All five conflict with `main`.

- **Fix:** delete them, or pick out what is still wanted.

**L6 · A fixed EUR/CZK rate** · Effort S

- **The problem:** `config.CZK_PER_EUR = 24.355`, as of 14 October 2026. It
  feeds the combined ranking and some Czech cost conversions. Each card keeps
  its own currency.
- **Fix:** fetch the ČNB daily rate, and warn when the rate is more than a week
  old.

**L7 · Tax-rate updater housekeeping** · Effort S

- **The problem:** two small inefficiencies:
    - a list-membership test inside the scheduling loop runs over about 2,800
    villages;
    - a `requests.Session` is created per town and never closed.

- **Fix:** use a set for the membership test, and close each session.

**L8 · Sreality.cz is not scraped** · Effort none (by design)

Its robots.txt disallows crawlers, so the largest Czech portal is missing from
the data. 🔗 TEST CZ SITES re-checks it.

## 4. Cleanup done in this pass

These changes don't alter the app's behaviour. All 3,578 tests pass after
them, and CI's lint is clean.

- **Fixed: the tests opened the real database.** Six tests reached
  `database.get_conn()` with no test database of their own, through the Slovak
  property-tax engine's read of the municipality list. Five ran in the test
  process and one in a child Python process. On your machine they read the
  real `data/sovereign.db`, so their results could differ from CI's. In a
  fresh checkout they left an empty database file behind. An autouse fixture
  in `tests/conftest.py` now gives every test its own temporary database path,
  and the child process gets one too. A trace over the whole suite confirmed
  that nothing opens the real file any more.
- **Optional type hints:** 45 `Optional[X]` hints became `X | None`, and the
  `typing` import they no longer need was removed (mainly
  `engine/financial.py`).
- **Small simplifications:** two superfluous `else: return`, four
  `split(...)[0]` calls given `maxsplit`, one mixed `and`/`or` condition
  bracketed, one quoted annotation, and one `repr()` written as `!r`.
- **Dead code removed:** two functions nothing called,
  `location_iq.geocode()` and `cuzk_cz.find_unit()`.
- **Minor tidy-ups:** an unused loop variable was renamed, and an implicit
  Optional hint was fixed (`scraper/_http.py`).

## 5. Ideas for the dashboard

Ranked by how much each helps day to day.

1. **A portal health strip.** For each portal: listings found today, a 7-day
   trend and the last successful read, turning red at zero. This catches H3 the
   day it starts.
2. **Separate "cheap" from "profitable".** GREEN means at least 20 % below the
   market price, not positive income. In the test data, 14 of 15 green
   listings lost money each month. Put the monthly cash flow next to the grade
   on every card, and add a "positive cash flow only" filter.
3. **Say why listings are waiting.** A notice such as "21 Czech listings are
   not scored: no rent figure for Plzeň, Olomouc …". A second notice should say
   that Czech grading is off until price medians are loaded.
4. **Group the sidebar.** It has 17 buttons in one long column. Group them
   under "Daily run", "Repair data" and "Diagnostics". Give the portal buttons
   full names: today "NEH…", "BAZ…" and "TOP…" are cut off, and the Slovak and
   Czech Bazoš buttons look identical.
5. **Fewer, grouped tabs.** The 11 tabs overflow at 1440 px wide, and the last
   one is hidden behind an arrow. Group them, for example:
   - **Deals:** triage, snag list, map, satellite;
   - **Analysis:** what-if, rent comps, tax rates;
   - **Workflow:** pipeline, LV to-do, rejected, contract.
6. **A column chooser for the triage table.** It scrolls sideways today. Pin
   Grade, Title, Price and Cash flow, and let you hide the rest.
7. **Alerts.** An email or Telegram message when a new listing appears that is
   green and cash-flow positive, or when a tracked deal's price drops.
8. **Side-by-side comparison.** Pick two to four listings and compare price
   per m², yield, costs and risks.
9. **A richer map.** Colour pins by grade and cash flow, cluster them, and
   filter by travel time to a chosen point.
10. **Freshness everywhere.** Show the "last seen" age on each card, show
    stale-data notes on the KPI tiles, and refresh the ČNB rate daily.
11. **Export.** A CSV or XLSX of the current filtered table.
12. **A faster feel.** Cache the listing load (M5), and run database set-up
    once per process (M4).
13. **Hide Streamlit's "Deploy" button.** Set `client.toolbarMode =
    "minimal"` in `.streamlit/config.toml`.
14. **A compact card view for phones.**

## 6. How this review was done

- **Static checks:** `ruff` with bug-finding rule sets beyond CI's, a scan for
  unused code (`vulture`), a scan for HTTP calls without timeouts, and checks
  for file encodings and for listing text inserted into raw HTML unescaped.
- **Running the app:** a copy of the code with a synthetic database, 72
  listings and then 20,072, all made up. Every tab was clicked in Chromium, and
  the Czech contract flow was exercised.
- **Fuzzing:** the financial engine with 3,000 random and extreme inputs in
  both markets.
- **Timing:** database calls and full dashboard runs at both sizes.
- **Reading the code:** the scheduler's run logic, the shared lock, the
  database set-up, the tax-rate updater (new in PR #56) and the Czech
  tax-table merge.

The real database and any real listing data were never touched.

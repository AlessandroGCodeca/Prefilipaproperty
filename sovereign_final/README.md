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

Storage is one SQLite file, `data/sovereign.db` — locally, and in Docker on
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

Expected: ~750 passing.

---

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (4 tabs)
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
│   └── slovak_cases.py       ← Locative place names ("v Nitre", "v Košiciach")
├── engine/
│   ├── financial.py          ← 2026 Slovak tax + cashflow engine
│   └── regional_prices.py    ← Sale-price floor + ceiling sanity filters
├── modules/
│   ├── debt_bot.py           ← LV title deed checker (PASS / UNVERIFIED / REJECTED)
│   ├── lv_screen.py          ← Entry-by-entry LV encumbrance screen
│   ├── cashflow_runner.py    ← Financial scoring runner
│   └── location_iq.py        ← Google Places location scorer
└── dev/                      ← One-off debug/exploration scripts (not runtime)
```

---

## Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| TRIAGE TABLE | Flat, sortable view of every scored listing — composite grade, cap rate, surplus, yield. Default sort: best deal grade first |
| ACTIVE SNAG LIST | 🟢🟡 deals with full cost breakdown, location IQ, LV status, flat-LV verify |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download |

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + discount to the regional median), location, energy class,
condition and risk flags — so a GREEN deal in a poor location doesn't outrank
a genuinely solid one. An LV that is verified clean scores above an unverified one.

---

## Pipeline (Sidebar Buttons)

```
NEHNUT → BAZOS → TOPREAL → housekeeping → LV DEBT FILTER → CASHFLOW SCORE → LOCATION IQ
```

Housekeeping = deactivate stale listings (>21d unseen) + flag dev projects.
A nehnutelnosti listing is deactivated sooner, the moment any read of its page
finds a grid of similar listings where the listing was — that is what a
removed listing's URL serves.
Runs automatically every morning at 06:00 CET via scheduler container.
Or click buttons in sidebar to run manually anytime.

Changed the rent/tax assumptions in `config.py`? Click **♻️ RESCORE ALL** to
clear existing scores and re-run scoring (the plain CASHFLOW SCORE button only
processes listings that have never been scored).

---

## Classification

Classes compare the asking €/m² with the region's median
(`engine/regional_prices.py` — Realitná únia / NBS), and the GREEN / YELLOW
lists rank by that discount, then gross yield.

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
   press RE-VERIFY LV. A shared LV with a flag on it stays UNVERIFIED until
   you've checked part C against the flat's number.

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
| GOOGLE_PLACES_API_KEY | console.cloud.google.com | Real location scoring + satellite view |

> LV debt checking needs **no key**: ÚGKK SR has no public API, so
> `kataster_scraper.py` scrapes kataster.skgeodesy.sk directly (unofficial —
> may break if the portal changes). Listings it cannot verify are stored and
> shown as ⚠ UNVERIFIED, never as clean.

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

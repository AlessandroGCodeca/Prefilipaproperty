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

Expected: ~103 passing, 1 xfailed (known Slovak-declension limitation).

---

## Files

```
sovereign_final/
├── app.py                    ← Streamlit dashboard (4 tabs)
├── scheduler.py              ← Daily 06:00 CET automation
├── config.py                 ← All 2026 Slovak tax rates
├── database.py               ← PostgreSQL + SQLite fallback
├── START.bat                 ← Windows one-click launcher
├── docker-compose.yml        ← 4 Docker containers
├── docker/Dockerfile         ← App image
├── requirements.txt
├── .env.example              ← Copy to .env
├── scraper/
│   ├── nehnutelnosti.py      ← Nehnutelnosti.sk scraper (Playwright)
│   ├── bazos.py              ← Bazos.sk scraper
│   └── topreality.py         ← Topreality.sk scraper
├── engine/
│   ├── financial.py          ← 2026 Slovak tax + cashflow engine
│   └── regional_prices.py    ← Sale-price floor (dev-project filter)
├── modules/
│   ├── debt_bot.py           ← LV title deed checker + Mistral LLM
│   ├── cashflow_runner.py    ← Financial scoring runner
│   └── location_iq.py        ← Google Places location scorer
└── dev/                      ← One-off debug/exploration scripts (not runtime)
```

---

## Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| TRIAGE TABLE | Flat, sortable view of every scored listing — composite grade, cap rate, surplus, yield. Default sort: best deal grade first |
| ACTIVE SNAG LIST | 🟢🟡 deals with full cost breakdown, location IQ, one-click LV re-verify |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download |

Each listing also gets a **composite deal grade (A–D)** blending financial
(cap rate + self-funding ratio), location, energy class and risk flags — so a
GREEN deal in a poor location doesn't outrank a genuinely solid one.

---

## Pipeline (Sidebar Buttons)

```
NEHNUT → BAZOS → TOPREAL → housekeeping → LV DEBT FILTER → CASHFLOW SCORE → LOCATION IQ
```

Housekeeping = deactivate stale listings (>21d unseen) + flag dev projects.
Runs automatically every morning at 06:00 CET via scheduler container.
Or click buttons in sidebar to run manually anytime.

Changed the rent/tax assumptions in `config.py`? Click **♻️ RESCORE ALL** to
clear existing scores and re-run scoring (the plain CASHFLOW SCORE button only
processes listings that have never been scored).

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
| GOOGLE_PLACES_API_KEY | console.cloud.google.com | Real location scoring + satellite view |
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

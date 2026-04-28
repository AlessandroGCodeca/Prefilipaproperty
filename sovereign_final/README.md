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
│   ├── nehnutelnosti.py      ← Nehnutelnosti.sk scraper
│   └── bazos.py              ← Bazos.sk scraper
├── engine/
│   └── financial.py          ← 2026 Slovak tax engine
└── modules/
    ├── debt_bot.py           ← LV title deed checker + Mistral LLM
    ├── cashflow_runner.py    ← Financial scoring runner
    └── location_iq.py        ← Google Places location scorer
```

---

## Dashboard Tabs

| Tab | What it does |
|-----|-------------|
| ACTIVE SNAG LIST | 🟢🟡 deals with full cost breakdown, location IQ, one-click LV re-verify |
| SATELLITE VIEWER | Listing photo vs Google satellite + Street View + vibe score |
| s.r.o. vs PERSONAL | Live 2026 tax calculator — both structures side by side |
| ONE-CLICK CLOSE | Pre-filled Slovak notary contract draft with download |

---

## Pipeline (Sidebar Buttons)

```
NEHNUT → BAZOS → LV DEBT FILTER → CASHFLOW SCORE → LOCATION IQ
```

Runs automatically every morning at 06:00 CET via scheduler container.
Or click buttons in sidebar to run manually anytime.

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

| | Personal | s.r.o. |
|--|---------|--------|
| Income Tax | 19% / 25% | 21% flat |
| Health Levy | 16% | 0% ← Key saving |
| Mortgage | 3.4% p.a. | 3.4% p.a. |

**Update `config.py` every January.**

---

## API Keys (all optional — demo mode without them)

| Key | Where | Enables |
|-----|-------|---------|
| GOOGLE_PLACES_API_KEY | console.cloud.google.com | Real location scoring + satellite view |
| CADASTRAL_API_KEY | skgeodesy.sk dev portal | Real LV debt checking |
| FINSTAT_API_KEY | finstat.sk/api | Company owner lookup |

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

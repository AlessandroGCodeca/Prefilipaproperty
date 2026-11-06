# M1 — the Czech cash-flow inputs, checked against a source

Review item M1 (`docs/PROJECT_REVIEW.md`) listed the unconfirmed figures that
move Czech cash flow most. Each was checked on **2026-11-05**. Unlike the
first build, the Czech hosts could be reached this time, so the law texts, ČNB's
notice, Deloitte's report and MF's rent map were read directly.

Every default below can still be overridden in `.env` (names in brackets).

| # | Figure | Was | Now | Status |
|---|---|---|---|---|
| 1 | Deloitte Rent Index: asking or achieved rents | unknown | asking rents of flats that let | **Verified** |
| 1b | Rent table coverage | 8 places | 23: Praha 1–10 and all 13 regional capitals | **Verified** (same report) |
| 2 | ČNB stress add-on | +2 pp, unconfirmed | +2 pp | **Verified** |
| 3 | SVJ správa per flat (`CZ_SVJ_SPRAVA_PER_UNIT`) | 0 Kč | 200 Kč/month | **Verified** (price lists) |
| 4 | SVJ fond oprav (`CZ_SVJ_FOND_OPRAV_PER_M2`) | 20 Kč/m² | 20 Kč/m² | Range only; no statistic exists |
| 5 | Purchase costs (`CZ_ACQUISITION_COST_FIXED`, `_RATE`) | 1 % + 2 000 Kč | 19 000 Kč flat | **Verified** |
| 6 | s.r.o. setup (`CZ_SRO_SETUP_COST`) | 61 000 Kč (€2 500) | 4 000 Kč | **Verified** (tariff) |
| 7 | s.r.o. running (`CZ_SRO_ANNUAL_RUNNING_COST`) | 29 000 Kč (€1 200) | 20 000 Kč/yr | **Verified** (price lists) |
| 8 | Balcony premium | +3 % | +3 % | **Verified** (MF rent map) |
| 9 | Furnished premium | +10 % | +10 % | **Verified**, inside MF's range |
| 10 | Parking premium | +5 % | +5 % | UNVERIFIED: a blend of two features |
| 11 | Semi-furnished premium | +5 % | +5 % | UNVERIFIED: MF has no such class |
| 12 | Exit costs (`CZ_EXIT_COST_RATE`) | 3.5 % | 4 % | **Verified** (market practice) |
| 13 | Growth rates (price, rent, costs) | SK's | SK's | UNVERIFIED: these are forecasts |
| 14 | s.r.o. loan premium and LTV | SK's | SK's | UNVERIFIED: needs a bank's quote |

## 1. The Deloitte Rent Index measures asking rents of flats that let

- **Source:** Deloitte, *Rent Index Q2 2026*, the PDF linked from
  deloitte.com/cz-sk/…/rent-index.html (`2026-Q2-cz-rent-index.pdf`).
- **What it says:** "Data sbírá z realitních portálů" (it collects its data
  from the real-estate portals). The chart legend reads "Cena nájmu ze
  zrealizovaných nabídek" (rent from realised offers). The English page says
  the index "addresses rent offers".
- **What "realised" means:** the Ministry of Finance's methodology for the
  official rent map (mf.gov.cz, *Metodika*, updated 17 Apr 2026; vyhláška
  456/2024 Sb.) defines the same measure. "Realizované nabídkové nájemné" is
  the asking rent at the moment the listing is taken down, read as the sign
  that a lease was signed.
- **Conclusion:** these are asking rents, not contract rents, but each is
  the last ask of a flat that actually let. No Czech source publishes
  contract rents. The baseline is therefore not cut by the 5 % asking
  haircut that live comps get, because those are fresh asks.
- **Also found:** the same report gives figures for every regional capital
  and for Praha 1–10, not only the eight places the table held:
  - Plzeň 301, Olomouc 296, Liberec 289, Zlín 287, České Budějovice 283
    and Karlovy Vary 246 Kč/m², confirmed on the rendered map.
  - Praha 1 490, 2 482, 3 480, 4 443, 5 461, 6 454, 8 465, 9 468 and
    10 442 Kč/m².

  These are now in `engine/rent_cz.py`. Listings in those towns no longer
  wait for live comps before they can be scored. The Středočeský kraj figure
  (328) covers a whole region, so it is not given to any one town.

## 2. ČNB stress add-on: +2 pp

- **Source:** ČNB, *úřední sdělení of 27 November 2025*, Věstník ČNB
  částka 17/2025 (cnb.cz), which applies from 1 April 2026.
- **Doporučení B.3:** DSTI is computed "using both the intended rate and the
  intended contract rate increased by at least 2 percentage points".
- **Same notice:**
  - Doporučení D sets LTV ≤ 70 % and DTI ≤ 7 for an investment mortgage.
  - D.2 makes any loan whose income counts the expected rent an investment
    loan.
  - DSTI 40 % and DTI 8 are thresholds for "very prudent" assessment, not
    caps.
  - Maturity should normally stay within 30 years.

  All of this matches `markets.CZ`.

## 3–4. SVJ fees

- **Správa:** under § 1180 of the civil code, it is split equally per flat.
  Published price lists for full management, read on 2026-11-05:

  | Manager | Kč per flat a month |
  |---|---|
  | brnoreal.cz | 140 basic / 190 complete (not a VAT payer) |
  | sprava85.cz | 150 + DPH |
  | alfabyt.cz | 160 + DPH |
  | spravujeme-svj.cz | 220 + DPH = 266.20 |
  | svjcompass.cz | at most 230 + DPH |

  That is 182–278 Kč with VAT, so the new default is **200 Kč**. The old
  0 Kč understated every Czech flat's costs.
- **Fond oprav:** published ranges are 15–35 (realfree.cz, 2026), 15–50
  (flatio.cz), 15–20 (dostupnyadvokat.cz) and about 17 across one manager's
  buildings (svjpredseda.cz). There is no national statistic
  (domovniasistent.cz). 20 Kč/m² stays as an estimate; the building's own
  předpis záloh is the real figure.

## 5. Purchase costs: a fixed 19 000 Kč, not 1 % of the price

| Item | Kč | Source |
|---|---|---|
| 2 × návrh na vklad (ownership and the bank's lien) | 4 000 | zákon 634/2004 Sb., položka 120: 2 000 Kč each (zakonyprolidi.cz) |
| Advokát's purchase contract, úschova and filing | 10 000 | top of the 5 000–10 000 Kč packages (bricks.legal, martinpleskac.cz); judrnosek.cz: úschova 2 500–3 500 |
| Bank valuation of a flat | 5 000 | hyponamiru.cz, from the banks' price lists; some banks charge nothing |
| Transfer tax | 0 | abolished by zákon 386/2020 Sb. |

A **notářská** úschova is charged as a share of the price (vyhláška 196/2001
Sb., položka C; about 16 500 Kč on 5 mil. Kč). If you use one, set
`CZ_ACQUISITION_COST_RATE`.

On a 5 mil. Kč flat the old 1 % + 2 000 Kč came to 52 000 Kč, nearly three
times the documented cost.

## 6–7. s.r.o. costs

- **Setup:** an s.r.o. on the statutory model articles, with cash capital,
  where the notary also files the entry:

  | Item | Kč | Basis |
  |---|---|---|
  | Notary's deed | 2 000 | vyhláška 196/2001 Sb., položka A |
  | Register entry | 500 | položka S.1 |
  | Beneficial-owner entry | 500 | položka S.2 |
  | DPH 21 % | 630 | |
  | Court fee | 0 | waived by zákon 549/1991 Sb., § 11 |

  The total is 3 630 Kč, rounded up to **4 000**. Letting flats without
  services needs no trade licence. Tailored articles cost more: the notary
  charges from 4 000 Kč + DPH, and the court fee is 2 700 or 6 000 Kč.
  The old 61 000 Kč was the Slovak estimate converted from euros.
- **Running:** bookkeeping, annual accounts and the corporate tax return for
  an s.r.o. that is not a VAT payer (residential letting is VAT-exempt):

  | Accountant | Price |
  |---|---|
  | eskont.cz | 1 500 Kč a month for monthly bookkeeping with annual accounts and return (4 000 Kč a year for annual processing only) |
  | kancelarska-krysa.cz | from 1 900 Kč a month |

  Monthly bookkeeping comes to 18 000–22 800 Kč a year, so the new default
  is **20 000**.

## 8–11. Rent premiums: MF's official rent map

- **Source:** Ministerstvo financí, *Cenová mapa nájemného*, release of
  2026-08-15 (`2026-08-15_Cenova-mapa.xlsx`, data to 30 June 2026), sheet
  *Základní informace*.
- **What it publishes:** a hedonic model's surcharge for each feature, in
  Kč/m² a month. For a flat older than 5 years:

  | Size category | Balcony | Furnished | Garage |
  |---|---|---|---|
  | 1+kk / 1+1 | 16 | 30 | 45 |
  | 2+kk / 2+1 | 7 | 32 | 48 |
  | 3+kk / 3+1 | 5 | 28 | 37 |
  | 4+ | 9 | 25 | 34 |

  An outdoor parking space is not published. MF publishes only significant
  attributes, so it has no measurable effect.
- **As a share of MF's own reference rent** for a 2+kk in the 13 regional
  capitals (Praha 358 Kč/m² … Ústí nad Labem 190):

  | Feature | Range | Code | Verdict |
  |---|---|---|---|
  | Balcony | +2.0 % to +3.7 % | +3 % | confirmed |
  | Furnished | +8.9 % to +16.8 % | +10 % | inside the range, towards its cautious end |
  | Garage | +13 % to +25 % | | |
  | Outdoor parking | about 0 | | |
  | Parking flag (garage or space) | | +5 % | a blend; stays UNVERIFIED |
  | Semi-furnished | MF has no such class | +5 % | UNVERIFIED |

  The description parser sets one parking flag for either a garage or a
  space, so no published figure can confirm a single premium for it.

## 12–13. Hold assumptions

- **Exit costs, now 4 %:** the seller pays the agent. The commission is
  typically about 3 % in Czechia (rulecalc.com, Feb 2026), and ARK cites
  3–6 % (novinky.cz). A VAT-paying agency adds 21 % DPH, making about 3.6 %;
  the seller's share of the contract and úschova brings it to 4 %.
- **Growth rates:** these are forecasts, so no source can confirm them. The
  Slovak values are kept (UNVERIFIED). For comparison:

  | Rate | Value | Comparison |
  |---|---|---|
  | Cost inflation | 2.5 % | ČNB's inflation target is 2 % |
  | Rent growth | 2.5 % | Deloitte's index of the regional capitals stands at 216.6 % of its 2014 level in Q2 2026, about 6.4 % a year |
  | Appreciation | 3 % nominal | |

## Still open

- s.r.o. loan premium (+1 pp) and LTV (70 %): a bank's quote.
- The parking premium as a blend, and the semi-furnished premium.
- The growth rates.
- Fond oprav: the building's own figure.

MF's rent map also gives a reference rent for every municipality and
cadastral area (7 630 of them), with lower and upper bounds. That could fill
the Czech rent table for the towns Deloitte doesn't cover. It would be a
separate change.

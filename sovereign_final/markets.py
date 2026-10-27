"""
markets.py — the market registry: Slovakia ("sk") and Czechia ("cz").

The dashboard runs both markets at once, in one database. Every figure that
differs between them lives in a Market profile here: lending rules and rates,
the tax-year table, building fees (HOA / SVJ), property tax, acquisition
costs, the currency, the plausible sale-price and rent bounds, the regional
price floor and ceiling, the s.r.o. assumptions, the rent table and where the
flood map is. A figure that is the same for both — the GREEN / YELLOW
thresholds, the location-score weights, the vacancy and owner-reserve
assumptions — stays in config.py.

Slovakia's figures are config.py's own names, unchanged: this module only
gathers them, so code that imports them directly keeps working and an .env
override of one still takes effect. Czechia's figures are defined here, each
group with a `source` and the date it was `checked`; a figure that could not
be confirmed says UNVERIFIED in its source, and the README lists them.

Every market-aware function takes `market="sk"` by default, so code written
before the Czech market existed — and every Slovak listing — runs exactly as
before. A listing row carries its market in `listings.market`.

Money is stored in the listing's own currency (`listings.currency`): EUR for
Slovak listings, CZK for Czech ones. to_eur() converts with the one dated
rate in config (CZK_PER_EUR) for ranking and the combined view.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import config

MARKET_CODES = ("sk", "cz")
DEFAULT_MARKET = "sk"


@dataclass(frozen=True)
class Market:
    code: str
    name: str                     # English, for the dashboard
    local_name: str               # in the market's own language
    country_code: str             # ISO 3166-1 alpha-2, lower case (Nominatim)
    currency: str                 # ISO 4217
    currency_symbol: str

    # ── Lending (central-bank rules and a representative rate) ───────────
    mortgage_rate_pa: float | None
    loan_term_years: int | None
    ltv_ratio: float | None             # owner-occupier / first purchase cap
    ltv_ratio_investor: float | None    # investment / 3rd+ property cap
    investor_ltv_from: str | None       # date the investor cap applies from
    rate_shock_pp: float | None         # the regulator's stress-test add-on
    lending_rules: dict = field(default_factory=dict)

    # ── Tax ───────────────────────────────────────────────────────────────
    tax_year_rules: dict = field(default_factory=dict)
    property_tax: dict = field(default_factory=dict)

    # ── Costs (native currency) ──────────────────────────────────────────
    hoa: dict = field(default_factory=dict)
    acquisition_cost_rate: float | None = None
    acquisition_cost_fixed: float | None = None
    acquisition_costs: dict = field(default_factory=dict)

    # ── s.r.o. (native currency) ─────────────────────────────────────────
    sro_setup_cost: float | None = None
    sro_annual_running_cost: float | None = None
    sro_rate_premium_pp: float | None = None
    sro_ltv_ratio: float | None = None
    sro_costs: dict = field(default_factory=dict)
    cashflow_min_surplus: float = 0.0

    # ── Plausibility bounds (native currency) ────────────────────────────
    sale_price_min: float | None = None
    sale_price_max: float | None = None
    rent_min: float | None = None
    rent_max: float | None = None
    rent_per_m2_min: float | None = None   # a rental comp's €/m² (or Kč/m²) range
    rent_per_m2_max: float | None = None
    blank_district_floor_m2: float | None = None    # €/m² with no district
    blank_district_ceiling_m2: float | None = None

    # ── Rent ──────────────────────────────────────────────────────────────
    rent_per_m2: dict = field(default_factory=dict)
    rent_source: dict = field(default_factory=dict)
    industrial_zones: tuple = ()
    industrial_rent_premium: float = 1.0
    parking_rent_premium: float = 1.0
    furnished_rent_premium: float = 1.0
    semi_furnished_premium: float = 1.0
    balcony_rent_premium: float = 1.0

    # ── Hold-period assumptions (engine.financial.project_irr) ───────────
    appreciation_rate: float | None = None
    rent_growth_rate: float | None = None
    cost_inflation_rate: float | None = None
    exit_cost_rate: float | None = None
    hold_assumptions: dict = field(default_factory=dict)

    # ── Title deed and location sources ──────────────────────────────────
    lv_bank_names: tuple = ()
    flood: dict = field(default_factory=dict)
    noise: dict = field(default_factory=dict)

    @property
    def is_sk(self) -> bool:
        return self.code == "sk"


# ── Slovakia: config.py's figures, gathered ───────────────────────────────────
SK = Market(
    code="sk", name="Slovakia", local_name="Slovensko", country_code="sk",
    currency="EUR", currency_symbol="€",
    mortgage_rate_pa=config.MORTGAGE_RATE_PA,
    loan_term_years=config.LOAN_TERM_YEARS,
    ltv_ratio=config.LTV_RATIO,
    ltv_ratio_investor=config.LTV_RATIO_INVESTOR,
    investor_ltv_from=config.INVESTOR_LTV_FROM,
    rate_shock_pp=config.RATE_SHOCK_PP,
    lending_rules={
        "regulator": "NBS",
        "ltv": config.LTV_RATIO, "ltv_investor": config.LTV_RATIO_INVESTOR,
        "investor_from": config.INVESTOR_LTV_FROM,
        "stress_pp": config.RATE_SHOCK_PP,
        "source": "config.py — NBS housing-loan measure, as entered May 2026",
        "checked": "2026-05",
    },
    tax_year_rules=config.TAX_YEAR_RULES,
    property_tax={"kind": "rate_of_value", "rate": config.PROPERTY_TAX_RATE_PA,
                  "source": "config.PROPERTY_TAX_RATE_PA (~0.4% of value)",
                  "checked": "2026-05"},
    hoa={"kind": "bands",
         "bands": ((40, config.HOA_SMALL), (70, config.HOA_MEDIUM),
                   (120, config.HOA_LARGE), (None, config.HOA_PREMIUM)),
         "label": "HOA (incl. fond opráv)",
         "source": "config.HOA_* (správa + fond opráv)", "checked": "2026-05"},
    acquisition_cost_rate=config.ACQUISITION_COST_RATE,
    acquisition_cost_fixed=0.0,
    acquisition_costs={"source": "config.ACQUISITION_COST_RATE — cadastre, contract, "
                                 "valuation; no transfer tax", "checked": "2026-05"},
    sro_setup_cost=config.SRO_SETUP_COST,
    sro_annual_running_cost=config.SRO_ANNUAL_RUNNING_COST,
    sro_rate_premium_pp=config.SRO_RATE_PREMIUM_PP,
    sro_ltv_ratio=config.SRO_LTV_RATIO,
    cashflow_min_surplus=config.CASHFLOW_MIN_SURPLUS,
    sale_price_min=config.SALE_PRICE_MIN_EUR,
    sale_price_max=10_000_000,
    rent_min=config.RENT_MIN_EUR,
    rent_max=config.RENT_MAX_EUR,
    rent_per_m2_min=3.0,
    rent_per_m2_max=45.0,
    # 50% of the cheapest regional median (Nitriansky kraj, ~€1,627/m²) and
    # above the dearest genuine new-builds (~€10–12k/m²) — see
    # engine/regional_prices.
    blank_district_floor_m2=800.0,
    blank_district_ceiling_m2=20_000.0,
    rent_per_m2=config.RENT_PER_M2,
    rent_source={"source": "config.RENT_PER_M2 — Deloitte, Bencont, Pravda, ASPNB, "
                           "trh.sk (April–May 2026)", "checked": "2026-05"},
    industrial_zones=tuple(config.INDUSTRIAL_ZONES),
    industrial_rent_premium=config.INDUSTRIAL_RENT_PREMIUM,
    parking_rent_premium=config.PARKING_RENT_PREMIUM,
    furnished_rent_premium=config.FURNISHED_RENT_PREMIUM,
    semi_furnished_premium=config.SEMI_FURNISHED_PREMIUM,
    balcony_rent_premium=config.BALCONY_RENT_PREMIUM,
    appreciation_rate=config.APPRECIATION_RATE,
    rent_growth_rate=config.RENT_GROWTH_RATE,
    cost_inflation_rate=config.COST_INFLATION_RATE,
    exit_cost_rate=config.EXIT_COST_RATE,
    lv_bank_names=tuple(config.LV_BANK_NAMES),
    flood={"url": config.FLOOD_IDENTIFY_URL, "layers": config.FLOOD_LAYER_IDS,
           "name": "SVP flood hazard map (Q100)"},
    noise={"kind": "osm_proxy"},
)


# ── Czechia ───────────────────────────────────────────────────────────────────
# Every figure below was checked on 2026-10-16 through web search. The
# container this was built in could not reach any .cz host (cnb.cz,
# financnisprava.gov.cz, cuzk.gov.cz, czso.cz), so each was read from search
# results quoting those sites or the press — "checked" says so. A figure that
# could not be confirmed, or is an assumption carried over from the Slovak
# profile, says UNVERIFIED and can be set in .env.

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


CZ_TAX_YEAR_RULES = {
    2026: {
        # Fyzická osoba, příjmy z nájmu (§ 9 ZDP).
        "personal_rate_low":   0.15,
        "personal_rate_high":  0.23,
        # 36 × the average wage used for 2026 (48 967 Kč) = 1 762 812 Kč. Only
        # these two bands are modelled; the rental stacks on your salary.
        "personal_threshold":  1_762_812,
        # No Slovak-style exempt slice: the whole rent is income, less either
        # the actual expenses or the flat-rate ones (výdajový paušál, § 9
        # odst. 4) — 30 % of the rent, at most 600 000 Kč, and all-inclusive
        # (no interest or depreciation on top). The engine takes the larger.
        # The actual expenses modelled: mortgage interest, the SVJ payment,
        # property tax, the repair reserve and management; depreciation
        # (odpisy) is left out, which overstates the tax. Whether an SVJ
        # fond oprav payment is deductible when paid or only when the fund
        # spends it is UNVERIFIED — sources disagree; it is deducted when
        # paid here (about 15 % of 20 Kč/m² a month).
        "rental_exemption":    0,
        "rental_flat_expense_rate": 0.30,
        "rental_flat_expense_cap":  600_000,
        # Rental income outside a živnost carries no social or health
        # insurance.
        "health_levy_personal": 0.00,
        # § 4 odst. 1 písm. b): a flat bought from 2021 is exempt when sold
        # after 10 years (5 years if bought before 2021); the 2-year own-
        # residence route does not apply to a let flat. A cap on exempt sale
        # income reported for 2025+ (40 mil. Kč) is UNVERIFIED and not modelled.
        "personal_cgt_exempt_years": 10,
        # s.r.o.: 21 % corporate tax since 2024 (zákon 349/2023 Sb.), no
        # reduced small-company rate; 15 % withholding on dividends (§ 36).
        "sro_rate":            0.21,
        "sro_rate_reduced":    0.21,
        "sro_reduced_revenue_limit": 0,
        "dividend_tax":        0.15,
        "summary": ("Personal: § 9 rental income, the larger of actual expenses (incl. "
                    "mortgage interest) and the 30 % flat rate (max 600 000 Kč), 15 % / "
                    "23 % above 1 762 812 Kč, no social or health insurance; a sale is "
                    "exempt after 10 years. s.r.o.: 21 % corporate tax, interest and "
                    "running cost deductible, 15 % dividend withholding; the sale is taxed "
                    "whenever it happens."),
        "source": ("ZDP (zákon 586/1992 Sb.) as reported by TPA Czech Republic, taxomat.cz "
                   "(threshold), finzi.cz / idealninajemce.cz / ucetnidasa.cz (§ 9, flat "
                   "rate), portal.gov.cz (21 % CIT, page checked by MF 11 Feb 2026), "
                   "rulecalc.com (§ 36 15 %), muj-pravnik.cz / portal.pohoda.cz (10-year "
                   "test) — read via web search, not fetched"),
        "checked": "2026-10-16 (web search)",
    },
}

CZ = Market(
    code="cz", name="Czechia", local_name="Česko", country_code="cz",
    currency="CZK", currency_symbol="Kč",
    # Swiss Life Hypoindex, September 2026: average offered mortgage rate
    # 5.51 % (press release 9 Sep 2026). Loans to buy to let are priced
    # above it (banky.cz lists investment mortgages from 5.19 % at 60 % LTV
    # to 5.69 % at 75 %), so this sits at the ~70 % LTV such a loan gets.
    mortgage_rate_pa=_env_float("CZ_MORTGAGE_RATE_PA", 0.0551),
    loan_term_years=25,          # the Hypoindex model mortgage's term
    ltv_ratio=0.80,              # ČNB: 80 % (90 % under 36) for own housing
    ltv_ratio_investor=0.70,     # ČNB: 70 % for an investment mortgage
    investor_ltv_from="2026-04-01",
    # The engine's +2 pp rate shock. ČNB's own stress add-on (if any) could
    # not be confirmed: UNVERIFIED as a ČNB figure; kept as the same test.
    rate_shock_pp=0.02,
    lending_rules={
        "regulator": "ČNB",
        "ltv": 0.80, "ltv_under_36": 0.90, "ltv_investor": 0.70,
        "investor_from": "2026-04-01", "dti_investor": 7,
        "dti": None, "dsti": None,          # deactivated for own housing
        # An investment mortgage is one for a 3rd+ residential property OR
        # a property bought to let — so every purchase this tool scores.
        "rental_is_investment": True,
        "investor_note": ("From 1 Apr 2026 ČNB recommends LTV ≤ 70 % and DTI ≤ 7 for an "
                          "investment mortgage — a 3rd+ residential property or one bought "
                          "to let. A recommendation, not a law."),
        "stress_pp_source": "UNVERIFIED — no ČNB stress add-on confirmed; the engine's +2 pp",
        "rate_source": ("Swiss Life Hypoindex 09/2026 (swisslifeselect.cz press release, "
                        "9 Sep 2026): 5.51 %; banky.cz investment-mortgage comparison"),
        "source": ("ČNB press release 'ČNB doporučuje přísnější limity pro investiční "
                   "hypotéky. Kapitálové rezervy se nemění' (2026): LTV 70 % / DTI 7 for "
                   "investment mortgages from 1 Apr 2026, DTI and DSTI otherwise "
                   "deactivated, LTV 80 % / 90 % under 36 — read via web search "
                   "(cnb.cz not reachable)"),
        "checked": "2026-10-16 (web search)",
    },
    tax_year_rules=CZ_TAX_YEAR_RULES,
    property_tax={"kind": "per_m2", "module": "engine.property_tax_cz",
                  "source": "see engine/property_tax_cz.SOURCE",
                  "checked": "2026-10-16 (web search)"},
    # SVJ: fond oprav per m² plus the správa (management) fee per flat. The
    # tenant pays the services (water, heating, lift) through zálohy; the
    # owner pays these two. No national statistic exists: sources give a
    # typical 15–35 Kč/m² (realfree.cz), 15–50 (flatio.cz), an average of
    # 15–20 (rulecalc.com) and ~17 across one manager's buildings
    # (svjpredseda.cz). 20 Kč/m² is inside all of them. The správa fee per
    # flat could not be confirmed: UNVERIFIED, 0 unless set in .env.
    hoa={"kind": "per_m2",
         "per_m2": _env_float("CZ_SVJ_FOND_OPRAV_PER_M2", 20.0),
         "per_unit": _env_float("CZ_SVJ_SPRAVA_PER_UNIT", 0.0),
         "label": "SVJ (fond oprav + správa)",
         "source": ("fond oprav 20 Kč/m²/month: within the ranges reported by realfree.cz, "
                    "flatio.cz, rulecalc.com, svjpredseda.cz (web search). správa per "
                    "flat: UNVERIFIED (CZ_SVJ_SPRAVA_PER_UNIT, default 0)"),
         "checked": "2026-10-16 (web search)"},
    # No transfer tax: daň z nabytí nemovitých věcí was abolished (zákon
    # 386/2020 Sb.). The katastr filing fee (návrh na vklad, položka 120 of
    # zákon 634/2004 Sb.) is 2 000 Kč (cuzk.gov.cz sazebník, via search). Legal,
    # escrow (advokátní / notářská úschova), valuation and mortgage fees could
    # not be confirmed: UNVERIFIED — the Slovak profile's 1 % of the price is
    # carried over for them.
    acquisition_cost_rate=_env_float("CZ_ACQUISITION_COST_RATE", 0.01),
    acquisition_cost_fixed=2_000.0,
    acquisition_costs={
        "katastr_fee": 2_000, "transfer_tax": 0,
        "legal_fees": "UNVERIFIED — 1 % of the price carried over from the SK profile",
        "source": ("zákon 386/2020 Sb. (transfer tax abolished; bezrealitky.cz, epravo.cz); "
                   "ČÚZK sazebník: 2 000 Kč per návrh na vklad (cuzk.gov.cz, via search)"),
        "checked": "2026-10-16 (web search)"},
    # The s.r.o. figures are the Slovak estimates converted at the dated rate
    # (setup €2,500, running €1,200/yr, +1 pp on the loan, 70 % LTV): no Czech
    # quote could be confirmed. UNVERIFIED — set them in .env from an účetní's
    # and a bank's quote.
    sro_setup_cost=_env_float("CZ_SRO_SETUP_COST", round(2_500 * config.CZK_PER_EUR, -3)),
    sro_annual_running_cost=_env_float("CZ_SRO_ANNUAL_RUNNING_COST",
                                       round(1_200 * config.CZK_PER_EUR, -3)),
    sro_rate_premium_pp=_env_float("CZ_SRO_RATE_PREMIUM_PP", 0.01),
    sro_ltv_ratio=_env_float("CZ_SRO_LTV_RATIO", 0.70),
    sro_costs={"source": ("UNVERIFIED — Slovak estimates converted at "
                          f"{config.CZK_PER_EUR} Kč/€; no Czech quote confirmed"),
               "checked": None},
    cashflow_min_surplus=_env_float("CZ_CASHFLOW_MIN_SURPLUS", 0.0),
    # Plausibility bounds, not market figures: a Kč amount on a sale listing
    # below 200 000 is a deposit, a rent or a fee; a rent outside
    # 3 000–150 000 Kč a month is a sale price, a nightly rate or a typo.
    sale_price_min=_env_float("CZ_SALE_PRICE_MIN", 200_000),
    sale_price_max=250_000_000,
    rent_min=3_000, rent_max=150_000,
    rent_per_m2_min=70.0, rent_per_m2_max=1_100.0,
    # With no median to judge against (every Czech listing until the price
    # tables are filled), the floor and ceiling are these backstops. The
    # floor is half the cheapest okres in ČSÚ's "Ceny nemovitostí 2022–2024"
    # (Sokolov, 27 862 Kč/m²), as Slovakia's is half its cheapest kraj; the
    # ceiling clears the dearest new builds (Deloitte Develop Index Q2 2026:
    # Praha 2 at 265 100 Kč/m², via search) and still catches a 10× misread.
    blank_district_floor_m2=13_900.0, blank_district_ceiling_m2=600_000.0,
    industrial_zones=(),
    # The Slovak description premiums, carried over: UNVERIFIED for Czechia.
    industrial_rent_premium=1.0,
    parking_rent_premium=config.PARKING_RENT_PREMIUM,
    furnished_rent_premium=config.FURNISHED_RENT_PREMIUM,
    semi_furnished_premium=config.SEMI_FURNISHED_PREMIUM,
    balcony_rent_premium=config.BALCONY_RENT_PREMIUM,
    # Hold-period assumptions, carried over from the Slovak profile: model
    # inputs, not a Czech forecast. UNVERIFIED for Czechia.
    appreciation_rate=_env_float("CZ_APPRECIATION_RATE", config.APPRECIATION_RATE),
    rent_growth_rate=_env_float("CZ_RENT_GROWTH_RATE", config.RENT_GROWTH_RATE),
    cost_inflation_rate=_env_float("CZ_COST_INFLATION_RATE", config.COST_INFLATION_RATE),
    exit_cost_rate=_env_float("CZ_EXIT_COST_RATE", config.EXIT_COST_RATE),
    hold_assumptions={"source": "UNVERIFIED — the Slovak profile's assumptions",
                      "checked": None},
    # Rents: engine/rent_cz (Deloitte Rent Index Q2 2026 for the places it
    # names) and live rental comps (engine/rent_comps_cz).
    rent_source={"source": "see engine/rent_cz.RENT_SOURCE",
                 "checked": "2026-10-16 (web search)"},
    # Flood: the Q100 flood areas (and active zone) the water authorities
    # publish through VÚV T. G. M., in the national ÚAP map service of ÚÚR —
    # "indicative only", VÚV's metadata says. Layer 82 "T0601 Záplavová
    # území Q100 a QA" (found via search; not reachable from here:
    # UNVERIFIED).
    flood={"url": os.getenv("CZ_FLOOD_IDENTIFY_URL",
                            "https://egis.uur.cz/arcgis/rest/services/UAP/UAP_CR/"
                            "MapServer/identify"),
           "layers": os.getenv("CZ_FLOOD_LAYER_IDS", "82"),
           "name": "ÚÚR / VÚV flood areas (Q100 and active zone)",
           "checked": "2026-10-16 (web search) — UNVERIFIED live"},
    # Noise: the OpenStreetMap proxy (as in Slovakia), plus the 2022 strategic
    # noise map of main roads (MZ ČR / Zdravotní ústav Ostrava, Ldvn in 5 dB
    # bands) where it gives a reading. The REST path beside its published
    # WMS is UNVERIFIED.
    noise={"kind": "osm_proxy+shm2022",
           "url": os.getenv("CZ_NOISE_IDENTIFY_URL",
                            "https://geoportal.mzcr.cz/server/rest/services/SHM2022/"
                            "Silnice_Ldvn/ImageServer/identify"),
           "name": "Strategická hluková mapa 2022 — hlavní silnice (Ldvn)",
           "checked": "2026-10-16 (web search) — UNVERIFIED live"},
    # Creditors a lien may be in favour of as ordinary housing finance. The
    # words "banka" and "spořitelna" already count; these are names that
    # don't contain them, and the state housing fund (SFPI, formerly SFRB).
    # The last six: banks whose name glues "bank" to another word, some no
    # longer lending but still named on old liens ("Sberbank CZ, a.s. v
    # likvidaci"). Spellings not checked against ČNB's list of banks from
    # here (UNVERIFIED).
    lv_bank_names=("čsob", "raiffeisenbank", "unicredit", "moneta", "mbank", "oberbank",
                   "wüstenrot", "hypoteční banka", "státní fond podpory investic",
                   "sfpi", "státní fond rozvoje bydlení", "sfrb",
                   "sberbank", "volksbank", "ebanka", "expobank", "citibank", "commerzbank"),
)

MARKETS = {"sk": SK, "cz": CZ}


def normalize(code) -> str:
    """'sk' / 'cz' from any spelling ('SK', ' cz '); blank or unknown is 'sk'
    — every row from before the Czech market is Slovak."""
    c = str(code or "").strip().lower()
    return c if c in MARKETS else DEFAULT_MARKET


def get(code=DEFAULT_MARKET) -> Market:
    """The profile for a market code (see normalize)."""
    return MARKETS[normalize(code)]


def of_row(row) -> str:
    """A listing row's market — 'sk' for a row from before the column."""
    return normalize((row or {}).get("market"))


# ── Tax tables ───────────────────────────────────────────────────────────────
def tax_rules(year: int | None = None, market: str = DEFAULT_MARKET) -> dict:
    """A market's tax table for `year` (default config.TAX_YEAR): that year's
    own, or the latest earlier one — as config.tax_rules does for Slovakia.
    Carries "year", "requested", "stale" and "market"."""
    m = get(market)
    if m.is_sk:
        return {**config.tax_rules(year), "market": "sk"}
    requested = int(year or config.TAX_YEAR)
    known = sorted(m.tax_year_rules)
    if not known:
        raise LookupError(f"no tax table for {m.name} yet")
    usable = [y for y in known if y <= requested] or known[:1]
    used = usable[-1]
    return {**m.tax_year_rules[used], "year": used, "requested": requested,
            "stale": used != requested, "market": m.code}


# ── Currency ──────────────────────────────────────────────────────────────────
def to_eur(amount, currency: str = "EUR"):
    """`amount` in EUR at config.CZK_PER_EUR (dated config.FX_RATE_DATE).
    None stays None."""
    if amount is None:
        return None
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return float(amount)
    if cur == "CZK":
        return float(amount) / config.CZK_PER_EUR
    raise ValueError(f"no exchange rate for {currency}")


def fx_note() -> str:
    """One line on the rate the combined view converts with."""
    return (f"1 € = {config.CZK_PER_EUR:.3f} Kč ({config.FX_RATE_SOURCE}, "
            f"{config.FX_RATE_DATE})")


_NBSP = " "


def format_money(v, currency: str = "EUR", decimals: int = 0, suffix: str = "",
                 signed: bool | None = None) -> str:
    """Money the way each market writes it, sign first:
    EUR  → -€41/mo, €78,000          (as the dashboard always has)
    CZK  → -1 200 Kč/měs., 3 450 000 Kč
    signed (default: on for a per-month amount) adds + to non-negative ones.
    None → '—'."""
    if v is None:
        return "—"
    if signed is None:
        signed = suffix in ("/mo", "/měs.")
    v = round(float(v), decimals) + 0.0      # -0.0 → 0.0: no "-€0"
    sign = "-" if v < 0 else ("+" if signed else "")
    if (currency or "EUR").upper() == "CZK":
        digits = f"{abs(v):,.{decimals}f}".replace(",", _NBSP).replace(".", ",")
        return f"{sign}{digits}{_NBSP}Kč{suffix}"
    return f"{sign}€{abs(v):,.{decimals}f}{suffix}"

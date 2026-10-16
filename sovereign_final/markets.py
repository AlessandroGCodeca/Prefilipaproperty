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
# Filled in step by step (tax / lending / costs, regional prices, rents). A
# figure left None has no confirmed value yet; the engine says so instead of
# using one.
CZ = Market(
    code="cz", name="Czechia", local_name="Česko", country_code="cz",
    currency="CZK", currency_symbol="Kč",
    mortgage_rate_pa=None, loan_term_years=None, ltv_ratio=None,
    ltv_ratio_investor=None, investor_ltv_from=None, rate_shock_pp=None,
    lv_bank_names=(),
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

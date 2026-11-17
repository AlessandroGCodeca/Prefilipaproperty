"""
modules/settings.py — "Your situation": the handful of model inputs that are
yours, not the market's, set from the dashboard instead of a file.

  your other yearly income, how many properties you own, and your bank's
  rate, term and loan share — for Slovakia; your other income and rate for
  Czechia.

They are saved to data/settings.json (config.SETTINGS_PATH), beside the
database, so the dashboard and the scheduler — two processes, in Docker two
containers — read the same file. A saved value outranks the same key in .env.
Nothing else is ever written there: API keys and passwords stay in .env.

config.py reads the file when a process starts. apply() puts a change into
the running process as well (config, the engine's own copies, the market
profiles), and sync() does it whenever the file changed — the scheduler calls
it before each run, the dashboard on each rerun. A change to any of them makes
every stored score stale: the panel re-scores (dashboard/sidebar.py).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os

import config

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class Field:
    key: str            # the setting's name, as in .env
    label: str
    kind: str           # "money" | "int" | "pct" | "years"
    low: float
    high: float
    help: str
    market: str = "sk"


FIELDS = (
    Field("OTHER_ANNUAL_INCOME", "Your other yearly income (tax base, €)", "money", 0, 2_000_000,
          "Your tax base from everything but the flat (salary after your own "
          "contributions). The rental is taxed on top of it: with €50,000 at 25 %, "
          "not 19 %. 0 taxes the rental as your only income."),
    Field("PROPERTIES_OWNED", "Residential properties you own", "int", 0, 50,
          "From 2 on, the next flat is your 3rd: the NBS caps its loan at 70 %."),
    Field("MORTGAGE_RATE_PA", "Your mortgage rate (% a year)", "pct", 0.0, 0.25,
          "The rate your bank offers you. Every surplus, the triage table and the "
          "alerts use it."),
    Field("LOAN_TERM_YEARS", "Loan term (years)", "years", 5, 40,
          "25 is cautious; 30 is the usual maximum and lowers the monthly payment."),
    Field("LTV_RATIO", "Loan share of the price (%)", "pct", 0.0, 0.9,
          "How much of the price the bank lends you: at most 80 %, or 70 % for a "
          "3rd and later property (applied by itself from PROPERTIES_OWNED)."),
    Field("CZ_OTHER_ANNUAL_INCOME", "Your other yearly income (tax base, Kč)", "money", 0,
          50_000_000, "As above, in crowns: the 23 % band starts at 1,762,812 Kč.", "cz"),
    Field("CZ_MORTGAGE_RATE_PA", "Your Czech mortgage rate (% a year)", "pct", 0.0, 0.25,
          "The rate a Czech bank offers you for a flat bought to let.", "cz"),
)
_BY_KEY = {f.key: f for f in FIELDS}

_seen_mtime: float | None = None


def current() -> dict:
    """Each field's value in use in this process."""
    import markets
    cz = markets.CZ
    return {
        "OTHER_ANNUAL_INCOME": config.OTHER_ANNUAL_INCOME,
        "PROPERTIES_OWNED": config.PROPERTIES_OWNED,
        "MORTGAGE_RATE_PA": config.MORTGAGE_RATE_PA,
        "LOAN_TERM_YEARS": config.LOAN_TERM_YEARS,
        "LTV_RATIO": config.LTV_RATIO,
        "CZ_OTHER_ANNUAL_INCOME": cz.other_annual_income,
        "CZ_MORTGAGE_RATE_PA": cz.mortgage_rate_pa,
    }


def clean(values: dict) -> dict:
    """`values` cut down to the known fields, each a number inside its
    range; a field that is missing or no number is left out."""
    out = {}
    for key, raw in (values or {}).items():
        f = _BY_KEY.get(key)
        if f is None or raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v != v:                                   # NaN
            continue
        v = min(max(v, f.low), f.high)
        out[key] = int(round(v)) if f.kind in ("int", "years") else v
    return out


def save(values: dict) -> dict:
    """Write the fields in `values` to data/settings.json (the rest of the
    file is kept), put them into this process (apply) and return what was
    saved."""
    new = clean(values)
    data = {k: v for k, v in config.saved_settings().items() if k in _BY_KEY}
    data.update(new)
    os.makedirs(os.path.dirname(config.SETTINGS_PATH), exist_ok=True)
    tmp = config.SETTINGS_PATH + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, config.SETTINGS_PATH)
    apply(data)
    return new


def apply(values: dict | None = None) -> list[str]:
    """Put saved settings into the running process: config, the engine's own
    copies of the Slovak figures, and both market profiles. Returns the keys
    whose value changed."""
    import markets
    from engine import financial
    values = clean(config.saved_settings() if values is None else values)
    before = current()
    changed = [k for k, v in values.items() if before.get(k) != v]
    for key in ("OTHER_ANNUAL_INCOME", "PROPERTIES_OWNED", "MORTGAGE_RATE_PA",
                "LOAN_TERM_YEARS", "LTV_RATIO"):
        if key in values:
            setattr(config, key, values[key])
            setattr(financial, key, values[key])
    sk = {k: v for k, v in (
        ("other_annual_income", values.get("OTHER_ANNUAL_INCOME")),
        ("mortgage_rate_pa", values.get("MORTGAGE_RATE_PA")),
        ("loan_term_years", values.get("LOAN_TERM_YEARS")),
        ("ltv_ratio", values.get("LTV_RATIO"))) if v is not None}
    cz = {k: v for k, v in (
        ("other_annual_income", values.get("CZ_OTHER_ANNUAL_INCOME")),
        ("mortgage_rate_pa", values.get("CZ_MORTGAGE_RATE_PA"))) if v is not None}
    if sk:
        markets.SK = dataclasses.replace(markets.SK, **sk)
        markets.MARKETS["sk"] = markets.SK
    if cz:
        markets.CZ = dataclasses.replace(markets.CZ, **cz)
        markets.MARKETS["cz"] = markets.CZ
    return changed


def sync() -> list[str]:
    """apply() when data/settings.json changed since this process last
    looked (the other process saved it). Cheap otherwise: one stat()."""
    global _seen_mtime
    try:
        mtime = os.path.getmtime(config.SETTINGS_PATH)
    except OSError:
        return []
    if mtime == _seen_mtime:
        return []
    _seen_mtime = mtime
    changed = apply()
    if changed:
        log.info(f"⚙️  Settings picked up from the dashboard: {', '.join(changed)}")
    return changed

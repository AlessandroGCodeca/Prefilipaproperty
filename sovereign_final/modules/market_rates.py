"""
modules/market_rates.py — the average rate on new housing loans, read from
the central banks, so the model's mortgage rate is not a number someone typed
in once and forgot.

  Slovakia: the ECB Data Portal, series MIR.M.SK.B.A2C.A.R.A.2250.EUR.N — the
            monthly annualised agreed rate on new loans to households for
            house purchase. Free, no key.
  Czechia:  ČNB ARAD (cnb.cz/arad). Free, but it needs an account and a key
            (CZ_ARAD_API_KEY) and the indicator you chose in ARAD
            (CZ_ARAD_RATE_INDICATOR). Without them Czechia keeps its default.

The latest value of each is kept in data/market_rates.json
(config.MARKET_RATES_PATH), beside the database, so the dashboard and the
scheduler read the same one. It is the model's rate only where you set none:
a rate typed in 👤 YOUR SITUATION or in .env always wins. When the market rate
in use moves, the scores worked out on the old one are redone by the next
scoring run (database.requeue_scores_from_older_model compares each score's
rate with the one in use).

The scheduler calls refresh() before each run; it reads the banks at most
once every REFRESH_DAYS (the series is monthly). A failure keeps the last
value and never fails the run.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import config

log = logging.getLogger(__name__)

ECB_SERIES = "MIR.M.SK.B.A2C.A.R.A.2250.EUR.N"
ECB_URL = ("https://data-api.ecb.europa.eu/service/data/MIR/"
           "M.SK.B.A2C.A.R.A.2250.EUR.N?lastNObservations=3&format=csvdata")
ECB_PAGE = "https://data.ecb.europa.eu/data/datasets/MIR/MIR.M.SK.B.A2C.A.R.A.2250.EUR.N"
ARAD_URL = "https://www.cnb.cz/aradb/api/v1/data"
REFRESH_DAYS = 7
TIMEOUT_S = 20
# The setting a market's rate is typed under (YOUR SITUATION or .env).
RATE_KEYS = {"sk": "MORTGAGE_RATE_PA", "cz": "CZ_MORTGAGE_RATE_PA"}
_FALLBACK = {"sk": 0.038, "cz": 0.0551}


def _load() -> dict:
    return config.market_rates()


def _write(data: dict) -> None:
    os.makedirs(os.path.dirname(config.MARKET_RATES_PATH), exist_ok=True)
    tmp = config.MARKET_RATES_PATH + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, config.MARKET_RATES_PATH)


def latest(market: str) -> dict | None:
    """The stored reading for `market`: {"rate", "period", "source",
    "fetched_at"}, or None."""
    entry = _load().get(market)
    return entry if isinstance(entry, dict) and config.market_rate(market) else None


def user_rate_set(market: str) -> bool:
    """Whether you typed a rate for `market` (YOUR SITUATION or .env)."""
    key = RATE_KEYS[market]
    return config.saved_settings().get(key) is not None or bool((os.getenv(key) or "").strip())


def rate_in_use(market: str) -> float:
    """The mortgage rate the model uses for `market` in this process."""
    import markets
    from engine import financial
    if market == "sk":
        return financial.MORTGAGE_RATE_PA
    return markets.get(market).mortgage_rate_pa


def parse_ecb_csv(text: str) -> tuple[str, float]:
    """(period "YYYY-MM", rate as a fraction) of the newest observation in
    the ECB's csvdata answer."""
    rows = [r for r in csv.DictReader(io.StringIO(text))
            if r.get("TIME_PERIOD") and (r.get("OBS_VALUE") or "").strip()]
    if not rows:
        raise ValueError("no observation in the ECB answer")
    newest = max(rows, key=lambda r: r["TIME_PERIOD"])
    rate = float(newest["OBS_VALUE"]) / 100
    if not 0 < rate < 0.25:
        raise ValueError(f"implausible rate {rate:.4f}")
    return newest["TIME_PERIOD"], rate


def parse_arad_csv(text: str) -> tuple[str, float]:
    """(period "YYYY-MM", rate as a fraction) of the newest row in ARAD's
    /data answer: semicolon-separated, header first, the value with a decimal
    comma unless decimal_separator=point was asked for."""
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = [r for r in reader if (r.get("period") or "").strip() and (r.get("value") or "").strip()]
    if not rows:
        raise ValueError("no value in the ARAD answer")
    newest = max(rows, key=lambda r: r["period"])
    rate = float(newest["value"].replace(",", ".")) / 100
    if not 0 < rate < 0.25:
        raise ValueError(f"implausible rate {rate:.4f}")
    p = newest["period"].strip()
    return (f"{p[:4]}-{p[4:6]}" if len(p) >= 6 and p.isdigit() else p), rate


def fetch_sk(get=None) -> dict:
    """The ECB's newest Slovak reading."""
    import requests
    get = get or requests.get
    r = get(ECB_URL, timeout=TIMEOUT_S, headers={"Accept": "text/csv"})
    r.raise_for_status()
    period, rate = parse_ecb_csv(r.text)
    return {"rate": rate, "period": period, "source": f"ECB {ECB_SERIES}"}


def fetch_cz(get=None) -> dict | None:
    """ARAD's newest reading for CZ_ARAD_RATE_INDICATOR; None without a key
    or an indicator."""
    key = (os.getenv("CZ_ARAD_API_KEY") or "").strip()
    indicator = (os.getenv("CZ_ARAD_RATE_INDICATOR") or "").strip()
    if not key or not indicator:
        return None
    import requests
    get = get or requests.get
    r = get(ARAD_URL, timeout=TIMEOUT_S, params={
        "indicator_id_list": indicator, "months_before": 6, "decimal_separator": "point",
        "lang": "en", "api_key": key})
    r.raise_for_status()
    r.encoding = r.encoding or "cp1250"
    period, rate = parse_arad_csv(r.text)
    return {"rate": rate, "period": period, "source": f"ČNB ARAD {indicator}"}


def refresh(force: bool = False, get=None, now: datetime | None = None) -> list[str]:
    """Read the banks when the stored readings are older than REFRESH_DAYS
    (or `force`), store what came back and put it into this process. Returns
    the markets whose rate in use changed. A market that can't be read keeps
    its last value."""
    now = now or datetime.now(timezone.utc)
    data = _load()
    fetched = False
    for market, fetch in (("sk", fetch_sk), ("cz", fetch_cz)):
        old = data.get(market) or {}
        try:
            when = datetime.fromisoformat(old["fetched_at"])
        except (KeyError, TypeError, ValueError):
            when = None
        if not force and when and now - when < timedelta(days=REFRESH_DAYS):
            continue
        try:
            got = fetch(get=get)
        except Exception as e:
            log.warning(f"Market rate ({market.upper()}) not read: {type(e).__name__}: {e}")
            continue
        if got is None:
            continue
        got["fetched_at"] = now.isoformat()
        if old.get("rate") != got["rate"]:
            log.info(f"🏦 {market.upper()} average new mortgage rate: {got['rate'] * 100:.2f} % "
                     f"({got['period']}, {got['source']})")
        data[market] = got
        fetched = True
    if fetched:
        _write(data)
    return apply()


def apply() -> list[str]:
    """Put the stored market rates into this process, for each market whose
    rate you didn't set yourself. Returns the markets whose rate changed."""
    import markets
    from engine import financial
    changed = []
    for market in ("sk", "cz"):
        if user_rate_set(market):
            continue
        rate = config.market_rate(market) or _FALLBACK[market]
        if abs(rate_in_use(market) - rate) < 1e-12:
            continue
        if market == "sk":
            config.MORTGAGE_RATE_PA = rate
            financial.MORTGAGE_RATE_PA = rate
            markets.SK = dataclasses.replace(markets.SK, mortgage_rate_pa=rate)
            markets.MARKETS["sk"] = markets.SK
        else:
            markets.CZ = dataclasses.replace(markets.CZ, mortgage_rate_pa=rate)
            markets.MARKETS["cz"] = markets.CZ
        changed.append(market)
    return changed


_seen_mtime: float | None = None


def sync() -> list[str]:
    """apply() when data/market_rates.json changed since this process last
    looked (the scheduler refreshed it). One stat() otherwise."""
    global _seen_mtime
    try:
        mtime = os.path.getmtime(config.MARKET_RATES_PATH)
    except OSError:
        return []
    if mtime == _seen_mtime:
        return []
    _seen_mtime = mtime
    return apply()


def describe(market: str) -> str:
    """One line for the dashboard: the market's average and whether the
    model uses it."""
    entry = latest(market)
    if not entry:
        if market == "cz":
            return ("No Czech market rate: set CZ_ARAD_API_KEY and CZ_ARAD_RATE_INDICATOR "
                    "in .env (README “Market rates”).")
        return "The ECB rate hasn't been read yet; it is read before the next run."
    used = "in use" if not user_rate_set(market) else "yours is used instead"
    return (f"Market average for new housing loans: {entry['rate'] * 100:.2f} % "
            f"({entry.get('period', '?')}, {entry.get('source', '')}) — {used}.")

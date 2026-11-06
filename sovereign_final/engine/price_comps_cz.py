"""
engine/price_comps_cz.py — how a Prague or Brno district's asking prices
compare with its whole city's, from the Czech sale listings scraped.

ČSÚ's purchase-price table (engine/cz_regional_prices.csv) stops at the
okres: Prague and Brno-město are one figure each, and a Praha 14 flat judged
against all of Prague would look like a bargain beside Praha 1's prices.
This module measures each district's level relative to its city from the
listings themselves:

    factor = median asking Kč/m² of the district's listings
             ÷ median asking Kč/m² of all the city's listings

and engine.regional_prices_cz scales the city's ČSÚ figure by it. Only the
ratio is taken from asking prices, so the benchmark stays ČSÚ's measure (a
purchase price); the asks set only how far above or below the city's figure
a district sits.

A factor needs MIN_DISTRICT_SAMPLE listings in the district and
MIN_CITY_SAMPLE in the city, and is kept within FACTOR_BOUNDS. One flat
listed on several portals counts once (listings.dup_group); developer
projects, rejected titles and prices outside the Czech bounds are left out.

  rebuild()          re-measure from the active listings; drops the scores
                     of listings whose benchmark moved so they are redone
  district_factor()  (factor, listings) for a district, or None
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

MARKET = "cz"
MIN_DISTRICT_SAMPLE = 8
MIN_CITY_SAMPLE = 30
FACTOR_BOUNDS = (0.6, 1.6)
# A factor that moved this much sends the district's scored listings back.
RESCORE_THRESHOLD = 0.02
# How long a process keeps the factors it read (the scheduler rebuilds them
# in its own process; the dashboard reads them again after this).
CACHE_S = 300
CITIES = {"Hlavní město Praha": "Praha", "Brno-město": "Brno"}

_DDL = """
    CREATE TABLE IF NOT EXISTS price_comps_cz (
        district            TEXT PRIMARY KEY,
        city                TEXT NOT NULL,
        n                   INTEGER NOT NULL,
        median_czk_m2       REAL NOT NULL,
        city_n              INTEGER NOT NULL,
        city_median_czk_m2  REAL NOT NULL,
        factor              REAL,
        updated_at          TEXT NOT NULL
    )"""

_cache: dict = {"key": None, "at": 0.0, "factors": {}}


def place_of(district: str) -> tuple[str, str | None] | None:
    """(city, district) a Czech district string is in — ("Praha", "Praha 7"),
    ("Brno", "Žabovřesky"), ("Praha", None) for Prague with no district — or
    None outside Prague and Brno."""
    from engine import regional_prices_cz as rp
    p = rp.praha_district(district or "")
    if p:
        return "Praha", p
    b = rp.brno_district(district or "")
    if b:
        return "Brno", b
    okres = rp.okres_for_district(district or "")
    return (CITIES[okres], None) if okres in CITIES else None


def _bounds() -> tuple[float, float]:
    import markets
    m = markets.get(MARKET)
    return m.blank_district_floor_m2, m.blank_district_ceiling_m2


def measure(rows: list[dict]) -> dict[str, dict]:
    """{district: {"city", "n", "median", "city_n", "city_median", "factor"}}
    from listing rows (district, price_eur, size_m2, dup_group). factor is
    None below the sample sizes."""
    lo, hi = _bounds()
    seen: set = set()
    by_city: dict[str, list[float]] = {}
    by_district: dict[str, tuple[str, list[float]]] = {}
    for r in rows:
        group = r.get("dup_group") or r.get("id")
        if group in seen:
            continue
        place = place_of(r.get("district") or "")
        if not place or not r.get("size_m2") or not r.get("price_eur"):
            continue
        per_m2 = r["price_eur"] / r["size_m2"]
        if not lo <= per_m2 <= hi:
            continue
        seen.add(group)
        city, district = place
        by_city.setdefault(city, []).append(per_m2)
        if district:
            by_district.setdefault(district, (city, []))[1].append(per_m2)
    out = {}
    for district, (city, values) in by_district.items():
        city_values = by_city[city]
        median, city_median = statistics.median(values), statistics.median(city_values)
        factor = None
        if len(values) >= MIN_DISTRICT_SAMPLE and len(city_values) >= MIN_CITY_SAMPLE:
            factor = round(min(max(median / city_median, FACTOR_BOUNDS[0]), FACTOR_BOUNDS[1]), 3)
        out[district] = {"city": city, "n": len(values), "median": round(median, 2),
                         "city_n": len(city_values), "city_median": round(city_median, 2),
                         "factor": factor}
    return out


def _cache_key():
    import database
    return (database.SQLITE_PATH, id(database.get_conn))


def _stored(conn) -> dict[str, dict]:
    conn.execute(_DDL)
    return {r["district"]: dict(r) for r in conn.execute("SELECT * FROM price_comps_cz")}


def reload() -> None:
    """Forget the factors this process read: the next lookup reads them again."""
    _cache.update(key=None, at=0.0, factors={})


def _factors() -> dict[str, tuple[float, int]]:
    key = _cache_key()
    if _cache["key"] == key and time.monotonic() - _cache["at"] < CACHE_S:
        return _cache["factors"]
    import database
    factors: dict[str, tuple[float, int]] = {}
    try:
        conn = database.get_conn()
        try:
            if database._has_table(conn, "price_comps_cz"):
                factors = {d: (r["factor"], r["n"]) for d, r in _stored(conn).items()
                           if r["factor"]}
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("Czech district price factors not read: %s: %s", type(e).__name__, e)
    _cache.update(key=key, at=time.monotonic(), factors=factors)
    return factors


def district_factor(district: str) -> tuple[float, int] | None:
    """(factor, listings it is measured from) for a Prague or Brno district
    ("Praha 7", "Žabovřesky"), or None until it has enough listings."""
    return _factors().get(district)


def rebuild() -> dict:
    """Re-measure every district from the active Czech listings, store the
    factors, and drop the scores of listings in a district whose factor
    appeared, went or moved by RESCORE_THRESHOLD, so the next scoring run
    judges them against the new benchmark. Returns {"districts", "with_factor",
    "changed", "rescored"}."""
    import database
    from database import (_drop_cashflow_score, _ensure_dev_project_column,
                          _ensure_enrichment_columns, _ensure_market_columns)
    conn = database.get_conn()
    try:
        _ensure_market_columns(conn)
        _ensure_enrichment_columns(conn)
        _ensure_dev_project_column(conn)
        old = {d: r["factor"] for d, r in _stored(conn).items()}
        rows = [dict(r) for r in conn.execute(
            "SELECT id, district, price_eur, size_m2, dup_group FROM listings "
            "WHERE market = ? AND is_active = 1 AND price_eur > 0 AND size_m2 > 0 "
            "AND lv_status != 'REJECTED' AND COALESCE(is_dev_project, 0) = 0",
            (MARKET,)).fetchall()]
        now = datetime.now(timezone.utc).isoformat()
        measured = measure(rows)
        conn.execute("DELETE FROM price_comps_cz")
        for district, m in measured.items():
            conn.execute(
                "INSERT INTO price_comps_cz (district, city, n, median_czk_m2, city_n, "
                "city_median_czk_m2, factor, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (district, m["city"], m["n"], m["median"], m["city_n"], m["city_median"],
                 m["factor"], now))
        new = {d: m["factor"] for d, m in measured.items()}
        changed = sorted(
            d for d in set(old) | set(new)
            if (old.get(d) is None) != (new.get(d) is None)
            or (old.get(d) and new.get(d) and abs(new[d] / old[d] - 1) >= RESCORE_THRESHOLD))
        rescored = 0
        if changed:
            wanted = set(changed)
            for r in rows:
                place = place_of(r["district"] or "")
                if place and place[1] in wanted:
                    rescored += _drop_cashflow_score(conn, r["id"])
        conn.commit()
    finally:
        conn.close()
    reload()
    return {"districts": len(measured),
            "with_factor": sum(1 for m in measured.values() if m["factor"]),
            "changed": changed, "rescored": rescored}


def factors_table() -> list[dict]:
    """Rows for the dashboard: each measured district, its listings and factor."""
    import database
    conn = database.get_conn()
    try:
        if not database._has_table(conn, "price_comps_cz"):
            return []
        stored = _stored(conn)
    except sqlite3.Error as e:
        log.warning("Czech district price factors not read: %s: %s", type(e).__name__, e)
        return []
    finally:
        conn.close()
    return [{"District": d, "City": r["city"], "Listings": r["n"],
             "Median ask Kč/m²": r["median_czk_m2"], "City median ask Kč/m²":
             r["city_median_czk_m2"], "Factor": r["factor"]}
            for d, r in sorted(stored.items(), key=lambda kv: (kv[1]["city"], -kv[1]["n"]))]

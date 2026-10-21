"""
engine/rent_comps_cz.py — live Kč/m² rents from Czech rental (pronájem)
listings, built the way engine/rent_comps builds Slovakia's:

  scraper/rentals_cz.py   reads rentals into rental_listings (market "cz", Kč)
  rebuild_rent_comps()    aggregates them into rent_comps (market "cz",
                          source "live_pronajem"), one row per rent key
                          (engine.rent_cz.match_rent_key: a town, or a key of
                          the Deloitte table)
  load_live_rates()       {key: Kč/m²} for get_rent_estimate(rates=...)

Each comp is restated as a bare-rent unfurnished flat's Kč/m² (no rooms
adjustment: the Czech baseline is an all-sizes average), rentals that
include energies are dropped, and the bounds are the Czech profile's (rent
3 000–150 000 Kč, 70–1 100 Kč/m²). There is no ceiling check against a
regulated rent (Slovakia's ASPNB): Czech rents are not capped that way.

The rate in use for a key: with a Deloitte figure, the live median (less the
asking-rent haircut) blended with it as engine/rent_comps does; without one,
the live median less the haircut, once RENT_COMP_MIN_SAMPLE comps agree on it
— the method's parameters are Slovakia's, the same for both markets.
"""

from __future__ import annotations

import logging
import re
import statistics
import unicodedata
from datetime import datetime, timedelta, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    RENT_COMP_ASKING_HAIRCUT, RENT_COMP_MIN_SAMPLE, RENT_COMP_PRIOR_WEIGHT,
    RENT_COMP_MAX_AGE_DAYS,
)

log = logging.getLogger(__name__)

MARKET = "cz"
SOURCE_TAG = "live_pronajem"
RESCORE_THRESHOLD = 0.02


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _profile():
    import markets
    return markets.get(MARKET)


# ── Reading a Czech rental ad ─────────────────────────────────────────────────
_ENERGIES_INCLUDED_RE = re.compile(
    r"vc(?:etne|\.)\s*(?:vsech\s+)?(?:energi|poplatk|sluzeb|zaloh|inkas)|"
    r"(?<!\w)(?:i\s+)?se?\s+(?:energiemi|poplatky|zalohami)(?!\w)|"
    r"energie\s+(?:jsou\s+)?v\s+cene|v\s+cene\s+(?:jsou\s+|je\s+)?(?:i\s+)?energi|"
    r"vse\s+v\s+cene|all\s+inclusive")


def energies_included(text: str) -> bool:
    """True when the ad says the rent already covers energies / services."""
    return bool(_ENERGIES_INCLUDED_RE.search(_fold(text)))


def furnishing_from_text(text: str) -> str:
    """'furnished' / 'semi' / 'unfurnished' / 'unknown' from Czech ad text."""
    t = _fold(text)
    # A bathroom's fittings or a fitted kitchen say nothing about furniture.
    t = re.sub(r"socialni\w*\s+zarizeni\w*|zarizen\w*\s+kuchyn\w*|"
               r"kuchyn\w*(?:\s+\w+){0,2}\s+zarizen\w*", " ", t)
    if re.search(r"nezarizen|nevybaven|bez\s+nabytku", t):
        return "unfurnished"
    if re.search(r"castecne\s+(?:zarizen|vybaven)", t):
        return "semi"
    if re.search(r"(?<!\w)zarizen|(?<!\w)vybaven\w*\s+nabyt|kompletne\s+vybaven", t):
        return "furnished"
    return "unknown"


# Not a whole flat let long-term: a room on offer (not a flat that names its
# "obývací pokoj" or "3 pokoje"), a bed, a shared flat, a nightly let.
_NOT_A_FLAT_RE = re.compile(
    r"(?:pro|pod)najem\s+pokoj|pokoj\w*\s+k\s+(?:pro|pod)najmu|"
    r"(?:volny|samostatny)\s+pokoj\s+ve?\s+|pokoj\w*\s+ve\s+sdilen|ve\s+sdilen\w*\s+byt|"
    r"(?:pro|pod)naj\w*\s+(?:(?!byt|dum|domu|rd(?!\w))\w+\s+){0,2}pokoj(?:e|u|ik\w*)?(?!\w)|"
    r"spolubydl|(?<!\w)luzk|ubytovan|"
    r"(?:na|za|/)\s*noc(?!\w)|na\s+den(?!\w)|kratkodob|airbnb")


def is_long_term_flat(*texts: str) -> bool:
    """False for a room, a bed, a shared or a short let. The first text is
    the title: one that starts with "Pokoj" offers a room."""
    if texts and re.match(r"\W*pokoj", _fold(texts[0])):
        return False
    return not _NOT_A_FLAT_RE.search(" ".join(_fold(t) for t in texts))


def is_plausible_rent(rent: float, size_m2: float) -> bool:
    p = _profile()
    if not rent or not size_m2 or size_m2 <= 0:
        return False
    if not (p.rent_min <= rent <= p.rent_max):
        return False
    return p.rent_per_m2_min <= rent / size_m2 <= p.rent_per_m2_max


def baseline_czk_per_m2(rent: float, size_m2: float, furnished: str | None = None) -> float:
    """A rental's Kč/m² restated as a bare, unfurnished flat's."""
    p = _profile()
    rate = rent / size_m2
    if furnished == "furnished":
        rate /= p.furnished_rent_premium
    elif furnished == "semi":
        rate /= p.semi_furnished_premium
    return rate


def aggregate(rentals: list[dict]) -> dict[str, dict]:
    """{key: {n, median_czk_per_m2, median_rent, mean_rent}} from rental rows
    (rent_eur — the rent in Kč —, size_m2, furnished, energies_included,
    rent_key)."""
    by_key: dict[str, list[dict]] = {}
    for r in rentals:
        key = r.get("rent_key")
        if not key or key == "default" or r.get("energies_included"):
            continue
        if not is_plausible_rent(r.get("rent_eur") or 0, r.get("size_m2") or 0):
            continue
        by_key.setdefault(key, []).append(r)
    out = {}
    for key, rows in by_key.items():
        per_m2 = [baseline_czk_per_m2(r["rent_eur"], r["size_m2"], r.get("furnished"))
                  for r in rows]
        rents = [r["rent_eur"] for r in rows]
        out[key] = {"n": len(rows),
                    "median_czk_per_m2": round(statistics.median(per_m2), 2),
                    "median_rent": round(statistics.median(rents), 2),
                    "mean_rent": round(statistics.fmean(rents), 2)}
    return out


def rate_for(key: str, median: float, n: int) -> float | None:
    """The Kč/m² in use for a key with `n` comps at `median`, or None when
    there are too few."""
    from engine.rent_cz import baseline_rent
    if n < RENT_COMP_MIN_SAMPLE:
        return None
    live = median * RENT_COMP_ASKING_HAIRCUT
    baseline = baseline_rent(key)
    if baseline is None:
        return round(live, 2)
    k = RENT_COMP_PRIOR_WEIGHT
    return round((n * live + k * baseline) / (n + k), 2)


def rates_from_comps(comps: dict[str, dict]) -> dict[str, float]:
    rates = {}
    for key, c in comps.items():
        rate = rate_for(key, c["median_czk_per_m2"], c["n"])
        if rate is not None:
            rates[key] = rate
    return rates


# ── DB side ───────────────────────────────────────────────────────────────────
def _stored_comps(conn) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT district, sample_count, eur_per_m2 FROM rent_comps "
        "WHERE source = ? AND size_band = 'all' AND market = ?",
        (SOURCE_TAG, MARKET)).fetchall()
    return {r["district"]: {"n": r["sample_count"] or 0,
                            "median_czk_per_m2": r["eur_per_m2"] or 0} for r in rows}


def load_live_rates() -> dict[str, float]:
    """The Czech live rates scoring should use now; {} when none are built."""
    from database import get_conn
    conn = get_conn()
    try:
        return rates_from_comps(_stored_comps(conn))
    except Exception:
        return {}
    finally:
        conn.close()


def rebuild_rent_comps(max_age_days: int = RENT_COMP_MAX_AGE_DAYS) -> dict:
    """Re-aggregate the Czech comps from current Czech rentals and send the
    Czech listings whose rate moved back for scoring. Returns {"keys",
    "rentals", "changed", "rescored"} like engine.rent_comps."""
    from database import get_conn, _drop_cashflow_score, _ensure_market_columns
    from engine.rent_cz import match_rent_key, baseline_rent
    conn = get_conn()
    try:
        _ensure_market_columns(conn)
        old_rates = rates_from_comps(_stored_comps(conn))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        rentals = [dict(r) for r in conn.execute(
            "SELECT rent_eur, size_m2, rooms, furnished, energies_included, rent_key, district "
            "FROM rental_listings WHERE is_active = 1 AND last_seen_at >= ? AND market = ?",
            (cutoff, MARKET)).fetchall()]
        for r in rentals:                       # keyed as the rules read it now
            r["rent_key"] = match_rent_key(r["district"]) if r.get("district") else r["rent_key"]
        comps = aggregate(rentals)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM rent_comps WHERE source = ? AND market = ?",
                     (SOURCE_TAG, MARKET))
        for key, c in comps.items():
            conn.execute(
                "INSERT INTO rent_comps (id, district, city, size_band, avg_rent_eur, "
                "median_rent_eur, sample_count, source, updated_at, eur_per_m2, market) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"live-cz-{key}", key, "", "all", c["mean_rent"], c["median_rent"],
                 c["n"], SOURCE_TAG, now, c["median_czk_per_m2"], MARKET))
        new_rates = rates_from_comps(comps)
        changed = []
        for key in set(old_rates) | set(new_rates):
            before = old_rates.get(key) or baseline_rent(key)
            after = new_rates.get(key) or baseline_rent(key)
            if before is None or after is None:
                if before != after:
                    changed.append(key)         # a rate appeared or went away
            elif abs(after / before - 1) >= RESCORE_THRESHOLD:
                changed.append(key)
        rescored = 0
        if changed:
            wanted = set(changed)
            for r in conn.execute("SELECT id, district FROM listings "
                                  "WHERE is_active = 1 AND market = ?", (MARKET,)).fetchall():
                if match_rent_key(r["district"] or "") in wanted:
                    rescored += _drop_cashflow_score(conn, r["id"])
        conn.commit()
    finally:
        conn.close()
    return {"keys": len(comps), "rentals": sum(c["n"] for c in comps.values()),
            "changed": sorted(changed), "rescored": rescored}


def comps_table() -> list[dict]:
    """Rows for the dashboard's comps tab, Czech keys."""
    from database import get_conn
    from engine.rent_cz import baseline_rent
    conn = get_conn()
    try:
        stored = _stored_comps(conn)
    except Exception:
        stored = {}
    finally:
        conn.close()
    rates = rates_from_comps(stored)
    rows = []
    for key, c in sorted(stored.items(), key=lambda kv: -kv[1]["n"]):
        base = baseline_rent(key)
        rows.append({
            "District key": key, "Comps": c["n"],
            "Live median Kč/m²": c["median_czk_per_m2"],
            "Baseline Kč/m²": base,
            "In use Kč/m²": rates.get(key, base),
            "Source": ("live blend" if key in rates and base else
                       "live" if key in rates else
                       "baseline (too few)" if base else "none (too few)"),
        })
    return rows

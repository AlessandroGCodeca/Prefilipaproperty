"""
engine/rent_comps.py — live €/m² rents from real "prenájom" listings.

Every number the engine produces starts from the rent estimate, and the rent
estimate starts from RENT_PER_M2 in config.py: a hand-maintained table of
published-report figures. This module replaces it, district by district, with
what flats are actually being offered for.

  scraper/rentals.py      reads rental listings into rental_listings
  rebuild_rent_comps()    aggregates them into rent_comps, one row per
                          RENT_PER_M2 key (engine.financial.match_rent_key)
  load_live_rates()       {key: €/m²} for get_rent_estimate(rates=...)

Each comp is normalised to the same basis as the baseline table before it is
compared with it — a bare-rent, unfurnished 2-izb flat:
  - rentals whose price includes energies are dropped (the baseline is bare
    rent; "+ energie" is the usual Slovak quote and is kept);
  - €/m² is divided by the rooms multiplier (a garsónka lets for 1.15× a
    2-izb per m²) and by the furnished premium when the ad says furnished,
    because get_rent_estimate multiplies both back in per listing.

A key's live rate is the median of its comps, cut by RENT_COMP_ASKING_HAIRCUT
(asking rent is above achieved rent), then blended with the baseline with the
baseline weighted as RENT_COMP_PRIOR_WEIGHT comps — so a handful of rentals
nudges the rate and dozens replace it. Keys with fewer than
RENT_COMP_MIN_SAMPLE comps keep the baseline outright.
"""

from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    RENT_PER_M2, RENT_COMP_ASKING_HAIRCUT, RENT_COMP_MIN_SAMPLE,
    RENT_COMP_PRIOR_WEIGHT, RENT_COMP_MAX_AGE_DAYS, RENT_MIN_EUR, RENT_MAX_EUR,
    FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
)

# €/m² outside this is a parse error (a sale price, a per-night rate, a size
# read off a balcony), not a market.
_MIN_EUR_PER_M2 = 3.0
_MAX_EUR_PER_M2 = 45.0

# A rate that moved less than this since the last rebuild is not worth
# re-scoring every listing in its district for.
RESCORE_THRESHOLD = 0.02


def _fold(text: str) -> str:
    from scraper.textparse import strip_diacritics
    return strip_diacritics(text or "").lower()


_ENERGIES_INCLUDED_RE = re.compile(
    r"vratane\s+(?:vsetkych\s+)?(?:energi|poplatk|sluzieb)"
    r"|s\s+energiami|energie\s+(?:su\s+)?v\s+cene|v\s+cene\s+(?:su\s+|je\s+)?(?:aj\s+)?energi"
    r"|vsetko\s+v\s+cene|all\s+inclusive|cena\s+s\s+energiami"
)


def energies_included(text: str) -> bool:
    """True when the ad says the rent already covers energies/services."""
    return bool(_ENERGIES_INCLUDED_RE.search(_fold(text)))


def furnishing_from_text(text: str) -> str:
    """'furnished' / 'semi' / 'unfurnished' / 'unknown' from rental ad text."""
    t = _fold(text)
    if "nezariaden" in t:
        return "unfurnished"
    if re.search(r"ciastocne\s+zariaden|polozariaden|ciastocne\s+vybaven", t):
        return "semi"
    if re.search(r"zariaden|vybaven[ya]\s+nabytk|kompletne\s+vybaven", t):
        return "furnished"
    return "unknown"


# Not a whole flat let long-term: a single room, a bed, a nightly let.
_NOT_A_FLAT_RE = re.compile(
    r"\bizba\b|prenajom\s+izby|podnajom\s+izby|spolubyv|\blozko\b|ubytovan"
    r"|na\s+noc\b|/\s*noc\b|za\s+noc\b|na\s+den\b|kratkodob|airbnb|apartman\s+na\s+noc"
)


def is_long_term_flat(*texts: str) -> bool:
    folded = " ".join(_fold(t) for t in texts)
    return not _NOT_A_FLAT_RE.search(folded)


def is_plausible_rent(rent_eur: float, size_m2: float) -> bool:
    if not rent_eur or not size_m2 or size_m2 <= 0:
        return False
    if not (RENT_MIN_EUR <= rent_eur <= RENT_MAX_EUR):
        return False
    return _MIN_EUR_PER_M2 <= rent_eur / size_m2 <= _MAX_EUR_PER_M2


def baseline_eur_per_m2(rent_eur: float, size_m2: float, rooms=None,
                        furnished: str | None = None) -> float:
    """A rental's €/m² restated as a bare, unfurnished 2-izb flat's."""
    from engine.financial import _rooms_multiplier
    rate = rent_eur / size_m2 / _rooms_multiplier(rooms)
    if furnished == "furnished":
        rate /= FURNISHED_RENT_PREMIUM
    elif furnished == "semi":
        rate /= SEMI_FURNISHED_PREMIUM
    return rate


def blended_rate(live_median: float, n: int, baseline: float) -> float:
    """Shrink a live median towards the baseline by sample size."""
    live = live_median * RENT_COMP_ASKING_HAIRCUT
    k = RENT_COMP_PRIOR_WEIGHT
    return round((n * live + k * baseline) / (n + k), 2)


def aggregate(rentals: list[dict]) -> dict[str, dict]:
    """{rent key: {n, median_eur_per_m2, median_rent, mean_rent}} from rental
    rows (rent_eur, size_m2, rooms, furnished, energies_included, rent_key).
    Rows that fail the plausibility checks or include energies are skipped.
    """
    by_key: dict[str, list[dict]] = {}
    for r in rentals:
        key = r.get("rent_key")
        if not key or key == "default":
            continue
        if r.get("energies_included"):
            continue
        if not is_plausible_rent(r.get("rent_eur") or 0, r.get("size_m2") or 0):
            continue
        by_key.setdefault(key, []).append(r)
    out = {}
    for key, rows in by_key.items():
        per_m2 = [baseline_eur_per_m2(r["rent_eur"], r["size_m2"], r.get("rooms"),
                                      r.get("furnished")) for r in rows]
        rents = [r["rent_eur"] for r in rows]
        out[key] = {
            "n":                 len(rows),
            "median_eur_per_m2": round(statistics.median(per_m2), 2),
            "median_rent":       round(statistics.median(rents), 2),
            "mean_rent":         round(statistics.fmean(rents), 2),
        }
    return out


def rates_from_comps(comps: dict[str, dict]) -> dict[str, float]:
    """{key: blended €/m²} for every key with enough comps."""
    rates = {}
    for key, c in comps.items():
        if c["n"] < RENT_COMP_MIN_SAMPLE:
            continue
        baseline = RENT_PER_M2.get(key, RENT_PER_M2["default"])
        rates[key] = blended_rate(c["median_eur_per_m2"], c["n"], baseline)
    return rates


# ── DB side ───────────────────────────────────────────────────────────────────
def _active_rentals(conn, max_age_days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    rows = conn.execute("""
        SELECT rent_eur, size_m2, rooms, furnished, energies_included, rent_key
        FROM rental_listings
        WHERE is_active = 1 AND last_seen_at >= ?
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def _stored_comps(conn) -> dict[str, dict]:
    rows = conn.execute("""
        SELECT district, sample_count, eur_per_m2 FROM rent_comps
        WHERE source = 'live_prenajom' AND size_band = 'all'
    """).fetchall()
    return {r["district"]: {"n": r["sample_count"] or 0,
                            "median_eur_per_m2": r["eur_per_m2"] or 0} for r in rows}


def load_live_rates() -> dict[str, float]:
    """The live rates scoring should use right now. Empty (→ baseline
    everywhere) when no comps have been built or the tables don't exist yet."""
    from database import get_conn
    conn = get_conn()
    try:
        return rates_from_comps(_stored_comps(conn))
    except Exception:
        return {}
    finally:
        conn.close()


def rebuild_rent_comps(max_age_days: int = RENT_COMP_MAX_AGE_DAYS) -> dict:
    """Re-aggregate rent_comps from current rentals and re-score the listings
    whose district rate moved.

    Returns {"keys": n districts with comps, "rentals": n rentals used,
             "changed": [keys whose rate moved ≥ RESCORE_THRESHOLD],
             "rescored": n scores dropped for re-scoring}.
    """
    from database import get_conn, _drop_cashflow_score
    from engine.financial import match_rent_key
    conn = get_conn()
    try:
        old_rates = rates_from_comps(_stored_comps(conn))
        comps = aggregate(_active_rentals(conn, max_age_days))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM rent_comps WHERE source = 'live_prenajom'")
        for key, c in comps.items():
            conn.execute("""
                INSERT INTO rent_comps
                (id, district, city, size_band, avg_rent_eur, median_rent_eur,
                 sample_count, source, updated_at, eur_per_m2)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (f"live-{key}", key, "", "all", c["mean_rent"], c["median_rent"],
                  c["n"], "live_prenajom", now, c["median_eur_per_m2"]))
        new_rates = rates_from_comps(comps)

        changed = []
        for key in set(old_rates) | set(new_rates):
            before = old_rates.get(key) or RENT_PER_M2.get(key, RENT_PER_M2["default"])
            after = new_rates.get(key) or RENT_PER_M2.get(key, RENT_PER_M2["default"])
            if before and abs(after / before - 1) >= RESCORE_THRESHOLD:
                changed.append(key)

        rescored = 0
        if changed:
            wanted = set(changed)
            for r in conn.execute(
                    "SELECT id, district FROM listings WHERE is_active = 1").fetchall():
                if match_rent_key(r["district"] or "") in wanted:
                    rescored += _drop_cashflow_score(conn, r["id"])
        conn.commit()
    finally:
        conn.close()
    return {"keys": len(comps), "rentals": sum(c["n"] for c in comps.values()),
            "changed": sorted(changed), "rescored": rescored}


def comps_table() -> list[dict]:
    """Rows for the dashboard: key, baseline, live median, n, rate in use."""
    from database import get_conn
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
        baseline = RENT_PER_M2.get(key, RENT_PER_M2["default"])
        rows.append({
            "District key":   key,
            "Comps":          c["n"],
            "Live median €/m²": c["median_eur_per_m2"],
            "Baseline €/m²":  baseline,
            "In use €/m²":    rates.get(key, baseline),
            "Source":         "live blend" if key in rates else "baseline (too few)",
        })
    return rows

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

By flat type (M10 of the 12 Nov audit): the comps of each key are also split
by rooms (1, 2, 3, 4+). Where one type has ROOMS_MIN_SAMPLE comps of its own,
its median (furnishing still normalised away) is blended with that type's
baseline and replaces the district rate × the fixed rooms multiplier for
flats of that type — under the key "<key>#r<rooms>" in the rates. The split
by furnishing is shown, not scored. time_to_let() is how long rental ads of
a type stay up: the days between first and last seen, of ads gone for good.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    RENT_COMP_ASKING_HAIRCUT, RENT_COMP_MIN_SAMPLE,
    RENT_COMP_PRIOR_WEIGHT, RENT_COMP_MAX_AGE_DAYS, RENT_MIN_EUR, RENT_MAX_EUR,
    FURNISHED_RENT_PREMIUM, SEMI_FURNISHED_PREMIUM,
)

log = logging.getLogger(__name__)

# €/m² outside this is a parse error (a sale price, a per-night rate, a size
# read off a balcony), not a market.
_MIN_EUR_PER_M2 = 3.0
_MAX_EUR_PER_M2 = 45.0

# A rate that moved less than this since the last rebuild is not worth
# re-scoring every listing in its district for.
RESCORE_THRESHOLD = 0.02
# Comps a flat type needs before its own rate replaces the rooms multiplier.
ROOMS_MIN_SAMPLE = 6
# A rental ad unseen this many days before the newest sighting is gone (let).
GONE_AFTER_DAYS = 5


def _fold(text: str) -> str:
    from scraper.textparse import strip_diacritics
    return strip_diacritics(text or "").lower()


_ENERGIES_INCLUDED_RE = re.compile(
    r"vratane\s+(?:vsetkych\s+)?(?:energi|poplatk|sluzieb|zaloh)|(?<!\w)so\s+zalohami"
    r"|s\s+energiami|energie\s+(?:su\s+)?v\s+cene|v\s+cene\s+(?:su\s+|je\s+)?(?:aj\s+)?energi"
    r"|vsetko\s+v\s+cene|all\s+inclusive|cena\s+s\s+energiami"
)


def energies_included(text: str) -> bool:
    """True when the ad says the rent already covers energies/services."""
    return bool(_ENERGIES_INCLUDED_RE.search(_fold(text)))


def furnishing_from_text(text: str) -> str:
    """'furnished' / 'semi' / 'unfurnished' / 'unknown' from rental ad text."""
    t = _fold(text)
    # A bathroom's fittings or a fitted (or unequipped) kitchen say nothing
    # about furniture: "nevybavená kuchyňa, inak zariadený byt" is furnished.
    t = re.sub(r"(?:socialn|sanitarn|hygienick)\w*\s+zariaden\w*|zariaden\w*\s+kuchyn\w*|"
               r"kuchyn\w*(?:\s+\w+){0,2}\s+zariaden\w*|"
               r"nevybaven\w*\s+kuchyn\w*|kuchyn\w*(?:\s+\w+){0,2}\s+nevybaven\w*", " ", t)
    if re.search(r"nezariaden|bez\s+(?:zariadenia|nabytku)|nevybaven", t):
        return "unfurnished"
    if re.search(r"ciastocne\s+zariaden|polozariaden|ciastocne\s+vybaven"
                 r"|ciastocne\s+s\s+nabytkom", t):
        return "semi"
    # The participle that describes the flat ("zariadený", "plne zariadená")
    # or a flat let "so zariadením", never the noun on its own (a facility:
    # "predškolské zariadenie").
    if re.search(r"(?<!\w)zariaden(?:y|a|e|eho|emu|om|ej|u|ych|ym|ymi)(?!\w)"
                 r"|(?<!\w)(?:so|s\s+(?:kompletnym|celym|plnym|novym))\s+zariadenim(?!\w)"
                 r"|vybaven[ya]\s+nabytk|kompletne\s+vybaven"
                 r"|(?<!\w)s\s+nabytkom|nabytok\s+(?:je\s+)?v\s+cene", t):
        return "furnished"
    return "unknown"


# Not a whole flat let long-term: a single room on offer (not a flat that
# names its "obývacia izba"), a bed, a nightly let. Folded, "prenájom" is
# "prenajom" and "prenájmu"/"prenajmem" are "prenajm…": both stems count
# ("izba na prenájom", "izbu do prenájmu", "Na prenájom izba").
_NOT_A_FLAT_RE = re.compile(
    r"prenajom\s+izby|podnajom\s+izby|"
    r"izb[au]\s+(?:na|k|do)\s+(?:(?:pre|pod)naj(?:om|m\w*)|naj(?:om|mu)(?!\w))|"
    r"(?:pre|pod)naj(?:om|m\w*)\s+(?:(?!byt)\w+\s+){0,2}izbu(?!\w)|"
    r"(?:pre|pod)najom(?:\s*[:\-–]\s*|\s+)izb[auy](?!\w)|"
    r"(?:volna|samostatna)\s+izba\s+v|spolubyv|\blozko\b|ubytovan"
    r"|na\s+noc\b|/\s*noc\b|za\s+noc\b|na\s+den\b|kratkodob|airbnb|apartman\s+na\s+noc"
)

# A title that offers a room: "Izba …", "Voľná izba od 1.11.", "Samostatná
# izba pre 1 osobu". Only at the start of the title — inside a whole flat's
# ad "obývačka a samostatná izba" is one of its rooms.
_ROOM_TITLE_RE = re.compile(r"\W*(?:(?:volna|samostatna|volnu|samostatnu)\s+)?izb[auy](?!\w)")


def is_long_term_flat(*texts: str) -> bool:
    """False for a room, a bed, a shared or a short let. The first text is
    the title: one that starts with "Izba" (or "Voľná/Samostatná izba")
    offers a room."""
    if texts and _ROOM_TITLE_RE.match(_fold(texts[0])):
        return False
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


def room_band(rooms) -> int:
    """1, 2, 3 or 4 (four rooms or more); 2 when unknown."""
    try:
        r = int(float(rooms))
    except (TypeError, ValueError):
        return 2
    return min(max(r, 1), 4)


def _furnish_bucket(furnished) -> str:
    return "furnished" if furnished in ("furnished", "semi") else "unfurnished"


def aggregate_by_rooms(rentals: list[dict]) -> dict[tuple[str, int], dict]:
    """{(key, rooms band): {n, median_eur_per_m2, by_furnishing: {bucket:
    {n, median_eur_per_m2}}}} — €/m² with furnishing normalised away but not
    the rooms (that is what the split is for); by_furnishing is as asked."""
    groups: dict[tuple[str, int], list[dict]] = {}
    for r in rentals:
        key = r.get("rent_key")
        if not key or key == "default" or r.get("energies_included"):
            continue
        if not is_plausible_rent(r.get("rent_eur") or 0, r.get("size_m2") or 0):
            continue
        groups.setdefault((key, room_band(r.get("rooms"))), []).append(r)
    out = {}
    for gk, rows in groups.items():
        norm = [baseline_eur_per_m2(r["rent_eur"], r["size_m2"], None, r.get("furnished"))
                for r in rows]
        split: dict[str, list[float]] = {}
        for r in rows:
            split.setdefault(_furnish_bucket(r.get("furnished")), []).append(
                r["rent_eur"] / r["size_m2"])
        out[gk] = {"n": len(rows), "median_eur_per_m2": round(statistics.median(norm), 2),
                   "by_furnishing": {b: {"n": len(v), "median_eur_per_m2":
                                         round(statistics.median(v), 2)}
                                     for b, v in split.items()}}
    return out


def rates_by_rooms(comps: dict[tuple[str, int], dict]) -> dict[str, float]:
    """{"<key>#r<band>": blended €/m²} for each flat type with
    ROOMS_MIN_SAMPLE comps; its baseline is the key's × the rooms multiplier."""
    from engine.financial import _rooms_multiplier, baseline_rent
    out = {}
    for (key, band), c in comps.items():
        if c["n"] < ROOMS_MIN_SAMPLE:
            continue
        prior = baseline_rent(key) * _rooms_multiplier(band)
        out[f"{key}#r{band}"] = blended_rate(c["median_eur_per_m2"], c["n"], prior)
    return out


def time_to_let(rentals: list[dict], min_n: int = 3) -> dict[tuple[str, int], dict]:
    """{(key, rooms band): {n, median_days}} — how long ads gone for good
    stayed up. An ad already up when tracking began is left out (its start
    is unknown), as is one still up."""
    seen = [r for r in rentals if r.get("scraped_at") and r.get("last_seen_at")]
    if not seen:
        return {}
    parse = datetime.fromisoformat
    newest = max(parse(r["last_seen_at"]) for r in seen)
    first = min(parse(r["scraped_at"]) for r in seen)
    groups: dict[tuple[str, int], list[float]] = {}
    for r in seen:
        start, last = parse(r["scraped_at"]), parse(r["last_seen_at"])
        if (newest - last).days < GONE_AFTER_DAYS or (start - first).days < 2:
            continue
        key = r.get("rent_key")
        if not key or key == "default":
            continue
        groups.setdefault((key, room_band(r.get("rooms"))), []).append(
            max((last - start).total_seconds() / 86400, 0.0))
    return {k: {"n": len(v), "median_days": round(statistics.median(v))}
            for k, v in groups.items() if len(v) >= min_n}


def rates_from_comps(comps: dict[str, dict]) -> dict[str, float]:
    """{key: blended €/m²} for every key with enough comps."""
    from engine.financial import baseline_rent
    rates = {}
    for key, c in comps.items():
        if c["n"] < RENT_COMP_MIN_SAMPLE:
            continue
        baseline = baseline_rent(key)
        rates[key] = blended_rate(c["median_eur_per_m2"], c["n"], baseline)
    return rates


# ── DB side ───────────────────────────────────────────────────────────────────
def _sk_rows(conn, table: str) -> str:
    """" AND market = 'sk'" when `table` has a market column — another
    market's rentals, comps and listings are its own (engine.rent_comps_cz) —
    else "" (a database from before markets: every row is Slovak)."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return " AND market = 'sk'" if "market" in cols else ""


def _active_rentals(conn, max_age_days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    rows = conn.execute(f"""
        SELECT rent_eur, size_m2, rooms, furnished, energies_included, rent_key,
               scraped_at, last_seen_at
        FROM rental_listings
        WHERE is_active = 1 AND last_seen_at >= ?{_sk_rows(conn, "rental_listings")}
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def _stored_room_comps(conn) -> dict[tuple[str, int], dict]:
    rows = conn.execute(f"""
        SELECT district, size_band, sample_count, eur_per_m2 FROM rent_comps
        WHERE source = 'live_prenajom' AND size_band LIKE 'r_'{_sk_rows(conn, "rent_comps")}
    """).fetchall()
    return {(r["district"], int(r["size_band"][1])): {"n": r["sample_count"] or 0,
                                                       "median_eur_per_m2": r["eur_per_m2"] or 0}
            for r in rows}


def _stored_comps(conn) -> dict[str, dict]:
    rows = conn.execute(f"""
        SELECT district, sample_count, eur_per_m2 FROM rent_comps
        WHERE source = 'live_prenajom' AND size_band = 'all'{_sk_rows(conn, "rent_comps")}
    """).fetchall()
    return {r["district"]: {"n": r["sample_count"] or 0,
                            "median_eur_per_m2": r["eur_per_m2"] or 0} for r in rows}


def load_live_rates(market: str = "sk") -> dict[str, float]:
    """The live rates scoring should use right now. Empty (→ baseline
    everywhere) when no comps have been built or the tables don't exist yet.
    (Another market's comps: engine.rent_comps_cz.)"""
    if market != "sk":
        from engine import rent_comps_cz
        return rent_comps_cz.load_live_rates()
    from database import get_conn, _has_table
    conn = get_conn()
    try:
        if not _has_table(conn, "rent_comps"):
            return {}
        return {**rates_from_comps(_stored_comps(conn)),
                **rates_by_rooms(_stored_room_comps(conn))}
    except sqlite3.Error as e:
        log.warning("Live rent comps not read, scoring uses the baseline rents: %s: %s",
                    type(e).__name__, e)
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
    from engine.financial import match_rent_key, baseline_rent
    conn = get_conn()
    try:
        old_rates = {**rates_from_comps(_stored_comps(conn)),
                     **rates_by_rooms(_stored_room_comps(conn))}
        active = _active_rentals(conn, max_age_days)
        comps = aggregate(active)
        by_rooms = aggregate_by_rooms(active)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM rent_comps WHERE source = 'live_prenajom'"
                     + _sk_rows(conn, "rent_comps"))
        for key, c in comps.items():
            conn.execute("""
                INSERT INTO rent_comps
                (id, district, city, size_band, avg_rent_eur, median_rent_eur,
                 sample_count, source, updated_at, eur_per_m2)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (f"live-{key}", key, "", "all", c["mean_rent"], c["median_rent"],
                  c["n"], "live_prenajom", now, c["median_eur_per_m2"]))
        for (key, band), c in by_rooms.items():
            conn.execute("""
                INSERT INTO rent_comps
                (id, district, city, size_band, avg_rent_eur, median_rent_eur,
                 sample_count, source, updated_at, eur_per_m2)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (f"live-{key}-r{band}", key, "", f"r{band}", None, None,
                  c["n"], "live_prenajom", now, c["median_eur_per_m2"]))
        new_rates = {**rates_from_comps(comps), **rates_by_rooms(by_rooms)}

        changed = []
        for key in set(old_rates) | set(new_rates):
            base = baseline_rent(key.split("#")[0])
            before = old_rates.get(key) or base
            after = new_rates.get(key) or base
            if before and abs(after / before - 1) >= RESCORE_THRESHOLD:
                changed.append(key.split("#")[0])
        changed = sorted(set(changed))

        rescored = 0
        if changed:
            wanted = set(changed)
            for r in conn.execute(
                    "SELECT id, district FROM listings WHERE is_active = 1"
                    + _sk_rows(conn, "listings")).fetchall():
                if match_rent_key(r["district"] or "") in wanted:
                    rescored += _drop_cashflow_score(conn, r["id"])
        conn.commit()
    finally:
        conn.close()
    return {"keys": len(comps), "rentals": sum(c["n"] for c in comps.values()),
            "changed": sorted(changed), "rescored": rescored}


def comps_table() -> list[dict]:
    """Rows for the dashboard: key, baseline, live median, n, rate in use."""
    from database import get_conn, _has_table
    conn = get_conn()
    try:
        stored = _stored_comps(conn) if _has_table(conn, "rent_comps") else {}
    except sqlite3.Error as e:
        log.warning("Live rent comps not read for the comps table: %s: %s", type(e).__name__, e)
        stored = {}
    finally:
        conn.close()
    from engine.financial import baseline_rent
    rates = rates_from_comps(stored)
    rows = []
    for key, c in sorted(stored.items(), key=lambda kv: -kv[1]["n"]):
        baseline = baseline_rent(key)
        rows.append({
            "District key":   key,
            "Comps":          c["n"],
            "Live median €/m²": c["median_eur_per_m2"],
            "Baseline €/m²":  baseline,
            "In use €/m²":    rates.get(key, baseline),
            "Source":         "live blend" if key in rates else "baseline (too few)",
        })
    return rows


def rooms_table(max_age_days: int = RENT_COMP_MAX_AGE_DAYS) -> list[dict]:
    """Rows for the dashboard, one per district key and flat type: the comps,
    the unfurnished and furnished €/m² as asked, the rate scoring uses, and
    how long such ads stay up."""
    from database import get_conn, _has_table
    from engine.financial import _rooms_multiplier, baseline_rent
    conn = get_conn()
    try:
        if not _has_table(conn, "rental_listings"):
            return []
        active = _active_rentals(conn, max_age_days)
        everyone = [dict(r) for r in conn.execute(
            "SELECT rent_key, rooms, scraped_at, last_seen_at FROM rental_listings WHERE 1=1"
            + _sk_rows(conn, "rental_listings")).fetchall()]
    except sqlite3.Error as e:
        log.warning("Rent comps by type not read: %s: %s", type(e).__name__, e)
        return []
    finally:
        conn.close()
    comps = aggregate_by_rooms(active)
    rates = rates_by_rooms(comps)
    days = time_to_let(everyone)
    label = {1: "1 room", 2: "2 rooms", 3: "3 rooms", 4: "4+ rooms"}
    rows = []
    for (key, band), c in sorted(comps.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        fur = c["by_furnishing"]
        rows.append({
            "District key": key, "Flat": label[band], "Comps": c["n"],
            "Unfurnished €/m²": (fur.get("unfurnished") or {}).get("median_eur_per_m2"),
            "Furnished €/m²": (fur.get("furnished") or {}).get("median_eur_per_m2"),
            "In use €/m²": rates.get(f"{key}#r{band}",
                                     round(baseline_rent(key) * _rooms_multiplier(band), 2)),
            "Source": "this type's comps" if f"{key}#r{band}" in rates else "district × rooms factor",
            "Days to let": (days.get((key, band)) or {}).get("median_days"),
        })
    return rows


def type_note(district: str, rooms, table: list[dict] | None = None) -> str:
    """One line for a card: this flat type's comps and time to let, or "".
    `table` is rooms_table() when the caller has it already."""
    from engine.financial import match_rent_key
    key, band = match_rent_key(district or ""), room_band(rooms)
    for r in (rooms_table() if table is None else table):
        if r["District key"] == key and r["Flat"].startswith(str(band)):
            days = f" · ads stay up ~{r['Days to let']} days" if r["Days to let"] else ""
            return (f"{r['Flat']} in {key}: {r['Comps']} rental comps, "
                    f"€{r['In use €/m²']:.2f}/m² in use ({r['Source']}){days}")
    return ""

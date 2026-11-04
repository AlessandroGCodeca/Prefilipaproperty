"""
modules/tax_rates.py — the dashboard's "update property-tax rates" button.

One click reads every town's flat rate (daň z bytov, €/m² a year) from the
town's own site (scraper/property_tax_rates), compares it with what the
engine charges (engine/property_tax_sk) and acts on it:

  confirmed  the site states the rate the engine already charges;
  applied    a dated ordinance sets another rate from a later tax year than
             the one the table was checked for (TABLE_YEAR) — stored, and
             charged from that year;
  upcoming   the current rate is confirmed and a published ordinance sets a
             new one for a later year — stored for that year;
  new        a town the table doesn't have — its rate stored and charged
             instead of the 1.35 fallback;
  review     anything a program shouldn't settle alone: the site disagrees
             with the hand-checked table for a year the table covers, states
             several flat rates, has two documents for one year that
             disagree, or has a newer ordinance about flats this can't read.
             Nothing changes until the user accepts it (one click) — or
             keeps the table's figure;
  kept       the user kept the table's figure over a review;
  not_found  no flat rate in anything read (the reasons are listed);
  blocked    the site refused the request (a CAPTCHA, a reset connection,
             "Access Forbidden"). A document saved in the browser can be
             uploaded instead (upload()).

Then it drops the scores whose property tax changed, and the dashboard's job
re-scores them.

A town rated by cadastral area or pásmo (Bratislava, Košice, Žilina,
Dunajská Streda) is only verified: a change there needs its areas mapped by
hand, so it goes to review and nothing is stored.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine import property_tax_sk as tax
from scraper import property_tax_rates as scr

log = logging.getLogger(__name__)

STATUS_LABEL = {
    "confirmed": "✅ confirmed", "applied": "🔄 updated", "upcoming": "📅 new rate ahead",
    "new": "➕ added", "review": "⚠️ needs review", "kept": "🔒 table kept",
    "not_found": "❔ not found", "blocked": "⛔ site blocked",
}
WORKERS = 16                    # sites read at a time (each town its own site)
RECHECK_DAYS = 30               # a village is read again after this long
VILLAGE_TIME_BUDGET_S = 25 * 60 # per click: the villages due, as many as fit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _year() -> int:
    return tax._year()


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 0.0005


def rate_text(r: float) -> str:
    """1.0 → '1.00', 0.85 → '0.85', 0.675 → '0.675'."""
    t = f"{r:.3f}"
    return t[:-1] if t.endswith("0") else t


def _fmt(rates) -> str:
    return " / ".join(rate_text(r) for r in rates) + " €/m²"


def doc_name(title: str, url: str = "") -> str:
    """A document's name without the download clutter around its link
    ("VZN_17_2023.pdf 30.10.2025 (PDF, 4,96 MB)" → "VZN_17_2023.pdf")."""
    t = re.sub(r"\s+", " ", title or "")
    t = re.sub(r"(?i)stiahnu[tť]\w*|ve[lľ]kos[tť]:?\s*[\d.,]+\s*[kmg]b|typ:\s*[^,]*,?|"
               r"otvori[tť] s[uú]bor:?|s[uú]bor na stiahnutie:?|\d{1,2}\.\s?\d{1,2}\.\s?20\d\d|"
               r",?\s*otvor[ií] sa v novom okne\)?|ve[lľ]kos[tť] a typ s[uú]boru\s*/?|"
               r"(?:^|\s)s[uú]bor:?\s|\bform[aá]t\b", " ", t)
    t = re.sub(r"\(?\s*(?:pdf|docx?|odt)?\s*,?\s*[\d.,]+\s*[kmg]b\s*\)?", " ", t, flags=re.I)
    t = re.sub(r"(?i)\bplatn[ée] znenie\b|\s[-–|]\s(?:ofici[aá]lne?|mesto)\b.*$", " ", t)
    t = re.sub(r"\s(?:\||::)\s.*$", " ", t)        # a page title's " | Dunajská Streda"
    t = re.sub(r"(?i)[\s,(·]+(?:pdf|docx?|odt)[\s,)·]*$", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,;:-–·")
    if not t or t.startswith("http"):
        tail = (url or title or "").rstrip("/").split("/")[-1].split("?")[0]
        t = tail or url
    return t[:90]


# ── Deciding ──────────────────────────────────────────────────────────────────
@dataclass
class Outcome:
    town: str
    status: str
    message: str
    candidate: scr.Reading | None = None        # what a review would accept
    store: list[tuple[int, float, scr.Reading]] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _stored_rate(town: str, year: int) -> float | None:
    """The rate stored for `town` in force in `year`, if any."""
    for r in tax.stored_rates().get(tax.town_key(town), []):
        if r["tax_year"] <= year:
            return r["rate"]
    return None


def _year_note(r: scr.Reading) -> str:
    if r.tax_year:
        return f"in force from {r.tax_year}"
    return "no date stated" if r.kind == "ordinance" else "the page states no year"


def assess(town: scr.Town, res: scr.TownResult, year: int | None = None) -> Outcome:
    """What one town's reading means for the rates the engine charges."""
    year = year or _year()
    detail = {"fetched": res.fetched, "problems": res.problems[:15],
              "visited": res.visited[:40]}
    if res.upcoming:
        detail["upcoming"] = {"rates": res.upcoming.rates, "tax_year": res.upcoming.tax_year,
                              "url": res.upcoming.url, "document": doc_name(res.upcoming.title,
                                                                          res.upcoming.url)}
    cur, up = res.current, res.upcoming
    if not res.readings:
        if res.blocked:
            return Outcome(town.name, "blocked",
                           f"{res.blocked[:1].upper()}{res.blocked[1:]}. Open the town's site in "
                           f"your browser, save its VZN o miestnych daniach as PDF and upload it "
                           f"here.", detail=detail)
        why = ""
        unreadable = [p for p in res.problems if "scanned" in p or "Word (.doc)" in p]
        if unreadable:
            why = f" {len(unreadable)} could not be read (a scan or an old Word file)."
        return Outcome(town.name, "not_found",
                       f"No flat rate in the {res.fetched} pages and documents read.{why} "
                       f"Upload the ordinance, or add the page that links to it.", detail=detail)

    table = tax.table_rates(town.name)
    src = (lambda r: f"{doc_name(r.title, r.url)}, {_year_note(r)}")

    if town.zoned or tax.town_key(town.name) in tax.ZONED:
        notes, status = [], "confirmed"
        if cur:
            found = sorted(set(cur.rates))
            if table and all(any(_same(f, t) for t in table) for f in found) \
                    and all(any(_same(f, t) for f in found) for t in table):
                notes.append(f"{_fmt(found)} — the table's rates ({src(cur)}).")
            else:
                status = "review"
                notes.append(f"The site lists {_fmt(found)} ({src(cur)}); the table charges "
                             f"{_fmt(table) if table else 'nothing'} by area. A town rated by area "
                             f"needs its areas updated by hand in engine/property_tax_sk.py.")
        if up and not (table and sorted(set(up.rates)) == table):
            status = "review"
            notes.append(f"From {up.tax_year}: {_fmt(sorted(set(up.rates)))} ({src(up)}) — update "
                         f"the areas by hand.")
        return Outcome(town.name, status, " ".join(notes), candidate=cur or up, detail=detail)

    # A town with one rate for every flat.
    store: list[tuple[int, float, scr.Reading]] = []
    notes: list[str] = []
    if cur and len(set(cur.rates)) > 1:
        return Outcome(town.name, "review",
                       f"The site states several flat rates, {_fmt(cur.rates)} ({src(cur)}): by "
                       f"area, or a table of past years. Accept the one in force, if any.",
                       candidate=cur, detail=detail)
    if res.conflict:
        others = "; ".join(f"{_fmt(c.rates)} in {doc_name(c.title, c.url)}" for c in res.conflict)
        return Outcome(town.name, "review",
                       f"Two documents for the same year disagree: {_fmt(cur.rates)} in "
                       f"{doc_name(cur.title, cur.url)}; {others}.", candidate=cur, detail=detail)
    status = "confirmed"
    in_use = None
    if cur:
        rate = cur.rates[0]
        newest = next((r for r in tax.stored_rates().get(tax.town_key(town.name), [])
                       if r["tax_year"] <= year), None)
        if table:
            in_use, label = tax.rate_source(town.name, year)
            fallback = label.startswith("UNVERIFIED")
        else:
            # Not by name: "Brestov (okres Prešov)" would find Prešov's rate.
            fallback = newest is None
            in_use = tax.UNKNOWN_PLACE_RATE_PER_M2 if fallback else newest["rate"]
        if not fallback and _same(rate, in_use):
            notes.append(f"{rate_text(rate)} €/m² — as charged ({src(cur)}).")
        elif newest and newest["origin"] != "scraped" and not _same(rate, newest["rate"]):
            # A rate the user accepted or uploaded is changed only by the user.
            return Outcome(town.name, "review",
                           f"The site says {rate_text(rate)} €/m² ({src(cur)}); you set "
                           f"{rate_text(newest['rate'])} ({newest['origin']}, from "
                           f"{newest['tax_year']}). Accept the site's figure only if it is "
                           f"newer.", candidate=cur, detail=detail)
        elif table:
            if cur.dated and cur.tax_year and cur.tax_year > tax.TABLE_YEAR:
                status = "applied"
                store.append((cur.tax_year, rate, cur))
                notes.append(f"{rate_text(rate)} €/m² from {cur.tax_year}, was "
                             f"{rate_text(in_use)} ({src(cur)}).")
            else:
                return Outcome(town.name, "review",
                               f"The site says {rate_text(rate)} €/m² ({src(cur)}); the table "
                               f"charges {rate_text(in_use)}, checked by hand for "
                               f"{tax.TABLE_YEAR}. Accept it only if that document is the one "
                               f"in force.", candidate=cur, detail=detail)
        else:
            if cur.kind == "ordinance" and not cur.dated:
                return Outcome(town.name, "review",
                               f"{rate_text(rate)} €/m² in {doc_name(cur.title, cur.url)}, which "
                               f"states no date — it may be a repealed ordinance. Accept it if "
                               f"it is the one in force.", candidate=cur, detail=detail)
            first = cur.tax_year or year
            if newest and newest["tax_year"] > first:
                return Outcome(town.name, "review",
                               f"The site's newest reading, {rate_text(rate)} €/m² ({src(cur)}), "
                               f"is older than the {rate_text(newest['rate'])} charged from "
                               f"{newest['tax_year']}.", candidate=cur, detail=detail)
            status = "new" if fallback else "applied"
            store.append((first, rate, cur))
            was = (f"was the {rate_text(in_use)} fallback" if fallback
                   else f"was {rate_text(in_use)}")
            notes.append(f"{rate_text(rate)} €/m² ({src(cur)}); {was}.")
        in_use = rate
    if up:
        if len(set(up.rates)) > 1:
            return Outcome(town.name, "review",
                           " ".join(notes) + f" From {up.tax_year} the site states several flat "
                           f"rates, {_fmt(up.rates)} ({src(up)}).", candidate=up, detail=detail)
        ahead = _stored_rate(town.name, up.tax_year)
        if in_use is None or not _same(up.rates[0], in_use):
            if ahead is None or not _same(ahead, up.rates[0]):
                store.append((up.tax_year, up.rates[0], up))
            if status == "confirmed":
                status = "upcoming"
            was = f", now {rate_text(in_use)}" if in_use is not None else ""
            notes.append(f"From {up.tax_year}: {rate_text(up.rates[0])} €/m²{was} ({src(up)}).")
    if res.unread_newer:
        return Outcome(town.name, "review",
                       " ".join(notes) + " A newer ordinance about flats states no rate this "
                       f"can read ({'; '.join(doc_name(t) for t in res.unread_newer[:3])}) — check "
                       f"whether it changes the rate.", candidate=cur or up, detail=detail)
    unreadable = [p for p in res.problems if "scanned" in p]
    if unreadable:
        notes.append(f"{len(unreadable)} document(s) are scans that can't be read.")
    return Outcome(town.name, status, " ".join(notes), candidate=cur or up, store=store,
                   detail=detail)


# ── Storing ───────────────────────────────────────────────────────────────────
def _conn():
    import database
    conn = database.get_conn()
    conn.executescript(_SCHEMA)
    return conn


def _schema() -> str:
    import database
    s = database.SQLITE_SCHEMA
    return "\n".join(m.group(0) for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (?:property_tax_(?:rates|checks|sources)|sk_municipalities) "
        r"\(.*?\);", s, re.S))


_SCHEMA = _schema()


def _save_rate(conn, name: str, tax_year: int, rate: float, url: str, document: str,
               excerpt: str, origin: str) -> None:
    conn.execute("""
        INSERT INTO property_tax_rates
            (town, name, tax_year, rate, source_url, document, excerpt, origin, saved_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(town, tax_year) DO UPDATE SET
            name=excluded.name, rate=excluded.rate, source_url=excluded.source_url,
            document=excluded.document, excerpt=excluded.excerpt, origin=excluded.origin,
            saved_at=excluded.saved_at
    """, (tax.town_key(name), name, int(tax_year), float(rate), url, document, excerpt, origin,
          _now()))


def _save_check(conn, o: Outcome) -> None:
    c = o.candidate
    conn.execute("""
        INSERT OR REPLACE INTO property_tax_checks
            (town, name, status, message, rates, tax_year, source_url, document, excerpt,
             detail, checked_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (tax.town_key(o.town), o.town, o.status, o.message,
          json.dumps(c.rates) if c else None, c.tax_year if c else None,
          c.url if c else None, doc_name(c.title, c.url) if c else None,
          c.excerpt if c else None, json.dumps(o.detail, ensure_ascii=False), _now()))


def record(o: Outcome) -> None:
    """Store an outcome: its rates, and the town's check."""
    conn = _conn()
    try:
        for tax_year, rate, r in o.store:
            _save_rate(conn, o.town, tax_year, rate, r.url, doc_name(r.title, r.url),
                       r.excerpt, "scraped")
        _save_check(conn, o)
        conn.commit()
    finally:
        conn.close()


# ── Towns ─────────────────────────────────────────────────────────────────────
def refresh_municipalities(session=None, force: bool = False) -> int:
    """Every Slovak municipality and its website, from Wikidata, at most once
    a month (`force`: now). Returns how many are on file."""
    conn = _conn()
    try:
        n, newest = conn.execute("SELECT COUNT(*), MAX(refreshed_at) FROM sk_municipalities").fetchone()
    finally:
        conn.close()
    fresh = newest and (datetime.now(timezone.utc) - datetime.fromisoformat(newest)).days < RECHECK_DAYS
    if n and fresh and not force:
        return n
    try:
        found = scr.municipalities(session)
    except Exception as e:
        log.warning(f"Tax rates: the list of municipalities couldn't be read ({e}); "
                    f"keeping the {n} on file")
        return n
    shared: dict[str, int] = {}
    for m in found:
        shared[m.name] = shared.get(m.name, 0) + 1
    now = _now()
    rows = [(f"{m.name} (okres {m.okres})" if shared[m.name] > 1 and m.okres else m.name,
             m.name, m.okres, m.web, m.population, now) for m in found]
    conn = _conn()
    try:
        conn.execute("DELETE FROM sk_municipalities")
        conn.executemany("INSERT OR REPLACE INTO sk_municipalities VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    tax.reload()
    return len(rows)


def towns(municipalities: bool = True) -> dict[str, scr.Town]:
    """The towns checked: scraper.property_tax_rates.TOWNS, those a user
    added on the dashboard, and (`municipalities`) every other Slovak
    municipality with a website, from its home page."""
    out = dict(scr.TOWNS)
    have = {tax.town_key(n) for n in out}
    conn = _conn()
    try:
        for r in conn.execute("SELECT name, start_url FROM property_tax_sources ORDER BY name"):
            if r["name"] not in out:
                out[r["name"]] = scr.Town(r["name"], (r["start_url"],))
                have.add(tax.town_key(r["name"]))
        if municipalities:
            for r in conn.execute("SELECT key, web FROM sk_municipalities ORDER BY key"):
                if r["web"] and tax.town_key(r["key"]) not in have:
                    out[r["key"]] = scr.Town(r["key"], (r["web"],))
    finally:
        conn.close()
    return out


def _custom() -> set[str]:
    conn = _conn()
    try:
        return {r[0] for r in conn.execute("SELECT name FROM property_tax_sources")}
    finally:
        conn.close()


def _with_listings(names: list[str]) -> set[str]:
    """The municipalities among `names` that Slovak listings are in."""
    try:
        import database
        conn = database.get_conn()
        try:
            only, params = database._market_sql(conn, "sk")
            districts = {tax._fold(r[0]) for r in conn.execute(
                f"SELECT DISTINCT district FROM listings WHERE is_active = 1 AND district != ''{only}",
                params) if r[0]}
        finally:
            conn.close()
    except Exception:
        return set()
    if not districts:
        return set()
    from engine import regional_prices as rp
    out = set()
    for name in names:
        n, _, okres = tax.town_key(name).partition("|")
        if any(rp._has_place(n, d, rp._CITY_TAIL) and (not okres or okres in d) for d in districts):
            out.add(name)
    return out


def _last_checked() -> dict[str, str]:
    conn = _conn()
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT name, checked_at FROM property_tax_checks")}
    finally:
        conn.close()


def add_town(name: str, start_url: str) -> str | None:
    """Add a town and the page its search starts from (its tax page or list
    of ordinances). Returns why not, or None."""
    name = re.sub(r"\s+", " ", (name or "")).strip()
    start_url = (start_url or "").strip()
    if not name or len(name) > 60:
        return "Give the town's name."
    if not re.match(r"https?://[^\s/]+\.[^\s]+$", start_url):
        return "Give the full address of the town's tax page or list of ordinances (https://…)."
    if name in scr.TOWNS:
        return f"{name} is checked already."
    conn = _conn()
    try:
        conn.execute("INSERT OR REPLACE INTO property_tax_sources (name, start_url, added_at) "
                     "VALUES (?,?,?)", (name, start_url, _now()))
        conn.commit()
    finally:
        conn.close()
    return None


def remove_town(name: str) -> None:
    """Remove a town a user added (its stored rates go too)."""
    conn = _conn()
    try:
        conn.execute("DELETE FROM property_tax_sources WHERE name=?", (name,))
        conn.execute("DELETE FROM property_tax_checks WHERE town=?", (tax.town_key(name),))
        conn.execute("DELETE FROM property_tax_rates WHERE town=?", (tax.town_key(name),))
        conn.commit()
    finally:
        conn.close()
    _changed()


# ── The button ────────────────────────────────────────────────────────────────
def update(progress=None, year: int | None = None, only: list[str] | None = None,
           fetcher=None, full: bool = False,
           time_budget_s: float = VILLAGE_TIME_BUDGET_S) -> dict:
    """Check the towns (or `only` these), store what assess() says to, and
    drop the scores whose property tax changed.

    Every run reads the towns of TOWNS, those a user added and every
    municipality a listing is in. The other ~2,800 municipalities are read
    when due — never read, or last read RECHECK_DAYS ago — as many as fit in
    `time_budget_s`, the never-read first; the rest wait for the next click
    (`full`: all of them now). A village's site is read more briefly: at
    most 14 pages and documents, stopping at the first dated rate.

    Returns {"outcomes": [Outcome], "counts": {status: n}, "requeued": n,
             "left": municipalities still due}."""
    import time as _time
    import requests
    from collections import deque
    year = year or _year()
    if only is None:
        refresh_municipalities()
    all_towns = towns()
    custom = _custom()
    villages = [n for n in all_towns if n not in scr.TOWNS and n not in custom]
    if only is not None:
        names = [n for n in only if n in all_towns]
        due: list[str] = []
    else:
        listed = _with_listings(villages)
        names = [n for n in all_towns if n not in villages] + sorted(listed)
        checked = _last_checked()
        cutoff = (datetime.now(timezone.utc).timestamp() - RECHECK_DAYS * 86400)
        due = [n for n in villages if n not in listed and (
            full or n not in checked
            or datetime.fromisoformat(checked[n]).timestamp() < cutoff)]
        due.sort(key=lambda n: checked.get(n, ""))       # never read first, then the oldest
    village = set(villages)
    total = len(names) + len(due)
    outcomes: list[Outcome] = []

    def one(name: str) -> Outcome:
        try:
            quick = name in village
            read = fetcher or (functools.partial(scr.fetch, timeout=20, retry=False)
                               if quick else None)
            res = scr.check_town(all_towns[name], year, session=requests.Session(),
                                 fetcher=read, delay=0.1 if quick else 0.4,
                                 budget=12 if quick else scr.MAX_FETCHES,
                                 stop_when_found=quick)
            return assess(all_towns[name], res, year)
        except Exception as e:                     # one town's failure isn't the run's
            log.exception(f"Tax rates: {name} failed")
            return Outcome(name, "not_found", f"The check failed: {type(e).__name__}: {e}")

    pending = deque(names + due)
    stop_villages_at = _time.monotonic() + time_budget_s
    started = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        running = set()
        while pending or running:
            while pending and len(running) < WORKERS:
                n = pending[0]
                if n in due and not full and _time.monotonic() > stop_villages_at:
                    pending.clear()                 # the rest wait for the next click
                    break
                pending.popleft()
                started.add(n)
                running.add(ex.submit(one, n))
            if not running:
                break
            done = next(as_completed(running))
            running.discard(done)
            o = done.result()
            record(o)
            outcomes.append(o)
            log.info(f"  {STATUS_LABEL.get(o.status, o.status)} {o.town}: {o.message[:140]}")
            if progress:
                progress(len(outcomes), total, note=o.town)
    requeued = _changed()
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    order = {n: i for i, n in enumerate(names + due)}
    outcomes.sort(key=lambda o: order.get(o.town, 0))
    return {"outcomes": outcomes, "counts": counts, "requeued": requeued,
            "left": len([n for n in due if n not in started])}


def _changed() -> int:
    """After stored rates changed: the engine reads them again, and the
    scores they move are dropped for re-scoring."""
    tax.reload()
    try:
        from database import requeue_scores_with_stale_property_tax
        return requeue_scores_with_stale_property_tax()
    except Exception as e:
        log.warning(f"Tax rates: re-queueing scores failed: {e}")
        return 0


def summary_text(s: dict) -> str:
    """One line for the dashboard: what the run found and did."""
    c = s["counts"]
    total = sum(c.values())
    changed = [o for o in s["outcomes"] if o.status in ("applied", "new", "upcoming")]
    parts = [f"{total} towns checked"]
    for key, word in (("confirmed", "confirmed"), ("applied", "updated"),
                      ("upcoming", "with a new rate ahead"), ("new", "added"),
                      ("review", "for review"), ("blocked", "blocked"),
                      ("not_found", "without a readable rate")):
        if c.get(key):
            parts.append(f"{c[key]} {word}")
    line = " · ".join(parts)
    if changed:
        line += " — " + "; ".join(f"{o.town}: {o.message.split(' (')[0]}" for o in changed[:6])
    if s.get("requeued"):
        line += f". {s['requeued']} listing(s) re-scored at the new rates"
    if s.get("left"):
        line += (f". {s['left']:,} more municipalities are due — click again to read them "
                 f"(each is read at most once a month)")
    return line + "."


# ── The user's decisions ──────────────────────────────────────────────────────
def check_rows() -> list[dict]:
    """Every town's last check with the rate the engine charges there now,
    for the dashboard table. A municipality outside TOWNS is charged its
    stored rate, or the fallback."""
    tax.reload()
    conn = _conn()
    try:
        checks = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM property_tax_checks")}
        stored = {}
        for r in conn.execute("SELECT * FROM property_tax_rates ORDER BY tax_year DESC"):
            stored.setdefault(r["name"], []).append(dict(r))
    finally:
        conn.close()
    year = _year()
    custom = _custom()
    rows = []
    for name, town in towns().items():
        c = checks.get(name, {})
        kind = "table" if name in scr.TOWNS else "custom" if name in custom else "municipality"
        if kind == "municipality":
            now = next((r for r in stored.get(name, []) if r["tax_year"] <= year), None)
            rate, label = ((now["rate"], f"{name} — stored") if now else
                           (tax.UNKNOWN_PLACE_RATE_PER_M2, "UNVERIFIED — fallback"))
        else:
            rate, label = tax.rate_source(name, year)
        rows.append({
            "town": name, "kind": kind, "custom": kind == "custom", "zoned": town.zoned,
            "status": c.get("status", ""), "message": c.get("message", "Not checked yet."),
            "charged": rate, "charged_from": label,
            "found": json.loads(c["rates"]) if c.get("rates") else [],
            "found_year": c.get("tax_year"), "source_url": c.get("source_url") or "",
            "document": c.get("document") or "", "excerpt": c.get("excerpt") or "",
            "checked_at": c.get("checked_at") or "", "stored": stored.get(name, []),
            "detail": json.loads(c["detail"]) if c.get("detail") else {},
            "start": list(town.start),
        })
    return rows


def accept(name: str, rate: float | None = None) -> str | None:
    """Accept what a review found for `name` (`rate`: which of several):
    stored as the user's decision, so it is charged even over the table.
    Returns why not, or None."""
    conn = _conn()
    try:
        c = conn.execute("SELECT * FROM property_tax_checks WHERE town=?",
                         (tax.town_key(name),)).fetchone()
        if not c or not c["rates"]:
            return f"Nothing to accept for {name}: check it first."
        if tax.town_key(name) in tax.ZONED:
            return (f"{name} is rated by area: its areas are mapped in engine/property_tax_sk.py, "
                    f"so a change there is made by hand.")
        found = json.loads(c["rates"])
        if rate is None:
            if len(found) > 1:
                return f"The site states several rates ({_fmt(found)}): choose the one in force."
            rate = found[0]
        if not any(_same(rate, f) for f in found):
            return f"{rate_text(rate)} is not one of the rates found ({_fmt(found)})."
        _save_rate(conn, name, c["tax_year"] or _year(), rate, c["source_url"], c["document"],
                   c["excerpt"], "accepted")
        conn.execute("UPDATE property_tax_checks SET status='applied', message=? WHERE town=?",
                     (f"{rate_text(rate)} €/m² — accepted by you ({c['document'] or c['source_url']}).",
                      tax.town_key(name)))
        conn.commit()
    finally:
        conn.close()
    _changed()
    return None


def keep(name: str) -> None:
    """Keep the table's figure over a review (until the next check)."""
    conn = _conn()
    try:
        conn.execute("UPDATE property_tax_checks SET status='kept', "
                     "message='You kept the table’s figure. ' || COALESCE(message, '') "
                     "WHERE town=?", (tax.town_key(name),))
        conn.commit()
    finally:
        conn.close()


def revert(name: str) -> int:
    """Forget every rate stored for `name`: the engine charges the table's
    figure (or the fallback) again. Returns how many rates were removed."""
    conn = _conn()
    try:
        n = conn.execute("DELETE FROM property_tax_rates WHERE town=?",
                         (tax.town_key(name),)).rowcount
        conn.execute("UPDATE property_tax_checks SET status='kept', "
                     "message='Stored rates removed: the table’s figure is charged.' "
                     "WHERE town=?", (tax.town_key(name),))
        conn.commit()
    finally:
        conn.close()
    _changed()
    return n


def upload(name: str, filename: str, content: bytes, year: int | None = None
           ) -> tuple[str, str]:
    """A town's ordinance saved in the browser (for a site that refuses
    automated requests): read it and, for a town with one rate, store that
    rate as the user's. Returns (status, message)."""
    year = year or _year()
    town = towns().get(name) or scr.Town(name, ())
    reading, why = scr.read_upload(filename, content, town, year)
    if reading is None:
        return "error", f"{filename}: {why}."
    reading.title = filename
    if town.zoned or tax.town_key(name) in tax.ZONED:
        res = scr.TownResult(name, readings=[reading], fetched=1)
        res.current, res.upcoming, res.conflict = scr.pick([reading], year)
        o = assess(town, res, year)
        o.message = f"From your upload: {o.message}"
        record(o)
        return o.status, o.message
    if len(set(reading.rates)) > 1:
        return "review", (f"{filename} states several flat rates, {_fmt(reading.rates)} — "
                          f"by area or past years; nothing was stored.")
    rate = reading.rates[0]
    first = reading.tax_year or year
    conn = _conn()
    try:
        _save_rate(conn, name, first, rate, f"upload: {filename}", filename, reading.excerpt,
                   "upload")
        o = Outcome(name, "applied",
                    f"{rate_text(rate)} €/m² from your upload {filename} ({_year_note(reading)}).",
                    candidate=reading, detail={"upload": filename})
        _save_check(conn, o)
        conn.commit()
    finally:
        conn.close()
    _changed()
    return "applied", o.message

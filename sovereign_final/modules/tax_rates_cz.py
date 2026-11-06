"""
modules/tax_rates_cz.py — 🏛️ UPDATE TAX RATES for Czechia: every Czech
municipality's property-tax coefficients for a flat.

One run (scraper/tax_coefficients_cz does the reading):
  1. the population of all 6,258 municipalities on 1 January of the two
     years the size coefficient needs (§ 12f: the year before the tax year)
     — once a year; the Statistical Office's file is large;
  2. every valid ordinance on the coefficients in the central collection
     (sbirkapp.gov.cz), and the text of each one not read before — a
     published ordinance never changes, so later runs read only new ones;
  3. the municipality behind each publisher's IČO (ARES), once per IČO;
  4. each municipality's size and local coefficients for this tax year and
     the next, stored in property_tax_cz for engine/property_tax_cz.

Then the Czech scores whose tax moved are dropped for re-scoring.

Unlike the Slovak rates nothing here waits for review: the coefficients come
from the state's own collection in the Interior Ministry's model wording,
and a flat's tax is a few thousand crowns a year at most. What couldn't be
read is counted and listed (an old .doc ordinance, a scan) — those
municipalities keep the defaults the act gives them.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper import tax_coefficients_cz as cz

log = logging.getLogger(__name__)
WORKERS = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn():
    import database
    import re
    conn = database.get_conn()
    conn.executescript("\n".join(m.group(0) for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (?:cz_\w+|property_tax_cz) \(.*?\);",
        database.SQLITE_SCHEMA, re.S)))
    return conn


class Sources:
    """Where the data comes from — the network by default; a test passes
    its own."""

    def __init__(self, session=None):
        import requests
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "Mozilla/5.0 (compatible; property-tax-check)")

    def close(self):
        self.session.close()

    def populations(self, years):
        return cz.populations(self.session, tuple(years))

    def list_ordinances(self):
        return cz.list_ordinances(self.session)

    def text(self, ordinance_id):
        return cz.fetch_text(self.session, ordinance_id)

    def municipality_of(self, ico):
        return cz.municipality_of(self.session, ico)


def _year() -> int:
    from engine import property_tax_sk
    return property_tax_sk._year()


def update(progress=None, year: int | None = None, sources: Sources | None = None) -> dict:
    """Bring every Czech municipality's coefficients up to date. Returns
    {"municipalities", "with_ordinances", "ordinances", "read_now",
     "unreadable", "changed": [(name, before, after)], "requeued"}."""
    if sources is not None:
        return _update(progress, year, sources)
    src = Sources()
    try:
        return _update(progress, year, src)
    finally:
        src.close()                                 # the run's own session


def _update(progress, year: int | None, src: Sources) -> dict:
    year = year or _year()
    # The engine's hand-checked tables are for TABLE_YEAR: reading that year
    # too shows whether a later year's reading differs from it.
    from engine.property_tax_cz import TABLE_YEAR
    years = tuple(sorted({min(year, TABLE_YEAR), year, year + 1}))
    note = (lambda i, n, what: progress(i, n, note=what)) if progress else (lambda *a: None)

    # 1. Population, for the size coefficient (§ 12f: 1 January of Y − 1).
    conn = _conn()
    try:
        have = {r[0] for r in conn.execute("SELECT DISTINCT year FROM cz_population")}
    finally:
        conn.close()
    need = [y - 1 for y in years if (y - 1) not in have]
    if need:
        note(0, 4, "population of every municipality (once a year)")
        pops = src.populations(need)
        conn = _conn()
        try:
            for y, rows in pops.items():
                conn.executemany("INSERT OR REPLACE INTO cz_population VALUES (?,?,?,?,?)",
                                 [(c, y, n, o, p) for c, (n, o, p) in rows.items()])
            conn.commit()
        finally:
            conn.close()

    # 2. The ordinances, each read once.
    note(1, 4, "listing the ordinances on sbirkapp.gov.cz")
    listed = src.list_ordinances()
    conn = _conn()
    try:
        known = {r[0] for r in conn.execute("SELECT id FROM cz_ordinances")}
    finally:
        conn.close()
    new = [o for o in listed if o.id not in known]

    def read(o):
        try:
            doc = src.text(o.id)
            if doc.problem:
                return o, None, doc.problem
            return o, cz.parse(doc.text), ""
        except Exception as e:                       # one broken file isn't the run's
            return o, None, f"{type(e).__name__}: {e}"

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for f in as_completed([ex.submit(read, o) for o in new]):
            o, parsed, problem = f.result()
            conn = _conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO cz_ordinances VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (o.id, o.ico, o.publisher, o.number, o.title,
                     o.published.isoformat() if o.published else None,
                     o.effective.isoformat() if o.effective else None,
                     json.dumps(parsed.to_json(), ensure_ascii=False) if parsed else None,
                     problem or None, _now()))
                conn.commit()
            finally:
                conn.close()
            done += 1
            if progress and done % 20 == 0:
                progress(done, len(new), note=f"read {done} of {len(new)} new ordinances")

    # 3. The municipality behind each publisher.
    conn = _conn()
    try:
        mapped = {r[0] for r in conn.execute("SELECT ico FROM cz_ico")}
    finally:
        conn.close()
    icos = sorted({o.ico for o in listed if o.ico and o.ico not in mapped})
    note(2, 4, f"finding the municipality of {len(icos)} publishers (ARES)")
    with ThreadPoolExecutor(max_workers=6) as ex:
        found = list(ex.map(lambda i: (i, _safe(src.municipality_of, i)), icos))
    conn = _conn()
    try:
        conn.executemany("INSERT OR REPLACE INTO cz_ico VALUES (?,?,?,?)",
                         [(i, m["code"], m["name"], m["district"]) for i, m in found if m])
        conn.commit()
    finally:
        conn.close()

    # 4. Each municipality's coefficients.
    note(3, 4, "working out every municipality's coefficients")
    valid = {o.id for o in listed}
    conn = _conn()
    try:
        ico_code = {r[0]: r[1] for r in conn.execute("SELECT ico, code FROM cz_ico")}
        pops = {(r[0], r[1]): (r[2], r[3], r[4]) for r in conn.execute(
            "SELECT code, year, name, okres, population FROM cz_population")}
        by_code: dict[str, list[cz.Ordinance]] = {}
        unreadable = []
        for r in conn.execute("SELECT * FROM cz_ordinances"):
            if r["id"] not in valid:
                continue                         # repealed or withdrawn since
            if r["problem"] or not r["parsed"]:
                unreadable.append(f"{r['publisher']} {r['number']}: {r['problem'] or 'unread'}")
                continue
            code = ico_code.get(r["ico"])
            if not code:
                continue
            by_code.setdefault(code, []).append(cz.Ordinance(
                r["id"], r["number"], _d(r["published"]), _d(r["effective"]),
                cz.Parsed.from_json(json.loads(r["parsed"])), r["title"] or ""))
        before = {(r["code"], r["tax_year"]): (r["size"], r["local"])
                  for r in conn.execute("SELECT code, tax_year, size, local FROM property_tax_cz")}
        codes = {c for c, _ in pops}
        rows, changed = [], []
        for code in codes:
            for y in years:
                name, okres, population = (pops.get((code, y - 1)) or pops.get((code, y - 2))
                                           or (None, None, None))
                if name is None:
                    continue
                c = cz.coefficients(name, population, by_code.get(code, []), y)
                size, local = json.dumps(c.size, sort_keys=True), json.dumps(c.local, sort_keys=True)
                old = before.get((code, y))
                if y == year and old and old != (size, local):
                    changed.append((name, _main(old), (c.size[""], c.local[""])))
                rows.append((code, y, name, okres, population, size, local,
                             json.dumps(c.sources, ensure_ascii=False), _now()))
        conn.executemany("INSERT OR REPLACE INTO property_tax_cz VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()

    from engine import property_tax_cz
    property_tax_cz.reload()
    requeued = 0
    try:
        from database import requeue_scores_with_stale_property_tax
        requeued = requeue_scores_with_stale_property_tax(market="cz")
    except Exception as e:
        log.warning(f"Czech tax: re-queueing scores failed: {e}")
    note(4, 4, "done")
    return {"municipalities": len({c for c, _ in pops}), "with_ordinances": len(by_code),
            "ordinances": len(listed), "read_now": len(new), "unreadable": unreadable,
            "changed": sorted(changed), "requeued": requeued}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log.warning(f"Czech tax: {fn.__name__}{a} failed: {e}")
        return None


def _d(s):
    return date.fromisoformat(s) if s else None


def _main(old) -> tuple[float, float]:
    size, local = (json.loads(x) for x in old)
    return size.get("", 0.0), local.get("", 1.0)


def summary_text(s: dict) -> str:
    line = (f"🇨🇿 {s['municipalities']:,} Czech municipalities: {s['with_ordinances']:,} with "
            f"ordinances on the coefficients ({s['ordinances']:,} in force, {s['read_now']:,} "
            f"read now)")
    if s["changed"]:
        line += f"; {len(s['changed'])} changed — " + "; ".join(
            f"{n}: size {a[0]:g}×local {a[1]:g} → {b[0]:g}×{b[1]:g}" for n, a, b in s["changed"][:5])
    if s["unreadable"]:
        line += f"; {len(s['unreadable'])} couldn't be read (old .doc files or scans)"
    if s.get("requeued"):
        line += f". {s['requeued']} listing(s) re-scored"
    return line + "."


def table(year: int | None = None, only_set: bool = True) -> list[dict]:
    """Rows for the dashboard: each municipality's coefficients for a flat
    this tax year — by default those an ordinance sets (the rest pay the
    act's defaults)."""
    year = year or _year()
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM property_tax_cz WHERE tax_year=? ORDER BY name",
                            (year,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        sources = json.loads(r["sources"] or "[]")
        if only_set and not sources:
            continue
        size, local = json.loads(r["size"]), json.loads(r["local"])
        out.append({"code": r["code"], "name": r["name"], "okres": r["okres"] or "",
                    "population": r["population"],
                    "size": size, "local": local, "sources": sources,
                    "computed_at": r["computed_at"]})
    return out


def unreadable() -> list[dict]:
    """The valid ordinances that couldn't be read (an old .doc, a scan), with
    a link to each: those municipalities pay the act's defaults here."""
    conn = _conn()
    try:
        return [{"publisher": r["publisher"], "number": r["number"], "problem": r["problem"],
                 "url": f"{cz.SBIRKA}/detail/{r['id']}"}
                for r in conn.execute("SELECT * FROM cz_ordinances WHERE problem IS NOT NULL "
                                      "ORDER BY publisher")]
    finally:
        conn.close()


def last_run() -> str:
    conn = _conn()
    try:
        r = conn.execute("SELECT MAX(computed_at) FROM property_tax_cz").fetchone()
        return (r[0] or "") if r else ""
    finally:
        conn.close()

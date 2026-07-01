"""
backfill_enrichment.py — one-shot enrichment backfills across the existing DB.

════════════════════════════════════════════════════════════════════════════
⚠️  UNOFFICIAL SLOVAK CADASTRE SCRAPER — READ BEFORE RELYING ON IT
════════════════════════════════════════════════════════════════════════════
The cadastre lookup in this file (`cadastre` / `cadastre-backfill` modes,
enrich_parcel() and helpers) is an UNOFFICIAL scraper of kataster.skgeodesy.sk.
ÚGKK SR publishes NO official public API and issues NO API keys — the
CADASTRAL_API_KEY env var referenced elsewhere in this repo (config.py,
modules/debt_bot.py, .env.example, README) points at a service that does not
exist. This code instead talks to the same undocumented OData backend that
powers the public cadastre portal, following the approach proven by
verejnedigital/verejne.digital (kataster/skgeodesy.py). It can break WITHOUT
NOTICE whenever ÚGKK changes the portal, and requests may be geo-blocked
outside Slovakia (a zbgis.skgeodesy.sk proxy fallback is attempted on 403).

What it CAN reliably return (straight from the OData entities):
  - cadastral unit (katastrálne územie) name + code
  - parcel: number, register (C/E), area m², house number, land use,
    utilisation, ownership type, municipality
  - LV (list vlastníctva) number + a link to the official HTML report
  - owner names + registered addresses (via parcel participants → subjects)
  - the raw text of the LV HTML report (sections A/B/C), scanned for the
    LV_REJECT_FLAGS keywords from config.py

What it CANNOT reliably return (be honest with yourself before a purchase):
  - ownership shares (podiel) as structured data — only inside the raw LV text
  - structured encumbrance (ťarchy) records — only keyword hits in raw text
  - anything at all if the portal changes, throttles, or geo-blocks you
Always verify the title deed via the official portal or a notary before
committing money. Scrape politely: results are cached in the cadastre_cache
table and requests are throttled (CADASTRAL_DELAY_SEC) + retried with backoff.
════════════════════════════════════════════════════════════════════════════

Modes:
  python3 backfill_enrichment.py [limit]
      LLM enrichment backfill (the original job): run every LLM enricher
      across the existing DB, then rescore so the new signals take effect.
      Order matters — address + description enrichment first, THEN cashflow
      scores are cleared and recomputed. Needs ANTHROPIC_API_KEY (no-ops
      without it); the rescore always runs. `limit` (default 1000) caps how
      many listings each enricher processes — run again to continue.

  python3 backfill_enrichment.py cadastre AREA PARCEL [--register C|E|auto]
                                                       [--refresh] [--no-lv]
      Look up ONE parcel: AREA is the katastrálne územie name (e.g. "Nitra")
      or its numeric code (e.g. 838365); PARCEL is the parcelné číslo
      (e.g. "1234/5"). Prints the enrichment result as JSON.

  python3 backfill_enrichment.py cadastre-backfill [limit]
      Enrich every active listing that carries cadastral_area +
      cadastral_number (default limit 100). Results land in cadastre_cache.
"""

import json
import random
import re
import sys, os
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html import unescape as _html_unescape

import requests

sys.path.insert(0, os.path.dirname(__file__))

import database
from database import init_db, clear_cashflow_scores
from config import (
    CADASTRAL_DELAY_SEC, CADASTRAL_BACKOFF_MAX,
    LV_REJECT_FLAGS, LV_BANK_NAMES,
)
from modules.address_enrichment import run_address_enrichment
from modules.description_enrichment import run_description_enrichment
from modules.cashflow_runner import run_scoring


# ══════════════════════════════════════════════════════════════════════════
# Mode 1 — LLM enrichment backfill (original job, unchanged)
# ══════════════════════════════════════════════════════════════════════════
def main(limit: int = 1000) -> dict:
    """Run the full backfill and return a summary of what changed."""
    init_db()
    print("=" * 60)
    print("BACKFILL ENRICHMENT — addresses, descriptions, then rescore")
    print("=" * 60)

    addresses    = run_address_enrichment(limit=limit)
    descriptions = run_description_enrichment(limit=limit)

    print("\n♻️  Clearing cashflow scores so the new signals take effect...")
    cleared = clear_cashflow_scores()
    scored  = run_scoring()

    summary = {
        "addresses": addresses,
        "descriptions": descriptions,
        "cleared": cleared,
        "scored": scored,
    }
    print("=" * 60)
    print(f"✅ Backfill done. {addresses} districts resolved, "
          f"{descriptions} descriptions parsed, "
          f"{cleared} scores cleared, {scored} rescored.")
    print("=" * 60)
    return summary


# ══════════════════════════════════════════════════════════════════════════
# Mode 2 — Slovak cadastre enrichment (unofficial scraper — see module
# docstring). Endpoints and query shapes mirror verejnedigital/verejne.digital
# kataster/skgeodesy.py, the community-proven way to read the portal backend.
# ══════════════════════════════════════════════════════════════════════════
PORTAL_ODATA = "https://kataster.skgeodesy.sk/PortalOData/"
# Official LV (list vlastníctva) report generator — returns the full title
# deed as HTML (sections A: majetková podstata, B: vlastníci, C: ťarchy).
GENERATE_PRF = ("https://kataster.skgeodesy.sk/EsknBo/Bo.svc/GeneratePrf"
                "?prfNumber={lv_no}&cadastralUnitCode={ku_code}&outputType=html")
# skgeodesy geo-blocks many non-Slovak IPs; the public zbgis map proxy relays
# requests from inside their network (same workaround as verejne.digital).
GEOBLOCK_PROXY_PREFIX = "https://zbgis.skgeodesy.sk/mkzbgis/proxy.ashx?"

HTTP_TIMEOUT       = 30
MAX_ATTEMPTS       = 4
CACHE_TTL_DAYS     = float(os.getenv("CADASTRE_CACHE_TTL_DAYS", "30"))
NOT_FOUND_TTL_DAYS = float(os.getenv("CADASTRE_NOT_FOUND_TTL_DAYS", "7"))
LV_TEXT_MAX_CHARS  = 100_000

_HEADERS = {"User-Agent": "prefilipaproperty-enrichment/1.0 (personal research tool)"}

# Field selection copied verbatim from the verejne.digital scraper — these are
# the OData entity fields known to exist on ParcelsC/ParcelsE.
_PARCEL_QUERY = (
    "?$select=Id,ValidTo,No,Area,HouseNo,Extent"
    "&$expand=OwnershipType($select=Name,Code),CadastralUnit($select=Name,Code),"
    "Localization($select=Name),Municipality($select=Name),LandUse($select=Name),"
    "SharedProperty($select=Name),ProtectedProperty($select=Name),"
    "Affiliation($select=Name),Folio($select=Id,No),Utilisation($select=Name),"
    "Status($select=Code)"
)

_geoblock      = {"active": False}   # latches on after the first 403
_last_request  = {"t": 0.0}


class CadastreError(Exception):
    """A cadastre request failed in a way retries could not fix."""


# ── low-level HTTP (throttle, retry, geoblock fallback) ──────────────────────
def _throttle():
    wait = CADASTRAL_DELAY_SEC - (time.monotonic() - _last_request["t"])
    if wait > 0:
        time.sleep(wait)
    _last_request["t"] = time.monotonic()


def _cadastral_get(url: str, accept: str = "application/json") -> str:
    """GET with polite throttling, exponential backoff on 429/5xx/network
    errors, and a one-time switch to the zbgis proxy on 403 (geo-block)."""
    backoff = 2.0
    last_error = "no request made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        target = (GEOBLOCK_PROXY_PREFIX + url) if _geoblock["active"] else url
        try:
            resp = requests.get(target, headers={**_HEADERS, "Accept": accept},
                                timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            last_error = f"network error: {e}"
        else:
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 451) and not _geoblock["active"]:
                _geoblock["active"] = True
                print(f"    cadastre: HTTP {resp.status_code} — likely geo-block, "
                      f"retrying via zbgis proxy")
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
            else:
                raise CadastreError(
                    f"skgeodesy.sk returned HTTP {resp.status_code} for {url} — "
                    f"the portal may have changed. Body: {resp.text[:200]!r}")
        if attempt < MAX_ATTEMPTS:
            pause = min(backoff + random.uniform(0, 1), CADASTRAL_BACKOFF_MAX)
            print(f"    cadastre: attempt {attempt}/{MAX_ATTEMPTS} failed "
                  f"({last_error}); retrying in {pause:.1f}s")
            time.sleep(pause)
            backoff = min(backoff * 2, CADASTRAL_BACKOFF_MAX)
    raise CadastreError(
        f"skgeodesy.sk unreachable after {MAX_ATTEMPTS} attempts ({last_error}). "
        f"The portal may be down, rate-limiting, or geo-blocking this IP. URL: {url}")


def _get_json(url: str):
    text = _cadastral_get(url)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise CadastreError(
            f"non-JSON response from {url} — the portal layout may have "
            f"changed. Body: {text[:200]!r}") from e
    if isinstance(data, dict) and str(data.get("Message", "")).startswith("Error"):
        raise CadastreError(f"cadastre API error from {url}: {data['Message']}")
    return data


def _get_pages(url: str) -> list:
    """Follow OData @odata.nextLink pagination and concatenate all pages."""
    values = []
    while url:
        data = _get_json(url)
        if not isinstance(data, dict) or "value" not in data:
            raise CadastreError(f"unexpected OData shape (no 'value') from {url}")
        values += data["value"]
        url = data.get("@odata.nextLink")
    return values


# ── helpers ──────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Accent-stripped, lowercased, whitespace-collapsed — for cache keys and
    accent-insensitive name matching."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _odata_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ── OData lookups ────────────────────────────────────────────────────────────
def resolve_cadastral_unit(area: str):
    """Resolve a katastrálne územie name or numeric code to {'code', 'name'}.
    Returns None when nothing matches; raises CadastreError when the name is
    ambiguous (caller should pass the exact name or the numeric code)."""
    area = (area or "").strip()
    if not area:
        raise CadastreError("empty cadastral area / commune name")

    base = PORTAL_ODATA + "CadastralUnits?$select=Id,Name,Code&$filter="
    if area.isdigit():
        rows = _get_pages(base + "Code eq " + area)
        if not rows:
            return None
        return {"code": rows[0]["Code"], "name": rows[0].get("Name", "")}

    rows = _get_pages(base + "Name eq " + _odata_str(area))
    if not rows:
        rows = _get_pages(base + "contains(Name," + _odata_str(area) + ")")
    if not rows:
        return None
    want = _norm(area)
    exact = [r for r in rows if _norm(r.get("Name", "")) == want]
    if exact:
        return {"code": exact[0]["Code"], "name": exact[0]["Name"]}
    if len(rows) == 1:
        return {"code": rows[0]["Code"], "name": rows[0]["Name"]}
    names = ", ".join(f"{r.get('Name')} ({r.get('Code')})" for r in rows[:10])
    raise CadastreError(
        f"cadastral area '{area}' is ambiguous — {len(rows)} matches: {names}. "
        f"Pass the exact katastrálne územie name or its numeric code.")


def find_parcel(ku_code, parcel_no: str, register: str):
    """Find a parcel by number inside one cadastral unit. register: 'C' or 'E'.
    Returns a flat parcel dict, or None when the parcel doesn't exist."""
    entity = "ParcelsC" if register == "C" else "ParcelsE"
    url = (PORTAL_ODATA + entity + _PARCEL_QUERY +
           "&$filter=No eq " + _odata_str(parcel_no) +
           " and CadastralUnit/Code eq " + str(ku_code))
    rows = _get_pages(url)
    if not rows:
        return None
    # Prefer parcels still in force (ValidTo null) over historical ones.
    live = [r for r in rows if not r.get("ValidTo")] or rows
    p = live[0]

    def _name(key):
        v = p.get(key)
        return v.get("Name") if isinstance(v, dict) else None

    return {
        "id":                 p.get("Id"),
        "register":           register,
        "no":                 p.get("No"),
        "area_m2":            p.get("Area"),
        "house_no":           p.get("HouseNo"),
        "valid_to":           p.get("ValidTo"),
        "ownership_type":     _name("OwnershipType"),
        "land_use":           _name("LandUse"),
        "utilisation":        _name("Utilisation"),
        "municipality":       _name("Municipality"),
        "shared_property":    _name("SharedProperty"),
        "protected_property": _name("ProtectedProperty"),
        "folio_id":           (p.get("Folio") or {}).get("Id"),
        "lv_no":              (p.get("Folio") or {}).get("No"),
    }


def fetch_owners(parcel_id, register: str) -> list:
    """Owners of a parcel via its participants → subjects. Names + registered
    addresses only — ownership shares (podiel) are NOT exposed here, they only
    appear in the raw LV report text."""
    entity = "ParcelsC" if register == "C" else "ParcelsE"
    url = (PORTAL_ODATA + f"{entity}({parcel_id})/Kn.Participants"
           "?$select=Id,Name"
           "&$expand=Subjects($select=Id,FirstName,Surname,BirthSurname;"
           "$expand=Address($select=Id,Street,HouseNo,Municipality,Zip,State))")
    owners, seen = [], set()
    for participant in _get_pages(url):
        for subject in participant.get("Subjects") or []:
            sid = subject.get("Id")
            if sid in seen:
                continue
            seen.add(sid)
            addr = subject.get("Address") or {}
            address = ", ".join(part for part in (
                " ".join(x for x in (addr.get("Street"), addr.get("HouseNo")) if x),
                " ".join(x for x in (addr.get("Zip"), addr.get("Municipality")) if x),
                addr.get("State"),
            ) if part)
            name = participant.get("Name") or " ".join(
                x for x in (subject.get("FirstName"), subject.get("Surname")) if x)
            owners.append({
                "name":          name or None,
                "first_name":    subject.get("FirstName"),
                "surname":       subject.get("Surname"),
                "birth_surname": subject.get("BirthSurname"),
                "address":       address or None,
            })
    return owners


def fetch_lv_text(lv_no, ku_code) -> str:
    """Download the official LV HTML report and strip it to plain text —
    the only place encumbrances (ťarchy, section C) are visible."""
    url = GENERATE_PRF.format(lv_no=lv_no, ku_code=ku_code)
    raw = _cadastral_get(url, accept="text/html")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", _html_unescape(text)).strip()
    if len(text) < 50:
        raise CadastreError(
            f"LV report came back empty/unusable from {url} — the report "
            f"service may have changed or rejected the request")
    return text[:LV_TEXT_MAX_CHARS]


def scan_risk_flags(lv_text: str) -> list:
    """Keyword scan of raw LV text for the config LV_REJECT_FLAGS. Coarse,
    document-level (same heuristic as modules/debt_bot._parse_lv): bank_related
    means SOME bank name appears in the document, not that this specific flag
    is a bank lien. A human or the Claude LV analysis must make the final call."""
    low = (lv_text or "").lower()
    found = []
    for flag in LV_REJECT_FLAGS:
        if flag in low:
            found.append({"flag": flag,
                          "bank_related": any(b in low for b in LV_BANK_NAMES)})
    return found


# ── cache (avoid re-scraping the same parcel) ────────────────────────────────
def _ensure_cache_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadastre_cache (
            cache_key      TEXT PRIMARY KEY,
            cadastral_area TEXT,
            parcel_no      TEXT,
            register       TEXT,
            status         TEXT,
            result_json    TEXT,
            fetched_at     TEXT
        )
    """)
    conn.commit()


def _cache_key(area: str, parcel_no: str, register: str) -> str:
    return f"{_norm(area)}|{_norm(parcel_no)}|{register.upper()}"


def _cache_get(key: str, need_lv_text: bool):
    conn = database.get_conn()
    try:
        _ensure_cache_table(conn)
        row = conn.execute(
            "SELECT status, result_json, fetched_at FROM cadastre_cache "
            "WHERE cache_key=?", (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    status, payload, fetched_at = row[0], row[1], row[2]
    ttl_days = CACHE_TTL_DAYS if status == "OK" else NOT_FOUND_TTL_DAYS
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return None
    if age > timedelta(days=ttl_days):
        return None
    result = json.loads(payload)
    # A cached hit without LV text can't serve a caller who wants it.
    if need_lv_text and result.get("lv") and not result.get("lv_text"):
        return None
    result["source"] = "cache"
    return result


def _cache_put(key: str, result: dict):
    q = result["query"]
    conn = database.get_conn()
    try:
        _ensure_cache_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO cadastre_cache "
            "(cache_key, cadastral_area, parcel_no, register, status, "
            " result_json, fetched_at) VALUES (?,?,?,?,?,?,?)",
            (key, q["cadastral_area"], q["parcel_no"], q["register"],
             result["status"], json.dumps(result, ensure_ascii=False),
             result["fetched_at"]))
        conn.commit()
    finally:
        conn.close()


# ── main entry point ─────────────────────────────────────────────────────────
def enrich_parcel(cadastral_area: str, parcel_no: str, register: str = "auto",
                  refresh: bool = False, fetch_lv: bool = True) -> dict:
    """Look up one parcel on the (unofficial) cadastre portal.

    cadastral_area: katastrálne územie name ("Nitra") or numeric code (838365).
    parcel_no:      parcelné číslo, e.g. "1234/5".
    register:       'C', 'E', or 'auto' (try C then E).
    refresh:        bypass the cadastre_cache and re-scrape.
    fetch_lv:       also download + flag-scan the LV report text.

    Returns a dict with status OK / NOT_FOUND / ERROR and a human-readable
    `detail` — failures are explicit, never silent. OK and NOT_FOUND results
    are cached (30 / 7 days by default); ERRORs are not, so transient portal
    failures get retried on the next run.
    """
    register = (register or "auto").upper()
    if register not in ("C", "E", "AUTO"):
        raise ValueError("register must be 'C', 'E' or 'auto'")

    key = _cache_key(cadastral_area, parcel_no, register)
    if not refresh:
        cached = _cache_get(key, need_lv_text=fetch_lv)
        if cached is not None:
            return cached

    result = {
        "status": "ERROR",
        "detail": "",
        "source": "live",
        "query": {"cadastral_area": cadastral_area, "parcel_no": parcel_no,
                  "register": register},
        "cadastral_unit": None,
        "parcel": None,
        "lv": None,
        "owners": [],
        "lv_text": None,
        "risk_flags": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        ku = resolve_cadastral_unit(cadastral_area)
        if ku is None:
            result.update(status="NOT_FOUND", detail=(
                f"cadastral unit '{cadastral_area}' not found on skgeodesy.sk — "
                f"check the official katastrálne územie spelling or pass its "
                f"numeric code"))
            _cache_put(key, result)
            return result
        result["cadastral_unit"] = ku

        registers = ["C", "E"] if register == "AUTO" else [register]
        parcel = None
        for reg in registers:
            parcel = find_parcel(ku["code"], parcel_no, reg)
            if parcel:
                break
        if parcel is None:
            result.update(status="NOT_FOUND", detail=(
                f"parcel '{parcel_no}' not found in register "
                f"{'/'.join(registers)} of {ku['name']} ({ku['code']})"))
            _cache_put(key, result)
            return result
        result["parcel"] = parcel

        if parcel["lv_no"] is None:
            result["detail"] = ("parcel found but has no folio (list "
                                "vlastníctva) attached — no ownership record")
        else:
            result["lv"] = {
                "no": parcel["lv_no"],
                "url": GENERATE_PRF.format(lv_no=parcel["lv_no"],
                                           ku_code=ku["code"]),
            }
            result["owners"] = fetch_owners(parcel["id"], parcel["register"])
            if fetch_lv:
                try:
                    result["lv_text"] = fetch_lv_text(parcel["lv_no"], ku["code"])
                    result["risk_flags"] = scan_risk_flags(result["lv_text"])
                except CadastreError as e:
                    result["detail"] = f"owners fetched, but LV report failed: {e}"

        result["status"] = "OK"
        if not result["detail"]:
            result["detail"] = (
                f"LV {parcel['lv_no']}: {len(result['owners'])} owner(s), "
                f"{len(result['risk_flags'])} risk flag(s)"
                if parcel["lv_no"] is not None else "parcel found (no LV)")

        # Don't cache a partial result whose LV text failed — retry next run.
        if not (fetch_lv and result["lv"] and result["lv_text"] is None):
            _cache_put(key, result)
    except CadastreError as e:
        result.update(status="ERROR", detail=str(e))
    return result


def run_cadastre_backfill(limit: int = 100) -> dict:
    """Enrich every active listing that already carries a cadastral area +
    parcel number. Results are cached in cadastre_cache; risk-flag hits are
    printed so they can be verified manually (this does NOT flip lv_status —
    that stays modules/debt_bot's job)."""
    init_db()
    conn = database.get_conn()
    try:
        rows = conn.execute("""
            SELECT id, cadastral_area, cadastral_number, address_raw
            FROM listings
            WHERE is_active=1
              AND cadastral_number IS NOT NULL AND cadastral_number != ''
              AND cadastral_area   IS NOT NULL AND cadastral_area   != ''
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

    counts = {"processed": 0, "ok": 0, "not_found": 0, "errors": 0}
    if not rows:
        print("ℹ️  No active listings carry a cadastral area + parcel number — "
              "nothing to enrich. (Listing scrapers rarely provide parcel "
              "numbers; fill cadastral_area/cadastral_number where known.)")
        return counts

    print(f"🏛  Cadastre backfill on {len(rows)} listings (unofficial "
          f"skgeodesy.sk scraper — may break without notice)...")
    for row in rows:
        counts["processed"] += 1
        addr = (row["address_raw"] or "")[:55]
        res = enrich_parcel(row["cadastral_area"], row["cadastral_number"])
        if res["status"] == "OK":
            counts["ok"] += 1
            lv_no = (res.get("lv") or {}).get("no")
            flags = ", ".join(f["flag"] for f in res["risk_flags"]) or "none"
            print(f"  ✅ {addr} — LV {lv_no}, {len(res['owners'])} owner(s), "
                  f"flags: {flags} [{res['source']}]")
        elif res["status"] == "NOT_FOUND":
            counts["not_found"] += 1
            print(f"  ⚠️  {addr} — {res['detail']}")
        else:
            counts["errors"] += 1
            print(f"  ❌ {addr} — {res['detail']}")

    print(f"\n🏛  Cadastre backfill done. OK: {counts['ok']} | "
          f"not found: {counts['not_found']} | errors: {counts['errors']}")
    return counts


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli_cadastre(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="backfill_enrichment.py cadastre",
        description="Look up one parcel on the (unofficial) Slovak cadastre "
                    "portal and print the result as JSON.")
    ap.add_argument("area", help="katastrálne územie name (e.g. 'Nitra') or "
                                 "numeric code (e.g. 838365)")
    ap.add_argument("parcel", help="parcelné číslo, e.g. '1234/5'")
    ap.add_argument("--register", default="auto", choices=["C", "E", "auto"],
                    help="parcel register (default: try C then E)")
    ap.add_argument("--refresh", action="store_true",
                    help="bypass cadastre_cache and re-scrape")
    ap.add_argument("--no-lv", action="store_true",
                    help="skip downloading the LV (title deed) report text")
    args = ap.parse_args(argv)

    result = enrich_parcel(args.area, args.parcel, register=args.register,
                           refresh=args.refresh, fetch_lv=not args.no_lv)
    printable = dict(result)
    if printable.get("lv_text") and len(printable["lv_text"]) > 600:
        printable["lv_text"] = printable["lv_text"][:600] + "…"
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "cadastre":
        sys.exit(_cli_cadastre(argv[1:]))
    elif argv and argv[0] == "cadastre-backfill":
        run_cadastre_backfill(int(argv[1]) if len(argv) > 1 else 100)
    else:
        main(int(argv[0]) if argv else 1000)

"""
kataster_scraper.py — Slovak cadastre (kataster nehnuteľností) scraper.

════════════════════════════════════════════════════════════════════════════
⚠️  UNOFFICIAL SCRAPER OF A PUBLIC GOVERNMENT SITE — NOT AN API
════════════════════════════════════════════════════════════════════════════
ÚGKK SR publishes NO official public API and issues NO API keys. This module
scrapes kataster.skgeodesy.sk directly, talking to the same undocumented
OData backend that powers the public cadastre portal — the approach proven by
verejnedigital/verejne.digital (kataster/skgeodesy.py). It can break WITHOUT
NOTICE whenever ÚGKK changes the portal, and requests may be geo-blocked
outside Slovakia (a zbgis.skgeodesy.sk proxy fallback is attempted on 403).
Scrape politely: requests are throttled (CADASTRAL_DELAY_SEC) and retried
with backoff, and results are cached in the cadastre_cache table.

What it CAN reliably return (straight from the OData entities):
  - cadastral unit (katastrálne územie) name + code — KU names usually match
    the obec/commune name, so pass either the KU name or its numeric code
  - parcel: number, register (C/E), area m², house number, land use,
    utilisation (≈ parcel type), ownership type, municipality
  - LV (list vlastníctva) number + a link to the official HTML report
  - owner names + registered addresses (via parcel participants → subjects)
  - the raw text of the LV HTML report (sections A/B/C), scanned for the
    LV_REJECT_FLAGS keywords from config.py

Best-effort only (verify against the raw LV text / official report):
  - ownership share (podiel): the portal's participant records don't
    documentedly expose it; we extract it opportunistically from participant
    fields when present, else it is None — the authoritative share is in the
    raw LV text ("spoluvlastnícky podiel").
  - structured encumbrance (ťarchy) records: only keyword hits in raw text.
Always verify the title deed via the official portal or a notary before
committing money.

Entry points:
  enrich_parcel(area, parcel_no)  — main: parcel → details, LV, owners,
                                    LV text + derived risk flags
  enrich_lv(area, lv_no)          — direct LV lookup: LV text + risk flags
  identify_parcels(lat, lon)      — coordinates → parcel ids (demo/debug)

Demo (real parcel, resolved live from central Bratislava coordinates):
  python3 kataster_scraper.py                      # coordinate demo
  python3 kataster_scraper.py "Nitra" "1234/5"     # one parcel
  python3 kataster_scraper.py --lv "Nitra" 4321    # one LV directly
════════════════════════════════════════════════════════════════════════════
"""

import json
import math
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
from config import (
    CADASTRAL_DELAY_SEC, CADASTRAL_BACKOFF_MAX,
    LV_REJECT_FLAGS, LV_BANK_NAMES,
)

PORTAL_ODATA = "https://kataster.skgeodesy.sk/PortalOData/"
# Official LV (list vlastníctva) report generator — returns the full title
# deed as HTML (sections A: majetková podstata, B: vlastníci, C: ťarchy).
GENERATE_PRF = ("https://kataster.skgeodesy.sk/EsknBo/Bo.svc/GeneratePrf"
                "?prfNumber={lv_no}&cadastralUnitCode={ku_code}&outputType=html")
# ArcGIS identify service — resolves map coordinates to parcel entity ids.
IDENTIFY_URL = ("https://kataster.skgeodesy.sk/eskn/rest/services/VRM/identify"
                "/MapServer/identify")
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

_geoblock     = {"active": False}   # latches on after the first 403
_last_request = {"t": 0.0}


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


_EARTH_EQUATORIAL_RADIUS = 6378137.0


def _wgs84_to_mercator(lat: float, lon: float):
    """EPSG:4326 → EPSG:3857 (the identify service speaks Web Mercator)."""
    x = math.radians(lon) * _EARTH_EQUATORIAL_RADIUS
    y = (math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
         * _EARTH_EQUATORIAL_RADIUS)
    return x, y


# ── OData lookups ────────────────────────────────────────────────────────────
def resolve_cadastral_unit(area: str):
    """Resolve a katastrálne územie name or numeric code to {'code', 'name'}.
    KU names usually equal the obec/commune name, so either works. Returns
    None when nothing matches; raises CadastreError when the name is ambiguous
    (caller should pass the exact name or the numeric code)."""
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


def _flatten_parcel(p: dict, register: str) -> dict:
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
    return _flatten_parcel(live[0], register)


def get_parcel_by_id(parcel_id, register: str):
    """Fetch one parcel by its OData entity id (e.g. from identify_parcels)."""
    entity = "ParcelsC" if register == "C" else "ParcelsE"
    p = _get_json(PORTAL_ODATA + f"{entity}({parcel_id})/" + _PARCEL_QUERY)
    return _flatten_parcel(p, register)


def identify_parcels(lat: float, lon: float, tolerance: float = 0.000005) -> list:
    """Resolve WGS84 coordinates to parcel entity ids via the portal's ArcGIS
    identify service (the reference scraper's primary lookup path). Returns
    [{'register': 'C'|'E', 'parcel_id': ...}]."""
    xmin, ymin = _wgs84_to_mercator(lat - tolerance, lon - tolerance)
    xmax, ymax = _wgs84_to_mercator(lat + tolerance, lon + tolerance)
    # mapExtent/imageDisplay are required by the identify API but their exact
    # values don't affect an envelope query — fixed values as in the reference.
    url = (IDENTIFY_URL +
           "?f=json&geometryType=esriGeometryEnvelope"
           f"&geometry={xmin:.9f},{ymin:.9f},{xmax:.9f},{ymax:.9f}"
           "&sr=3857&layers=all&time=&layerTimeOptions=&layerdefs=&tolerance=0"
           "&mapExtent=1902836.4433083886,6131302.14771959,"
           "1902310.3415745723,6130808.890021369"
           "&imageDisplay=881,826,96&returnGeometry=false&maxAllowableOffset=")
    data = _get_json(url)
    results = [r for r in data.get("results", [])
               if "PARCELS" in r.get("layerName", "")]
    return [{"register": r["layerName"][-1], "parcel_id": r["attributes"]["ID"]}
            for r in results]


# Participant field names that may carry the ownership share (podiel) as a
# numerator/denominator pair. The portal backend doesn't documentedly expose
# the share, so this is opportunistic — see module docstring.
_SHARE_NUM_MARKERS = ("citatel", "numerator")
_SHARE_DEN_MARKERS = ("menovatel", "denominator")


def _extract_share(participant: dict):
    """Best-effort ownership share from a participant record: a num/den field
    pair, or any scalar field named like podiel/share/ratio holding 'n/d'.
    Returns 'n/d' or None."""
    flat = {k.lower(): v for k, v in participant.items()
            if not isinstance(v, (dict, list))}
    num = den = None
    for k, v in flat.items():
        if v is None:
            continue
        if any(m in k for m in _SHARE_NUM_MARKERS):
            num = v
        elif any(m in k for m in _SHARE_DEN_MARKERS):
            den = v
    if num is not None and den is not None:
        return f"{num}/{den}"
    for k, v in flat.items():
        if (isinstance(v, str) and re.fullmatch(r"\d+\s*/\s*\d+", v.strip())
                and any(m in k for m in ("podiel", "share", "ratio"))):
            return re.sub(r"\s+", "", v)
    return None


def fetch_owners(parcel_id, register: str) -> list:
    """Owners of a parcel via its participants → subjects: names, registered
    addresses, and (best-effort) ownership share. The participant level is
    fetched WITHOUT $select so share-carrying fields, if the backend exposes
    any, come through for _extract_share."""
    entity = "ParcelsC" if register == "C" else "ParcelsE"
    url = (PORTAL_ODATA + f"{entity}({parcel_id})/Kn.Participants"
           "?$expand=Subjects($select=Id,FirstName,Surname,BirthSurname;"
           "$expand=Address($select=Id,Street,HouseNo,Municipality,Zip,State))")
    owners, seen = [], set()
    for participant in _get_pages(url):
        share = _extract_share(participant)
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
                "share":         share,
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


# ── cache (avoid re-scraping the same parcel/LV) ─────────────────────────────
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
            (key, q["cadastral_area"], q.get("parcel_no") or q.get("lv_no"),
             q.get("register", ""), result["status"],
             json.dumps(result, ensure_ascii=False), result["fetched_at"]))
        conn.commit()
    finally:
        conn.close()


def _new_result(query: dict) -> dict:
    return {
        "status": "ERROR",
        "detail": "",
        "source": "live",
        "query": query,
        "cadastral_unit": None,
        "parcel": None,
        "lv": None,
        "owners": [],
        "lv_text": None,
        "risk_flags": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── entry points ─────────────────────────────────────────────────────────────
def enrich_parcel(cadastral_area: str, parcel_no: str, register: str = "auto",
                  refresh: bool = False, fetch_lv: bool = True) -> dict:
    """Look up one parcel on the (unofficial) cadastre portal.

    cadastral_area: katastrálne územie / obec name ("Nitra") or numeric
                    KU code (838365).
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

    key = f"{_norm(cadastral_area)}|{_norm(parcel_no)}|{register}"
    if not refresh:
        cached = _cache_get(key, need_lv_text=fetch_lv)
        if cached is not None:
            return cached

    result = _new_result({"cadastral_area": cadastral_area,
                          "parcel_no": parcel_no, "register": register})
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


def enrich_lv(cadastral_area: str, lv_no, refresh: bool = False) -> dict:
    """Look up one LV (list vlastníctva) directly by number.

    Fetches the official LV report text and derives risk flags. Owner names,
    shares and parcels are inside the returned lv_text — the portal offers no
    documented structured lookup from an LV number alone, so `owners` stays
    empty here; use enrich_parcel for structured owners.
    """
    key = f"lv|{_norm(cadastral_area)}|{_norm(str(lv_no))}"
    if not refresh:
        cached = _cache_get(key, need_lv_text=True)
        if cached is not None:
            return cached

    result = _new_result({"cadastral_area": cadastral_area,
                          "lv_no": str(lv_no), "register": "LV"})
    try:
        ku = resolve_cadastral_unit(cadastral_area)
        if ku is None:
            result.update(status="NOT_FOUND", detail=(
                f"cadastral unit '{cadastral_area}' not found on skgeodesy.sk"))
            _cache_put(key, result)
            return result
        result["cadastral_unit"] = ku
        result["lv"] = {
            "no": lv_no,
            "url": GENERATE_PRF.format(lv_no=lv_no, ku_code=ku["code"]),
        }
        result["lv_text"] = fetch_lv_text(lv_no, ku["code"])
        result["risk_flags"] = scan_risk_flags(result["lv_text"])
        result["status"] = "OK"
        result["detail"] = (f"LV {lv_no} in {ku['name']}: "
                            f"{len(result['risk_flags'])} risk flag(s); owners "
                            f"are in lv_text (no structured lookup by LV number)")
        _cache_put(key, result)
    except CadastreError as e:
        result.update(status="ERROR", detail=str(e))
    return result


# ── demo / self-test ─────────────────────────────────────────────────────────
def _print_result(result: dict):
    printable = dict(result)
    if printable.get("lv_text") and len(printable["lv_text"]) > 600:
        printable["lv_text"] = printable["lv_text"][:600] + "…"
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))


def _demo_by_coordinates():
    """End-to-end self-test on a real parcel: central Bratislava (Hodžovo
    námestie area — the same coordinates the verejne.digital test-suite uses),
    resolved live via the identify service so no parcel number is hardcoded."""
    lat, lon = 48.1451953, 17.0910016
    print(f"# identify parcels at ({lat}, {lon}) — central Bratislava …")
    hits = identify_parcels(lat, lon)
    if not hits:
        print("No parcel found at the demo coordinates — the identify service "
              "may have changed. Try: python3 kataster_scraper.py AREA PARCEL")
        return 1
    hit = hits[0]
    print(f"# found parcel id {hit['parcel_id']} (register {hit['register']}); "
          f"fetching …")
    parcel = get_parcel_by_id(hit["parcel_id"], hit["register"])
    ku_name = parcel["municipality"] or ""
    print(f"# parcel {parcel['no']} in {ku_name}, LV {parcel['lv_no']}; "
          f"running full enrich_parcel …")
    # Re-enter through the main entry point so cache + owners + LV text all run.
    ku = _get_json(PORTAL_ODATA + f"Parcels{hit['register']}({hit['parcel_id']})"
                   "/CadastralUnit?$select=Name,Code")
    result = enrich_parcel(str(ku["Code"]), parcel["no"],
                           register=hit["register"])
    _print_result(result)
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--lv" and len(args) >= 3:
        res = enrich_lv(args[1], args[2])
    elif len(args) >= 2:
        res = enrich_parcel(args[0], args[1])
    else:
        sys.exit(_demo_by_coordinates())
    _print_result(res)
    sys.exit(0 if res["status"] == "OK" else 1)

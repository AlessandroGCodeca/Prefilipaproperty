"""
modules/cuzk_cz.py — the Czech cadastre (ČÚZK) and address register (RÚIAN),
read the ways ČÚZK offers to programs.

  RÚIAN    the address point (adresní místo) nearest a listing's map pin, from
           ČÚZK's public RÚIAN map service (ArcGIS REST, no key):
             GET {CZ_RUIAN_MAPSERVER}/{layer}/query?geometry=lng,lat&inSR=4326
                 &distance=…&units=esriSRUnit_Meter&outFields=*&f=json
           Layer 1 is AdresniMisto, field "kod" its code.
  API KN   ČÚZK's free REST API to the cadastre (since 1 July 2024; a key from
           registrace.cuzk.gov.cz in CZ_CUZK_API_KEY, sent as the ApiKey
           header):
             GET /api/v1/Stavby/AdresniMisto/{kod}   the building at an address
                 → its LV, katastrální území, units, parcels, and the
                   proceedings pending on it (rizeniPlomby)
             GET /api/v1/Jednotky/{id}              a unit → its own LV
             GET /api/v1/Jednotky/Vyhledani         a unit by část obce, house
                 number and unit number

What neither gives: the LV's contents. The API answers which LV a unit is on
and whether a change of rights is pending, not what part C of that LV
carries (liens, exekuce, easements). That is in the výpis z LV — sold by
CzechPOINT and ČÚZK's dálkový přístup — or shown one query at a time by
nahlížení do katastru, which ČÚZK guards with a CAPTCHA and does not open to
automated reading. So no answer from here is ever a clean title
(modules/lv_cz).

The API paths and fields are from the OpenAPI document of API KN v1.0 (as
copied in the open-source client petrolivka/cuzk_api, January 2025); the
RÚIAN layer number and field name from ČÚZK's published layer list. Neither
host could be reached from here — UNVERIFIED until a live call answers.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)

API_BASE = os.getenv("CZ_CUZK_API_BASE", "https://api-kn.cuzk.gov.cz").rstrip("/")
RUIAN_MAPSERVER = os.getenv(
    "CZ_RUIAN_MAPSERVER",
    "https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer").rstrip("/")
RUIAN_ADDRESS_LAYER = int(os.getenv("CZ_RUIAN_ADDRESS_LAYER", "1") or 1)
# How far from a pin an address point may be.
PIN_RADIUS_M = 30
_timeout = 20.0

SOURCE = {
    "api_kn": ("ČÚZK API KN v1.0 — free REST API, ApiKey header (OpenAPI document as "
               "copied in github.com/petrolivka/cuzk_api, 2025-01; cuzk.gov.cz notice "
               "of 1 July 2024). UNVERIFIED live."),
    "ruian": ("ČÚZK RÚIAN map service, layer AdresniMisto (1), field kod "
              "(ags.cuzk.gov.cz layer list, read via web search). UNVERIFIED live."),
    "checked": "2026-10-16 (web search; no ČÚZK host reachable from here)",
}


def api_key() -> str:
    return (os.getenv("CZ_CUZK_API_KEY") or "").strip()


def enabled() -> bool:
    return bool(api_key())


@contextmanager
def quick_requests(timeout: float = 8.0):
    """Short patience for a click on the dashboard."""
    global _timeout
    old, _timeout = _timeout, timeout
    try:
        yield
    finally:
        _timeout = old


def _http_get(url: str, params=None, headers=None):
    import requests
    return requests.get(url, params=params, headers=headers or {}, timeout=_timeout)


def _api(path: str, params=None) -> dict:
    """{"status": "OK" | "NO_KEY" | "NOT_FOUND" | "ERROR", "data", "detail"}."""
    if not enabled():
        return {"status": "NO_KEY", "data": None,
                "detail": "CZ_CUZK_API_KEY is not set (a free key from registrace.cuzk.gov.cz)"}
    try:
        r = _http_get(f"{API_BASE}{path}", params=params,
                      headers={"ApiKey": api_key(), "Accept": "application/json"})
    except Exception as e:
        return {"status": "ERROR", "data": None, "detail": f"API KN unreachable ({type(e).__name__})"}
    if r.status_code == 404:
        return {"status": "NOT_FOUND", "data": None, "detail": "not in the cadastre"}
    if r.status_code != 200:
        why = {401: "the API key was refused", 403: "the API key was refused",
               429: "the daily call limit is used up"}.get(r.status_code, "")
        return {"status": "ERROR", "data": None,
                "detail": f"API KN answered HTTP {r.status_code}" + (f" — {why}" if why else "")}
    try:
        body = r.json()
    except ValueError:
        return {"status": "ERROR", "data": None, "detail": "API KN answered with no JSON"}
    data = body.get("data") if isinstance(body, dict) else None
    if data is None:
        msgs = "; ".join(str(z.get("text")) for z in (body.get("zpravy") or [])
                         if isinstance(z, dict)) if isinstance(body, dict) else ""
        return {"status": "NOT_FOUND", "data": None, "detail": msgs or "no data"}
    return {"status": "OK", "data": data, "detail": ""}


def building_at_address(kod) -> dict:
    return _api(f"/api/v1/Stavby/AdresniMisto/{int(kod)}")


def unit(unit_id) -> dict:
    return _api(f"/api/v1/Jednotky/{int(unit_id)}")


def find_unit(kod_casti_obce, cislo_domovni, cislo_jednotky, typ_stavby: int = 1) -> dict:
    return _api("/api/v1/Jednotky/Vyhledani",
                {"KodCastiObce": int(kod_casti_obce), "TypStavby": int(typ_stavby),
                 "CisloDomovni": int(cislo_domovni), "CisloJednotky": int(cislo_jednotky)})


def proceeding_label(r: dict) -> str:
    """"V-1234/2026" from a RizeniDef."""
    if not isinstance(r, dict):
        return ""
    kind = str(r.get("typRizeni") or "?")
    return f"{kind}-{r.get('poradoveCislo', '?')}/{r.get('rok', '?')}"


def summarize_building(stavba: dict) -> dict:
    """The parts of an API KN Stavba the LV check uses."""
    stavba = stavba or {}
    lv = stavba.get("lv") or {}
    ku = lv.get("katastralniUzemi") or {}
    parcels = stavba.get("parcely") or []
    parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    pno = parcel.get("kmenoveCisloParcely")
    if pno is not None and parcel.get("poddeleniCislaParcely"):
        pno = f"{pno}/{parcel['poddeleniCislaParcely']}"
    return {
        "lv_no": lv.get("cislo"),
        "ku_name": ku.get("nazev") or (parcel.get("katastralniUzemi") or {}).get("nazev"),
        "ku_code": ku.get("kod") or (parcel.get("katastralniUzemi") or {}).get("kod"),
        "house_numbers": [str(n) for n in stavba.get("cislaDomovni") or []],
        "part_of_town": (stavba.get("castObce") or {}).get("nazev"),
        "municipality": (stavba.get("obec") or {}).get("nazev"),
        "units": [u.get("cisloJednotky") for u in stavba.get("jednotky") or []
                  if isinstance(u, dict)],
        "unit_ids": {u.get("cisloJednotky"): u.get("id") for u in stavba.get("jednotky") or []
                     if isinstance(u, dict)},
        "parcel_no": str(pno) if pno is not None else None,
        "pending": [proceeding_label(r) for r in stavba.get("rizeniPlomby") or []],
    }


def address_point_near(lat: float, lng: float, radius_m: int = PIN_RADIUS_M) -> dict:
    """{"status": "OK", "kod", "attributes"} for the RÚIAN address point
    nearest (lat, lng) within radius_m, else {"status": "NOT_FOUND" | "ERROR"}."""
    params = {"geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint",
              "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
              "distance": radius_m, "units": "esriSRUnit_Meter", "outFields": "*",
              "returnGeometry": "true", "outSR": 4326, "f": "json"}
    try:
        r = _http_get(f"{RUIAN_MAPSERVER}/{RUIAN_ADDRESS_LAYER}/query", params=params)
        body = r.json() if r.status_code == 200 else None
    except Exception as e:
        return {"status": "ERROR", "detail": f"RÚIAN unreachable ({type(e).__name__})"}
    if not isinstance(body, dict) or "features" not in body:
        err = (body or {}).get("error", {}).get("message") if isinstance(body, dict) else None
        return {"status": "ERROR", "detail": err or f"RÚIAN answered HTTP {r.status_code}"}

    def dist(f):
        g = f.get("geometry") or {}
        try:
            return (float(g["x"]) - lng) ** 2 + (float(g["y"]) - lat) ** 2
        except (KeyError, TypeError, ValueError):
            return float("inf")
    feats = [f for f in body["features"] if isinstance(f, dict)]
    for f in sorted(feats, key=dist):
        attrs = {k.lower(): v for k, v in (f.get("attributes") or {}).items()}
        if attrs.get("kod"):
            return {"status": "OK", "kod": int(attrs["kod"]), "attributes": attrs}
    return {"status": "NOT_FOUND", "detail": f"no address point within {radius_m} m of the pin"}


def building_at_pin(lat: float, lng: float) -> dict:
    """The building under a map pin: RÚIAN's nearest address point, then API
    KN's building for it. {"status", "building" (summarize_building), "detail"}."""
    if not enabled():
        return {"status": "NO_KEY", "detail": _api("/")["detail"]}
    point = address_point_near(lat, lng)
    if point["status"] != "OK":
        return {"status": point["status"], "detail": point["detail"]}
    found = building_at_address(point["kod"])
    if found["status"] != "OK":
        return {"status": found["status"],
                "detail": f"address point {point['kod']}: {found['detail']}"}
    return {"status": "OK", "building": summarize_building(found["data"]),
            "address_point": point["kod"], "detail": ""}

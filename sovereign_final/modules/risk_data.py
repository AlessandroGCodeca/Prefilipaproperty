"""
modules/risk_data.py — real location-risk data in place of the old stubs.

check_construction() and check_noise() in modules/location_iq used to return
False for every flat ("no data source = no flag"), and flood_zone was written
as 0. This module answers all three from open data, with no API keys:

  construction  OpenStreetMap: landuse=construction / building=construction
                within CONSTRUCTION_RADIUS_M.
  noise         OpenStreetMap, as a proxy for the EU strategic noise maps: a
                motorway/trunk, primary road, main-line railway or airport
                close enough that ≥NOISE_LIMIT_DB Lden is the norm (distances
                in config.NOISE_*). It is a proxy — a quiet courtyard flat
                30 m from a primary road gets flagged too.
  flood         SVP's flood-hazard map service: is the point inside the
                mapped Q100 (100-year) flood extent? Only rivers SVP has
                mapped are covered, so "no" means "outside the mapped area".

Each answer is True / False / None. None means the source could not be asked
(network error) or the coordinates are too vague to ask about — a district
centroid is not a flat. location_iq stores None as "unknown", never as a flag.

One Overpass query per flat also returns the nearest public-transport stop
and nearby groceries/pharmacies/schools, which location_iq uses when there is
no Google key. Nominatim geocodes in that case too.
"""

from __future__ import annotations

import math
import time

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    OVERPASS_URL, NOMINATIM_URL, NOMINATIM_EMAIL,
    FLOOD_IDENTIFY_URL, FLOOD_LAYER_IDS,
    CONSTRUCTION_RADIUS_M, AMENITY_RADIUS_METERS,
    NOISE_MAJOR_ROAD_M, NOISE_PRIMARY_M, NOISE_RAIL_M, NOISE_AIRPORT_M,
)

USER_AGENT = "SovereignRE/1.0 (private Slovak property research tool)"
TRANSIT_SEARCH_M = 2000

# Geocode precision. Only "address" / "street" are precise enough to judge
# what is next to the flat; "area" is a district or town centroid.
PRECISE = ("address", "street")


def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Geocoding (Nominatim) ────────────────────────────────────────────────────
_NOMINATIM_ADDRESS = {"house", "building", "house_number"}
_NOMINATIM_STREET = {"road", "street", "pedestrian", "residential", "square",
                     "neighbourhood", "quarter"}


def nominatim_precision(result: dict) -> str:
    kind = (result.get("addresstype") or result.get("type") or "").lower()
    if kind in _NOMINATIM_ADDRESS:
        return "address"
    if kind in _NOMINATIM_STREET:
        return "street"
    return "area"


_last_nominatim = 0.0


def geocode_nominatim(address: str) -> tuple[float | None, float | None, str]:
    """(lat, lng, precision) for a Slovak address, or (None, None, "") when
    Nominatim finds nothing. Throttled to Nominatim's 1 request/second."""
    global _last_nominatim
    if not (address or "").strip():
        return None, None, ""
    wait = 1.1 - (time.monotonic() - _last_nominatim)
    if wait > 0:
        time.sleep(wait)
    params = {"q": address, "format": "jsonv2", "countrycodes": "sk", "limit": 1}
    if NOMINATIM_EMAIL:
        params["email"] = NOMINATIM_EMAIL
    try:
        r = requests.get(NOMINATIM_URL, params=params, timeout=15,
                         headers={"User-Agent": USER_AGENT})
        _last_nominatim = time.monotonic()
        results = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"    Nominatim error: {type(e).__name__}")
        return None, None, ""
    if not results:
        return None, None, ""
    top = results[0]
    return float(top["lat"]), float(top["lon"]), nominatim_precision(top)


def google_precision(result: dict) -> str:
    """Precision of a Google Geocoding result."""
    loc_type = (result.get("geometry") or {}).get("location_type", "")
    types = set(result.get("types") or [])
    if loc_type in ("ROOFTOP", "RANGE_INTERPOLATED") or types & {"street_address", "premise"}:
        return "address"
    if "route" in types:
        return "street"
    return "area"


# ── OpenStreetMap (Overpass) ─────────────────────────────────────────────────
def overpass_query(lat: float, lng: float) -> str:
    c = f"{lat:.6f},{lng:.6f}"
    return f"""[out:json][timeout:40];
(
  nwr(around:{CONSTRUCTION_RADIUS_M},{c})["landuse"="construction"];
  nwr(around:{CONSTRUCTION_RADIUS_M},{c})["building"="construction"];
  way(around:{NOISE_MAJOR_ROAD_M},{c})["highway"~"^(motorway|trunk|motorway_link|trunk_link)$"];
  way(around:{NOISE_PRIMARY_M},{c})["highway"="primary"];
  way(around:{NOISE_RAIL_M},{c})["railway"="rail"][!"service"];
  nwr(around:{NOISE_AIRPORT_M},{c})["aeroway"="aerodrome"]["iata"];
  nwr(around:{AMENITY_RADIUS_METERS},{c})["shop"~"^(supermarket|convenience|greengrocer)$"];
  nwr(around:{AMENITY_RADIUS_METERS},{c})["amenity"~"^(pharmacy|school|kindergarten)$"];
  node(around:{TRANSIT_SEARCH_M},{c})["highway"="bus_stop"];
  node(around:{TRANSIT_SEARCH_M},{c})["railway"~"^(tram_stop|station|halt)$"];
  node(around:{TRANSIT_SEARCH_M},{c})["public_transport"="platform"];
);
out tags center qt;"""


def fetch_osm(lat: float, lng: float) -> list[dict] | None:
    """Overpass elements around the point, or None when Overpass can't be
    reached (one retry on a rate-limit / timeout answer)."""
    q = overpass_query(lat, lng)
    for attempt in range(2):
        try:
            r = requests.post(OVERPASS_URL, data={"data": q}, timeout=60,
                              headers={"User-Agent": USER_AGENT})
        except Exception as e:
            print(f"    Overpass error: {type(e).__name__}")
            return None
        if r.status_code == 200:
            try:
                payload = r.json()
            except ValueError:
                return None
            # A query that hit its timeout or memory cap still answers 200,
            # with partial (often empty) elements and a "remark". Empty would
            # read as "nothing nearby", so it counts as no answer.
            if "error" in str(payload.get("remark", "")).lower():
                print("    Overpass: query did not complete")
                return None
            return payload.get("elements", [])
        if r.status_code in (429, 504) and attempt == 0:
            time.sleep(10)
            continue
        print(f"    Overpass HTTP {r.status_code}")
        return None
    return None


def _coords(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    if c and "lat" in c:
        return c["lat"], c["lon"]
    return None


def _name(tags: dict) -> str:
    return tags.get("name") or tags.get("ref") or ""


def classify_osm(elements: list[dict], lat: float, lng: float) -> dict:
    """Turn Overpass elements into the location facts.

    Every element is already within its own radius (the query asked
    `around:` per tag), so a road or railway being present is the finding —
    a way's centre can be far from where it passes the flat, so no distance is
    claimed for it.
    """
    construction, roads, primary, rail, airports = [], [], [], [], []
    groceries = pharmacies = schools = 0
    transit_m: float | None = None
    for el in elements or []:
        t = el.get("tags") or {}
        hw, rw = t.get("highway", ""), t.get("railway", "")
        if t.get("landuse") == "construction" or t.get("building") == "construction":
            construction.append(_name(t) or "construction site")
        elif hw in ("motorway", "trunk", "motorway_link", "trunk_link"):
            roads.append(_name(t) or hw)
        elif hw == "primary":
            primary.append(_name(t) or "primary road")
        elif rw == "rail" and el.get("type") == "way":
            rail.append(_name(t) or "railway")
        elif t.get("aeroway") == "aerodrome":
            airports.append(_name(t) or t.get("iata", "airport"))
        elif t.get("shop") in ("supermarket", "convenience", "greengrocer"):
            groceries += 1
        elif t.get("amenity") == "pharmacy":
            pharmacies += 1
        elif t.get("amenity") in ("school", "kindergarten"):
            schools += 1
        if (hw == "bus_stop" or rw in ("tram_stop", "station", "halt")
                or t.get("public_transport") == "platform") and el.get("type") == "node":
            xy = _coords(el)
            if xy:
                d = _haversine(lat, lng, *xy)
                transit_m = d if transit_m is None else min(transit_m, d)

    noise_parts = []
    if roads:
        noise_parts.append(f"motorway/trunk ≤{NOISE_MAJOR_ROAD_M} m ({_uniq(roads)})")
    if primary:
        noise_parts.append(f"primary road ≤{NOISE_PRIMARY_M} m ({_uniq(primary)})")
    if rail:
        noise_parts.append(f"railway ≤{NOISE_RAIL_M} m ({_uniq(rail)})")
    if airports:
        noise_parts.append(f"airport ≤{NOISE_AIRPORT_M} m ({_uniq(airports)})")
    return {
        "construction":        bool(construction),
        "construction_detail": (f"{len(construction)} within {CONSTRUCTION_RADIUS_M} m: "
                                f"{_uniq(construction)}" if construction else
                                f"none within {CONSTRUCTION_RADIUS_M} m (OSM)"),
        "noise":               bool(noise_parts),
        "noise_detail":        "; ".join(noise_parts) if noise_parts else "no major road/rail/airport nearby (OSM)",
        "nearest_transit_m":   round(transit_m, 1) if transit_m is not None else None,
        "grocery_count":       groceries,
        "pharmacy_count":      pharmacies,
        "school_count":        schools,
    }


def _uniq(names: list[str], limit: int = 3) -> str:
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    more = f" +{len(seen) - limit}" if len(seen) > limit else ""
    return ", ".join(seen[:limit]) + more


# ── Flood (SVP flood hazard maps) ────────────────────────────────────────────
def flood_identify_params(lat: float, lng: float) -> dict:
    d = 0.002
    return {
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "sr": 4326,
        "layers": f"all:{FLOOD_LAYER_IDS}",
        "tolerance": 0,
        "mapExtent": f"{lng - d},{lat - d},{lng + d},{lat + d}",
        "imageDisplay": "400,400,96",
        "returnGeometry": "false",
        "f": "json",
    }


def classify_flood(payload: dict) -> tuple[bool | None, str]:
    """Read an ArcGIS identify answer. Any feature at the point means it lies
    in the mapped Q100 extent; a raster layer reports NoData outside it."""
    if not isinstance(payload, dict) or "error" in payload:
        return None, "flood service error"
    hits = []
    for res in payload.get("results") or []:
        attrs = res.get("attributes") or {}
        pixel = str(attrs.get("Pixel Value", attrs.get("Pixel value", ""))).lower()
        if pixel in ("nodata", "no data"):
            continue
        hits.append(res.get("layerName") or "flood area")
    if hits:
        return True, f"inside {', '.join(dict.fromkeys(hits))} (SVP flood hazard map)"
    return False, "outside the mapped Q100 flood area (SVP)"


_flood_layers_checked: tuple[bool, str] | None = None


def flood_layers_usable() -> tuple[bool, str]:
    """Check once per process that FLOOD_LAYER_IDS name area layers.

    identify with zero tolerance only ever hits a point inside a polygon or on
    a raster cell. Pointed at a line layer (a flood *line*) or a layer id that
    doesn't exist, it would answer "outside" for every flat — so that is
    detected here and the flood answer becomes unknown instead.
    """
    global _flood_layers_checked
    if _flood_layers_checked is not None:
        return _flood_layers_checked
    base = FLOOD_IDENTIFY_URL.rsplit("/identify", 1)[0]
    verdict = (True, "")
    for layer_id in [x.strip() for x in FLOOD_LAYER_IDS.split(",") if x.strip()]:
        try:
            r = requests.get(f"{base}/{layer_id}", params={"f": "json"}, timeout=20,
                             headers={"User-Agent": USER_AGENT})
            meta = r.json() if r.status_code == 200 else {}
        except Exception as e:
            # Unreachable now — say so for this call, but try again next time.
            return False, f"flood service unreachable ({type(e).__name__})"
        if not meta.get("name") or "error" in meta:
            verdict = (False, f"flood layer {layer_id} not found — check FLOOD_LAYER_IDS")
            break
        geom = meta.get("geometryType") or ""
        if geom and geom != "esriGeometryPolygon":
            verdict = (False, f"flood layer {layer_id} is {geom}, not areas — "
                              f"check FLOOD_LAYER_IDS")
            break
    _flood_layers_checked = verdict
    return verdict


def check_flood(lat: float, lng: float) -> tuple[bool | None, str]:
    ok, why = flood_layers_usable()
    if not ok:
        return None, why
    try:
        r = requests.get(FLOOD_IDENTIFY_URL, params=flood_identify_params(lat, lng),
                         timeout=20, headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None, f"flood service HTTP {r.status_code}"
        return classify_flood(r.json())
    except Exception as e:
        return None, f"flood service unreachable ({type(e).__name__})"


# ── All together ─────────────────────────────────────────────────────────────
def assess(lat: float, lng: float, precision: str = "address",
           osm_elements: list[dict] | None = None) -> dict:
    """Construction, noise and flood for one point.

    With an area-level geocode every risk answer is None ("too vague"), but
    the OSM transit/amenity facts are still returned for the area. Pass
    osm_elements to reuse a response already fetched.
    """
    elements = osm_elements if osm_elements is not None else fetch_osm(lat, lng)
    osm = classify_osm(elements, lat, lng) if elements is not None else None
    out = {
        "osm_ok": osm is not None,
        "nearest_transit_m": osm["nearest_transit_m"] if osm else None,
        "grocery_count":     osm["grocery_count"] if osm else None,
        "pharmacy_count":    osm["pharmacy_count"] if osm else None,
        "school_count":      osm["school_count"] if osm else None,
    }
    if precision not in PRECISE:
        vague = "address too vague to judge (geocoded to an area, not a street)"
        out.update(construction=None, construction_detail=vague,
                   noise=None, noise_detail=vague,
                   flood=None, flood_detail=vague)
        return out
    if osm:
        out.update(construction=osm["construction"],
                   construction_detail=osm["construction_detail"],
                   noise=osm["noise"], noise_detail=osm["noise_detail"])
    else:
        out.update(construction=None, construction_detail="OSM unreachable",
                   noise=None, noise_detail="OSM unreachable")
    flood, flood_detail = check_flood(lat, lng)
    out.update(flood=flood, flood_detail=flood_detail)
    return out

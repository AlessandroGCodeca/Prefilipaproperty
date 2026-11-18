"""
modules/location_iq.py — Sovereign Investor Dashboard
Module C: Location IQ — transit, amenities and noise/flood/construction risk.

Transit and amenities come from Google when GOOGLE_PLACES_API_KEY is set,
and from OpenStreetMap (Overpass) when it isn't. Addresses are geocoded by
Mapy.com (MAPY_API_KEY; first for Czech addresses), Google, then OpenStreetMap
(Nominatim) — see providers(). The risk
flags always come from open data via modules/risk_data — never invented.

Each listing is located in its own market's country (listings.market): a
Czech address is geocoded in Czechia and its flood answer comes from the
Czech map.
"""

import logging
import time, math
from datetime import datetime, timezone

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    GOOGLE_API_KEY,
    TRANSIT_WALK_METERS, AMENITY_RADIUS_METERS,
    POINTS_TRANSIT, POINTS_AMENITIES, POINTS_CONSTRUCTION,
    POINTS_NOISE, POINTS_ENERGY,
    PRIME_THRESHOLD, SOLID_THRESHOLD,
    INDUSTRIAL_ZONES, SCRAPE_DELAY_SEC,
)
from database import (
    get_unscored_location, upsert_location, init_db,
    get_location_rows_missing_risk, update_location_risk, mark_location_tried,
)
from modules import risk_data

log = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Places API (New): the legacy Nearby Search (maps/api/place/nearbysearch)
# can't be enabled for new Google Cloud projects any more. Enable "Places API
# (New)" for the key; while it refuses (not enabled, no billing), transit and
# amenities come from OpenStreetMap as they do without a key.
PLACES_URL  = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_FIELDS = "places.location"
# Each count's place types in Places API (New) (Table A).
AMENITY_TYPES = {
    "grocery_count":  ("grocery_store", "supermarket"),
    "pharmacy_count": ("pharmacy",),
    "school_count":   ("school", "primary_school", "secondary_school"),
}


class PlacesUnavailable(Exception):
    """Google refused the request (the API not enabled, no billing, a bad key)."""


def _places_nearby(lat: float, lng: float, radius: float, types) -> list[tuple[float, float]]:
    """The points of up to 20 places of `types` within `radius` metres
    (Places API (New) searchNearby). Raises PlacesUnavailable on a refusal."""
    r = requests.post(PLACES_URL, json={
        "includedTypes": list(types), "maxResultCount": 20,
        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                           "radius": float(radius)}},
    }, headers={"X-Goog-Api-Key": GOOGLE_API_KEY, "X-Goog-FieldMask": PLACES_FIELDS},
        timeout=10)
    if getattr(r, "status_code", 200) in (400, 401, 403):
        msg = ""
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except Exception:
            pass
        raise PlacesUnavailable(f"HTTP {r.status_code} {msg[:120]}")
    out = []
    for p in (r.json() or {}).get("places", []) or []:
        try:
            loc = p["location"]
            out.append((float(loc["latitude"]), float(loc["longitude"])))
        except (KeyError, TypeError, ValueError):
            continue        # a place without a usable location
    return out


def _osm_counts(lat: float, lng: float) -> dict | None:
    elements = risk_data.fetch_osm(lat, lng)
    return risk_data.classify_osm(elements, lat, lng) if elements else None


# ── Geocoding ─────────────────────────────────────────────────────────────────
def _geocode_google(address: str, market: str) -> tuple[float | None, float | None, str]:
    import markets
    try:
        r = requests.get(GEOCODE_URL, params={
            "address": address + ", " + markets.get(market).name,
            "key": GOOGLE_API_KEY,
            **({} if market == "sk" else {"region": markets.get(market).country_code}),
        }, timeout=10)
        data = r.json()
        if data.get("results"):
            top = data["results"][0]
            loc = top["geometry"]["location"]
            return loc["lat"], loc["lng"], risk_data.google_precision(top)
    except Exception as e:
        # The request's URL carries the key; requests puts it in the error.
        from modules.redact import redact
        log.warning(f"    Geocode error: {redact(e)}")
    return None, None, ""


def providers(market: str = "sk") -> list[str]:
    """The geocoders to try, in order, for a market. A Czech address goes to
    Mapy.com first (it knows every house number from the register of
    addresses, RUIAN, and is free), then Google; a Slovak one to Google first,
    then Mapy.com. Nominatim, which needs no key, is always last."""
    from config import MAPY_API_KEY
    mapy = ["mapy"] if (MAPY_API_KEY or os.getenv("MAPY_API_KEY")) else []
    google = ["google"] if GOOGLE_API_KEY else []
    return (mapy + google if market == "cz" else google + mapy) + ["nominatim"]


def geocode_precise(address: str, market: str = "sk") -> tuple[float | None, float | None, str]:
    """(lat, lng, precision) — precision is "address", "street" or "area"
    (see modules/risk_data). The first of providers(market) that finds the
    address, in the market's country (Slovakia by default); (None, None, "")
    when none does."""
    for name in providers(market):
        if name == "mapy":
            got = risk_data.geocode_mapy(address, market)
        elif name == "google":
            got = _geocode_google(address, market)
        elif market == "sk":
            got = risk_data.geocode_nominatim(address)
        else:
            got = risk_data.geocode_nominatim(address, market=market)
        if got[0] is not None:
            return got
    return None, None, ""


# ── Places Queries ────────────────────────────────────────────────────────────
def nearest_transit(lat: float, lng: float) -> float:
    """Metres to the nearest transit stop, or 9999.0 when none is found.

    Google's Nearby Search lists results by prominence, not distance, so the
    first result is often a main station a kilometre away while a tram stop
    sits at the door: the nearest is the shortest distance over all results."""
    def from_osm():
        osm = _osm_counts(lat, lng)
        t = osm["nearest_transit_m"] if osm else None
        return 9999.0 if t is None else t
    if not GOOGLE_API_KEY:
        return from_osm()
    try:
        dists = [_haversine(lat, lng, plat, plng)
                 for plat, plng in _places_nearby(lat, lng, 2000, ("transit_station",))]
        if dists:
            return min(dists)
    except PlacesUnavailable as e:
        log.warning(f"    Google Places (New) refused ({e}) — OpenStreetMap instead")
        return from_osm()
    except Exception as e:
        log.warning(f"    Transit error: {e}")
    return 9999.0


def count_amenities(lat: float, lng: float) -> dict:
    counts = {"grocery_count": 0, "pharmacy_count": 0, "school_count": 0}

    def from_osm():
        osm = _osm_counts(lat, lng)
        return {k: osm[k] for k in counts} if osm else counts
    if not GOOGLE_API_KEY:
        return from_osm()

    for key, ptypes in AMENITY_TYPES.items():
        try:
            counts[key] = len(_places_nearby(lat, lng, AMENITY_RADIUS_METERS, ptypes))
            time.sleep(0.3)
        except PlacesUnavailable as e:
            log.warning(f"    Google Places (New) refused ({e}) — OpenStreetMap instead")
            return from_osm()
        except Exception as e:
            log.warning(f"    Amenity error ({key}): {e}")

    return counts


def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lng2 - lng1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def is_industrial(district: str, market: str = "sk") -> tuple[bool, str]:
    key = (district or "").lower().strip()
    if market == "sk":
        zones = INDUSTRIAL_ZONES
    else:
        import markets
        zones = markets.get(market).industrial_zones
    for z in zones:
        if z in key:
            return True, z
    return False, ""


def _geocode(address: str, market: str):
    """geocode_precise, called for a Slovak listing exactly as it always was."""
    return geocode_precise(address) if market == "sk" else geocode_precise(address, market=market)


def _assess(lat, lng, precision, market: str):
    """risk_data.assess, called for a Slovak listing exactly as it always was."""
    if market == "sk":
        return risk_data.assess(lat, lng, precision)
    return risk_data.assess(lat, lng, precision, market=market)


# ── Score Computation ─────────────────────────────────────────────────────────
def compute_score(transit_m, amenity_counts, construction, noise, energy) -> tuple[int, str]:
    score = 0
    total_amenities = sum(amenity_counts.values())

    if transit_m <= TRANSIT_WALK_METERS:       score += POINTS_TRANSIT
    if total_amenities >= 3:                   score += POINTS_AMENITIES
    if not construction:                       score += POINTS_CONSTRUCTION
    if not noise:                              score += POINTS_NOISE
    if (energy or "").upper() in ("A0","A1","A"): score += POINTS_ENERGY

    if noise:              tier = "POOR"
    elif score >= PRIME_THRESHOLD: tier = "PRIME"
    elif score >= SOLID_THRESHOLD: tier = "SOLID"
    else:                          tier = "STANDARD"

    return score, tier


# ── Main Runner ───────────────────────────────────────────────────────────────
def _flag(v) -> int | None:
    return None if v is None else int(bool(v))


def run_location_scoring(progress_callback=None, limit: int | None = 200,
                         market: str | None = None) -> int:
    """Score every PASS listing that has no location row yet.

    With a Google key: Google geocoding, transit and amenities. Without one:
    Nominatim + OpenStreetMap — real data either way (this used to refuse to
    run without a key rather than fabricate coordinates). Risk flags always
    come from modules/risk_data; a flag that can't be determined is stored as
    NULL, and an area-level geocode leaves every risk flag NULL.
    """
    listings = get_unscored_location()
    if market is not None:
        listings = [r for r in listings if (r.get("market") or "sk") == market]
    if not listings:
        log.info("✅ No listings to score for location.")
        return 0
    # Each listing is a few seconds of polite requests to free services, so a
    # first run over a full backlog is spread over several days.
    if limit:
        listings = listings[:limit]

    provider = {"mapy": "Mapy.com", "google": "Google", "nominatim": "OpenStreetMap"}[
        providers(market="sk")[0]]
    log.info(f"📍 Scoring {len(listings)} locations ({provider})...")
    scored = 0
    tier_emoji = {"PRIME":"⭐","SOLID":"✅","STANDARD":"🟡","POOR":"🔴"}

    for i, row in enumerate(listings):
        lid    = row["id"]
        addr   = row.get("address_raw") or row.get("district") or ""
        energy = row.get("energy_class","UNKNOWN")
        dist   = row.get("district","")
        mkt    = row.get("market") or "sk"

        if progress_callback:
            progress_callback(i + 1, len(listings), addr[:50])

        # The portal's own map pin beats geocoding an address that is often
        # just "Petržalka, Bratislava". Pins are street-level at best (some
        # agencies offset them), so that is the precision claimed for them.
        if row.get("coords_source") == "listing" and row.get("lat") is not None:
            lat, lng, precision = row["lat"], row["lng"], "street"
        else:
            lat, lng, precision = _geocode(addr, mkt)
        if lat is None:
            log.warning(f"  ⚠️ No geocode: {addr[:50]}")
            # To the back of the queue: listings that never geocode would
            # otherwise take the first `limit` places on every run.
            mark_location_tried(lid)
            continue

        risk = _assess(lat, lng, precision, mkt)
        if GOOGLE_API_KEY:
            transit   = nearest_transit(lat, lng)
            amenities = count_amenities(lat, lng)
        else:
            transit = risk["nearest_transit_m"]
            transit = 9999.0 if transit is None else transit
            amenities = {k: risk[k] or 0 for k in
                         ("grocery_count", "pharmacy_count", "school_count")}
        ind, ind_name = is_industrial(dist) if mkt == "sk" else is_industrial(dist, mkt)
        score, tier  = compute_score(transit, amenities, bool(risk["construction"]),
                                     bool(risk["noise"]), energy)

        upsert_location({
            "listing_id":           lid,
            "lat":                  lat,
            "lng":                  lng,
            "nearest_transit_m":    round(transit, 1),
            "amenity_count":        sum(amenities.values()),
            "grocery_count":        amenities["grocery_count"],
            "pharmacy_count":       amenities["pharmacy_count"],
            "school_count":         amenities["school_count"],
            "construction_risk":    _flag(risk["construction"]),
            "construction_detail":  risk["construction_detail"],
            "noise_flag":           _flag(risk["noise"]),
            "noise_detail":         risk["noise_detail"],
            "flood_zone":           _flag(risk["flood"]),
            "flood_detail":         risk["flood_detail"],
            "geo_precision":        precision,
            "risk_checked_at":      datetime.now(timezone.utc).isoformat(),
            "walkability_score":    score,
            "industrial_zone":      int(ind),
            "industrial_zone_name": ind_name,
            "location_score":       score,
            "location_tier":        tier,
            "scored_at":            datetime.now(timezone.utc).isoformat(),
        })

        e = tier_emoji.get(tier, "")
        flags = " ".join(n for n, v in (("🏗", risk["construction"]),
                                        ("🔊", risk["noise"]),
                                        ("🌊", risk["flood"])) if v)
        log.info(f"  {e} {tier} {score}/100 | Transit: {transit:.0f}m | "
                 f"Amenities: {sum(amenities.values())} | {precision} {flags} | {addr[:40]}")
        scored += 1
        time.sleep(SCRAPE_DELAY_SEC)

    log.info(f"✅ Location scoring done. {scored} scored.")
    return scored


def run_risk_backfill(limit: int = 100, progress_callback=None,
                      market: str | None = None) -> int:
    """Give rows scored before the real risk data existed their noise, flood
    and construction answers. Those rows hold a stored False for each (the old
    stubs' answer), and no record of how precise their geocode was. The
    portal's own map pin is used when the listing has one, as in
    run_location_scoring; otherwise the address is geocoded again to learn the
    precision before anything is judged. The location score and tier were
    computed from the stubs' answers, so they are recomputed from the new
    flags with the stored transit and amenity facts."""
    rows = get_location_rows_missing_risk(limit)
    if market is not None:
        rows = [r for r in rows if (r.get("market") or "sk") == market]
    done = 0
    for i, row in enumerate(rows):
        if progress_callback:
            progress_callback(i + 1, len(rows), (row.get("address_raw") or "")[:50])
        addr = row.get("address_raw") or row.get("district") or ""
        mkt = row.get("market") or "sk"
        if row.get("coords_source") == "listing" and row.get("listing_lat") is not None:
            lat, lng, precision = row["listing_lat"], row["listing_lng"], "street"
        else:
            lat, lng, precision = _geocode(addr, mkt)
            if lat is None:
                lat, lng, precision = row.get("lat"), row.get("lng"), "area"
        if lat is None:
            continue
        risk = _assess(lat, lng, precision, mkt)
        transit = row.get("nearest_transit_m")
        score, tier = compute_score(
            9999.0 if transit is None else transit,
            {"amenities": row.get("amenity_count") or 0},
            bool(risk["construction"]), bool(risk["noise"]), row.get("energy_class"))
        update_location_risk(row["listing_id"], {
            "construction_risk":   _flag(risk["construction"]),
            "construction_detail": risk["construction_detail"],
            "noise_flag":          _flag(risk["noise"]),
            "noise_detail":        risk["noise_detail"],
            "flood_zone":          _flag(risk["flood"]),
            "flood_detail":        risk["flood_detail"],
            "geo_precision":       precision,
            "lat":                 lat,
            "lng":                 lng,
            "location_score":      score,
            "location_tier":       tier,
            "walkability_score":   score,
        })
        done += 1
        time.sleep(1.0)
    return done


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run_location_scoring()

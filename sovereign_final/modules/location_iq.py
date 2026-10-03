"""
modules/location_iq.py — Sovereign Investor Dashboard
Module C: Location IQ — transit, amenities and noise/flood/construction risk.

Geocoding, transit and amenities come from Google when GOOGLE_PLACES_API_KEY
is set, and from OpenStreetMap (Nominatim + Overpass) when it isn't. The risk
flags always come from open data via modules/risk_data — never invented.
"""

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
    get_location_rows_missing_risk, update_location_risk,
)
from modules import risk_data

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL  = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


# ── Geocoding ─────────────────────────────────────────────────────────────────
def geocode_precise(address: str) -> tuple[float | None, float | None, str]:
    """(lat, lng, precision) — precision is "address", "street" or "area"
    (see modules/risk_data). Google when a key is set, else Nominatim."""
    if not GOOGLE_API_KEY:
        return risk_data.geocode_nominatim(address)
    try:
        r = requests.get(GEOCODE_URL, params={
            "address": address + ", Slovakia",
            "key": GOOGLE_API_KEY,
        }, timeout=10)
        data = r.json()
        if data.get("results"):
            top = data["results"][0]
            loc = top["geometry"]["location"]
            return loc["lat"], loc["lng"], risk_data.google_precision(top)
    except Exception as e:
        print(f"    Geocode error: {e}")
    return None, None, ""


def geocode(address: str) -> tuple[float | None, float | None]:
    lat, lng, _ = geocode_precise(address)
    return lat, lng


# ── Places Queries ────────────────────────────────────────────────────────────
def nearest_transit(lat: float, lng: float) -> float:
    if not GOOGLE_API_KEY:
        elements = risk_data.fetch_osm(lat, lng)
        t = risk_data.classify_osm(elements, lat, lng)["nearest_transit_m"] if elements else None
        return 9999.0 if t is None else t
    try:
        r = requests.get(PLACES_URL, params={
            "location": f"{lat},{lng}", "radius": 2000,
            "type": "transit_station", "key": GOOGLE_API_KEY,
        }, timeout=10)
        results = r.json().get("results", [])
        if results:
            rl = results[0]["geometry"]["location"]
            return _haversine(lat, lng, rl["lat"], rl["lng"])
    except Exception as e:
        print(f"    Transit error: {e}")
    return 9999.0


def count_amenities(lat: float, lng: float) -> dict:
    types = {
        "grocery_or_supermarket": "grocery_count",
        "pharmacy":               "pharmacy_count",
        "school":                 "school_count",
    }
    counts = {"grocery_count": 0, "pharmacy_count": 0, "school_count": 0}

    if not GOOGLE_API_KEY:
        elements = risk_data.fetch_osm(lat, lng)
        if elements:
            osm = risk_data.classify_osm(elements, lat, lng)
            counts = {k: osm[k] for k in counts}
        return counts

    for ptype, key in types.items():
        try:
            r = requests.get(PLACES_URL, params={
                "location": f"{lat},{lng}", "radius": AMENITY_RADIUS_METERS,
                "type": ptype, "key": GOOGLE_API_KEY,
            }, timeout=10)
            counts[key] = len(r.json().get("results", []))
            time.sleep(0.3)
        except Exception as e:
            print(f"    Amenity error ({ptype}): {e}")

    return counts


def check_construction(lat: float, lng: float) -> bool | None:
    """Construction site within CONSTRUCTION_RADIUS_M (OpenStreetMap), or None
    when OSM can't be reached. Never a guess: this used to hash coordinates
    into a random 15% flag."""
    elements = risk_data.fetch_osm(lat, lng)
    if elements is None:
        return None
    return risk_data.classify_osm(elements, lat, lng)["construction"]


def check_noise(lat: float, lng: float) -> bool | None:
    """Major road / railway / airport close enough for ≥65 dB Lden
    (OpenStreetMap proxy for the strategic noise maps), or None when OSM can't
    be reached."""
    elements = risk_data.fetch_osm(lat, lng)
    if elements is None:
        return None
    return risk_data.classify_osm(elements, lat, lng)["noise"]


def check_flood(lat: float, lng: float) -> bool | None:
    """Inside the SVP-mapped Q100 flood extent, or None when unknown."""
    return risk_data.check_flood(lat, lng)[0]


def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lng2 - lng1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def is_industrial(district: str) -> tuple[bool, str]:
    key = district.lower().strip()
    for z in INDUSTRIAL_ZONES:
        if z in key:
            return True, z
    return False, ""


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


def run_location_scoring(progress_callback=None, limit: int | None = 200) -> int:
    """Score every PASS listing that has no location row yet.

    With a Google key: Google geocoding, transit and amenities. Without one:
    Nominatim + OpenStreetMap — real data either way (this used to refuse to
    run without a key rather than fabricate coordinates). Risk flags always
    come from modules/risk_data; a flag that can't be determined is stored as
    NULL, and an area-level geocode leaves every risk flag NULL.
    """
    listings = get_unscored_location()
    if not listings:
        print("✅ No listings to score for location.")
        return 0
    # Each listing is a few seconds of polite requests to free services, so a
    # first run over a full backlog is spread over several days.
    if limit:
        listings = listings[:limit]

    provider = "Google" if GOOGLE_API_KEY else "OpenStreetMap"
    print(f"📍 Scoring {len(listings)} locations ({provider})...")
    scored = 0
    tier_emoji = {"PRIME":"⭐","SOLID":"✅","STANDARD":"🟡","POOR":"🔴"}

    for i, row in enumerate(listings):
        lid    = row["id"]
        addr   = row.get("address_raw") or row.get("district") or ""
        energy = row.get("energy_class","UNKNOWN")
        dist   = row.get("district","")

        if progress_callback:
            progress_callback(i + 1, len(listings), addr[:50])

        # The portal's own map pin beats geocoding an address that is often
        # just "Petržalka, Bratislava". Pins are street-level at best (some
        # agencies offset them), so that is the precision claimed for them.
        if row.get("coords_source") == "listing" and row.get("lat") is not None:
            lat, lng, precision = row["lat"], row["lng"], "street"
        else:
            lat, lng, precision = geocode_precise(addr)
        if lat is None:
            print(f"  ⚠️ No geocode: {addr[:50]}")
            continue

        risk = risk_data.assess(lat, lng, precision)
        if GOOGLE_API_KEY:
            transit   = nearest_transit(lat, lng)
            amenities = count_amenities(lat, lng)
        else:
            transit = risk["nearest_transit_m"]
            transit = 9999.0 if transit is None else transit
            amenities = {k: risk[k] or 0 for k in
                         ("grocery_count", "pharmacy_count", "school_count")}
        ind, ind_name = is_industrial(dist)
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
        print(f"  {e} {tier} {score}/100 | Transit: {transit:.0f}m | "
              f"Amenities: {sum(amenities.values())} | {precision} {flags} | {addr[:40]}")
        scored += 1
        time.sleep(SCRAPE_DELAY_SEC)

    print(f"\n✅ Location scoring done. {scored} scored.\n")
    return scored


def run_risk_backfill(limit: int = 100, progress_callback=None) -> int:
    """Give rows scored before the real risk data existed their noise, flood
    and construction answers. Those rows hold a stored False for each (the old
    stubs' answer), and no record of how precise their geocode was, so the
    address is geocoded again to learn that before anything is judged."""
    rows = get_location_rows_missing_risk(limit)
    done = 0
    for i, row in enumerate(rows):
        if progress_callback:
            progress_callback(i + 1, len(rows), (row.get("address_raw") or "")[:50])
        addr = row.get("address_raw") or row.get("district") or ""
        lat, lng, precision = geocode_precise(addr)
        if lat is None:
            lat, lng, precision = row.get("lat"), row.get("lng"), "area"
        if lat is None:
            continue
        risk = risk_data.assess(lat, lng, precision)
        update_location_risk(row["listing_id"], {
            "construction_risk":   _flag(risk["construction"]),
            "construction_detail": risk["construction_detail"],
            "noise_flag":          _flag(risk["noise"]),
            "noise_detail":        risk["noise_detail"],
            "flood_zone":          _flag(risk["flood"]),
            "flood_detail":        risk["flood_detail"],
            "geo_precision":       precision,
        })
        done += 1
        time.sleep(1.0)
    return done


if __name__ == "__main__":
    init_db()
    run_location_scoring()

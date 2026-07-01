"""
modules/location_iq.py — Sovereign Investor Dashboard
Module C: Location IQ — Google Places + noise/construction risk scoring
"""

import time, math, random
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
from database import get_unscored_location, upsert_location, init_db

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL  = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


# ── Geocoding ─────────────────────────────────────────────────────────────────
def geocode(address: str) -> tuple[float | None, float | None]:
    if not GOOGLE_API_KEY:
        return _demo_coords(address)
    try:
        r = requests.get(GEOCODE_URL, params={
            "address": address + ", Slovakia",
            "key": GOOGLE_API_KEY,
        }, timeout=10)
        data = r.json()
        if data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        print(f"    Geocode error: {e}")
    return None, None


def _demo_coords(address: str) -> tuple[float, float]:
    city_coords = {
        "bratislava": (48.1486, 17.1077), "košice":  (48.7164, 21.2611),
        "žilina":     (49.2231, 18.7394), "nitra":   (48.3069, 18.0853),
        "trnava":     (48.3774, 17.5869), "prešov":  (48.9986, 21.2392),
        "banská bystrica": (48.7395, 19.1531),
        "trenčín":    (48.8946, 18.0446), "martin":  (49.0627, 18.9218),
        "poprad":     (49.0594, 20.2981),
    }
    addr_lo = address.lower()
    for city, coords in city_coords.items():
        if city in addr_lo:
            rng = random.Random(hash(address))
            return (coords[0] + rng.uniform(-0.025, 0.025),
                    coords[1] + rng.uniform(-0.025, 0.025))
    rng = random.Random(hash(address))
    return 48.1486 + rng.uniform(-0.5, 0.5), 17.1077 + rng.uniform(-0.5, 0.5)


# ── Places Queries ────────────────────────────────────────────────────────────
def nearest_transit(lat: float, lng: float) -> float:
    if not GOOGLE_API_KEY:
        return _demo_float(lat, lng, 100, 1200)
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
        rng = random.Random(int(lat * 100 + lng * 100))
        for k in counts:
            counts[k] = rng.randint(0, 4)
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


def check_construction(lat: float, lng: float) -> bool:
    """
    TODO: Wire to Slovak planning portal (egov.sk) when API is available.
    Until then: no data source = no flag. (Previously this hashed the
    coordinates into a random 15% construction flag that docked real
    listings' deal scores — never fabricate risk.)
    """
    return False


def check_noise(lat: float, lng: float) -> bool:
    """
    TODO: Wire to enviroportal.sk noise map WMS layer.
    Until then: no data source = no flag (was a fabricated 20% random flag
    that forced POOR tiers on real listings).
    """
    return False


def _demo_float(lat, lng, lo, hi) -> float:
    return random.Random(int(lat * 1000 + lng * 1000)).uniform(lo, hi)


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
def run_location_scoring(progress_callback=None) -> int:
    # Without a Google key every input here is fabricated: geocode() jitters a
    # city centre by up to ~2.5 km (so the satellite view would show the wrong
    # spot as "the property"), and the random noise/construction flags would
    # penalise real listings' deal scores. Skip honestly instead — the deal
    # score already rescales when location data is absent, and the "Demo data"
    # toggle covers the demo experience with fixed coordinates.
    if not GOOGLE_API_KEY:
        print("ℹ️  Location IQ skipped — no GOOGLE_PLACES_API_KEY set "
              "(refusing to score real listings with fabricated coordinates).")
        return 0

    listings = get_unscored_location()
    if not listings:
        print("✅ No listings to score for location.")
        return 0

    print(f"📍 Scoring {len(listings)} locations...")
    scored = 0
    tier_emoji = {"PRIME":"⭐","SOLID":"✅","STANDARD":"🟡","POOR":"🔴"}

    for i, row in enumerate(listings):
        lid    = row["id"]
        addr   = row.get("address_raw","")
        energy = row.get("energy_class","UNKNOWN")
        dist   = row.get("district","")

        if progress_callback:
            progress_callback(i + 1, len(listings), addr[:50])

        lat, lng = geocode(addr)
        if lat is None:
            print(f"  ⚠️ No geocode: {addr[:50]}")
            continue

        transit      = nearest_transit(lat, lng)
        amenities    = count_amenities(lat, lng)
        construction = check_construction(lat, lng)
        noise        = check_noise(lat, lng)
        ind, ind_name = is_industrial(dist)
        score, tier  = compute_score(transit, amenities, construction, noise, energy)

        upsert_location({
            "listing_id":           lid,
            "lat":                  lat,
            "lng":                  lng,
            "nearest_transit_m":    round(transit, 1),
            "amenity_count":        sum(amenities.values()),
            "grocery_count":        amenities["grocery_count"],
            "pharmacy_count":       amenities["pharmacy_count"],
            "school_count":         amenities["school_count"],
            "construction_risk":    int(construction),
            "noise_flag":           int(noise),
            "flood_zone":           0,
            "walkability_score":    score,
            "industrial_zone":      int(ind),
            "industrial_zone_name": ind_name,
            "location_score":       score,
            "location_tier":        tier,
            "scored_at":            datetime.now(timezone.utc).isoformat(),
        })

        e = tier_emoji.get(tier, "")
        print(f"  {e} {tier} {score}/100 | Transit: {transit:.0f}m | "
              f"Amenities: {sum(amenities.values())} | {addr[:40]}")
        scored += 1
        time.sleep(SCRAPE_DELAY_SEC)

    print(f"\n✅ Location scoring done. {scored} scored.\n")
    return scored


if __name__ == "__main__":
    init_db()
    run_location_scoring()

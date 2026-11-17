"""
modules/travel.py — how long it takes from each flat to a point you choose
(work, a university, a station), on foot, by car or by public transport.
A straight line misleads across a river, a motorway or a hill.

  walk / drive — openrouteservice (ORS_API_KEY, free: openrouteservice.org →
                 sign up → request a token) when set; otherwise the public
                 OSRM servers run by FOSSGIS (routing.openstreetmap.de), free
                 and keyless but meant for light use: requests are batched
                 and paused, and every answer is kept (travel_times).
  transit      — Google Routes API (GOOGLE_ROUTES_API_KEY, with the Routes
                 API enabled in Google Cloud); no free keyless service plans
                 public transport for both countries.

Times are in minutes, door to door as the router sees it; a missing time
means the router found no way.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import database as _db

log = logging.getLogger(__name__)

MODES = {"walk": "On foot", "drive": "By car", "transit": "Public transport"}
OSRM = {"walk": "https://routing.openstreetmap.de/routed-foot/table/v1/foot/",
        "drive": "https://routing.openstreetmap.de/routed-car/table/v1/driving/"}
ORS = "https://api.openrouteservice.org/v2/matrix/{profile}"
ORS_PROFILE = {"walk": "foot-walking", "drive": "driving-car"}
GOOGLE = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
BATCH = {"osrm": 80, "ors": 200, "google": 50}
PAUSE_S = 1.0
TIMEOUT_S = 40


def available_modes() -> list[str]:
    return ["walk", "drive"] + (["transit"] if os.getenv("GOOGLE_ROUTES_API_KEY") else [])


def provider(mode: str) -> str:
    if mode == "transit":
        return "google"
    return "ors" if os.getenv("ORS_API_KEY") else "osrm"


def _ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS travel_times (
        origin TEXT NOT NULL, target TEXT NOT NULL, mode TEXT NOT NULL, minutes REAL,
        provider TEXT, computed_at TEXT, PRIMARY KEY (origin, target, mode))""")


def _key(lat: float, lng: float) -> str:
    return f"{lat:.5f},{lng:.5f}"


def _osrm(target, chunk, mode, post=None, get=None):
    import requests
    get = get or requests.get
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in [target] + chunk)
    r = get(OSRM[mode] + coords, timeout=TIMEOUT_S, params={
        "sources": ";".join(str(i) for i in range(1, len(chunk) + 1)), "destinations": "0",
        "annotations": "duration"})
    r.raise_for_status()
    return [row[0] / 60 if row and row[0] is not None else None for row in r.json()["durations"]]


def _ors(target, chunk, mode, post=None, get=None):
    import requests
    post = post or requests.post
    locs = [[target[1], target[0]]] + [[lng, lat] for lat, lng in chunk]
    r = post(ORS.format(profile=ORS_PROFILE[mode]), timeout=TIMEOUT_S,
             headers={"Authorization": os.environ["ORS_API_KEY"]},
             json={"locations": locs, "destinations": [0], "metrics": ["duration"],
                   "sources": list(range(1, len(locs)))})
    r.raise_for_status()
    return [row[0] / 60 if row and row[0] is not None else None for row in r.json()["durations"]]


def _google(target, chunk, mode, post=None, get=None):
    import requests
    post = post or requests.post

    def wp(lat, lng):
        return {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}}
    r = post(GOOGLE, timeout=TIMEOUT_S,
             headers={"X-Goog-Api-Key": os.environ["GOOGLE_ROUTES_API_KEY"],
                      "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition"},
             json={"origins": [wp(lat, lng) for lat, lng in chunk], "destinations": [wp(*target)],
                   "travelMode": "TRANSIT"})
    r.raise_for_status()
    out = [None] * len(chunk)
    for el in r.json():
        if el.get("condition") == "ROUTE_EXISTS" and el.get("duration"):
            out[el["originIndex"]] = float(el["duration"].rstrip("s")) / 60
    return out


_CALL = {"osrm": _osrm, "ors": _ors, "google": _google}


def travel_times(target: tuple[float, float], origins: dict[str, tuple[float, float]],
                 mode: str, post=None, get=None) -> dict[str, float | None]:
    """{origin id: minutes to `target`} for each origin (lat, lng); answers
    already kept are not asked again."""
    if mode not in MODES:
        raise ValueError(mode)
    who = provider(mode)
    tkey = _key(*target)
    conn = _db.get_conn()
    try:
        _ensure(conn)
        known = {r[0]: r[1] for r in conn.execute(
            "SELECT origin, minutes FROM travel_times WHERE target=? AND mode=?", (tkey, mode))}
    finally:
        conn.close()
    out, todo = {}, []
    for oid, (lat, lng) in origins.items():
        k = _key(lat, lng)
        if k in known:
            out[oid] = known[k]
        else:
            todo.append((oid, (lat, lng)))
    step = BATCH[who]
    for i in range(0, len(todo), step):
        chunk = todo[i:i + step]
        try:
            mins = _CALL[who](target, [p for _, p in chunk], mode, post=post, get=get)
        except Exception as e:
            log.warning(f"Travel times ({who}, {mode}) failed: {type(e).__name__}: {e}")
            break
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = _db.get_conn()
        try:
            _ensure(conn)
            for (oid, (lat, lng)), m in zip(chunk, mins):
                out[oid] = round(m, 1) if m is not None else None
                conn.execute("INSERT OR REPLACE INTO travel_times VALUES (?,?,?,?,?,?)",
                             (_key(lat, lng), tkey, mode, out[oid], who, now))
            conn.commit()
        finally:
            conn.close()
        if i + step < len(todo):
            time.sleep(PAUSE_S)
    return out

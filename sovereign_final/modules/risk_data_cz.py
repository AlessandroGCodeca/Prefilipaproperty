"""
modules/risk_data_cz.py — Czech flood and noise sources for Location IQ.

modules/risk_data asks OpenStreetMap about construction and noise sources in
both markets; the flood map and the official noise map are national:

  flood  the Q100 flood areas and active zones the water authorities (the
         Povodí state enterprises, through VÚV T. G. M.) publish, as served
         by ÚÚR's national ÚAP map service — layer 82 "T0601 Záplavová území
         Q100 a QA" (markets.CZ.flood). VÚV calls the polygons indicative;
         the binding line is the local water authority's. An ArcGIS identify
         at the flat's point: a hit is "inside", none is "outside the mapped
         area", no answer is unknown — never a guessed "no".
  noise  the 2022 strategic noise map of main roads (Ministry of Health,
         prepared by Zdravotní ústav Ostrava: Ldvn in 5 dB bands, roads with
         over 3 million vehicles a year — markets.CZ.noise). Read with an
         ImageServer identify; a reading of 65 dB or more flags the flat,
         whatever the OpenStreetMap proxy said. A cell outside the mapped
         roads, or a value that isn't a decibel figure, leaves the proxy's
         answer as it was.

Neither host could be reached from here: the layer number, the REST path and
the value encoding are as published (via search) — UNVERIFIED until a live
call answers. Both fail soft.
"""

from __future__ import annotations

import logging

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger(__name__)

USER_AGENT = "SovereignInvestorDashboard/1.0 (Czech flood and noise check)"
NOISE_LIMIT_DB = 65.0
_layers_checked: dict[str, tuple[bool, str]] = {}


def _profile():
    import markets
    return markets.get("cz")


def _flood_layers_usable(url: str, layers: str) -> tuple[bool, str]:
    """Once per process: the flood layer ids name area (or group) layers —
    a line layer or a missing id would answer "outside" everywhere."""
    key = f"{url}|{layers}"
    if key in _layers_checked:
        return _layers_checked[key]
    base = url.rsplit("/identify", 1)[0]
    verdict = (True, "")
    for layer_id in [x.strip() for x in layers.split(",") if x.strip()]:
        try:
            r = requests.get(f"{base}/{layer_id}", params={"f": "json"}, timeout=20,
                             headers={"User-Agent": USER_AGENT})
            meta = r.json() if r.status_code == 200 else {}
        except Exception as e:
            return False, f"flood service unreachable ({type(e).__name__})"
        if not isinstance(meta, dict) or not meta.get("name") or "error" in meta:
            verdict = (False, f"flood layer {layer_id} not found — check CZ_FLOOD_LAYER_IDS")
            break
        geom = meta.get("geometryType") or ""
        if geom and geom != "esriGeometryPolygon":
            verdict = (False, f"flood layer {layer_id} is {geom}, not areas — "
                              f"check CZ_FLOOD_LAYER_IDS")
            break
    _layers_checked[key] = verdict
    return verdict


def classify_flood(payload) -> tuple[bool | None, str]:
    if not isinstance(payload, dict) or "error" in payload or "results" not in payload:
        return None, "flood service error"
    hits = [res.get("layerName") or "flood area" for res in payload.get("results") or []
            if isinstance(res, dict)]
    if hits:
        return True, (f"inside {', '.join(dict.fromkeys(hits))} (ÚÚR / VÚV flood areas — "
                      f"indicative)")
    return False, "outside the mapped Q100 flood areas (ÚÚR / VÚV — indicative)"


def check_flood(lat: float, lng: float) -> tuple[bool | None, str]:
    flood = _profile().flood or {}
    url, layers = flood.get("url"), str(flood.get("layers") or "")
    if not url or not layers:
        return None, "no Czech flood source configured"
    ok, why = _flood_layers_usable(url, layers)
    if not ok:
        return None, why
    d = 0.002
    params = {"geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326,
              "layers": f"all:{layers}", "tolerance": 0,
              "mapExtent": f"{lng - d},{lat - d},{lng + d},{lat + d}",
              "imageDisplay": "400,400,96", "returnGeometry": "false", "f": "json"}
    try:
        r = requests.get(url, params=params, timeout=20, headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None, f"flood service HTTP {r.status_code}"
        return classify_flood(r.json())
    except Exception as e:
        return None, f"flood service unreachable ({type(e).__name__})"


def noise_db(payload) -> float | None:
    """The Ldvn reading of an ImageServer identify, in dB — or None for
    NoData or a value that is not a decibel figure (a class code)."""
    if not isinstance(payload, dict):
        return None
    try:
        v = float(str(payload.get("value", "")).split(",")[0].strip())
    except ValueError:
        return None
    return v if 35.0 <= v <= 95.0 else None


def refine_noise(lat: float, lng: float, osm: dict) -> dict:
    """Overrides for risk_data.assess: the official map's ≥65 dB reading."""
    noise = _profile().noise or {}
    url = noise.get("url")
    if not url:
        return {}
    params = {"geometry": f'{{"x":{lng},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
              "geometryType": "esriGeometryPoint", "returnGeometry": "false",
              "returnCatalogItems": "false", "f": "json"}
    try:
        r = requests.get(url, params=params, timeout=20, headers={"User-Agent": USER_AGENT})
        db = noise_db(r.json()) if r.status_code == 200 else None
    except Exception as e:
        log.info(f"  noise map unreachable ({type(e).__name__})")
        return {}
    if db is None or db < NOISE_LIMIT_DB:
        return {}
    return {"noise": True,
            "noise_detail": f"{db:.0f}+ dB Ldvn on the 2022 strategic noise map (main roads)"}

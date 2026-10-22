"""Regression tests for the third review, geo-enrich area: the nearest transit
stop with a Google key, and the precision of a Nominatim address point.

Synthetic coordinates and payloads only; every HTTP call is stubbed, so no
request leaves the test.
"""

from types import SimpleNamespace

import pytest

import modules.location_iq as liq
from config import TRANSIT_WALK_METERS, POINTS_TRANSIT
from modules import risk_data as rd

FLAT = (48.1486, 17.1077)
FAR_STATION = {"name": "Test main station",
               "geometry": {"location": {"lat": 48.1585, "lng": 17.1067}}}
NEAR_STOP = {"name": "Test tram stop",
             "geometry": {"location": {"lat": 48.1490, "lng": 17.1080}}}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _stub_places(monkeypatch, results, calls=None):
    """Replace location_iq's requests with one that answers Nearby Search
    with `results`, in the order given (Google's prominence order)."""
    def get(url, params=None, timeout=None, **kw):
        if calls is not None:
            calls.append((url, dict(params or {})))
        assert url == liq.PLACES_URL, f"unexpected request to {url}"
        return _Resp({"results": results})
    monkeypatch.setattr(liq, "GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(liq, "requests", SimpleNamespace(get=get))


def _dist(point):
    loc = point["geometry"]["location"]
    return liq._haversine(*FLAT, loc["lat"], loc["lng"])


# ── #15: with a Google key the nearest stop is the nearest by distance ────────
class TestGoogleNearestTransit:
    def test_nearest_result_wins_over_the_more_prominent_first_one(self, monkeypatch):
        _stub_places(monkeypatch, [FAR_STATION, NEAR_STOP])
        t = liq.nearest_transit(*FLAT)
        assert t == pytest.approx(_dist(NEAR_STOP))
        assert t < TRANSIT_WALK_METERS < _dist(FAR_STATION)

    def test_order_of_results_does_not_matter(self, monkeypatch):
        _stub_places(monkeypatch, [NEAR_STOP, FAR_STATION])
        a = liq.nearest_transit(*FLAT)
        _stub_places(monkeypatch, [FAR_STATION, NEAR_STOP])
        assert liq.nearest_transit(*FLAT) == pytest.approx(a)

    def test_single_result_is_still_measured(self, monkeypatch):
        _stub_places(monkeypatch, [FAR_STATION])
        assert liq.nearest_transit(*FLAT) == pytest.approx(_dist(FAR_STATION))

    def test_result_without_a_location_is_skipped(self, monkeypatch):
        broken = {"name": "Test stop without geometry"}
        bad_coords = {"name": "Test stop", "geometry": {"location": {"lat": None, "lng": 17.1}}}
        _stub_places(monkeypatch, [broken, bad_coords, FAR_STATION, NEAR_STOP])
        assert liq.nearest_transit(*FLAT) == pytest.approx(_dist(NEAR_STOP))

    def test_no_results_is_no_stop(self, monkeypatch):
        _stub_places(monkeypatch, [])
        assert liq.nearest_transit(*FLAT) == 9999.0

    def test_only_unusable_results_is_no_stop(self, monkeypatch):
        _stub_places(monkeypatch, [{"name": "Test stop without geometry"}])
        assert liq.nearest_transit(*FLAT) == 9999.0

    def test_request_error_fails_soft(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("offline")
        monkeypatch.setattr(liq, "GOOGLE_API_KEY", "test-key")
        monkeypatch.setattr(liq, "requests", SimpleNamespace(get=boom))
        assert liq.nearest_transit(*FLAT) == 9999.0

    def test_request_itself_is_unchanged(self, monkeypatch):
        calls = []
        _stub_places(monkeypatch, [NEAR_STOP], calls)
        liq.nearest_transit(*FLAT)
        assert len(calls) == 1
        url, params = calls[0]
        assert url == liq.PLACES_URL
        assert params["radius"] == 2000 and params["type"] == "transit_station"
        assert params["location"] == f"{FLAT[0]},{FLAT[1]}"

    def test_scoring_run_stores_the_nearest_stop_and_its_points(self, monkeypatch):
        """End to end with a Google key: the stop at the door earns the
        transit points that the far, prominent station would have cost."""
        _stub_places(monkeypatch, [FAR_STATION, NEAR_STOP])
        monkeypatch.setattr(liq, "SCRAPE_DELAY_SEC", 0)
        monkeypatch.setattr(liq, "get_unscored_location", lambda: [
            {"id": "t1", "address_raw": "Testová 1, Testovo",
             "energy_class": "B", "district": "Testovo"}])
        monkeypatch.setattr(liq, "_geocode", lambda addr, mkt: (*FLAT, "address"))
        monkeypatch.setattr(liq, "_assess", lambda lat, lng, p, mkt: {
            "nearest_transit_m": None, "grocery_count": None, "pharmacy_count": None,
            "school_count": None, "construction": False, "construction_detail": "none",
            "noise": False, "noise_detail": "none", "flood": False,
            "flood_detail": "outside"})
        monkeypatch.setattr(liq, "count_amenities", lambda lat, lng: {
            "grocery_count": 2, "pharmacy_count": 1, "school_count": 0})
        stored = []
        monkeypatch.setattr(liq, "upsert_location", stored.append)
        assert liq.run_location_scoring() == 1
        row = stored[0]
        assert row["nearest_transit_m"] == round(_dist(NEAR_STOP), 1)
        far_score, _ = liq.compute_score(_dist(FAR_STATION),
                                         {"grocery_count": 2, "pharmacy_count": 1,
                                          "school_count": 0}, False, False, "B")
        assert row["location_score"] == far_score + POINTS_TRANSIT


# ── #17: a Nominatim address point labelled "place" is an address ─────────────
class TestNominatimAddressPoint:
    @pytest.mark.parametrize("res", [
        {"category": "place", "type": "house", "addresstype": "place", "place_rank": 30},
        {"type": "house", "addresstype": "place"},
        {"type": "House", "addresstype": "Place"},
    ])
    def test_place_house_is_address(self, res):
        assert rd.nominatim_precision(res) == "address"

    @pytest.mark.parametrize("res,prec", [
        # unchanged answers around the fix
        ({"addresstype": "building"}, "address"),
        ({"addresstype": "house_number"}, "address"),
        ({"type": "house"}, "address"),
        ({"addresstype": "road"}, "street"),
        ({"addresstype": "suburb"}, "area"),
        ({"addresstype": "city"}, "area"),
        # "place" with a type that is not an address stays an area
        ({"addresstype": "place", "type": "locality"}, "area"),
        ({"addresstype": "place"}, "area"),
        # a POI is not upgraded by its rank alone
        ({"category": "amenity", "type": "cafe", "addresstype": "amenity",
          "place_rank": 30}, "area"),
    ])
    def test_neighbouring_answers_unchanged(self, res, prec):
        assert rd.nominatim_precision(res) == prec

    def test_geocoded_address_point_gets_its_risk_flags_judged(self, monkeypatch):
        """No Google key, no portal pin: the address point geocode is precise
        enough for construction, noise and flood to be answered."""
        payload = [{"lat": "48.1500", "lon": "17.1300", "category": "place",
                    "type": "house", "addresstype": "place", "place_rank": 30}]
        sent = []

        def get(url, params=None, timeout=None, headers=None):
            sent.append(params)
            return _Resp(payload)
        monkeypatch.setattr(rd, "requests", SimpleNamespace(get=get))
        monkeypatch.setattr(rd, "_last_nominatim", float("-inf"))
        lat, lng, prec = rd.geocode_nominatim("Testová 1, Testovo")
        assert (lat, lng, prec) == (48.15, 17.13, "address")
        assert sent[0]["countrycodes"] == "sk"

        monkeypatch.setattr(rd, "check_flood", lambda la, ln: (True, "inside Q100"))
        quiet = [{"type": "node", "lat": lat + 0.001, "lon": lng,
                  "tags": {"highway": "bus_stop"}}]
        out = rd.assess(lat, lng, prec, osm_elements=quiet)
        assert (out["construction"], out["noise"], out["flood"]) == (False, False, True)
        assert "too vague" not in (out["flood_detail"] or "")

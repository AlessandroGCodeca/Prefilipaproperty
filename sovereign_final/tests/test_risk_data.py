"""Tests for modules/risk_data — real construction / noise / flood answers.

No network: Overpass, Nominatim and the SVP flood service are replaced by
fixture payloads shaped like their real JSON answers.
"""

import pytest

from config import (
    CONSTRUCTION_RADIUS_M, NOISE_PRIMARY_M, NOISE_MAJOR_ROAD_M, AMENITY_RADIUS_METERS,
)
from modules import risk_data as rd

LAT, LNG = 48.1500, 17.1300


def _node(tags, lat=LAT, lon=LNG):
    return {"type": "node", "lat": lat, "lon": lon, "tags": tags}


def _way(tags, lat=LAT, lon=LNG):
    return {"type": "way", "center": {"lat": lat, "lon": lon}, "tags": tags}


class TestClassifyOsm:
    def test_quiet_street(self):
        out = rd.classify_osm([_node({"shop": "supermarket"}),
                               _node({"amenity": "pharmacy"}),
                               _way({"amenity": "school"})], LAT, LNG)
        assert out["construction"] is False and out["noise"] is False
        assert (out["grocery_count"], out["pharmacy_count"], out["school_count"]) == (1, 1, 1)
        assert out["nearest_transit_m"] is None

    def test_construction_site(self):
        out = rd.classify_osm([_way({"landuse": "construction", "name": "Nivy Tower"})], LAT, LNG)
        assert out["construction"] is True
        assert "Nivy Tower" in out["construction_detail"]
        assert str(CONSTRUCTION_RADIUS_M) in out["construction_detail"]

    @pytest.mark.parametrize("tags,needle", [
        ({"highway": "primary", "name": "Bajkalská"}, f"primary road ≤{NOISE_PRIMARY_M} m (Bajkalská)"),
        ({"highway": "motorway", "ref": "D1"}, f"motorway/trunk ≤{NOISE_MAJOR_ROAD_M} m (D1)"),
        ({"railway": "rail", "name": "Trať 120"}, "railway"),
        ({"aeroway": "aerodrome", "iata": "BTS", "name": "Letisko M. R. Štefánika"}, "airport"),
    ])
    def test_noise_sources(self, tags, needle):
        out = rd.classify_osm([_way(tags)], LAT, LNG)
        assert out["noise"] is True and needle in out["noise_detail"]

    def test_tram_stop_is_transit_not_noise(self):
        out = rd.classify_osm([_node({"railway": "tram_stop"}, lat=LAT + 0.002)], LAT, LNG)
        assert out["noise"] is False
        assert out["nearest_transit_m"] == pytest.approx(222, abs=3)

    def test_nearest_of_several_stops(self):
        out = rd.classify_osm([_node({"highway": "bus_stop"}, lat=LAT + 0.004),
                               _node({"public_transport": "platform"}, lat=LAT + 0.001)], LAT, LNG)
        assert out["nearest_transit_m"] == pytest.approx(111, abs=2)


class TestQuery:
    def test_query_asks_each_radius(self):
        q = rd.overpass_query(LAT, LNG)
        assert f"around:{CONSTRUCTION_RADIUS_M},48.150000,17.130000" in q
        assert f'around:{NOISE_PRIMARY_M},48.150000,17.130000)["highway"="primary"]' in q
        assert f"around:{AMENITY_RADIUS_METERS}" in q
        assert '[!"service"]' in q       # sidings and yards are not main lines


class TestFlood:
    def test_inside_the_mapped_extent(self):
        flood, detail = rd.classify_flood({"results": [
            {"layerId": 24, "layerName": "Hranica záplavy Q100", "attributes": {"OBJECTID": 7}}]})
        assert flood is True and "Q100" in detail

    def test_outside(self):
        assert rd.classify_flood({"results": []})[0] is False

    def test_raster_nodata_is_outside(self):
        assert rd.classify_flood({"results": [
            {"layerName": "Hladina Q100", "attributes": {"Pixel Value": "NoData"}}]})[0] is False

    def test_service_error_is_unknown(self):
        assert rd.classify_flood({"error": {"code": 400}})[0] is None

    def test_identify_params(self):
        p = rd.flood_identify_params(LAT, LNG)
        assert p["geometry"] == f"{LNG},{LAT}" and p["sr"] == 4326
        assert p["layers"].startswith("all:") and p["tolerance"] == 0


class TestGeocodePrecision:
    @pytest.mark.parametrize("res,prec", [
        ({"addresstype": "building"}, "address"),
        ({"addresstype": "road"}, "street"),
        ({"addresstype": "suburb"}, "area"),
        ({"addresstype": "city"}, "area"),
    ])
    def test_nominatim(self, res, prec):
        assert rd.nominatim_precision(res) == prec

    @pytest.mark.parametrize("res,prec", [
        ({"geometry": {"location_type": "ROOFTOP"}, "types": ["street_address"]}, "address"),
        ({"geometry": {"location_type": "GEOMETRIC_CENTER"}, "types": ["route"]}, "street"),
        ({"geometry": {"location_type": "APPROXIMATE"}, "types": ["sublocality"]}, "area"),
    ])
    def test_google(self, res, prec):
        assert rd.google_precision(res) == prec


class TestAssess:
    NOISY = [_way({"highway": "primary", "name": "Bajkalská"}),
             _node({"highway": "bus_stop"}, lat=LAT + 0.001)]

    def test_precise_address_gets_every_answer(self, monkeypatch):
        monkeypatch.setattr(rd, "check_flood", lambda la, ln: (False, "outside"))
        out = rd.assess(LAT, LNG, "address", osm_elements=self.NOISY)
        assert (out["construction"], out["noise"], out["flood"]) == (False, True, False)
        assert out["nearest_transit_m"] == pytest.approx(111, abs=2)

    def test_area_geocode_judges_nothing(self, monkeypatch):
        monkeypatch.setattr(rd, "check_flood",
                            lambda la, ln: pytest.fail("asked about a centroid"))
        out = rd.assess(LAT, LNG, "area", osm_elements=self.NOISY)
        assert (out["construction"], out["noise"], out["flood"]) == (None, None, None)
        assert "too vague" in out["noise_detail"]
        assert out["nearest_transit_m"] is not None     # area facts still useful

    def test_osm_down_is_unknown(self, monkeypatch):
        monkeypatch.setattr(rd, "fetch_osm", lambda la, ln: None)
        monkeypatch.setattr(rd, "check_flood", lambda la, ln: (None, "unreachable"))
        out = rd.assess(LAT, LNG, "address")
        assert (out["construction"], out["noise"], out["flood"]) == (None, None, None)
        assert out["osm_ok"] is False


class TestRiskBackfill:
    def test_old_rows_get_real_answers(self, full_db, monkeypatch):
        import database as db
        import modules.location_iq as liq
        from tests.conftest import make_listing
        db.upsert_listing(make_listing("a", lv_status="PASS", address_raw="Miletičova 1, Bratislava"))
        c = full_db()
        c.execute("UPDATE listings SET lv_status='PASS'")
        c.execute("INSERT INTO location_scores (listing_id, lat, lng, construction_risk, "
                  "noise_flag, flood_zone) VALUES ('a', 48.15, 17.13, 0, 0, 0)")
        c.commit()
        c.close()
        monkeypatch.setattr(liq, "geocode_precise", lambda a: (48.1501, 17.1301, "address"))
        monkeypatch.setattr(liq.risk_data, "assess", lambda la, ln, p: {
            "construction": True, "construction_detail": "1 within 300 m",
            "noise": None, "noise_detail": "OSM unreachable",
            "flood": False, "flood_detail": "outside"})
        monkeypatch.setattr(liq.time, "sleep", lambda s: None)
        assert liq.run_risk_backfill() == 1
        c = full_db()
        row = dict(c.execute("SELECT * FROM location_scores WHERE listing_id='a'").fetchone())
        c.close()
        assert (row["construction_risk"], row["noise_flag"], row["flood_zone"]) == (1, None, 0)
        assert row["geo_precision"] == "address" and row["risk_checked_at"]
        assert db.get_location_rows_missing_risk() == []

    @staticmethod
    def _old_row(full_db, lv_status="PASS", pin=None, score=80, tier="PRIME"):
        """A listing with a location row from the stub era: every risk flag a
        stored 0, no risk_checked_at, a score that counted both 'clear's."""
        import database as db
        from tests.conftest import make_listing
        db.upsert_listing(make_listing("a", address_raw="Miletičova 1, Bratislava"))
        c = full_db()
        c.execute("UPDATE listings SET lv_status=?", (lv_status,))
        if pin:
            c.execute("UPDATE listings SET lat=?, lng=?, coords_source='listing'", pin)
        c.execute("INSERT INTO location_scores (listing_id, lat, lng, nearest_transit_m, "
                  "amenity_count, construction_risk, noise_flag, flood_zone, "
                  "location_score, location_tier, walkability_score) "
                  "VALUES ('a', 48.15, 17.13, 300, 5, 0, 0, 0, ?, ?, ?)",
                  (score, tier, score))
        c.commit()
        c.close()

    @staticmethod
    def _risk(construction=False, noise=False, flood=False):
        return lambda la, ln, p: {
            "construction": construction, "construction_detail": "",
            "noise": noise, "noise_detail": "", "flood": flood, "flood_detail": ""}

    def test_unverified_listings_are_backfilled(self, full_db, monkeypatch):
        # The location step scores UNVERIFIED listings too, so their stub-era
        # rows need real answers as much as PASS ones do.
        import database as db
        import modules.location_iq as liq
        self._old_row(full_db, lv_status="UNVERIFIED")
        assert [r["listing_id"] for r in db.get_location_rows_missing_risk()] == ["a"]
        monkeypatch.setattr(liq, "geocode_precise", lambda a: (48.1501, 17.1301, "address"))
        monkeypatch.setattr(liq.risk_data, "assess", self._risk())
        monkeypatch.setattr(liq.time, "sleep", lambda s: None)
        assert liq.run_risk_backfill() == 1
        assert db.get_location_rows_missing_risk() == []

    def test_rejected_listings_are_not_backfilled(self, full_db):
        import database as db
        self._old_row(full_db, lv_status="REJECTED")
        assert db.get_location_rows_missing_risk() == []

    def test_portal_pin_beats_a_geocode(self, full_db, monkeypatch):
        import modules.location_iq as liq
        self._old_row(full_db, pin=(48.1601, 17.1401))
        monkeypatch.setattr(liq, "geocode_precise",
                            lambda a: pytest.fail("geocoded despite the portal's pin"))
        seen = []

        def assess(la, ln, p):
            seen.append((la, ln, p))
            return self._risk()(la, ln, p)
        monkeypatch.setattr(liq.risk_data, "assess", assess)
        monkeypatch.setattr(liq.time, "sleep", lambda s: None)
        assert liq.run_risk_backfill() == 1
        assert seen == [(48.1601, 17.1401, "street")]
        c = full_db()
        row = dict(c.execute("SELECT lat, lng, geo_precision FROM location_scores").fetchone())
        c.close()
        assert row == {"lat": 48.1601, "lng": 17.1401, "geo_precision": "street"}

    def test_score_and_tier_follow_the_new_flags(self, full_db, monkeypatch):
        # Stub era: transit 300 m (+30), 5 amenities (+20), no construction
        # (+20), no noise (+20) → 90 PRIME. A real noise source makes it POOR
        # and takes the noise points away.
        import modules.location_iq as liq
        self._old_row(full_db, score=90, tier="PRIME")
        monkeypatch.setattr(liq, "geocode_precise", lambda a: (48.1501, 17.1301, "address"))
        monkeypatch.setattr(liq.risk_data, "assess", self._risk(noise=True))
        monkeypatch.setattr(liq.time, "sleep", lambda s: None)
        assert liq.run_risk_backfill() == 1
        c = full_db()
        row = dict(c.execute("SELECT location_score, location_tier, walkability_score, "
                             "noise_flag FROM location_scores").fetchone())
        c.close()
        assert row == {"location_score": 70, "location_tier": "POOR",
                       "walkability_score": 70, "noise_flag": 1}

    def test_unknown_flags_keep_the_points(self, full_db, monkeypatch):
        # Unknown (None) is not a finding, as in run_location_scoring.
        import modules.location_iq as liq
        self._old_row(full_db, score=90, tier="PRIME")
        monkeypatch.setattr(liq, "geocode_precise", lambda a: (48.1501, 17.1301, "address"))
        monkeypatch.setattr(liq.risk_data, "assess", self._risk(construction=None, noise=None))
        monkeypatch.setattr(liq.time, "sleep", lambda s: None)
        liq.run_risk_backfill()
        c = full_db()
        row = dict(c.execute("SELECT location_score, location_tier FROM location_scores").fetchone())
        c.close()
        assert row == {"location_score": 90, "location_tier": "PRIME"}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


class TestServiceGuards:
    def test_overpass_timeout_is_no_answer(self, monkeypatch):
        monkeypatch.setattr(rd.requests, "post", lambda *a, **k: _Resp(
            {"elements": [], "remark": "runtime error: Query timed out in \"query\""}))
        assert rd.fetch_osm(LAT, LNG) is None

    def test_overpass_answer(self, monkeypatch):
        monkeypatch.setattr(rd.requests, "post", lambda *a, **k: _Resp(
            {"elements": [_node({"highway": "bus_stop"})]}))
        assert len(rd.fetch_osm(LAT, LNG)) == 1

    @pytest.mark.parametrize("meta,ok", [
        ({"name": "Hranica záplavy Q100", "geometryType": "esriGeometryPolygon"}, True),
        ({"name": "Q100 raster", "type": "Raster Layer"}, True),
        ({"name": "Záplavová čiara Q100", "geometryType": "esriGeometryPolyline"}, False),
        ({"error": {"code": 400, "message": "Invalid layer"}}, False),
    ])
    def test_flood_layer_must_be_areas(self, monkeypatch, meta, ok):
        monkeypatch.setattr(rd, "_flood_layers_checked", None)
        monkeypatch.setattr(rd.requests, "get", lambda *a, **k: _Resp(meta))
        assert rd.flood_layers_usable()[0] is ok

    def test_a_line_layer_makes_flood_unknown_not_outside(self, monkeypatch):
        monkeypatch.setattr(rd, "_flood_layers_checked",
                            (False, "flood layer 3 is esriGeometryPolyline"))
        flood, detail = rd.check_flood(LAT, LNG)
        assert flood is None and "Polyline" in detail

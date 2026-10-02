"""Tests for scraper/geo.py and the scrapers' use of it: a listing's own map
pin, which the LV debt filter resolves to the building parcel under it."""

import json

import pytest

from scraper.geo import as_pin, pin_from_item, pin_from_ld, pin_from_meta


class TestAsPin:
    def test_point_in_slovakia(self):
        assert as_pin(48.1486, 17.1077) == (48.1486, 17.1077)
        assert as_pin("48,7164", "21,2611") == (48.7164, 21.2611)

    @pytest.mark.parametrize("lat,lng", [
        (0, 0),                 # the classic missing-value pin
        (17.1077, 48.1486),     # swapped
        (50.08, 14.43),         # Prague
        (None, 17.1), ("", ""), ("n/a", 17.1),
    ])
    def test_rejected(self, lat, lng):
        assert as_pin(lat, lng) is None


class TestReaders:
    def test_json_ld_geo(self):
        ld = {"@type": "Apartment", "name": "Byt",
              "geo": {"@type": "GeoCoordinates",
                      "latitude": 48.1129, "longitude": 17.1094}}
        assert pin_from_ld(ld) == (48.1129, 17.1094)

    @pytest.mark.parametrize("item", [
        {"location": {"latitude": 48.31, "longitude": 18.09}},
        {"gps": {"lat": 48.31, "lng": 18.09}},
        {"lat": "48.31", "lon": "18.09"},
        {"address": {"geo": {"latitude": 48.31, "longitude": 18.09}}},
    ])
    def test_api_item_shapes(self, item):
        assert pin_from_item(item) == (48.31, 18.09)

    def test_no_pin(self):
        assert pin_from_item({"location": {"city": "Nitra"}}) is None
        assert pin_from_ld({"@type": "Apartment"}) is None
        assert pin_from_item(None) is None

    def test_og_meta(self):
        html = ('<meta property="place:location:latitude" content="49.2231">'
                '<meta property="place:location:longitude" content="18.7394">')
        assert pin_from_meta(html) == (49.2231, 18.7394)
        assert pin_from_meta("<html></html>") is None


class TestScrapersCarryThePin:
    def test_nehnutelnosti_api_item(self):
        from scraper.nehnutelnosti import _parse_api_item
        rec = _parse_api_item({
            "url": "/detail/JuAbc/2-izbovy-byt-nitra", "price": {"value": 150000},
            "title": "2-izbový byt", "usableArea": 55,
            "location": {"latitude": 48.31, "longitude": 18.09},
        }, "2026-10-01T00:00:00+00:00")
        assert (rec["lat"], rec["lng"]) == (48.31, 18.09)

    def test_nehnutelnosti_item_without_pin(self):
        from scraper.nehnutelnosti import _parse_api_item
        rec = _parse_api_item({"url": "/detail/JuAbc/byt", "title": "Byt"},
                              "2026-10-01T00:00:00+00:00")
        assert rec["lat"] is None and rec["lng"] is None

    def test_nehnutelnosti_detail_json_ld(self):
        from scraper.nehnutelnosti import _merge_ld, _apply_detail, _minimal_listing
        data = {}
        _merge_ld(data, {"@type": "Apartment",
                         "geo": {"latitude": 48.31, "longitude": 18.09}})
        listing = _minimal_listing("https://www.nehnutelnosti.sk/detail/JuX/byt-nitra",
                                   "", "2026-10-01T00:00:00+00:00")
        _apply_detail(listing, data)
        assert (listing["lat"], listing["lng"]) == (48.31, 18.09)

    def test_topreality_detail(self):
        from scraper.topreality import _build_listing_from_detail
        ld = {"@type": "Apartment", "name": "2-izbový byt, Nitra",
              "offers": {"price": 150000}, "floorSize": {"value": 55},
              "geo": {"latitude": 48.31, "longitude": 18.09}}
        html = (f'<html><head><script type="application/ld+json">{json.dumps(ld)}'
                f'</script></head><body>Nitra</body></html>')
        rec = _build_listing_from_detail("https://www.topreality.sk/x-r1234567.html",
                                         html, "2026-10-01T00:00:00+00:00")
        assert (rec["lat"], rec["lng"]) == (48.31, 18.09)

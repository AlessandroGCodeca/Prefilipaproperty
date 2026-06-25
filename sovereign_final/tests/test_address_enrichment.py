"""Tests for modules/address_enrichment.py — composing a normalize_address()
result into a district string the rent matcher resolves, plus the disabled
no-op. The Claude call is never made here."""

import pytest

import modules.address_enrichment as addr
from modules.address_enrichment import _compose_district
from engine.financial import get_rent_estimate


class TestComposeDistrict:
    def test_suburb_and_city(self):
        assert _compose_district({"district": "Ružinov", "city": "Bratislava"}) \
            == "Ružinov, Bratislava"

    def test_city_only(self):
        assert _compose_district({"district": "", "city": "Nitra"}) == "Nitra"

    def test_district_only(self):
        assert _compose_district({"district": "Petržalka", "city": ""}) == "Petržalka"

    def test_dedupes_when_equal(self):
        assert _compose_district({"district": "Nitra", "city": "Nitra"}) == "Nitra"

    def test_strips_whitespace(self):
        assert _compose_district({"district": "  Ružinov ", "city": " Bratislava "}) \
            == "Ružinov, Bratislava"

    def test_all_blank_returns_empty(self):
        assert _compose_district({"district": "", "city": ""}) == ""
        assert _compose_district({"district": None, "city": None}) == ""
        assert _compose_district({}) == ""


class TestDisabledNoop:
    def test_returns_zero_when_disabled(self, monkeypatch):
        monkeypatch.setattr(addr, "is_enabled", lambda: False)
        # get_unnormalized_addresses must never be reached when disabled.
        monkeypatch.setattr(addr, "get_unnormalized_addresses",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("queried")))
        assert addr.run_address_enrichment() == 0


class TestResolvedDistrictEscapesDefault:
    """The whole point: a resolved district must lift rent off the €6.50/m²
    default that a blank district falls to."""

    def test_blank_falls_to_default(self):
        assert get_rent_estimate("", 60.0) == pytest.approx(6.5 * 60, abs=1.0)

    def test_composed_district_beats_default(self):
        composed = _compose_district({"district": "Ružinov", "city": "Bratislava"})
        rent = get_rent_estimate(composed, 60.0)
        assert rent > get_rent_estimate("", 60.0)
        assert rent / 60.0 >= 13.0  # Ružinov ≈ 13.5 €/m²

    def test_city_only_resolution_beats_default(self):
        composed = _compose_district({"district": "", "city": "Žilina"})
        assert get_rent_estimate(composed, 60.0) / 60.0 >= 9.0

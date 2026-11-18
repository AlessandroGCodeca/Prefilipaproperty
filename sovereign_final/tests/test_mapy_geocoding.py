"""Mapy.com geocoding for Czech addresses: the request is the one the API's
OpenAPI spec describes (key in the X-Mapy-Api-Key header, results restricted
to the market's country and to addresses), the answer is read from the
documented shape, and the providers are tried in the right order."""

import pytest

import tests.test_app_smoke as smoke
from modules import location_iq as liq
from modules import risk_data as rd

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs

TYNSKA = {"items": [{
    "name": "Týnská ulička 610/7", "label": "Adresa",
    "position": {"lon": 14.42212, "lat": 50.08861}, "type": "regional.address",
    "location": "Praha 1 - Staré Město, Česko",
    "regionalStructure": [
        {"name": "610/7", "type": "regional.address"},
        {"name": "Týnská ulička", "type": "regional.street"},
        {"name": "Praha", "type": "regional.municipality"},
        {"name": "Česko", "type": "regional.country", "isoCode": "CZ"}],
    "zip": "15000"}], "locality": []}


class Resp:
    def __init__(self, body, status=200):
        self._b, self.status_code = body, status

    def json(self):
        return self._b


def fake(body, status=200):
    asked = []

    def get(url, **kw):
        asked.append((url, kw))
        return Resp(body, status)
    return get, asked


def test_the_request_follows_the_spec():
    get, asked = fake(TYNSKA)
    got = rd.geocode_mapy("Týnská ulička 7, Praha", "cz", api_key="KEY-12345678", get=get)
    assert got == (50.08861, 14.42212, "address")
    url, kw = asked[0]
    assert url == "https://api.mapy.com/v1/geocode"
    assert kw["headers"] == {"X-Mapy-Api-Key": "KEY-12345678"}      # never in the URL
    p = kw["params"]
    assert p["query"] == "Týnská ulička 7, Praha" and p["locality"] == "cz" and p["lang"] == "cs"
    assert "regional.address" in p["type"] and "poi" not in p["type"]
    assert "KEY-12345678" not in str(p)


def test_precision_follows_what_matched():
    assert rd.mapy_precision({"type": "regional.address"}) == "address"
    assert rd.mapy_precision({"type": "regional.street"}) == "street"
    for t in ("regional.municipality", "regional.municipality_part", "poi", None):
        assert rd.mapy_precision({"type": t}) == "area"


def test_no_key_no_query_no_call():
    get, asked = fake(TYNSKA)
    assert rd.geocode_mapy("Praha", "cz", api_key="", get=get) == (None, None, "")
    assert rd.geocode_mapy("   ", "cz", api_key="K" * 12, get=get) == (None, None, "")
    assert asked == []


def test_a_long_address_is_cut_to_the_apis_limit():
    get, asked = fake(TYNSKA)
    rd.geocode_mapy("x" * 400, "cz", api_key="K" * 12, get=get)
    assert len(asked[0][1]["params"]["query"]) == 150


def test_a_result_in_another_country_is_skipped():
    abroad = {"items": [dict(TYNSKA["items"][0], regionalStructure=[
        {"name": "Slovensko", "type": "regional.country", "isoCode": "SK"}])]}
    get, _ = fake(abroad)
    assert rd.geocode_mapy("Hlavná 1", "cz", api_key="K" * 12, get=get) == (None, None, "")
    # The second item, in the right country, is taken.
    both = {"items": abroad["items"] + TYNSKA["items"]}
    get, _ = fake(both)
    assert rd.geocode_mapy("Hlavná 1", "cz", api_key="K" * 12, get=get)[2] == "address"


@pytest.mark.parametrize("status, body", [(401, {}), (403, {}), (422, {}), (500, {}),
                                          (200, {"items": []}), (200, {})])
def test_a_refusal_or_an_empty_answer_is_no_result(status, body):
    get, _ = fake(body, status)
    assert rd.geocode_mapy("Praha", "cz", api_key="K" * 12, get=get) == (None, None, "")


def test_a_network_error_is_no_result_and_names_no_url(caplog):
    import logging

    def get(url, **kw):
        raise ConnectionError(f"failed for {url}?apikey=SECRETKEY123")
    with caplog.at_level(logging.WARNING):
        assert rd.geocode_mapy("Praha", "cz", api_key="K" * 12, get=get) == (None, None, "")
    assert "ConnectionError" in caplog.text and "SECRETKEY123" not in caplog.text


# ── The order of the geocoders ───────────────────────────────────────────────
@pytest.fixture
def keys(monkeypatch):
    def set_(mapy, google):
        import config
        monkeypatch.setattr(config, "MAPY_API_KEY", mapy)
        monkeypatch.setenv("MAPY_API_KEY", mapy)
        monkeypatch.setattr(liq, "GOOGLE_API_KEY", google)
    return set_


def test_provider_order(keys):
    keys("m", "g")
    assert liq.providers("cz") == ["mapy", "google", "nominatim"]
    assert liq.providers("sk") == ["google", "mapy", "nominatim"]
    keys("", "g")
    assert liq.providers("cz") == ["google", "nominatim"]
    keys("m", "")
    assert liq.providers("cz") == ["mapy", "nominatim"]
    keys("", "")
    assert liq.providers("sk") == ["nominatim"]


def test_a_czech_address_is_geocoded_by_mapy_first(keys, monkeypatch):
    keys("m", "g")
    calls = []
    monkeypatch.setattr(liq.risk_data, "geocode_mapy",
                        lambda a, m: calls.append("mapy") or (50.0, 14.4, "address"))
    monkeypatch.setattr(liq, "_geocode_google", lambda a, m: calls.append("google") or (1, 1, "x"))
    assert liq.geocode_precise("Praha 1", "cz") == (50.0, 14.4, "address")
    assert calls == ["mapy"]


def test_the_next_provider_is_tried_when_one_finds_nothing(keys, monkeypatch):
    keys("m", "g")
    calls = []
    monkeypatch.setattr(liq.risk_data, "geocode_mapy",
                        lambda a, m: calls.append("mapy") or (None, None, ""))
    monkeypatch.setattr(liq, "_geocode_google",
                        lambda a, m: calls.append("google") or (None, None, ""))
    monkeypatch.setattr(liq.risk_data, "geocode_nominatim",
                        lambda a, market="sk": calls.append("nominatim") or (49.1, 16.6, "street"))
    assert liq.geocode_precise("Brno", "cz") == (49.1, 16.6, "street")
    assert calls == ["mapy", "google", "nominatim"]
    calls.clear()
    monkeypatch.setattr(liq.risk_data, "geocode_nominatim",
                        lambda a, market="sk": (None, None, ""))
    assert liq.geocode_precise("Nowhere", "cz") == (None, None, "")


def test_the_key_is_masked_like_the_others(monkeypatch):
    from modules import redact
    monkeypatch.setenv("MAPY_API_KEY", "mapy-key-0123456789")
    assert "mapy-key-0123456789" not in redact.redact("x apikey=mapy-key-0123456789")


def test_the_credit_is_the_clickable_green_logo_at_least_20px(monkeypatch):
    from dashboard import legal
    monkeypatch.delenv("MAPY_API_KEY", raising=False)
    assert legal.mapy_credit_html() == ""
    monkeypatch.setenv("MAPY_API_KEY", "mapy-key-0123456789")
    html = legal.mapy_credit_html(height=8)               # never smaller than the terms allow
    assert 'href="https://mapy.com/"' in html
    assert 'src="https://api.mapy.com/img/api/logo_green.svg"' in html
    assert "height:20px" in html and "Search by Mapy.com" in html
    assert "mapy-key-0123456789" not in html
    assert "height:30px" in legal.mapy_credit_html(height=30)


def test_the_page_credits_mapy_when_its_key_is_set(monkeypatch):
    import tests.test_app_smoke as smoke
    monkeypatch.setenv("MAPY_API_KEY", "mapy-key-0123456789")
    at = smoke.AppTest.from_file(smoke.APP, default_timeout=120).run()
    md = " ".join(m.value for m in at.markdown)
    assert "logo_green.svg" in md and "Powered by Mapy.com" in md
    assert "mapy-key-0123456789" not in md
    monkeypatch.delenv("MAPY_API_KEY")
    at = smoke.AppTest.from_file(smoke.APP, default_timeout=120).run()
    assert "logo_green.svg" not in " ".join(m.value for m in at.markdown)


def test_the_map_search_shows_the_credit_beside_its_results(populated_db, monkeypatch):
    import tests.test_app_smoke as smoke
    monkeypatch.setenv("MAPY_API_KEY", "mapy-key-0123456789")
    from dashboard.tabs import map_view
    monkeypatch.setattr(map_view, "_find_point", lambda text, market: ((48.15, 17.11), ""))
    at = smoke.AppTest.from_file(smoke.APP, default_timeout=120).run()
    at.text_input(key="map_near").input("Týnská 7, Praha").run()
    assert not at.exception, [e.value for e in at.exception]
    md = [m.value for m in at.markdown if "logo_green.svg" in m.value]
    assert len(md) >= 2                                   # the map's search and the footer

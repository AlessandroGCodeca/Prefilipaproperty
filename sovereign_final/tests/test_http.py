"""scraper/_http — the ScraperAPI route must not expose its key."""

import pytest
import requests

import scraper._http as http

KEY = "k3y-s3cr3t-0123456789"


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(http, "SCRAPER_API_KEY", KEY)


def test_scraperapi_is_called_over_https():
    assert http.SCRAPER_API_BASE.startswith("https://")


def test_request_goes_to_scraperapi_with_the_target_url_encoded(with_key, monkeypatch):
    seen = {}

    def fake_get(self, url, **kw):
        seen["url"] = url
        return "response"

    monkeypatch.setattr(requests.Session, "get", fake_get)
    assert http.get("https://reality.bazos.sk/predaj/byt/?a=1&b=2") == "response"
    assert seen["url"].startswith(f"https://api.scraperapi.com?api_key={KEY}&url=https%3A%2F%2F")
    assert "a%3D1%26b%3D2" in seen["url"]


@pytest.mark.parametrize("exc", [requests.ConnectionError, requests.Timeout,
                                 requests.exceptions.SSLError])
def test_errors_do_not_carry_the_key(with_key, monkeypatch, exc):
    def boom(self, url, **kw):
        raise exc(f"HTTPSConnectionPool(host='api.scraperapi.com'): Max retries "
                  f"exceeded with url: /?api_key={KEY}&url=https%3A%2F%2Fx.sk")

    monkeypatch.setattr(requests.Session, "get", boom)
    with pytest.raises(exc) as info:
        http.get("https://x.sk")
    assert KEY not in str(info.value)
    assert "api_key=***" in str(info.value)
    assert info.value.__cause__ is None      # `from None`: no chained original either


def test_direct_requests_are_left_alone(monkeypatch):
    monkeypatch.setattr(http, "SCRAPER_API_KEY", "")

    def boom(self, url, **kw):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests.Session, "get", boom)
    with pytest.raises(requests.ConnectionError, match="no route to host"):
        http.get("https://x.sk")

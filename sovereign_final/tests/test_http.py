"""scraper/_http — the ScraperAPI route must not expose its key."""

import pytest
import requests

import scraper._http as http

KEY = "k3y-s3cr3t-0123456789"


@pytest.fixture(autouse=True)
def fresh_routes(monkeypatch):
    """No site remembered as refusing, before or after a test."""
    monkeypatch.setattr(http, "_proxied", {})


@pytest.fixture
def with_key(monkeypatch):
    """Every request through ScraperAPI, as before EF4."""
    monkeypatch.setattr(http, "SCRAPER_API_KEY", KEY)
    monkeypatch.setattr(http, "SCRAPER_API_MODE", "always")


@pytest.fixture
def fallback(monkeypatch):
    """The default since EF4: direct first, ScraperAPI for a site that refuses."""
    monkeypatch.setattr(http, "SCRAPER_API_KEY", KEY)
    monkeypatch.setattr(http, "SCRAPER_API_MODE", "fallback")
    asked = []
    answers = {}

    class R:
        def __init__(self, status=200, body=b"<html>listings</html>"):
            self.status_code, self.content = status, body

    def fake_get(self, url, **kw):
        asked.append(url)
        if url.startswith(http.SCRAPER_API_BASE):
            return R(200, b"<html>through scraperapi</html>")
        got = answers.get(http._host(url), R())
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(requests.Session, "get", fake_get)
    return asked, answers, R


def _proxied(asked):
    return [u for u in asked if u.startswith(http.SCRAPER_API_BASE)]


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


# ── EF4: ScraperAPI only where it is needed ──────────────────────────────────
def test_a_site_that_answers_directly_costs_no_credit(fallback):
    asked, _, _ = fallback
    for page in range(3):
        assert http.get(f"https://reality.bazos.sk/predaj/byt/{page}/").content.endswith(
            b"listings</html>")
    assert asked and not _proxied(asked)


def test_a_refused_site_goes_through_scraperapi_for_the_rest_of_the_run(fallback):
    asked, answers, R = fallback
    answers["www.topreality.sk"] = R(403, b"Forbidden")
    r = http.get("https://www.topreality.sk/vyhladavanie/1")
    assert r.content == b"<html>through scraperapi</html>"
    assert len(asked) == 2                                  # the direct try, then the proxy
    asked.clear()
    http.get("https://www.topreality.sk/vyhladavanie/2")
    assert len(asked) == 1 and _proxied(asked)              # no wasted direct try
    asked.clear()
    http.get("https://reality.bazos.sk/predaj/byt/")
    assert asked == ["https://reality.bazos.sk/predaj/byt/"]   # another site: still direct


@pytest.mark.parametrize("status", [403, 407, 429, 503])
def test_each_refusal_status_counts(fallback, status):
    _, answers, R = fallback
    answers["x.sk"] = R(status, b"no")
    http.get("https://x.sk/a")
    assert http.is_proxied("https://x.sk/b")


def test_a_challenge_page_counts_but_a_page_with_a_form_captcha_does_not(fallback):
    _, answers, R = fallback
    answers["a.sk"] = R(200, b"<html><title>Just a moment...</title></html>")
    answers["b.sk"] = R(200, b"<html>" + b"x" * 30_000 + b"g-recaptcha</html>")
    http.get("https://a.sk/")
    http.get("https://b.sk/")
    assert http.is_proxied("https://a.sk/") and not http.is_proxied("https://b.sk/")


def test_a_dropped_connection_counts_and_a_missing_page_does_not(fallback):
    _, answers, R = fallback
    answers["drop.sk"] = requests.ConnectionError("Connection reset by peer")
    answers["gone.sk"] = R(404, b"Not found")
    assert http.get("https://drop.sk/").content == b"<html>through scraperapi</html>"
    assert http.get("https://gone.sk/").status_code == 404
    assert http.is_proxied("https://drop.sk/") and not http.is_proxied("https://gone.sk/")


def test_the_next_run_tries_directly_again(fallback, monkeypatch):
    _, answers, R = fallback
    answers["x.sk"] = R(429, b"slow down")
    now = [1000.0]
    monkeypatch.setattr(http.time, "monotonic", lambda: now[0])
    http.get("https://x.sk/")
    assert http.is_proxied("https://x.sk/")
    now[0] += http.ROUTE_TTL_S + 1
    assert not http.is_proxied("https://x.sk/")


def test_off_and_no_key_never_use_scraperapi(fallback, monkeypatch):
    asked, answers, R = fallback
    answers["x.sk"] = R(403, b"Forbidden")
    monkeypatch.setattr(http, "SCRAPER_API_MODE", "off")
    assert http.get("https://x.sk/").status_code == 403
    monkeypatch.setattr(http, "SCRAPER_API_MODE", "fallback")
    monkeypatch.setattr(http, "SCRAPER_API_KEY", "")
    assert http.get("https://x.sk/").status_code == 403
    assert not _proxied(asked)


def test_a_refused_warm_up_spends_no_credit_and_routes_the_site(fallback):
    asked, answers, R = fallback
    answers["www.idnes.cz"] = R(403, b"Forbidden")
    http.make_session("https://www.idnes.cz/")
    assert asked == ["https://www.idnes.cz/"] and http.is_proxied("https://www.idnes.cz/x")

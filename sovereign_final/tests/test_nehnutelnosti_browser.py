"""The Nehnutelnosti.sk scraper, in a real Chromium, against a fake site.

Every other scraper test stubs the browser out, and the main CI job does not
install Playwright at all, so a Playwright or Chromium upgrade went untested
(review M3). This test runs scraper.nehnutelnosti.run() unchanged, browser
launch included. Only the network is swapped: every request for
www.nehnutelnosti.sk is answered by a small HTTP server on 127.0.0.1, and every
request for any other host is refused. It needs no internet connection.

The fake pages cover each way the scraper reads the site:

  page 1   the search page fetches /api/v2 JSON, which the response listener
           captures (strategy 1). The request also reports navigator.webdriver,
           which the scraper's init script hides from the site's WAF.
  page 2   no JSON: links in the DOM (strategy 2) and a Next.js RSC chunk
           (strategy 3). Their detail pages are then opened:
             DM1    JSON-LD, plus an /api/v2 call that names one more listing
             RS1    no JSON-LD: price heading, size and energy class from the
                    rendered text, next to a dearer carousel price to ignore
             GONE1  the "similar listings" grid of a removed listing

Skipped where Playwright or its Chromium is missing, unless
SOVEREIGN_BROWSER_TESTS=1 (the CI browser job), where that is a failure.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from tests.conftest import make_full_db, make_listing

REQUIRED = os.environ.get("SOVEREIGN_BROWSER_TESTS") == "1"
if not REQUIRED:
    pytest.importorskip("playwright.sync_api")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "www.nehnutelnosti.sk"
BASE = f"https://{HOST}"
THIRD_PARTY = "https://www.googletagmanager.com/gtm.js"


def _page(body: str, head: str = "") -> str:
    return (f'<!doctype html><html lang="sk"><head><meta charset="utf-8">'
            f"{head}</head><body>{body}</body></html>")


def _ld(blob: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(blob)}</script>'


SEARCH_1 = _page(
    '<div id="list">Načítavam…</div>'
    "<script>"
    "fetch('/api/v2/search?page=1&webdriver=' + navigator.webdriver)"
    ".then(r => r.json())"
    ".then(d => { document.getElementById('list').textContent ="
    " d.items.length + ' inzerátov'; });"
    "</script>",
    head=f'<title>Byty na predaj | Nehnutelnosti.sk</title><script src="{THIRD_PARTY}"></script>',
)

# The RSC payload as Next.js writes it: a JSON string inside a push() call.
_RSC = json.dumps(json.dumps({"href": "/detail/RS1/1-izbovy-byt-nitra"}))
SEARCH_2 = _page(
    '<a href="/detail/DM1/3-izbovy-byt-ruzinov">3-izbový byt, Ružinov</a>'
    '<a href="/detail/GONE1/2-izbovy-byt-trnava">2-izbový byt, Trnava</a>'
    "<script>self.__next_f = self.__next_f || [];</script>"
    f"<script>self.__next_f.push([1,{_RSC}])</script>",
    head="<title>Byty na predaj, strana 2 | Nehnutelnosti.sk</title>",
)

SEARCH_API = {"items": [{
    "url": "/detail/AP1/2-izbovy-byt-zilina",
    "title": "2-izbový byt, Žilina",
    "price": {"value": 150000},
    "usableArea": 52,
    "location": {"city": "Žilina"},
}]}

DETAIL_DM1 = _page(
    "<h1>3-izbový byt, Ružinov</h1>"
    '<h3 class="MuiTypography-root MuiTypography-h3">250 000 €</h3>'
    "<script>fetch('/api/v2/advertisement/similar?id=DM1')</script>",
    head=(
        "<title>3-izbový byt, Ružinov | Nehnutelnosti.sk</title>"
        f'<link rel="canonical" href="{BASE}/detail/DM1/3-izbovy-byt-ruzinov">'
        + _ld({
            "@context": "https://schema.org", "@type": "Apartment",
            "name": "3-izbový byt, Ružinov",
            "offers": {"@type": "Offer", "price": 250000, "priceCurrency": "EUR"},
            "floorSize": {"@type": "QuantitativeValue", "value": 68},
            "numberOfRooms": 3,
            "address": {"@type": "PostalAddress",
                        "addressLocality": "Bratislava - Ružinov"},
        })
    ),
)

SIMILAR_API = {"items": [{
    "url": "/detail/HV1/2-izbovy-byt-senec",
    "title": "2-izbový byt, Senec",
    "price": {"value": 175000},
    "usableArea": 50,
}]}

DETAIL_RS1 = _page(
    "<h1>1-izbový byt, Nitra</h1>"
    '<div class="MuiTypography-root MuiTypography-h3">120 000 €</div>'
    "<p>Úžitková plocha</p><p>40 m²</p>"
    "<p>Energetická trieda: B</p>"
    "<p>Lokalita: Nitra</p>"
    "<h4>Mohlo by vás zaujímať</h4>"
    '<div class="MuiTypography-root MuiTypography-body2">1 399 000 €</div>',
    head='<meta property="og:title" content="1-izbový byt, Nitra">',
)

DETAIL_GONE1 = _page(
    "<h2>Podobné inzeráty</h2>"
    + "".join(
        f'<div class="MuiTypography-root MuiTypography-h5">{p} 000 €</div>'
        for p in range(140, 260, 10)
    ),
    head="<title>Podobné inzeráty | Nehnutelnosti.sk</title>",
)

SITE = {
    "/vysledky/byty/slovensko/predaj?page=1": ("text/html", SEARCH_1),
    "/vysledky/byty/slovensko/predaj?page=2": ("text/html", SEARCH_2),
    "/api/v2/search?page=1&webdriver=undefined": ("application/json", json.dumps(SEARCH_API)),
    "/api/v2/advertisement/similar?id=DM1": ("application/json", json.dumps(SIMILAR_API)),
    "/detail/DM1": ("text/html", DETAIL_DM1),
    "/detail/RS1": ("text/html", DETAIL_RS1),
    "/detail/GONE1": ("text/html", DETAIL_GONE1),
}


class _FakeSite(BaseHTTPRequestHandler):
    log: list[str] = []

    def do_GET(self):
        self.log.append(self.path)
        ctype, body = SITE.get(self.path, ("text/html", None))
        data = (body if body is not None else _page("<h1>404</h1>")).encode()
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fake_site():
    _FakeSite.log = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _FakeSite.log
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def chromium_ok():
    """Skip, or fail under SOVEREIGN_BROWSER_TESTS=1, when Chromium is missing:
    the pip package ships without the browser, and each Playwright version
    needs its own `playwright install chromium`."""
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception as e:
        if REQUIRED:
            raise
        pytest.skip(f"Chromium for this Playwright is not installed: {e}")


@pytest.fixture(scope="module")
def scraped(chromium_ok, fake_site, tmp_path_factory):
    """One scraper.nehnutelnosti.run() over the fake site's two search pages,
    shared by every test below: a run takes about ten seconds."""
    import database as db
    from engine import property_tax_cz, property_tax_sk
    from scraper import nehnutelnosti as n

    local, server_log = fake_site
    blocked: list[str] = []

    def _serve(route):
        parts = urlsplit(route.request.url)
        if parts.hostname != HOST:
            blocked.append(route.request.url)
            route.abort()
            return
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        route.fulfill(response=route.fetch(url=local + path))

    real_open = n._open_browser

    def _open_offline(pw):
        browser, page, capture = real_open(pw)
        page.context.route("**/*", _serve)
        return browser, page, capture

    path = str(tmp_path_factory.mktemp("browser") / "sovereign.db")
    conn_for = make_full_db(path)
    with pytest.MonkeyPatch.context() as mp:
        # What conftest's function-scoped full_db and autouse fixtures do,
        # which a module-scoped fixture runs outside of.
        mp.setattr(db, "SQLITE_PATH", path)
        mp.setattr(db, "get_conn", conn_for)
        mp.setattr(property_tax_sk, "_stored", {})
        mp.setattr(property_tax_cz, "_stored", {})
        mp.setattr(n, "_open_browser", _open_offline)
        mp.setattr(n, "SCRAPE_DELAY_SEC", 0)

        # The removed listing is still active in the database from an earlier run.
        db.upsert_listing(make_listing(
            "gone", source="nehnutelnosti", url=f"{BASE}/detail/GONE1",
            price_eur=190_000.0, district="Trnava",
        ))

        total = n.run(max_pages=2)

    conn = conn_for()
    rows = {r["url"].rsplit("/", 1)[-1]: dict(r) for r in conn.execute(
        "SELECT * FROM listings WHERE source='nehnutelnosti'")}
    conn.close()
    return total, rows, server_log, blocked


def test_every_listing_is_stored(scraped):
    total, rows, _log, _blocked = scraped
    assert total == 4
    assert {k for k, r in rows.items() if r["is_active"]} == {"AP1", "DM1", "RS1", "HV1"}


def test_search_page_api_json_is_captured(scraped):
    _total, rows, log, _blocked = scraped
    ap1 = rows["AP1"]
    assert (ap1["price_eur"], ap1["size_m2"], ap1["rooms"]) == (150_000, 52, 2)
    assert ap1["district"] == "Žilina"
    # A listing the API described in full needs no detail page.
    assert "/detail/AP1" not in log


def test_webdriver_flag_is_hidden_from_the_site(scraped):
    _total, _rows, log, _blocked = scraped
    assert "/api/v2/search?page=1&webdriver=undefined" in log


def test_json_ld_detail_page(scraped):
    _total, rows, _log, _blocked = scraped
    dm1 = rows["DM1"]
    assert (dm1["price_eur"], dm1["size_m2"], dm1["rooms"]) == (250_000, 68, 3)
    assert dm1["title"] == "3-izbový byt, Ružinov"
    assert "Ružinov" in dm1["district"]


def test_rendered_text_detail_page(scraped):
    _total, rows, _log, _blocked = scraped
    rs1 = rows["RS1"]
    # The listing's own heading, not the €1 399 000 carousel card beside it.
    assert rs1["price_eur"] == 120_000
    assert rs1["size_m2"] == 40
    assert rs1["energy_class"] == "B"
    assert rs1["district"] == "Nitra"


def test_detail_page_api_adds_a_listing(scraped):
    _total, rows, _log, _blocked = scraped
    hv1 = rows["HV1"]
    assert (hv1["price_eur"], hv1["size_m2"]) == (175_000, 50)
    assert hv1["district"] == "Senec"


def test_removed_listing_is_deactivated(scraped):
    _total, rows, _log, _blocked = scraped
    assert rows["GONE1"]["is_active"] == 0


def test_nothing_leaves_the_machine(scraped):
    _total, _rows, log, blocked = scraped
    # The one third-party script the fake search page loads was refused...
    assert blocked == [THIRD_PARTY]
    # ...and the fake site was asked for its own pages and nothing else.
    assert sorted(set(log)) == sorted(SITE)

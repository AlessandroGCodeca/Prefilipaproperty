"""The Czech portal scrapers (scraper/cz_common, sreality, bezrealitky, idnes,
bazos_cz) on synthetic pages: no request leaves the test, and every page,
advert and robots.txt below is made up for it."""

import gzip
import json

import pytest

import scraper.cz_common as cz
from scraper import bazos_cz, bezrealitky, idnes, sreality

NB = " "


# ── Fakes ─────────────────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, status=200, text="", content=None, payload=None):
        self.status_code = status
        self.text = text if payload is None else json.dumps(payload)
        self.content = content if content is not None else self.text.encode()
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


@pytest.fixture
def robots(monkeypatch):
    """Pre-loads each host's robots.txt, so no test fetches one."""
    cache = {}
    monkeypatch.setattr(cz, "_robots_cache", cache)

    def load(root, text):
        cache[root] = cz.Robots(text) if text is not None else None
    return load


def _offline(monkeypatch, module, pages):
    """`module.get` answers from `pages` {url: FakeResponse}; anything else
    is a 404. Returns the list of URLs requested."""
    asked = []

    def fake_get(url, session=None, timeout=20, render=False):
        asked.append(url)
        return pages.get(url, FakeResponse(404, "not found"))
    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(module, "make_session", lambda *a, **k: _Session())
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    return asked


class _Session:
    headers: dict = {}

    def __init__(self):
        self.headers = {}


def _rows(full_db, source):
    conn = full_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM listings WHERE source=? ORDER BY id", (source,))]
    finally:
        conn.close()


# ── robots.txt, read as RFC 9309 says ─────────────────────────────────────────
ROBOTS = """
User-agent: SomeSearchEngine
Allow: /

User-agent: *
Allow: /
Disallow: /s/*page=*sort=
Disallow: /*hledat=
Disallow: /private
Allow: /private/open$
Disallow: /vyhledat*
"""


@pytest.mark.parametrize("path,allowed", [
    ("/s/prodej/byty/", True),
    ("/s/prodej/byty/?page=3", True),
    ("/s/prodej/byty/?page=3&sort=price", False),     # wildcard in the middle
    ("/prodam/byt/?hledat=x", False),                 # wildcard at the start
    ("/private/x", False),
    ("/private/open", True),                          # longer Allow wins, $ anchors
    ("/private/open/more", False),
    ("/vyhledat?x=1", False),
])
def test_robots_longest_match_and_wildcards(path, allowed):
    assert cz.Robots(ROBOTS).allows("https://example.cz" + path) is allowed


def test_robots_disallow_all_for_the_generic_agent():
    text = "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"
    assert not cz.Robots(text).allows("https://example.cz/api/v1/x")
    # An empty Disallow allows everything.
    assert cz.Robots("User-agent: *\nDisallow:\n").allows("https://example.cz/a")


def test_robots_tie_goes_to_allow():
    text = "User-agent: *\nDisallow: /a\nAllow: /a\n"
    assert cz.Robots(text).allows("https://example.cz/a")


def test_robots_fetch_outcomes():
    cz._robots_cache.clear()
    try:
        assert cz.robots_allows("https://a.example.cz/x", lambda u: (404, ""))[0]
        ok, why = cz.robots_allows("https://b.example.cz/x", lambda u: (503, ""))
        assert not ok and "HTTP 503" in why

        def boom(u):
            raise ConnectionError("no route")
        ok, why = cz.robots_allows("https://c.example.cz/x", boom)
        assert not ok and "unreachable" in why
        with pytest.raises(cz.PortalBlocked, match="blocked by robots.txt"):
            cz.require_robots("https://d.example.cz/x",
                              lambda u: (200, "User-agent: *\nDisallow: /\n"))
        # A failed step, like any scraper's RuntimeError.
        assert issubclass(cz.PortalBlocked, RuntimeError)
    finally:
        cz._robots_cache.clear()


# ── Shared parsing ────────────────────────────────────────────────────────────
def test_czk_amounts_leave_out_rents_and_rates():
    text = "Cena 3 450 000 Kč, poplatky 4 500 Kč/měs., 85 000 Kč/m2"
    assert cz.czk_amounts(text) == [3_450_000.0]
    assert cz.czk_amounts("cena 2.950.000,- Kč") == [2_950_000.0]


@pytest.mark.parametrize("text,rooms", [
    ("Prodej bytu 2+kk 54 m²", 2), ("Prodej bytu 3 + 1", 3),
    ("Prodej garsoniéry 28 m²", 1), ("byt 6 pokojů a více", 6), ("Prodej bytu", None),
])
def test_rooms_cz(text, rooms):
    assert cz.rooms_cz(text) == rooms


@pytest.mark.parametrize("title,excluded", [
    ("Prodej bytu 2+kk 54 m²", False),
    ("Pronájem bytu 2+kk", True),
    ("Dražba bytu 3+1", True),
    ("Prodej podílu na bytě", True),
    ("Prodej bytu 3+1 s podílem na pozemku", False),
    ("Prodej garáže", True),
    ("Prodej bytu 2+1 s garáží", False),
    ("Prodej rodinného domu", True),
])
def test_is_excluded_cz(title, excluded):
    assert cz.is_excluded_cz(title) is excluded


def test_energy_cz():
    assert cz.energy_cz("Energetická náročnost budovy: Třída G - Mimořádně nehospodárná") == "G"
    assert cz.energy_cz("PENB: C") == "C"
    assert cz.energy_cz("hezký byt") == "UNKNOWN"


def test_listing_record_is_czech_and_in_crowns():
    rec = cz.listing_record("x", "1", "https://example.cz/1", title="Prodej bytu 2+kk",
                            price=3_000_000, pin=(50.08, 14.42))
    assert rec["market"] == "cz" and rec["currency"] == "CZK"
    assert rec["rooms"] == 2 and (rec["lat"], rec["lng"]) == (50.08, 14.42)
    assert rec["id"] == cz.listing_id("x", "1") != cz.listing_id("y", "1")


# ── Sreality ──────────────────────────────────────────────────────────────────
ESTATE = {
    "hash_id": 1234567890,
    "advert_name": "Prodej bytu 2+kk 54 m²",
    "category_sub_cb": {"name": "2+kk", "value": 4},
    "price_czk": {"value_raw": 5_400_000, "unit": ""},
    "locality": {"city": "Praha", "citypart": "Vinohrady", "street": "Testovací",
                 "city_seo_name": "praha", "citypart_seo_name": "vinohrady",
                 "street_seo_name": "testovaci", "gps_lat": 50.075, "gps_lon": 14.44},
}


def test_sreality_estate_to_listing():
    rec = sreality.listing_from_estate(ESTATE, "2026-10-01T00:00:00+00:00")
    assert rec["price_eur"] == 5_400_000 and rec["size_m2"] == 54
    assert rec["district"] == "Praha - Vinohrady"
    assert rec["address_raw"] == "Testovací, Praha - Vinohrady"
    assert (rec["lat"], rec["lng"]) == (50.075, 14.44)
    assert rec["url"] == ("https://www.sreality.cz/detail/prodej/byt/2+kk/"
                          "praha-vinohrady-testovaci/1234567890")
    assert rec["market"] == "cz" and rec["currency"] == "CZK"


def test_sreality_skips_per_m2_prices_and_reads_both_api_shapes():
    per_m2 = {**ESTATE, "price_czk": {"value_raw": 95_000, "unit": "za m²"}}
    assert sreality.listing_from_estate(per_m2)["price_eur"] == 0
    assert sreality.estates_in({"results": [ESTATE]}) == [ESTATE]
    assert sreality.estates_in({"_embedded": {"estates": [ESTATE]}}) == [ESTATE]
    assert sreality.estates_in(None) == []
    rental = {**ESTATE, "advert_name": "Pronájem bytu 2+kk 54 m²"}
    assert sreality.listing_from_estate(rental) is None


def test_sreality_detail_fills_in():
    rec = sreality.listing_from_estate(ESTATE)
    sreality.apply_detail(rec, {"result": {
        "usable_area": {"value": 56}, "floor_number": {"value": 3},
        "energy_efficiency_rating_cb": {"value": "Třída C - Úsporná"},
        "advert_description": "Světlý byt po rekonstrukci.",
        "items": [{"name": "Vlastnictví", "value": "Osobní"}],
    }})
    assert rec["size_m2"] == 56 and rec["floor"] == 3
    assert rec["description"].startswith("Vlastnictví: Osobní. Světlý byt")


def test_sreality_run_stops_at_robots_before_any_request(monkeypatch, robots):
    robots("https://www.sreality.cz", "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n")
    asked = _offline(monkeypatch, sreality, {})
    with pytest.raises(cz.PortalBlocked, match="robots.txt"):
        sreality.run(max_pages=1)
    assert asked == []


def test_sreality_run_when_allowed(monkeypatch, robots, full_db):
    robots("https://www.sreality.cz", None)          # no robots.txt: allowed
    from urllib.parse import urlencode
    search = (sreality.SEARCH_API + "?" + urlencode(
        {**sreality.SEARCH_PARAMS, "per_page": sreality.PER_PAGE, "offset": 0}))
    _offline(monkeypatch, sreality, {
        search: FakeResponse(payload={"results": [ESTATE]}),
        sreality.DETAIL_API.format(hash_id=ESTATE["hash_id"]):
            FakeResponse(payload={"result": {"advert_description": "Popis."}}),
    })
    assert sreality.run(max_pages=2) == 1
    (row,) = _rows(full_db, "sreality")
    assert row["market"] == "cz" and row["currency"] == "CZK"
    assert row["price_eur"] == 5_400_000 and row["description"] == "Popis."


# ── Bezrealitky ──────────────────────────────────────────────────────────────
B = "https://www.bezrealitky.cz/nemovitosti-byty-domy/"


def _next_data(advert):
    data = {"props": {"pageProps": {"apolloCache": {
        "Advert:1": {"id": "9", "uri": "x", "offerType": "PRODEJ"},   # a related stub
        "Advert:2": advert}}}}
    return (f'<html><script id="__NEXT_DATA__" type="application/json">'
            f'{json.dumps(data)}</script></html>')


ADVERT = {"id": "1000002", "uri": "1000002-nabidka-prodej-bytu-testovaci-brno",
          "offerType": "PRODEJ", "estateType": "BYT", "disposition": "DISP_2_KK",
          "surface": 61, "price": 4_200_000, "currency": "CZK", "etage": 4,
          "gps": {"lat": 49.195, "lng": 16.607}, "street": "Testovací",
          "houseNumber": "12", "city": "Brno", "cityDistrict": "Brno-střed",
          "description": "Byt po rekonstrukci.", "ownership": "OSOBNI", "penb": "PENB_C"}


def test_bezrealitky_sale_flat_urls():
    assert bezrealitky.sale_flat_url(B + "1000002-nabidka-prodej-bytu-testovaci-brno") == "1000002"
    assert bezrealitky.sale_flat_url(B + "1000003-nabidka-pronajem-bytu-testovaci-brno") is None
    assert bezrealitky.sale_flat_url(B + "1000004-nabidka-prodej-domu-testovaci") is None
    assert bezrealitky.sale_flat_url("https://www.bezrealitky.cz/vypis/x") is None


def test_bezrealitky_walks_a_gzipped_sitemap_index():
    child = "https://www.bezrealitky.cz/sitemap/adverts-1.xml.gz"
    index = f"<sitemapindex><sitemap><loc>{child}</loc></sitemap></sitemapindex>".encode()
    urls = "".join(f"<url><loc>{B}{u}</loc></url>" for u in (
        "1000001-nabidka-prodej-bytu-a-praha", "1000003-nabidka-prodej-bytu-b-brno",
        "1000002-nabidka-pronajem-bytu-c-praha"))
    pages = {bezrealitky.SITEMAP_INDEX: (200, index),
             child: (200, gzip.compress(f"<urlset>{urls}</urlset>".encode()))}
    got = bezrealitky.walk_sitemap(None, fetch=lambda u: pages.get(u, (404, b"")))
    assert [k for k, _ in got] == [1000003, 1000001]          # newest first, sales only
    with pytest.raises(cz.PortalBlocked):
        bezrealitky.walk_sitemap(None, fetch=lambda u: (403, b""))


def test_bezrealitky_advert_to_listing():
    advert = bezrealitky.advert_from_html(_next_data(ADVERT))
    assert advert["id"] == "1000002"                          # the page's own, not the stub
    rec = bezrealitky.listing_from_advert(advert, B + ADVERT["uri"])
    assert rec["price_eur"] == 4_200_000 and rec["size_m2"] == 61 and rec["rooms"] == 2
    assert rec["floor"] == 4 and rec["energy_class"] == "C"
    # The city part already names the city: not repeated.
    assert rec["district"] == "Brno-střed"
    assert rec["address_raw"] == "Testovací 12, Brno-střed"
    other = {**ADVERT, "city": "Praha", "cityDistrict": "Vinohrady"}
    assert bezrealitky.listing_from_advert(other, B + "x")["district"] == "Praha - Vinohrady"
    assert (rec["lat"], rec["lng"]) == (49.195, 16.607)
    assert rec["description"].startswith("Vlastnictví: osobní. Byt po")
    assert rec["title"] == "Prodej bytu 2+kk 61 m² Brno-střed"
    for other in ({"offerType": "PRONAJEM"}, {"estateType": "DUM"}, {"currency": "EUR"}):
        assert bezrealitky.listing_from_advert({**ADVERT, **other}, B + "x") is None
    assert bezrealitky.advert_from_html("<html>no data</html>") is None


def test_bezrealitky_run(monkeypatch, robots, full_db):
    robots("https://www.bezrealitky.cz",
           "User-agent: *\nDisallow: /vyhledat*\nDisallow: /search*\n")
    url = B + ADVERT["uri"]
    sitemap = f"<urlset><url><loc>{url}</loc></url></urlset>"
    _offline(monkeypatch, bezrealitky, {
        bezrealitky.SITEMAP_INDEX: FakeResponse(text=sitemap),
        url: FakeResponse(text=_next_data(ADVERT)),
    })
    assert bezrealitky.run(max_pages=1) == 1
    (row,) = _rows(full_db, "bezrealitky")
    assert row["market"] == "cz" and row["price_eur"] == 4_200_000
    assert row["detail_enriched_at"]


def test_bezrealitky_never_reads_the_api_host(monkeypatch, robots):
    robots("https://www.bezrealitky.cz", "User-agent: *\nDisallow: /\n")
    asked = _offline(monkeypatch, bezrealitky, {})
    with pytest.raises(cz.PortalBlocked):
        bezrealitky.run(max_pages=1)
    assert asked == [] and "api.bezrealitky" not in bezrealitky.SITEMAP_INDEX


# ── iDNES ─────────────────────────────────────────────────────────────────────
H = "0123456789abcdef01234567"


def _card(hex_id, title, info, price):
    return (f'<div class="c-products__item"><a href="https://reality.idnes.cz/detail/'
            f'prodej/byt/testovaci-mesto/{hex_id}/"><h2 class="c-products__title">{title}'
            f'</h2></a><p class="c-products__info">{info}</p>'
            f'<p class="c-products__price"><strong>{price}</strong></p></div>')


SEARCH_PAGE = ("<html><body>"
               + _card(H, "prodej bytu 2+kk 54 m²", "Testovací, Praha 10 - Malešice",
                       "6 480 000 Kč")
               + _card("f" * 24, "prodej bytu 3+1 70 m²", "Ostrava - Poruba, okres Ostrava-město",
                       "Info o ceně u RK")
               + '<div class="c-products__item"><a href="/jinde/">reklama</a></div>'
               + "</body></html>")


def test_idnes_cards():
    rows = idnes.parse_search(SEARCH_PAGE)
    assert [r["district"] for r in rows] == ["Praha 10 - Malešice", "Ostrava - Poruba"]
    first, second = rows
    assert first["price_eur"] == 6_480_000 and first["size_m2"] == 54 and first["rooms"] == 2
    assert first["address_raw"] == "Testovací, Praha 10 - Malešice"
    assert first["id"] == cz.listing_id("idnes", H)
    assert second["price_eur"] == 0                       # price on request
    assert idnes.page_url(1) == idnes.SEARCH and idnes.page_url(3).endswith("/?page=3")


def test_idnes_detail():
    rec = idnes.parse_search(SEARCH_PAGE)[1]
    html = ('<meta property="og:description" content="Prodej bytu 3+1 70 m², '
            'Ostrava - Poruba. Cena 3 150 000 Kč. Pěkný byt u parku.">'
            "<dl><dt>Vlastnictví</dt><dd>osobní</dd><dt>Podlaží</dt><dd>2. podlaží z 8</dd>"
            "<dt>Energetická náročnost budovy</dt><dd>Třída D</dd></dl>")
    idnes.apply_detail(rec, html)
    assert rec["price_eur"] == 3_150_000
    assert rec["description"] == "Vlastnictví: osobní. Pěkný byt u parku."
    assert rec["floor"] == 2 and rec["energy_class"] == "D"


def test_idnes_run_ends_at_the_404(monkeypatch, robots, full_db):
    robots("https://reality.idnes.cz", "User-agent: *\nAllow: /\nDisallow: /s/*page=*sort=\n")
    asked = _offline(monkeypatch, idnes, {idnes.page_url(1): FakeResponse(text=SEARCH_PAGE)})
    assert idnes.run(max_pages=5) == 2
    assert idnes.page_url(2) in asked and idnes.page_url(3) not in asked
    assert {r["market"] for r in _rows(full_db, "idnes")} == {"cz"}


# ── Bazoš CZ ──────────────────────────────────────────────────────────────────
def _bazos_card(n, title, price, place):
    return (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="/inzerat/{n}/test.php">{title}</a></div>'
            f'<div class="popis">Cihlový byt, 2. patro.</div>'
            f'<div class="inzeratycena"><b>{price}</b></div>'
            f'<div class="inzeratylok">{place}</div></div>')


BAZOS_PAGE = ("<html>"
              + _bazos_card(111, "Prodej bytu 2+1 56 m2", "2 890 000 Kč", "Kladno<br>272 01")
              + _bazos_card(112, "Pronájem bytu 1+kk", "12 000 Kč", "Praha<br>110 00")
              + "</html>")


def test_bazos_cz_cards():
    (rec,) = bazos_cz.parse_page(BAZOS_PAGE)               # the rental is dropped
    assert rec["url"] == "https://reality.bazos.cz/inzerat/111/test.php"
    assert rec["price_eur"] == 2_890_000 and rec["size_m2"] == 56 and rec["rooms"] == 2
    assert rec["district"] == "Kladno"
    assert rec["id"] == cz.listing_id("bazos_cz", "111")
    assert bazos_cz.page_url(0).endswith("/prodam/byt/")
    assert bazos_cz.page_url(20).endswith("/prodam/byt/20/")


def test_bazos_cz_detail_adds_the_full_text():
    rec = bazos_cz.parse_page(BAZOS_PAGE)[0]
    bazos_cz.apply_detail(rec, '<meta name="description" content="Prodám byt 2+1 56 m2 '
                               'v Kladně, PENB: E, po rekonstrukci koupelny a kuchyně.">')
    assert rec["energy_class"] == "E" and "rekonstrukci" in rec["description"]


def test_bazos_cz_reads_only_paths_robots_allows(monkeypatch, robots, full_db):
    robots("https://reality.bazos.cz", "User-agent: *\nDisallow: /*hledat=\nDisallow: /*rubriky=\n")
    asked = _offline(monkeypatch, bazos_cz, {bazos_cz.page_url(0): FakeResponse(text=BAZOS_PAGE)})
    assert bazos_cz.run(max_pages=3) == 1
    assert not any("hledat=" in u or "rubriky=" in u for u in asked)
    (row,) = _rows(full_db, "bazos_cz")
    assert row["market"] == "cz" and row["currency"] == "CZK"


def test_a_blocked_portal_fails_its_step_only(monkeypatch, robots):
    robots("https://reality.bazos.cz", "User-agent: *\nDisallow: /\n")
    _offline(monkeypatch, bazos_cz, {})
    with pytest.raises(RuntimeError, match="robots.txt"):
        bazos_cz.run(max_pages=1)


def test_the_czech_run_reads_only_portals_robots_allows():
    import scheduler
    modules = [m for _, m in scheduler.SCRAPERS["cz"]]
    assert modules == ["scraper.bezrealitky", "scraper.idnes", "scraper.bazos_cz"]
    assert [m for _, m, _ in scheduler.BLOCKED["cz"]] == ["scraper.sreality"]

"""Tests for deactivating a nehnutelnosti listing the moment its page says it
is gone, instead of waiting three weeks for deactivate_stale_listings.

An expired listing's URL still loads, but the listing is no longer on it. A
live probe of /detail/JuS4u4DYlpK showed what replaces it: no price-only h3,
and a grid of about 28 "similar listings" cards with their prices in
MuiTypography-h5. A live listing has its own price in an h3 and its only other
prices in the body2 carousel, which the heading selector never sees.

Before this, the expired page came back with no price and every caller treated
it as a listing still to be filled: repair_prices cleared it to PENDING,
enrich_pending upserted it (re-activating it and bumping last_seen_at), and it
sat in the pending list until the staleness sweep.
"""

import os
import sqlite3
import sys
import tempfile
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import (  # noqa: E402
    BASE, _HEADINGS_JS, _GRID_CARD_SELECTOR, _PRICE_HEADING_SELECTOR,
    _SIMILAR_GRID_MIN_PRICES, _is_similar_listings_page, _scrape_detail_page,
)

NBSP = " "
URL = BASE + "/detail/JuS4u4DYlpK"


def _eur(v: int) -> str:
    return f"{v:,}".replace(",", NBSP) + " €"


# 28 distinct prices, as the similar-listings grid showed them.
GRID = [_eur(150_000 + 7_300 * i) for i in range(28)]


# ── The page-level verdict ────────────────────────────────────────────────────
class TestIsSimilarListingsPage:
    def test_the_expired_page(self):
        """No own price heading, a grid of 28 priced cards."""
        assert _is_similar_listings_page(URL, [], GRID) is True

    def test_card_titles_outside_the_grid_do_not_count_as_a_price(self):
        own = ["Podobné inzeráty", "3-izbový byt, Ružinov", ""]
        assert _is_similar_listings_page(URL, own, GRID) is True

    def test_a_page_stating_its_own_price_is_live(self):
        """However many cards sit under it."""
        assert _is_similar_listings_page(URL, [_eur(342_000)], GRID) is False

    def test_a_labelled_own_price_is_live(self):
        assert _is_similar_listings_page(URL, [f"Cena: {_eur(342_000)}"], GRID) is False

    def test_an_own_price_of_any_amount_is_live(self):
        """The guard is "the page states a price", not "a plausible sale
        price" — a garage at €15 000 is still a listing on its page."""
        assert _is_similar_listings_page(URL, [_eur(15_000)], GRID) is False

    def test_a_developer_project_page_is_never_gone(self):
        """It lists its units' prices and states none of its own: the same
        shape as the grid, on a page that is very much live."""
        dev = BASE + "/detail/developersky-projekt/Ju7ib0Ch1k3"
        assert _is_similar_listings_page(dev, [], GRID) is False

    def test_a_short_list_is_not_the_grid(self):
        cards = GRID[:_SIMILAR_GRID_MIN_PRICES - 1]
        assert _is_similar_listings_page(URL, [], cards) is False

    def test_the_threshold_itself_counts(self):
        cards = GRID[:_SIMILAR_GRID_MIN_PRICES]
        assert _is_similar_listings_page(URL, [], cards) is True

    def test_threshold_is_on_distinct_prices(self):
        """Pages render each figure twice; 28 cards of three prices is not a
        grid of 28 listings."""
        cards = [_eur(200_000), _eur(250_000), _eur(300_000)] * 10
        assert _is_similar_listings_page(URL, [], cards) is False

    def test_a_card_container_still_counts_its_prices(self):
        """A wrapper whose text sweeps several cards confirms the grid; unlike
        the own price, nothing is written from it."""
        cards = [" ".join(GRID[:14]), " ".join(GRID[14:])]
        assert _is_similar_listings_page(URL, [], cards) is True

    def test_rents_and_per_m2_rates_are_not_grid_prices(self):
        cards = [f"{800 + i} €/mes." for i in range(20)]
        assert _is_similar_listings_page(URL, [], cards) is False

    def test_nothing_at_all(self):
        assert _is_similar_listings_page(URL, [], []) is False
        assert _is_similar_listings_page(URL, None, None) is False


class TestHeadingsJs:
    def test_tags_grid_cards_by_the_h5_variant(self):
        assert _GRID_CARD_SELECTOR == "[class*='MuiTypography-h5']"
        assert _GRID_CARD_SELECTOR in _HEADINGS_JS
        assert "innerText" in _HEADINGS_JS

    def test_the_price_selector_still_reaches_the_cards(self):
        """The cards have to be among the elements the heading read returns,
        or they could never be told apart from the listing's own price."""
        assert _GRID_CARD_SELECTOR in _PRICE_HEADING_SELECTOR


# ── The detail-page read ──────────────────────────────────────────────────────
class _DetailPage:
    """Stands in for a Playwright page on one detail URL."""

    def __init__(self, html="<html><title>Byt</title></html>", headings=(),
                 text="", heading_error=False):
        self.html = html
        self.headings = [list(h) for h in headings]
        self.text = text
        self.heading_error = heading_error
        self.url = ""

    def goto(self, url, **kw):
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self.html

    def evaluate(self, js):
        return self.text

    def eval_on_selector_all(self, selector, js):
        assert selector == _PRICE_HEADING_SELECTOR and js == _HEADINGS_JS
        if self.heading_error:
            raise RuntimeError("Execution context was destroyed")
        return self.headings


EXPIRED_TEXT = ("Inzerát\nPodobné inzeráty\n"
                + "\n".join(f"2-izbový byt, Petržalka\n{p}" for p in GRID))


class TestScrapeDetailPage:
    def test_expired_page_comes_back_gone_and_nothing_else(self):
        """Its title, text and towns belong to the similar listings — the
        address scan would otherwise hand this row a neighbour's suburb."""
        page = _DetailPage(headings=[(p, True) for p in GRID], text=EXPIRED_TEXT)
        assert _scrape_detail_page(page, URL) == {"gone": True}

    def test_live_page_reads_its_price(self):
        headings = [(_eur(342_000), False)]
        detail = _scrape_detail_page(_DetailPage(headings=headings), URL)
        assert detail["price"] == 342_000.0
        assert "gone" not in detail

    def test_live_page_with_a_grid_below_is_not_gone(self):
        headings = [(_eur(342_000), False)] + [(p, True) for p in GRID]
        detail = _scrape_detail_page(_DetailPage(headings=headings), URL)
        assert "gone" not in detail

    def test_json_ld_price_means_the_page_describes_the_listing(self):
        html = ('<script type="application/ld+json">{"@type": "Product", '
                '"name": "Byt", "offers": {"price": 342000}}</script>')
        page = _DetailPage(html=html, headings=[(p, True) for p in GRID])
        detail = _scrape_detail_page(page, URL)
        assert detail["price"] == 342_000.0
        assert "gone" not in detail

    def test_developer_project_page_is_read_not_retired(self):
        dev = BASE + "/detail/developersky-projekt/Ju7ib0Ch1k3"
        page = _DetailPage(headings=[(p, True) for p in GRID], text=EXPIRED_TEXT)
        detail = _scrape_detail_page(page, dev)
        assert "gone" not in detail
        assert not detail.get("price")   # several prices, none its own

    def test_a_failed_heading_read_is_not_a_verdict(self):
        page = _DetailPage(heading_error=True, text=EXPIRED_TEXT)
        assert "gone" not in _scrape_detail_page(page, URL)

    def test_unloadable_page_is_not_a_verdict(self):
        assert _scrape_detail_page(_DetailPage(html=""), URL) == {}


# ── The daily scrape ──────────────────────────────────────────────────────────
class _SearchPage:
    def __init__(self, links):
        self.links = links

    def goto(self, url, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html></html>"

    def eval_on_selector_all(self, selector, js):
        return self.links


@pytest.fixture
def scraped_page(monkeypatch):
    """One search page with a live listing and one whose page is the grid."""
    from scraper import nehnutelnosti as n

    live, gone = BASE + "/detail/Live1", BASE + "/detail/Gone2"
    links = [{"href": live + "/byt-ruzinov", "text": "Byt"},
             {"href": gone + "/byt-petrzalka", "text": "Byt"}]
    details = {live: {"price": 342_000.0, "size": 82.0},
               gone: {"gone": True}}
    monkeypatch.setattr(n, "_scrape_detail_page", lambda pg, url: details[url])
    monkeypatch.setattr(n, "_parse_rsc_chunks", lambda html: [])
    result = n._scrape_page_playwright(_SearchPage(links), n._ApiCapture(), 1,
                                       set(), set())
    return result, live, gone


class TestScrapePageDropsGoneListings:
    def test_gone_listing_is_not_upserted(self, scraped_page):
        """An upsert sets is_active=1 — it would bring the row straight back."""
        (listings, _enriched, _touch, _gone), live, gone = scraped_page
        assert [r["url"] for r in listings] == [live]

    def test_gone_listing_is_handed_back_for_deactivation(self, scraped_page):
        (_listings, _enriched, _touch, gone_urls), _live, gone = scraped_page
        assert gone_urls == [gone]

    def test_gone_listing_is_not_stamped_as_enriched(self, scraped_page):
        (listings, enriched, _touch, _gone), _live, _gone_url = scraped_page
        assert enriched == [r["id"] for r in listings]


def _stub_run(monkeypatch, pages):
    """Run nehnutelnosti.run() against canned _scrape_page_playwright results,
    with a stand-in playwright module (CI doesn't install the real one)."""
    from scraper import nehnutelnosti as n

    class _Browser:
        def close(self):
            pass

    class _PW:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = _PW
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr(n, "_check_playwright", lambda: True)
    monkeypatch.setattr(n, "_open_browser", lambda pw: (_Browser(), None, None))
    monkeypatch.setattr(n, "get_fresh_detail_urls", lambda *a, **k: set())
    it = iter(pages)
    monkeypatch.setattr(n, "_scrape_page_playwright", lambda *a: next(it))
    monkeypatch.setattr(n, "upsert_listing", lambda listing: None)
    monkeypatch.setattr(n, "mark_details_enriched", lambda ids: len(ids))
    monkeypatch.setattr(n, "touch_listings", lambda urls: len(urls))
    deactivated: list[str] = []
    monkeypatch.setattr(n, "deactivate_listings",
                        lambda urls: deactivated.extend(urls) or len(urls))
    # The post-run housekeeping passes all hit the real DB.
    import engine.regional_prices as rp
    for fn in ("_deactivate_non_apartments", "_dedupe_canonical_urls",
               "_zero_bogus_prices", "_backfill_blank_districts"):
        monkeypatch.setattr(n, fn, lambda: 0)
    monkeypatch.setattr(rp, "zero_below_regional_floor", lambda source: 0)
    monkeypatch.setattr(rp, "zero_above_regional_ceiling", lambda source: 0)
    monkeypatch.setattr(n, "time",
                        types.SimpleNamespace(sleep=lambda s: None))
    return n, deactivated


class TestRunDeactivates:
    def test_gone_urls_are_deactivated(self, monkeypatch):
        listing = {"id": "a", "url": BASE + "/detail/A", "title": "Byt"}
        n, deactivated = _stub_run(monkeypatch, [
            ([listing], ["a"], [], [BASE + "/detail/Gone1"]),
            ([], [], [], [BASE + "/detail/Gone2"]),
        ])
        assert n.run(max_pages=2) == 1
        assert deactivated == [BASE + "/detail/Gone1", BASE + "/detail/Gone2"]

    def test_a_run_that_only_found_gone_listings_is_not_broken(self, monkeypatch):
        """It saw listings and acted on them — not the zero-match failure."""
        n, deactivated = _stub_run(monkeypatch, [([], [], [], [BASE + "/detail/G"])])
        assert n.run(max_pages=1) == 0
        assert deactivated == [BASE + "/detail/G"]

    def test_seeing_nothing_at_all_still_raises(self, monkeypatch):
        n, _ = _stub_run(monkeypatch, [([], [], [], [])])
        with pytest.raises(RuntimeError, match="0 listings"):
            n.run(max_pages=1)


# ── The database side ─────────────────────────────────────────────────────────
@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import database as db
    conn = sqlite3.connect(path)
    conn.executescript(db.SQLITE_SCHEMA)
    for rid, active in (("live", 1), ("gone", 1), ("retired", 0)):
        conn.execute(
            "INSERT INTO listings (id, source, url, title, price_eur, size_m2,"
            " district, classification, scraped_at, last_seen_at, is_active)"
            " VALUES (?, 'nehnutelnosti', ?, 'Byt', 0, 70, '', 'PENDING',"
            " '2026-09-01', '2026-09-01', ?)",
            (rid, f"http://x/{rid}", active),
        )
    conn.commit()
    conn.close()

    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)
    yield path
    os.unlink(path)


def _active(path, rid):
    conn = sqlite3.connect(path)
    v = conn.execute("SELECT is_active FROM listings WHERE id=?", (rid,)).fetchone()[0]
    conn.close()
    return v


class TestDeactivateListings:
    def test_deactivates_by_url(self, temp_db):
        import database as db
        assert db.deactivate_listings(["http://x/gone"]) == 1
        assert _active(temp_db, "gone") == 0
        assert _active(temp_db, "live") == 1

    def test_already_inactive_is_not_counted(self, temp_db):
        import database as db
        assert db.deactivate_listings(["http://x/retired"]) == 0

    def test_unknown_and_empty_input(self, temp_db):
        import database as db
        assert db.deactivate_listings(["http://x/nope"]) == 0
        assert db.deactivate_listings([]) == 0
        assert db.deactivate_listings(None) == 0
        assert db.deactivate_listings(["", None]) == 0

    def test_an_upsert_brings_a_relisted_listing_back(self, temp_db):
        """Deactivation is not deletion: the listing reappearing in the
        search results re-activates it through the normal upsert."""
        import database as db
        db.deactivate_listings(["http://x/gone"])
        db.upsert_listing({
            "id": "gone", "source": "nehnutelnosti", "url": "http://x/gone",
            "url_hash": "gone", "title": "Byt", "description": "",
            "price_eur": 199_000.0, "size_m2": 70.0, "rooms": None,
            "floor": None, "year_built": None, "energy_class": "UNKNOWN",
            "address_raw": "", "district": "", "city": "",
            "primary_image_url": "", "image_urls": "",
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": "2026-09-24", "last_seen_at": "2026-09-24",
        })
        assert _active(temp_db, "gone") == 1


# ── repair_prices.py ──────────────────────────────────────────────────────────
class TestRepairDecide:
    """The "no single price" branch splits: a gone page is deactivated, any
    other page with no single price is still cleared to PENDING."""

    def _p(self, **kw):
        return {"id": "x", "old": 1_399_000.0, "price": 0.0, "gone": False, **kw}

    def test_gone_is_deactivated_without_a_price_write(self):
        from repair_prices import decide
        assert decide(self._p(gone=True), set()) == ("deactivated", None)

    def test_no_single_price_is_still_cleared(self):
        """A dev-project unit list states several prices and is not gone."""
        from repair_prices import decide
        assert decide(self._p(), set()) == ("cleared", 0)

    def test_other_outcomes_unchanged(self):
        from repair_prices import decide
        assert decide(self._p(price=342_000.0), {"x"}) == ("rejected", 0)
        assert decide(self._p(price=1_399_000.0), set()) == ("confirmed", None)
        assert decide(self._p(price=342_000.0), set()) == ("corrected", 342_000.0)

    def test_proposals_from_before_the_flag_still_decide(self):
        from repair_prices import decide
        p = {"id": "x", "old": 1.0, "price": 0.0}
        assert decide(p, set()) == ("cleared", 0)


# ── enrich_pending.py ─────────────────────────────────────────────────────────
ROW = {
    "id": "gone", "source": "nehnutelnosti", "url": "http://x/gone",
    "url_hash": "gone", "title": "Byt", "price_eur": 0.0, "size_m2": 70.0,
    "energy_class": "UNKNOWN", "address_raw": "", "district": "",
    "primary_image_url": "",
}


class TestEnrichPendingSettle:
    def test_gone_listing_is_deactivated_not_upserted(self, temp_db, monkeypatch):
        """The old path upserted it, which set is_active=1 and bumped
        last_seen_at — keeping a dead listing alive past the sweep."""
        import enrich_pending as ep
        monkeypatch.setattr(ep, "upsert_listing",
                            lambda listing: pytest.fail("gone listing upserted"))
        assert ep.settle(ROW, {"gone": True}, "2026-09-24") == {"gone"}
        assert _active(temp_db, "gone") == 0

    def test_dry_run_writes_nothing(self, temp_db, monkeypatch):
        import enrich_pending as ep
        monkeypatch.setattr(ep, "upsert_listing",
                            lambda listing: pytest.fail("dry run upserted"))
        assert ep.settle(ROW, {"gone": True}, "now", dry_run=True) == {"gone"}
        assert _active(temp_db, "gone") == 1
        assert ep.settle(ROW, {"price": 199_000.0}, "now", dry_run=True) == {"price"}

    def test_empty_read_changes_nothing(self, temp_db, monkeypatch):
        import enrich_pending as ep
        monkeypatch.setattr(ep, "upsert_listing",
                            lambda listing: pytest.fail("empty read upserted"))
        assert ep.settle(ROW, {}, "now") == set()

    def test_a_read_is_upserted_and_reported(self, temp_db):
        import enrich_pending as ep
        filled = ep.settle(ROW, {"price": 199_000.0, "address": "Petržalka, Bratislava"},
                           "2026-09-24")
        assert filled == {"price", "district"}
        conn = sqlite3.connect(temp_db)
        price, district = conn.execute(
            "SELECT price_eur, district FROM listings WHERE id='gone'").fetchone()
        conn.close()
        assert price == 199_000.0 and district == "Bratislava"

    @pytest.mark.parametrize("argv,limit,dry", [
        ([], 200, False), (["600"], 600, False),
        (["--dry-run"], 200, True), (["50", "--dry-run"], 50, True),
    ])
    def test_args(self, argv, limit, dry):
        import enrich_pending as ep
        assert ep._parse_args(argv) == (limit, dry)

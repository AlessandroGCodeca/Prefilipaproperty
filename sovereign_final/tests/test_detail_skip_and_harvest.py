"""Tests for the two scrape-run savings on nehnutelnosti.sk:

1. Detail pages are the expensive step (one browser navigation each), so a
   listing whose detail page was read recently — and that already has price +
   size — is skipped on the next run. database.get_fresh_detail_urls /
   mark_details_enriched carry that state.
2. Detail pages fire their own API calls (dev-project unit lists) that return
   fully structured listings the search page never showed. Those responses
   were being captured and thrown away; _harvest_api_listings keeps them.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import (  # noqa: E402
    _ApiCapture, _api_item_url, _harvest_api_listings, _parse_api_item, BASE,
)

NOW = "2026-01-01T00:00:00+00:00"


# ── API item URL resolution ───────────────────────────────────────────────────
class TestApiItemUrl:
    def test_prefers_real_url_field(self):
        url, real = _api_item_url({"url": "https://www.nehnutelnosti.sk/detail/A1/byt", "id": "X"})
        assert url == "https://www.nehnutelnosti.sk/detail/A1/byt"
        assert real is True

    def test_relative_url_is_absolutised(self):
        url, real = _api_item_url({"seoUrl": "/detail/A1/byt-ruzinov"})
        assert url == BASE + "/detail/A1/byt-ruzinov"
        assert real is True

    def test_id_only_item_is_flagged_as_guessed(self):
        url, real = _api_item_url({"id": "Ju9cw3H1PgW"})
        assert url == BASE + "/detail/Ju9cw3H1PgW"
        assert real is False

    def test_empty_item(self):
        assert _api_item_url({}) == ("", False)

    def test_guessed_url_matches_canonical_form(self):
        """An id-only item and the same listing's slug URL must reduce to one
        row, otherwise harvesting would duplicate every listing it finds."""
        from scraper.nehnutelnosti import _canonical_url
        guessed, _ = _api_item_url({"id": "Ju9cw3H1PgW"})
        slugged = _canonical_url(BASE + "/detail/Ju9cw3H1PgW/3-izbovy-byt-ruzinov")
        assert guessed == slugged


class TestRequireUrlField:
    def test_id_only_item_dropped_when_url_required(self):
        assert _parse_api_item({"id": "X1"}, NOW, require_url_field=True) is None

    def test_id_only_item_kept_by_default(self):
        rec = _parse_api_item({"id": "X1"}, NOW)
        assert rec is not None and rec["url"] == BASE + "/detail/X1"

    def test_real_url_item_kept_either_way(self):
        item = {"url": "/detail/X1/byt", "price": {"value": 150000}, "usableArea": 60}
        for require in (True, False):
            rec = _parse_api_item(item, NOW, require_url_field=require)
            assert rec is not None
            assert rec["price_eur"] == 150000
            assert rec["size_m2"] == 60


# ── Harvesting ────────────────────────────────────────────────────────────────
class TestHarvestApiListings:
    def test_extends_seen_and_returns_records(self):
        seen: set[str] = set()
        items = [{"url": "/detail/A1/x"}, {"url": "/detail/B2/y"}]
        out = _harvest_api_listings(items, seen, NOW)
        assert len(out) == 2
        assert seen == {BASE + "/detail/A1", BASE + "/detail/B2"}

    def test_skips_urls_already_seen(self):
        seen = {BASE + "/detail/A1"}
        out = _harvest_api_listings([{"url": "/detail/A1/x"}], seen, NOW)
        assert out == []

    def test_dedupes_within_one_batch(self):
        """The same unit turns up in several dev-project responses."""
        seen: set[str] = set()
        items = [{"url": "/detail/A1/slug-one"}, {"url": "/detail/A1/slug-two"}]
        assert len(_harvest_api_listings(items, seen, NOW)) == 1

    def test_drops_id_only_items_when_url_required(self):
        seen: set[str] = set()
        items = [{"id": "A1"}, {"url": "/detail/B2/y"}]
        out = _harvest_api_listings(items, seen, NOW, require_url_field=True)
        assert [r["url"] for r in out] == [BASE + "/detail/B2"]

    def test_tolerates_junk(self):
        seen: set[str] = set()
        assert _harvest_api_listings([None, "x", 5, {}], seen, NOW) == []
        assert _harvest_api_listings(None, seen, NOW) == []


# ── Response capture ──────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, url, payload, status=200, ctype="application/json"):
        self.url = url
        self.status = status
        self.headers = {"content-type": ctype}
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TestLooksLikeListings:
    """The site's dropdown endpoints return id/name lists under the same keys
    _extract_items_from_json looks for. One of them — /api/v2/advertisement/
    detail/report/form-categories — matches API_SIGNALS on every detail page,
    so a live run logged it ~130 times in a single scrape."""

    def test_report_form_categories_rejected(self):
        from scraper.nehnutelnosti import _looks_like_listings
        assert _looks_like_listings([{"id": i, "name": f"reason {i}"}
                                     for i in range(9)]) is False

    def test_label_value_dropdown_rejected(self):
        from scraper.nehnutelnosti import _looks_like_listings
        assert _looks_like_listings([{"value": 1, "label": "Spam"}]) is False

    @pytest.mark.parametrize("item", [
        {"url": "/detail/A1/x"},
        {"seoUrl": "/detail/A1/x"},
        {"price": {"value": 150000}},
        {"id": "A1", "usableArea": 55},
        {"id": "A1", "advertId": "B2"},
    ])
    def test_listing_shaped_items_accepted(self, item):
        from scraper.nehnutelnosti import _looks_like_listings
        assert _looks_like_listings([item]) is True

    def test_scans_past_a_leading_junk_item(self):
        from scraper.nehnutelnosti import _looks_like_listings
        items = [{"id": 1, "name": "x"}, {"url": "/detail/A1/x"}]
        assert _looks_like_listings(items) is True

    def test_empty_and_non_dict_items(self):
        from scraper.nehnutelnosti import _looks_like_listings
        assert _looks_like_listings([]) is False
        assert _looks_like_listings(["x", 5, None]) is False


class TestApiCapture:
    def test_dropdown_endpoint_is_not_captured(self):
        """The noise that drowned the live run's log."""
        cap = _ApiCapture()
        cap(_FakeResponse(
            BASE + "/api/v2/advertisement/detail/report/form-categories",
            {"items": [{"id": i, "name": f"reason {i}"} for i in range(9)]},
        ))
        assert cap.items == []

    def test_captures_listing_api_json(self):
        cap = _ApiCapture()
        cap(_FakeResponse(BASE + "/api/v2/dev-projects/detail/X/advertisements",
                          {"advertisements": [{"url": "/detail/A1/x"}]}))
        assert len(cap.items) == 1

    def test_take_drains(self):
        cap = _ApiCapture()
        cap(_FakeResponse(BASE + "/api/v2/listing", {"items": [{"url": "/detail/A1/x"}]}))
        assert len(cap.take()) == 1
        assert cap.take() == []

    def test_ignores_errors_non_json_and_unrelated_urls(self):
        cap = _ApiCapture()
        cap(_FakeResponse(BASE + "/api/v2/listing", {"items": [{"url": "/x"}]}, status=500))
        cap(_FakeResponse(BASE + "/api/v2/listing", {"items": [{"url": "/x"}]}, ctype="text/html"))
        cap(_FakeResponse(BASE + "/static/bundle.json", {"items": [{"url": "/x"}]}))
        cap(_FakeResponse(BASE + "/api/v2/listing", None))
        assert cap.items == []


# ── Detail-scrape freshness bookkeeping ───────────────────────────────────────
@pytest.fixture
def temp_db(monkeypatch):
    """Isolated SQLite file with a listings table, patched into database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id            TEXT PRIMARY KEY,
            source        TEXT NOT NULL,
            url           TEXT NOT NULL UNIQUE,
            price_eur     REAL NOT NULL,
            size_m2       REAL,
            scraped_at    TEXT NOT NULL,
            last_seen_at  TEXT NOT NULL,
            is_active     INTEGER DEFAULT 1
        )
    """)
    now = datetime.now(timezone.utc)
    # (id, price, size, enriched_days_ago | None, is_active)
    rows = [
        ("complete-fresh",  150000, 60,  1,    1),
        ("complete-old",    150000, 60,  30,   1),
        ("never-enriched",  150000, 60,  None, 1),
        ("no-price",        0,      60,  1,    1),
        ("no-size",         150000, 0,   1,    1),
        ("inactive",        150000, 60,  1,    0),
    ]
    for rid, price, size, days_ago, active in rows:
        stamp = now.isoformat()
        conn.execute("""
            INSERT INTO listings (id, source, url, price_eur, size_m2,
                                  scraped_at, last_seen_at, is_active)
            VALUES (?, 'nehnutelnosti', ?, ?, ?, ?, ?, ?)
        """, (rid, f"http://x/{rid}", price, size, stamp, stamp, active))
    # Another source must never leak into the nehnutelnosti set
    conn.execute("""
        INSERT INTO listings (id, source, url, price_eur, size_m2,
                              scraped_at, last_seen_at, is_active)
        VALUES ('other-src', 'topreality', 'http://x/other', 150000, 60, ?, ?, 1)
    """, (now.isoformat(), now.isoformat()))
    conn.commit()
    conn.close()

    import database as db

    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)

    # Stamp detail_enriched_at via the real helper so the column is created the
    # same way production does it.
    for rid, _, _, days_ago, _active in rows:
        if days_ago is not None:
            db.mark_details_enriched([rid], when=(now - timedelta(days=days_ago)).isoformat())
    db.mark_details_enriched(["other-src"], when=now.isoformat())

    yield path
    os.unlink(path)


class TestGetFreshDetailUrls:
    def test_only_complete_recent_active_rows_of_this_source(self, temp_db):
        import database as db
        assert db.get_fresh_detail_urls("nehnutelnosti", max_age_days=7) == {
            "http://x/complete-fresh"
        }

    def test_widening_the_window_lets_older_rows_back_in(self, temp_db):
        import database as db
        urls = db.get_fresh_detail_urls("nehnutelnosti", max_age_days=60)
        assert urls == {"http://x/complete-fresh", "http://x/complete-old"}

    def test_other_source_is_isolated(self, temp_db):
        import database as db
        assert db.get_fresh_detail_urls("topreality") == {"http://x/other"}

    def test_unknown_source_is_empty(self, temp_db):
        import database as db
        assert db.get_fresh_detail_urls("bazos") == set()


class TestMarkDetailsEnriched:
    def test_stamps_and_counts(self, temp_db):
        import database as db
        assert db.mark_details_enriched(["never-enriched"]) == 1
        assert "http://x/never-enriched" in db.get_fresh_detail_urls("nehnutelnosti")

    def test_empty_and_missing_ids_are_safe(self, temp_db):
        import database as db
        assert db.mark_details_enriched([]) == 0
        assert db.mark_details_enriched(None) == 0
        assert db.mark_details_enriched(["", None]) == 0
        assert db.mark_details_enriched(["no-such-id"]) == 0


class TestTouchListings:
    def test_bumps_last_seen_and_reactivates(self, temp_db):
        import database as db
        before = _last_seen(temp_db, "inactive")
        assert db.touch_listings(["http://x/inactive"]) == 1
        assert _last_seen(temp_db, "inactive") > before
        assert _is_active(temp_db, "inactive") == 1

    def test_unknown_url_is_a_noop(self, temp_db):
        import database as db
        assert db.touch_listings(["http://x/nope"]) == 0

    def test_empty_input_is_safe(self, temp_db):
        import database as db
        assert db.touch_listings([]) == 0
        assert db.touch_listings(None) == 0
        assert db.touch_listings(["", None]) == 0


def _last_seen(path, rid):
    conn = sqlite3.connect(path)
    v = conn.execute("SELECT last_seen_at FROM listings WHERE id=?", (rid,)).fetchone()[0]
    conn.close()
    return v


def _is_active(path, rid):
    conn = sqlite3.connect(path)
    v = conn.execute("SELECT is_active FROM listings WHERE id=?", (rid,)).fetchone()[0]
    conn.close()
    return v


def _stub_cleanup(monkeypatch, module):
    """Silence the post-run housekeeping passes — they all hit the real DB and
    none of them is what these tests are about."""
    import engine.regional_prices as rp
    for fn in ("_deactivate_non_apartments", "_deactivate_category_pages",
               "_zero_bogus_prices", "_backfill_blank_districts"):
        monkeypatch.setattr(module, fn, lambda: 0)
    monkeypatch.setattr(rp, "zero_below_regional_floor", lambda source: 0)
    monkeypatch.setattr(module, "time",
                        type("T", (), {"sleep": staticmethod(lambda s: None)}))


# ── Topreality: same skip, over plain HTTP ────────────────────────────────────
class TestTopRealityRun:
    @pytest.fixture
    def run_result(self, monkeypatch):
        """A 1-page topreality run where one of the two listings is already
        fresh in the DB."""
        from scraper import topreality as t

        fresh = "https://www.topreality.sk/byt-a-r111111.html"
        stale = "https://www.topreality.sk/byt-b-r222222.html"
        fetched: list[str] = []
        touched: list[str] = []

        def _fake_fetch(url, sess=None):
            fetched.append(url)
            return 200, "<html></html>"

        monkeypatch.setattr(t, "make_session", lambda base: None)
        monkeypatch.setattr(t, "_detect_search_url", lambda sess: "http://s/?page={page}")
        monkeypatch.setattr(t, "_fetch", _fake_fetch)
        monkeypatch.setattr(t, "_extract_listing_links", lambda html: [fresh, stale])
        monkeypatch.setattr(t, "get_fresh_detail_urls", lambda *a, **k: {fresh})
        monkeypatch.setattr(t, "touch_listings", lambda urls: touched.extend(urls) or len(urls))
        monkeypatch.setattr(t, "_build_listing_from_detail",
                            lambda url, html, now: {"id": "id-" + url[-12:-5], "url": url})
        monkeypatch.setattr(t, "upsert_listing", lambda listing: None)
        monkeypatch.setattr(t, "mark_details_enriched", lambda ids: len(ids))
        _stub_cleanup(monkeypatch, t)

        total = t.run(max_pages=1)
        return total, fetched, touched, fresh, stale

    def test_only_the_stale_detail_page_is_fetched(self, run_result):
        _total, fetched, _touched, fresh, stale = run_result
        assert stale in fetched
        assert fresh not in fetched

    def test_skipped_listing_is_touched_instead(self, run_result):
        _total, _fetched, touched, fresh, _stale = run_result
        assert touched == [fresh]

    def test_counts_only_real_upserts(self, run_result):
        total, _fetched, _touched, _fresh, _stale = run_result
        assert total == 1


def test_all_fresh_run_does_not_raise(monkeypatch):
    """A day where every listing is already fresh upserts nothing. That must
    not look like a broken scraper — the old code raised on total == 0."""
    from scraper import topreality as t

    urls = ["https://www.topreality.sk/byt-a-r111111.html"]
    monkeypatch.setattr(t, "make_session", lambda base: None)
    monkeypatch.setattr(t, "_detect_search_url", lambda sess: "http://s/?page={page}")
    monkeypatch.setattr(t, "_fetch", lambda url, sess=None: (200, "<html></html>"))
    monkeypatch.setattr(t, "_extract_listing_links", lambda html: urls)
    monkeypatch.setattr(t, "get_fresh_detail_urls", lambda *a, **k: set(urls))
    monkeypatch.setattr(t, "touch_listings", lambda u: len(u))
    monkeypatch.setattr(t, "mark_details_enriched", lambda ids: len(ids))
    _stub_cleanup(monkeypatch, t)

    assert t.run(max_pages=1) == 0


def test_genuinely_empty_run_still_raises(monkeypatch):
    """Nothing seen at all is still a real failure worth shouting about."""
    from scraper import topreality as t

    monkeypatch.setattr(t, "make_session", lambda base: None)
    monkeypatch.setattr(t, "_detect_search_url", lambda sess: "http://s/?page={page}")
    monkeypatch.setattr(t, "_fetch", lambda url, sess=None: (200, "<html></html>"))
    monkeypatch.setattr(t, "_extract_listing_links", lambda html: [])
    monkeypatch.setattr(t, "get_fresh_detail_urls", lambda *a, **k: set())
    monkeypatch.setattr(t, "mark_details_enriched", lambda ids: len(ids))
    _stub_cleanup(monkeypatch, t)

    with pytest.raises(RuntimeError, match="0 listings parsed"):
        t.run(max_pages=1)


# ── Whole-page orchestration against a fake browser ───────────────────────────
class _FakePage:
    """Stands in for a Playwright page: records navigations and replays the API
    responses a real detail page would fire."""

    def __init__(self, dom_links_by_page, capture, api_by_detail):
        self.dom_links_by_page = dom_links_by_page
        self.capture = capture
        self.api_by_detail = api_by_detail
        self.current = ""
        self.goto_log: list[str] = []

    def goto(self, url, **kw):
        self.goto_log.append(url)
        self.current = url
        for item in self.api_by_detail.get(url, []):
            self.capture.items.append(item)

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html></html>"

    def eval_on_selector_all(self, selector, js):
        return self.dom_links_by_page[int(self.current.rsplit("page=", 1)[1])]

    @property
    def detail_visits(self):
        return [u for u in self.goto_log if "page=" not in u]


@pytest.fixture
def two_page_run(monkeypatch):
    """A 2-page scrape where page 1 and 2 share a promoted listing, one listing
    is linked under two slugs, one is already fresh in the DB, and one detail
    page reveals sibling units through a dev-project API call."""
    from scraper import nehnutelnosti as n

    capture = n._ApiCapture()
    dom = {
        1: [{"href": BASE + "/detail/A1/byt-ruzinov", "text": "A1"},
            {"href": BASE + "/detail/A1/byt-ruzinov-2", "text": "A1 other slug"},
            {"href": BASE + "/detail/B2/byt-petrzalka", "text": "B2"}],
        2: [{"href": BASE + "/detail/A1/byt-ruzinov", "text": "A1 again"},
            {"href": BASE + "/detail/C3/byt-kosice", "text": "C3"}],
    }
    api_by_detail = {
        BASE + "/detail/B2": [
            {"url": "/detail/D4/novostavba", "price": {"value": 180000}, "usableArea": 55},
            {"id": "E5"},  # no URL field — must not be stored behind a guess
        ],
    }
    page = _FakePage(dom, capture, api_by_detail)

    def _fake_detail(pg, url):
        pg.goto(url)  # the real _scrape_detail_page navigates; that fires the API
        return {"price": 200000.0, "size": 70.0, "title": "Byt"}

    monkeypatch.setattr(n, "_scrape_detail_page", _fake_detail)
    monkeypatch.setattr(n, "_parse_rsc_chunks", lambda html: [])

    seen: set[str] = set()
    fresh = {BASE + "/detail/C3"}
    pages = [n._scrape_page_playwright(page, capture, p, seen, fresh) for p in (1, 2)]
    return page, seen, pages


class TestScrapePageOrchestration:
    def test_duplicate_slugs_collapse_to_one_listing(self, two_page_run):
        _page, _seen, pages = two_page_run
        urls = [r["url"] for r in pages[0][0]]
        assert urls.count(BASE + "/detail/A1") == 1

    def test_listing_repeated_on_page_two_is_not_revisited(self, two_page_run):
        page, _seen, pages = two_page_run
        assert page.detail_visits.count(BASE + "/detail/A1") == 1
        # Page 2 carried A1 again and C3; A1 is deduped away and C3 is fresh.
        assert [r["url"] for r in pages[1][0]] == []

    def test_fresh_listing_is_touched_not_upserted(self, two_page_run):
        page, _seen, pages = two_page_run
        listings, enriched, touch = pages[1]
        # It is not upserted — a card-text record would overwrite better data.
        assert listings == []
        # It is touched instead, so the staleness sweep leaves it alone...
        assert touch == [BASE + "/detail/C3"]
        # ...and its detail page was never loaded, so nothing is stamped.
        assert BASE + "/detail/C3" not in page.detail_visits
        assert enriched == []

    def test_detail_page_api_yields_an_extra_listing(self, two_page_run):
        _page, _seen, pages = two_page_run
        harvested = [r for r in pages[0][0] if r["url"] == BASE + "/detail/D4"]
        assert len(harvested) == 1
        # It arrives with real data, so it needs no detail visit of its own.
        assert harvested[0]["price_eur"] == 180000
        assert harvested[0]["size_m2"] == 55

    def test_id_only_api_item_is_not_stored(self, two_page_run):
        _page, seen, _pages = two_page_run
        assert BASE + "/detail/E5" not in seen

    def test_only_enriched_listings_are_stamped(self, two_page_run):
        _page, _seen, pages = two_page_run
        assert sorted(pages[0][1]) == sorted(
            r["id"] for r in pages[0][0] if r["url"] in (BASE + "/detail/A1", BASE + "/detail/B2")
        )

"""Tests for recovering the district that the canonical URL throws away.

_parse_slug() reads the town out of a listing's URL slug, but the URL stored
is canonical: _canonical_url() drops the slug so every variant of a listing
lands on one row. _minimal_listing() canonicalised the search card's href
before anything read it, so _apply_detail()'s slug fallback always ran on
/detail/{id} and found nothing. Of 544 nehnutelnosti rows, 195 have no slug to
read, and a blank district scores at the €6.50/m² default rent — half what a
Bratislava flat earns.

Recovered here from two places, neither touching _canonical_url():
  - the search card's href, read before it is canonicalised;
  - the listing's own page, which names its slugged address — accepted only
    when paired with the listing's own id, never a neighbour's link.

And a district filled in drops the cashflow score worked out without it, or
the €6.50/m² figure would stay on the row regardless.
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import (  # noqa: E402
    BASE, _apply_detail, _canonical_url, _minimal_listing, _own_slug_url,
    _parse_rsc_chunks, _scrape_detail_page, _PRICE_HEADING_SELECTOR,
)

OWN_ID = "Ju9cw3H1PgW"
URL = BASE + f"/detail/{OWN_ID}"
SLUG = "3-izbovy-byt-na-predaj-petrzalka-bratislava"


# ── The listing's own slug, off its page ──────────────────────────────────────
class TestOwnSlugUrl:
    def test_from_the_canonical_link(self):
        html = f'<link rel="canonical" href="{BASE}/detail/{OWN_ID}/{SLUG}"/>'
        assert _own_slug_url(URL, html) == f"{URL}/{SLUG}"

    def test_from_the_final_url_after_a_redirect(self):
        assert _own_slug_url(URL, "", f"{URL}/{SLUG}") == f"{URL}/{SLUG}"

    def test_from_a_relative_link(self):
        html = f'<a href="/detail/{OWN_ID}/{SLUG}">'
        assert _own_slug_url(URL, html) == f"{URL}/{SLUG}"

    def test_a_neighbours_slug_is_never_taken(self):
        """Every page links other listings. Taking the first slug on it would
        give this row the carousel's town."""
        html = ('<a href="/detail/JuOther0001/2-izbovy-byt-kosice">'
                '<a href="/detail/JuOther0002/byt-zilina">')
        assert _own_slug_url(URL, html) == ""

    def test_own_slug_found_among_neighbours(self):
        html = (f'<a href="/detail/JuOther0001/2-izbovy-byt-kosice">'
                f'<meta property="og:url" content="{BASE}/detail/{OWN_ID}/{SLUG}">')
        assert _own_slug_url(URL, html) == f"{URL}/{SLUG}"

    def test_an_id_that_merely_starts_with_ours_is_not_ours(self):
        html = f'<a href="/detail/{OWN_ID}X/byt-kosice">'
        assert _own_slug_url(URL, html) == ""

    def test_a_segment_without_hyphens_is_not_a_slug(self):
        """_parse_slug's own definition: a slug is hyphenated."""
        html = f'<a href="/detail/{OWN_ID}/foto">'
        assert _own_slug_url(URL, html) == ""

    def test_stored_url_that_still_has_its_slug(self):
        stored = f"{URL}/stary-slug-ruzinov"
        html = f'<link rel="canonical" href="{URL}/{SLUG}"/>'
        assert _own_slug_url(stored, html) == f"{URL}/{SLUG}"

    def test_developer_project_path(self):
        dev = BASE + "/detail/developersky-projekt/Ju7ib0Ch1k3"
        html = f'<link rel="canonical" href="{dev}/corvus-atrium-malacky"/>'
        assert _own_slug_url(dev, html) == f"{dev}/corvus-atrium-malacky"

    def test_not_a_detail_url(self):
        assert _own_slug_url("https://x/other", f"/detail/{OWN_ID}/{SLUG}") == ""
        assert _own_slug_url("", "") == ""

    def test_a_non_string_final_url_is_ignored(self):
        assert _own_slug_url(URL, "", None) == ""
        assert _own_slug_url(URL, "", object()) == ""

    def test_canonical_url_is_unchanged(self):
        """Slug-less /detail/{id} loads the same listing; the stored form and
        the row identity it feeds stay exactly as they were."""
        assert _canonical_url(f"{URL}/{SLUG}") == URL
        assert _canonical_url(URL) == URL


class _DetailPage:
    def __init__(self, html, headings=(), text="", final_url=None):
        self.html, self.headings, self.text = html, list(headings), text
        self.final_url, self.url = final_url, ""

    def goto(self, url, **kw):
        self.url = self.final_url or url

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self.html

    def evaluate(self, js):
        return self.text

    def eval_on_selector_all(self, selector, js):
        assert selector == _PRICE_HEADING_SELECTOR
        return self.headings


class TestDetailPageReportsItsSlug:
    def test_canonical_link_is_reported(self):
        html = f'<html><link rel="canonical" href="{URL}/{SLUG}"/></html>'
        detail = _scrape_detail_page(_DetailPage(html), URL)
        assert detail["slug_url"] == f"{URL}/{SLUG}"

    def test_redirect_is_reported(self):
        page = _DetailPage("<html></html>", final_url=f"{URL}/{SLUG}")
        assert _scrape_detail_page(page, URL)["slug_url"] == f"{URL}/{SLUG}"

    def test_no_own_link_reports_nothing(self):
        html = '<html><a href="/detail/JuOther0001/byt-kosice"></a></html>'
        assert "slug_url" not in _scrape_detail_page(_DetailPage(html), URL)


# ── Applying it ───────────────────────────────────────────────────────────────
def _blank(url=URL):
    listing = _minimal_listing(url, "Byt", "2026-09-24")
    listing["district"] = listing["address_raw"] = ""
    return listing


class TestApplyDetailUsesThePageSlug:
    def test_slugless_row_gets_its_town(self):
        listing = _blank()
        _apply_detail(listing, {"slug_url": f"{URL}/{SLUG}", "price": 199_000.0})
        assert listing["district"] == "Petržalka, Bratislava"
        assert listing["url"] == URL          # stored URL untouched

    def test_a_stated_address_still_wins(self):
        """Precedence is unchanged: the slug only fills what the page left blank."""
        listing = _blank()
        _apply_detail(listing, {"slug_url": f"{URL}/{SLUG}", "address": "Hlavná 5, Košice"})
        assert listing["district"] == "Košice"

    def test_without_a_page_slug_the_stored_url_is_used(self):
        listing = _blank(f"{URL}/byt-zilina")
        listing["url"] = f"{URL}/byt-zilina"   # a legacy row that kept its slug
        _apply_detail(listing, {"price": 150_000.0})
        assert listing["district"] == "Žilina"

    def test_generic_title_replaced_from_the_page_slug(self):
        listing = _blank()
        listing["title"] = "PREMIUM"
        _apply_detail(listing, {"slug_url": f"{URL}/{SLUG}"})
        assert listing["title"].lower().startswith("3 izbovy byt")


class TestSearchCardSlugIsKept:
    def test_minimal_listing_reads_the_town_before_canonicalising(self):
        rec = _minimal_listing(f"{URL}/{SLUG}", "Byt", "now")
        assert rec["url"] == URL
        assert rec["district"] == "Petržalka, Bratislava"
        assert rec["address_raw"] == "Petržalka, Bratislava"

    def test_a_slug_naming_no_town_leaves_it_blank(self):
        rec = _minimal_listing(f"{URL}/moderny-3-izbovy-byt", "Byt", "now")
        assert rec["district"] == ""

    def test_id_is_still_the_canonical_hash(self):
        a = _minimal_listing(f"{URL}/{SLUG}", "", "now")
        b = _minimal_listing(URL, "", "now")
        assert a["id"] == b["id"] and a["url"] == b["url"]

    def test_rsc_items_keep_the_href(self):
        html = ('<script>self.__next_f.push([1,"'
                f'\\"href\\":\\"/detail/{OWN_ID}/{SLUG}\\"'
                '"])</script>')
        items = _parse_rsc_chunks(html)
        assert items and items[0]["_url"] == URL
        assert items[0]["_href"] == f"{BASE}/detail/{OWN_ID}/{SLUG}"


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


def test_scrape_keeps_the_card_town_when_the_page_names_none(monkeypatch):
    """The live path end to end: the card links the slug, the detail page
    states a price but no address and no slug of its own."""
    from scraper import nehnutelnosti as n
    monkeypatch.setattr(n, "_scrape_detail_page",
                        lambda pg, url: {"price": 199_000.0, "size": 60.0})
    monkeypatch.setattr(n, "_parse_rsc_chunks", lambda html: [])
    links = [{"href": f"{URL}/{SLUG}", "text": "3-izbový byt"}]
    listings, *_ = n._scrape_page_playwright(_SearchPage(links), n._ApiCapture(),
                                             1, set(), set())
    assert listings[0]["url"] == URL
    assert listings[0]["district"] == "Petržalka, Bratislava"


# ── A filled district drops the score worked out without it ───────────────────
@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import database as db
    conn = sqlite3.connect(path)
    conn.executescript(db.SQLITE_SCHEMA)
    rows = [
        # id, url, district, classification, scored
        ("blank-scored",   f"{URL}",                    "",          "GREEN",   True),
        ("blank-unscored", BASE + "/detail/JuB2",       "",          "PENDING", False),
        ("known",          BASE + "/detail/JuK3",       "Ružinov",   "YELLOW",  True),
        ("null-district",  BASE + "/detail/JuN4",       None,        "WHITE",   True),
    ]
    for rid, url, district, cls, scored in rows:
        conn.execute(
            "INSERT INTO listings (id, source, url, title, description, "
            " address_raw, price_eur, size_m2, district, classification, "
            " scraped_at, last_seen_at) VALUES (?, 'nehnutelnosti', ?, "
            " 'Byt', '', '', 199000, 60, ?, ?, '2026-09-01', '2026-09-01')",
            (rid, url, district, cls),
        )
        if scored:
            conn.execute(
                "INSERT INTO cashflow_scores (listing_id, classification) VALUES (?, ?)",
                (rid, cls),
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


def _row(path, rid):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM listings WHERE id=?", (rid,)).fetchone()
    scored = conn.execute(
        "SELECT COUNT(*) FROM cashflow_scores WHERE listing_id=?", (rid,)).fetchone()[0]
    conn.close()
    return r, scored


def _fill(db, rid, district, address=None):
    conn = db.get_conn()
    try:
        ok = db.fill_blank_district(conn, rid, district, address)
        conn.commit()
    finally:
        conn.close()
    return ok


class TestFillBlankDistrict:
    def test_fills_and_drops_the_stale_score(self, temp_db):
        import database as db
        assert _fill(db, "blank-scored", "Petržalka, Bratislava") is True
        row, scored = _row(temp_db, "blank-scored")
        assert row["district"] == "Petržalka, Bratislava"
        assert scored == 0
        assert row["classification"] == "PENDING"

    def test_null_district_counts_as_blank(self, temp_db):
        import database as db
        assert _fill(db, "null-district", "Košice") is True
        assert _row(temp_db, "null-district")[1] == 0

    def test_an_unscored_row_keeps_its_classification(self, temp_db):
        import database as db
        assert _fill(db, "blank-unscored", "Nitra") is True
        assert _row(temp_db, "blank-unscored")[0]["classification"] == "PENDING"

    def test_a_known_district_is_never_overwritten(self, temp_db):
        import database as db
        assert _fill(db, "known", "Košice") is False
        row, scored = _row(temp_db, "known")
        assert row["district"] == "Ružinov" and scored == 1
        assert row["classification"] == "YELLOW"

    def test_address_only_written_when_given(self, temp_db):
        import database as db
        _fill(db, "blank-scored", "Nitra")
        assert _row(temp_db, "blank-scored")[0]["address_raw"] == ""
        _fill(db, "blank-unscored", "Nitra", "Štúrova 3, Nitra")
        assert _row(temp_db, "blank-unscored")[0]["address_raw"] == "Štúrova 3, Nitra"

    def test_an_empty_resolution_is_a_noop(self, temp_db):
        import database as db
        assert _fill(db, "blank-scored", "") is False
        assert _row(temp_db, "blank-scored")[1] == 1


def _listing(rid, url, district):
    return {
        "id": rid, "source": "nehnutelnosti", "url": url, "url_hash": rid,
        "title": "Byt", "description": "", "price_eur": 0.0, "size_m2": 0.0,
        "rooms": None, "floor": None, "year_built": None,
        "energy_class": "UNKNOWN", "address_raw": "", "district": district,
        "city": "", "primary_image_url": "", "image_urls": "",
        "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": "2026-09-24", "last_seen_at": "2026-09-24",
    }


class TestUpsertDropsTheStaleScore:
    def test_district_arriving_on_a_blank_row(self, temp_db):
        import database as db
        db.upsert_listing(_listing("blank-scored", URL, "Petržalka, Bratislava"))
        row, scored = _row(temp_db, "blank-scored")
        assert row["district"] == "Petržalka, Bratislava"
        assert scored == 0 and row["classification"] == "PENDING"

    def test_a_blank_upsert_keeps_the_score(self, temp_db):
        import database as db
        db.upsert_listing(_listing("blank-scored", URL, ""))
        assert _row(temp_db, "blank-scored")[1] == 1

    def test_a_row_that_already_had_a_district_keeps_its_score(self, temp_db):
        import database as db
        db.upsert_listing(_listing("known", BASE + "/detail/JuK3", "Ružinov, Bratislava"))
        row, scored = _row(temp_db, "known")
        assert scored == 1 and row["classification"] == "YELLOW"

    def test_a_new_row(self, temp_db):
        import database as db
        db.upsert_listing(_listing("new", BASE + "/detail/JuNew", "Nitra"))
        assert _row(temp_db, "new")[0]["district"] == "Nitra"


class TestUpdateAddressDropsTheStaleScore:
    def test_resolved_district(self, temp_db):
        import database as db
        db.update_address("blank-scored", "Ružinov, Bratislava", "Bratislava")
        row, scored = _row(temp_db, "blank-scored")
        assert row["district"] == "Ružinov, Bratislava" and scored == 0

    def test_unresolved_keeps_the_score(self, temp_db):
        import database as db
        db.update_address("blank-scored", "", "")
        assert _row(temp_db, "blank-scored")[1] == 1


class TestBackfillsDropTheStaleScore:
    def test_nehnutelnosti(self, temp_db):
        from scraper import nehnutelnosti as n
        conn = sqlite3.connect(temp_db)
        conn.execute("UPDATE listings SET title='Byt Karlova Ves' WHERE id='blank-scored'")
        conn.commit()
        conn.close()
        assert n._backfill_blank_districts() == 1
        row, scored = _row(temp_db, "blank-scored")
        assert row["district"] == "Karlova Ves, Bratislava"
        assert row["address_raw"] == "Karlova Ves, Bratislava"
        assert scored == 0

    @pytest.mark.parametrize("module", ["bazos", "topreality"])
    def test_other_sources(self, temp_db, module):
        import importlib
        m = importlib.import_module(f"scraper.{module}")
        conn = sqlite3.connect(temp_db)
        conn.execute("UPDATE listings SET source=?, title='Predaj bytu Žilina' "
                     "WHERE id='blank-scored'", (module,))
        conn.commit()
        conn.close()
        assert m._backfill_blank_districts() == 1
        row, scored = _row(temp_db, "blank-scored")
        assert row["district"] == "Žilina" and scored == 0


# ── enrich_pending.py reaches the rows the daily scrape skips ────────────────
@pytest.fixture
def ep(temp_db, monkeypatch):
    """enrich_pending bound get_conn at import; point it at the temp DB too."""
    import database as db
    import enrich_pending
    monkeypatch.setattr(enrich_pending, "get_conn", db.get_conn)
    return enrich_pending


class TestEnrichPendingSelectsBlankDistricts:
    def test_priced_and_sized_rows_with_no_district_are_selected(self, ep):
        """get_fresh_detail_urls() treats these as complete, so the daily
        scrape never re-opens them; this is their only read."""
        ids = {r["id"] for r in ep.fetch_pending(100)}
        assert ids == {"blank-scored", "blank-unscored", "null-district"}

    def test_inactive_rows_are_not(self, ep, temp_db):
        conn = sqlite3.connect(temp_db)
        conn.execute("UPDATE listings SET is_active=0 WHERE id='blank-scored'")
        conn.commit()
        conn.close()
        assert "blank-scored" not in {r["id"] for r in ep.fetch_pending(100)}

    def test_a_filled_district_is_reported_and_unscored(self, ep, temp_db):
        row = next(r for r in ep.fetch_pending(100) if r["id"] == "blank-scored")
        filled = ep.settle(row, {"slug_url": f"{URL}/{SLUG}"}, "2026-09-24")
        assert filled == {"district"}
        r, scored = _row(temp_db, "blank-scored")
        assert r["district"] == "Petržalka, Bratislava" and scored == 0

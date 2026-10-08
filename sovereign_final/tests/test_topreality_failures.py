"""Topreality's failure messages say what failed.

Every failure used to read "the site likely changed its URL scheme", including
the ones where the connection never answered — which sent the reader off to
edit SEARCH_URL_CANDIDATES for what was a network or proxy problem.
"""

import pytest

from scraper import topreality as t

PAGE = "<html>" + "x" * 6000 + "</html>"        # over the 5,000-character stub limit


def _answer(monkeypatch, *replies):
    """_fetch answers with `replies` in turn, then repeats the last one."""
    queue = list(replies)
    monkeypatch.setattr(
        t, "_fetch",
        lambda url, sess=None: queue.pop(0) if len(queue) > 1 else queue[0])


def _detect_error(monkeypatch, *replies) -> str:
    _answer(monkeypatch, *replies)
    monkeypatch.setattr(t, "_extract_listing_links", lambda html: [])
    with pytest.raises(RuntimeError) as err:
        t._detect_search_url(None)
    return str(err.value)


def test_no_response_is_reported_as_a_network_problem(monkeypatch):
    msg = _detect_error(monkeypatch, (0, ""))
    assert "could not reach the site" in msg
    assert "changed its URL scheme" not in msg


def test_a_page_that_loads_without_listings_still_blames_the_site(monkeypatch):
    msg = _detect_error(monkeypatch, (200, PAGE))
    assert "loaded but held no listings" in msg
    assert "likely changed its URL scheme" in msg


def test_not_found_everywhere_still_blames_the_url_scheme(monkeypatch):
    msg = _detect_error(monkeypatch, (404, ""))
    assert "likely changed its URL scheme" in msg


def test_a_blocked_request_is_neither_a_network_nor_a_url_problem(monkeypatch):
    msg = _detect_error(monkeypatch, (403, ""))
    assert "HTTP 403" in msg and "blocking" in msg
    assert "likely changed" not in msg and "could not reach" not in msg


def test_one_dropped_connection_among_404s_is_not_blamed_on_the_site(monkeypatch):
    msg = _detect_error(monkeypatch, (0, ""), (404, ""))
    assert "could not reach the site" in msg


def test_a_later_candidate_that_works_is_still_picked(monkeypatch):
    _answer(monkeypatch, (0, ""), (404, ""), (200, PAGE))
    monkeypatch.setattr(t, "_extract_listing_links", lambda html: ["https://x/a-r123456.html"])
    assert t._detect_search_url(None) == t.SEARCH_URL_CANDIDATES[2]


def _run_with_page_replies(monkeypatch, status):
    monkeypatch.setattr(t, "make_session", lambda base: None)
    monkeypatch.setattr(t, "_detect_search_url", lambda sess: "http://s/?page={page}")
    monkeypatch.setattr(t, "_fetch", lambda url, sess=None: (status, ""))
    monkeypatch.setattr(t, "get_fresh_detail_urls", lambda *a, **k: set())
    return t.run(max_pages=2)


def test_a_run_whose_pages_never_arrived_is_not_blamed_on_the_link_patterns(monkeypatch):
    # The probe worked, then the connection dropped: nothing was parsed because
    # nothing was read, not because DETAIL_HREF_PATTERNS went stale.
    with pytest.raises(RuntimeError) as err:
        _run_with_page_replies(monkeypatch, 0)
    assert "could not reach the site" in str(err.value)
    assert "DETAIL_HREF_PATTERNS" not in str(err.value)


def test_pages_that_arrive_without_listings_still_point_at_the_link_patterns(monkeypatch):
    monkeypatch.setattr(t, "_extract_listing_links", lambda html: [])
    with pytest.raises(RuntimeError, match="DETAIL_HREF_PATTERNS"):
        _run_with_page_replies(monkeypatch, 200)

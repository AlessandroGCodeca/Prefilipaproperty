"""
dashboard/diagnostics.py — 🔗 TEST SITES and 🔗 TEST CZ SITES: what each
portal answers the scrapers' own first URL; 📨 TEST TELEGRAM: whether an
alert reaches your chat.
"""

import streamlit as st

import scheduler as _scheduler


def render(sb) -> None:
    """The answers to the test buttons clicked on this run."""
    do_test = sb.do_test
    do_test_cz = sb.do_test_cz
    if do_test:
        from scraper._http import get as _http_get, SCRAPER_API_KEY as _sak
        _proxy_mode = bool(_sak)
        st.info(f"Proxy mode: {'✅ ScraperAPI' if _proxy_mode else '⚠️ Direct (no SCRAPER_API_KEY set)'}")
        # The scrapers' own URLs, so this tests what a scrape would actually fetch.
        from scraper import nehnutelnosti as _neh, bazos as _baz, topreality as _top
        for label, url in [
            ("nehnutelnosti.sk", _neh.SEARCH_PAGE.format(page=1)),
            ("bazos.sk",          _baz.BASE + _baz.CATEGORY),
            ("topreality.sk",     _top.SEARCH_URL_CANDIDATES[0].format(page=1)),
        ]:
            try:
                _r = _http_get(url, timeout=12)
                snippet = _r.text[:80].strip().replace("\n", " ")
                icon = "✅" if _r.status_code == 200 else "❌"
                st.info(f"{icon} **{label}** → HTTP {_r.status_code} | `{snippet}`")
            except Exception as _e:
                st.error(f"❌ **{label}** → {_e}")

    if do_test_cz:
        # Each Czech portal's robots.txt first (a disallowed one isn't fetched),
        # then the page its scraper starts from.
        from importlib import import_module as _imp
        from scraper._http import get as _http_get
        from scraper.cz_common import robots_allows as _robots_allows, _robots_cache
        _robots_cache.clear()           # the live answer, not this process's memory
        _cz_start = {"scraper.sreality": lambda m: m.SEARCH_API,
                     "scraper.bezrealitky": lambda m: m.SITEMAP_INDEX,
                     "scraper.idnes": lambda m: m.page_url(2),
                     "scraper.bazos_cz": lambda m: m.page_url(m.PAGE_SIZE)}
        _blocked = {mod: why for _n, mod, why in _scheduler.BLOCKED.get("cz", ())}
        for _name, _module in (list(_scheduler.SCRAPERS.get("cz") or ())
                               + [(n, mod) for n, mod, _w in _scheduler.BLOCKED.get("cz", ())]):
            _tag = " (left out of the run)" if _module in _blocked else ""
            try:
                _url = _cz_start[_module](_imp(_module))
                _ok, _why = _robots_allows(_url)
                if not _ok:
                    st.warning(f"⛔ **{_name}**{_tag} → {_why}")
                    continue
                _r = _http_get(_url, timeout=12)
                _icon = "✅" if _r.status_code == 200 else "❌"
                st.info(f"{_icon} **{_name}**{_tag} → robots.txt allows · HTTP {_r.status_code}")
            except Exception as _e:
                st.error(f"❌ **{_name}**{_tag} → {_e}")

    if getattr(sb, "do_test_tg", False):
        from modules import alerts
        if not alerts.enabled():
            st.warning("📨 Telegram alerts are off: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                       "in .env, then restart the dashboard (README \"Telegram alerts\").")
        else:
            try:
                alerts.send_test()
                st.success("📨 Test message sent — check Telegram.")
            except Exception as _e:
                st.error(f"📨 Telegram refused: {_e}")

"""
dashboard/sidebar.py — the sidebar: each market's last pipeline run, the job
a button started, ▶ RUN EVERYTHING and one button per pipeline step — grouped
under DAILY RUN (the steps the 06:00 run makes, in its order), REPAIR DATA
and DIAGNOSTICS — the filters, and the scoring settings in force.
"""

from types import SimpleNamespace

import streamlit as st

import markets

from dashboard.fmt import _SHOW, esc


@st.cache_data(ttl=3600, show_spinner=False)
def _fx_refresh_if_due() -> bool:
    # The ČNB EUR/CZK rate (modules/fx_rate) when the saved one is over 6 h
    # old — at most once an hour across reruns, with a short timeout so a
    # slow bank site can't hold the page.
    from modules import fx_rate
    try:
        return fx_rate.refresh_if_due(timeout=5)
    except Exception:
        return False


_FLAG = {"sk": "🇸🇰", "cz": "🇨🇿"}


def portal_label(market: str, name: str) -> str:
    """A portal's sidebar button: its full name with its country's flag
    ("🇸🇰 Bazos.sk", "🇨🇿 Bazos.cz")."""
    return f"{_FLAG.get(market, market.upper())} {name}"


def render() -> SimpleNamespace:
    """Draw the sidebar: the pipeline status and buttons, the filters and
    the scoring settings. Returns what the rest of the page reads from it:
    the buttons clicked on this run and the filter values."""
    # ── Pipeline status ───────────────────────────────────────────────────────────
    # The scheduler's last run (modules/pipeline_state), and the job a sidebar
    # button started (modules/jobs). Buttons run their step in the background, so
    # the page stays usable and the result stays on screen until the next one.
    from modules import jobs
    from modules.pipeline_state import read_status as _read_run_status, summarize as _summarize_run
    from database import get_pipeline_lock
    import scheduler as _scheduler

    _lock_now = get_pipeline_lock()
    _run_level, _run_text = _summarize_run(_read_run_status(), _lock_now)
    # Every other market with portals (or a run on record) gets its own line.
    _OTHER_RUNS = {}
    for _m in markets.MARKET_CODES:
        if _m == "sk":
            continue
        _st_m = _read_run_status(_m)
        if _scheduler.SCRAPERS.get(_m) or _st_m:
            _OTHER_RUNS[_m] = _summarize_run(_st_m, _lock_now)
    _RUN_ICON = {"ok": "✅", "running": "⏳", "warning": "⚠️", "error": "❌", "none": "ℹ️"}

    # Decorated on every run, as it was at the top of app.py: run_every
    # follows whether a job is running now.
    @st.fragment(run_every=2 if jobs.running() else None)
    def _job_panel():
        job = jobs.current()
        if job is None:
            return
        if job.running:
            st.session_state["_job_watch"] = job.id
            st.progress(job.progress or 0.0,
                        text=f"⏳ {job.label} · {job.elapsed()}" + (f" · {job.note}" if job.note else ""))
            return
        _SHOW.get(job.level, st.info)(job.message)
        if st.session_state.get("_job_watch") == job.id:
            # This page watched the job run: redraw all of it on the new data,
            # and toast the result for a page scrolled away from the sidebar.
            del st.session_state["_job_watch"]
            st.session_state["_job_toast"] = job.message
            st.rerun()
        if "_job_toast" in st.session_state:
            st.toast(st.session_state.pop("_job_toast"), duration="long")

    # ── Sidebar ───────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown('<div class="wordmark">SOVEREIGN</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub">Investor Dashboard · Slovakia · Czechia 2026</div>',
                    unsafe_allow_html=True)
        st.markdown("---")

        st.markdown("#### PIPELINE")
        # One status line per market: Slovakia's as it always read (tagged only
        # when another market has a line of its own), then the others'.
        st.caption(_RUN_ICON[_run_level] + " " + _run_text
                   + (" · SK" if _OTHER_RUNS else ""))
        for _m, (_lvl, _txt) in _OTHER_RUNS.items():
            st.caption(f"{_RUN_ICON[_lvl]} {_m.upper()} · {_txt}")
        _job_panel()
        _busy = jobs.running()
        do_all   = st.button("▶ RUN EVERYTHING", type="primary", width="stretch", disabled=_busy,
                             help="Every step under DAILY RUN, in order: each market's portals, "
                                  "missing details, rent comps, LV check, scoring, location, "
                                  "risk, portal copies — what the 06:00 scheduler runs. Takes "
                                  "a while (up to an hour); the page stays usable.")

        # The steps the daily run makes, one button each, in its order.
        with st.expander("📅 DAILY RUN — step by step", expanded=False):
            st.markdown('<div class="muted">Portals</div>', unsafe_allow_html=True)
            # One full-width button per portal, named in full with its country:
            # three abbreviations in a row were cut off ("NEH…"), and the Slovak
            # and Czech Bazoš looked the same.
            _sk_clicks = {_module: st.button(portal_label("sk", _name), key=f"sk_{_module}",
                                             width="stretch", disabled=_busy)
                          for _name, _module in _scheduler.SCRAPERS["sk"]}
            do_nehnut  = _sk_clicks.get("scraper.nehnutelnosti", False)
            do_bazos   = _sk_clicks.get("scraper.bazos", False)
            do_topreal = _sk_clicks.get("scraper.topreality", False)
            # Czech portals (scheduler.SCRAPERS["cz"]), one button each.
            _cz_clicks = []
            _cz_portals = _scheduler.SCRAPERS.get("cz") or ()
            for _name, _module in _cz_portals:
                _label = portal_label("cz", _name)
                _cz_clicks.append((st.button(_label, key=f"cz_{_module}", width="stretch",
                                             disabled=_busy), _label, _name, _module))
            st.markdown('<div class="muted">Then</div>', unsafe_allow_html=True)
            do_fill  = st.button("🔎 FILL MISSING DETAILS", width="stretch", disabled=_busy,
                                 help="Re-read nehnutelnosti listings saved without a price, "
                                      "size or district (one with no price or size can't be "
                                      "scored), retire the ones taken down, then score what "
                                      "it filled in. Bazos / Topreality listings aren't re-read.")
            do_rent  = st.button("🏘️ RENT COMPS", width="stretch", disabled=_busy,
                                 help="Scrape Slovak (prenájom) and Czech (pronájem) rentals, "
                                      "rebuild the live rents per district / town and re-score "
                                      "the listings whose rate moved — and the Czech ones that "
                                      "waited for a rent figure.")
            do_lv    = st.button("🔒 LV DEBT FILTER", width="stretch", disabled=_busy)
            do_addr  = st.button("🗺️ NORMALIZE ADDRESSES", width="stretch", disabled=_busy,
                                 help="Run Claude on listings with a blank district to "
                                      "resolve city/district from the raw address, so rent "
                                      "stops defaulting to €6.50/m². Needs ANTHROPIC_API_KEY. "
                                      "Re-score afterwards to apply.")
            do_desc  = st.button("📝 PARSE DESCRIPTIONS", width="stretch", disabled=_busy,
                                 help="Run Claude on un-parsed listing descriptions to "
                                      "extract parking / furnished / condition. Needs "
                                      "ANTHROPIC_API_KEY. Re-score afterwards to apply the "
                                      "parking & furnished rent premiums.")
            do_cf    = st.button("💰 CASHFLOW SCORE", width="stretch", disabled=_busy)
            do_loc   = st.button("📍 LOCATION IQ",    width="stretch", disabled=_busy,
                                 help="Geocode + transit/amenities + real noise/flood/"
                                      "construction flags. Google when GOOGLE_PLACES_API_KEY "
                                      "is set, OpenStreetMap otherwise.")
            do_risk  = st.button("🌊 RISK BACKFILL", width="stretch", disabled=_busy,
                                 help="Give listings located before the real risk data "
                                      "existed their noise / flood / construction answers.")
            do_dupes = st.button("📡 MERGE PORTAL COPIES", width="stretch", disabled=_busy,
                                 help="Group the same flat listed on several portals.")

        # Redoing work the daily run already did, after a rule or a table changed.
        with st.expander("🔧 REPAIR DATA", expanded=False):
            do_rescore = st.button("♻️ RESCORE ALL",  width="stretch", disabled=_busy,
                                   help="Clear all cashflow scores and re-run scoring from "
                                        "scratch. Use after updating rent/tax assumptions.")
            do_reparse = st.button("📝 RE-PARSE (new fields)", width="stretch", disabled=_busy,
                                   help="Re-run description parsing on listings parsed before "
                                        "floor / elevator / cellar / terrace were kept. Needs "
                                        "ANTHROPIC_API_KEY.")
            do_tax   = st.button("🏛️ UPDATE TAX RATES", width="stretch", disabled=_busy,
                                 help="Read each Slovak town's flat property-tax rate (daň z "
                                      "bytov) from its own site, apply the new ones, hold "
                                      "anything doubtful for review in the TAX RATES tab, and "
                                      "re-score the listings whose tax moved. Once a year is "
                                      "enough (most ordinances take effect on 1 January).")
            do_stale = st.button("🧹 CLEAN STALE (21d)", width="stretch", disabled=_busy,
                                 help="Retire listings not seen for 21 days — but not those "
                                      "of a portal that has returned nothing on its last runs.")

        with st.expander("🩺 DIAGNOSTICS", expanded=False):
            do_test  = st.button("🔗 TEST SITES",      width="stretch",
                                 help="robots.txt and HTTP status of each Slovak portal.")
            do_test_cz = (st.button("🔗 TEST CZ SITES", width="stretch",
                                    help="robots.txt and HTTP status of each Czech portal — "
                                         "the ones read and the ones left out.")
                          if _cz_portals or _scheduler.BLOCKED.get("cz") else False)
            do_test_tg = st.button("📨 TEST TELEGRAM", width="stretch",
                                   help="Send a test message to your Telegram chat "
                                        "(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env).")

        st.markdown("---")
        st.markdown("#### FILTERS")
        max_price  = st.slider("Max Price €",  10_000, 600_000, 300_000, 5_000)
        min_size   = st.slider("Min Size m²",  20, 150, 25, 5)
        classes    = st.multiselect(
            "Classification",
            ["GREEN", "YELLOW", "WHITE", "PENDING", "REJECTED"],
            default=["GREEN", "YELLOW", "WHITE", "PENDING"],
        )
        # The portals, plus any other source in the database — 'sample' for the
        # rows seed_market_data.py writes. A fixed list hid those rows behind a
        # filter that had no option to show them.
        from database import get_active_sources
        _portals = (["nehnutelnosti", "bazos", "topreality"]
                    + [mod.split(".", 1)[1] for _, mod in _cz_portals])
        _source_opts = _portals + [s for s in get_active_sources() if s not in _portals]
        sources    = st.multiselect(
            "Source",
            _source_opts,
            default=_source_opts,
        )
        district_q = st.text_input(
            "District contains",
            placeholder="e.g. Bratislava, Petržalka, Košice",
            help="Case-insensitive substring match. Leave blank to show all.",
        )
        cond_filter = st.multiselect(
            "Condition",
            ["new", "renovated", "good", "original", "poor"],
            default=[],
            help="Renovation state parsed from the description. "
                 "Empty = show all (including unparsed/unknown).",
        )
        req_parking = st.toggle(
            "🅿️ Parking only", value=False,
            help="Show only listings with a garage or parking spot "
                 "(parsed from the description).",
        )
        req_furnished = st.toggle(
            "🛋️ Furnished only", value=False,
            help="Show only fully or semi-furnished listings.",
        )
        req_elevator = st.toggle(
            "🛗 Elevator only", value=False,
            help="Show only listings whose description mentions an elevator.",
        )
        drops_only = st.toggle(
            "🔻 Price cuts only", value=False,
            help="Show only listings whose asking price has been cut.",
        )
        cf_positive_only = st.toggle(
            "💶 Cash-flow positive only", value=False,
            help="Show only scored listings whose monthly surplus (after the mortgage "
                 "and tax, for the structure shown) clears CASHFLOW_MIN_SURPLUS. "
                 "GREEN and YELLOW are price vs the market, not income: most "
                 "of them cost money every month.",
        )
        hide_dev   = st.toggle(
            "Hide dev projects",
            value=True,
            help='Dev-project listings (novostavba/developersky-projekt/etc.) quote "od €X" '
                 'starting prices for the cheapest unit and distort cashflow scoring.',
        )
        hide_dups  = st.toggle(
            "Hide portal copies", value=True,
            help="Show the same flat once even when it is listed on several portals "
                 "(the copy with a verified LV is kept, else the cheapest; the others "
                 "are linked from its card). It picks among the copies the other "
                 "filters let through, so a flat stays while any copy matches them.",
        )
        show_sro   = st.toggle("Show s.r.o. figures", value=True)
        show_demo  = st.toggle("Demo data (no DB)",   value=False)

        from engine.financial import default_ltv as _default_ltv
        from config import PROPERTIES_OWNED as _OWNED, tax_rules as _tax_rules
        st.markdown(
            f'<div class="muted">Scoring LTV {_default_ltv()*100:.0f}% · '
            f'PROPERTIES_OWNED={_OWNED}'
            f'{" (3rd+ property → 70% cap)" if _default_ltv() < 0.8 else ""}</div>',
            unsafe_allow_html=True)
        _tr = _tax_rules()
        st.markdown(f'<div class="muted">Tax rules {_tr["year"]} · checked '
                    f'{esc(_tr["checked"])}</div>', unsafe_allow_html=True)
        if _tr["stale"]:
            st.warning(f"No tax table for {_tr['requested']} yet — scoring uses the "
                       f"{_tr['year']} rules. Add {_tr['requested']} to TAX_YEAR_RULES "
                       f"in config.py.")
        # Each other market's financing and tax table, the same way.
        for _m in markets.MARKET_CODES:
            if _m == "sk":
                continue
            _p = markets.get(_m)
            try:
                _trm = markets.tax_rules(market=_m)
            except LookupError:
                continue
            _reg = _p.lending_rules.get("regulator", "")
            st.markdown(f'<div class="muted">{_m.upper()} · scoring LTV '
                        f'{_default_ltv(market=_m)*100:.0f}% ({esc(_reg)} investment mortgage) · '
                        f'rate {_p.mortgage_rate_pa*100:.2f}% · tax rules {_trm["year"]} · '
                        f'checked {esc(_trm["checked"])}</div>', unsafe_allow_html=True)
            if _trm["stale"]:
                st.warning(f"No {_p.name} tax table for {_trm['requested']} yet — scoring uses "
                           f"the {_trm['year']} rules. Add {_trm['requested']} to "
                           f"{_m.upper()}_TAX_YEAR_RULES in markets.py.")
        # The EUR/CZK rate the combined ranking converts with (modules/fx_rate):
        # fetched from the ČNB when the saved one is over 6 h old, at most hourly.
        # It is shown, and its age warned about, where Czech listings are.
        _fx_refresh_if_due()

        st.markdown("---")
        st.markdown('<div class="muted">Private use. Verify all data.<br>Notárska úschova always.</div>', unsafe_allow_html=True)

    return SimpleNamespace(
        other_runs=_OTHER_RUNS,
        busy=_busy,
        cz_clicks=_cz_clicks,
        run_level=_run_level,
        run_text=_run_text,
        cf_positive_only=cf_positive_only,
        classes=classes,
        cond_filter=cond_filter,
        district_q=district_q,
        do_addr=do_addr,
        do_all=do_all,
        do_bazos=do_bazos,
        do_cf=do_cf,
        do_desc=do_desc,
        do_dupes=do_dupes,
        do_fill=do_fill,
        do_loc=do_loc,
        do_lv=do_lv,
        do_nehnut=do_nehnut,
        do_rent=do_rent,
        do_reparse=do_reparse,
        do_rescore=do_rescore,
        do_risk=do_risk,
        do_stale=do_stale,
        do_tax=do_tax,
        do_test=do_test,
        do_test_cz=do_test_cz,
        do_test_tg=do_test_tg,
        do_topreal=do_topreal,
        drops_only=drops_only,
        hide_dev=hide_dev,
        hide_dups=hide_dups,
        max_price=max_price,
        min_size=min_size,
        req_elevator=req_elevator,
        req_furnished=req_furnished,
        req_parking=req_parking,
        show_demo=show_demo,
        show_sro=show_sro,
        sources=sources,
    )

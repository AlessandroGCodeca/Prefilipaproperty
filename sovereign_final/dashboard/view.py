"""
dashboard/view.py — the page state every tab reads: the market picked at the
top, the listings the sidebar filters let through, sorted by class, and the
helpers that depend on them (the view's currency, the filter-hid-it notes).
"""

from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

import markets
import scheduler as _scheduler

from dashboard.demo import DEMO
from dashboard.fmt import _tag_market, mkw
from dashboard.listing_cache import clear_after_finished_job, load_active


@dataclass
class View:
    """One run's page state, built by build() and handed to every tab. It is
    rebuilt on each rerun and belongs to that run alone (two browser tabs are
    two sessions, each with its own)."""
    market: str | None          # the market picked at the top; None = all of them
    cur: str                    # the currency money columns and totals are shown in
    using_demo: bool            # the demo rows, not the database
    show_sro: bool              # the s.r.o. toggle: which structure's figures show
    busy: bool                  # a pipeline job is running
    data: list                  # the listings the filters let through, this market's
    rejected_rows: list         # LV-rejected listings, this market's
    greens: list                # data, by class: GREEN and YELLOW best value first
    yellows: list
    whites: list
    pending: list
    n_loaded: int               # listings before the filters
    n_scored_loaded: int        # ... of them scored
    n_hidden: int               # ... kept off the page by the filters
    stages: dict                # listing id → its deal stage
    lv_docs: dict               # Czech listing id → its pasted LV extract
    in_view: Callable           # (row) → it belongs to the market picked
    in_view_cur: Callable       # (row, amount) → the amount in `cur`
    money_col: Callable         # (name, help=None) → a money column in `cur`
    cf_negative: Callable       # (row) → the structure shown loses money monthly
    passes_filters: Callable    # (row, by_class=True) → the sidebar filters let it through
    hidden_note: Callable       # (what="listings") → the "filters hid it" line
    unscored_note: Callable     # () → the "nothing is scored yet" line


def pick_market() -> str | None:
    """The market selector at the top of the page: a market code, or None
    for all of them."""
    # ── Market selector ───────────────────────────────────────────────────────────
    # At the top of the page, above every tab: "All markets" (the default) ranks
    # Slovak and Czech listings together, money converted to EUR at the dated
    # rate in config; a single market shows its own listings in its own currency.
    MARKET_VIEWS = {"All markets": None, "🇸🇰 Slovakia": "sk", "🇨🇿 Czechia": "cz"}
    view_market = MARKET_VIEWS[st.radio("Market", list(MARKET_VIEWS), horizontal=True,
                                        key="market_view", label_visibility="collapsed")]
    return view_market


def build(sb, view_market) -> View:
    """Load the listings, apply the market and the sidebar filters, and sort
    them into the lists the tabs show."""
    _busy = sb.busy
    cf_positive_only = sb.cf_positive_only
    classes = sb.classes
    cond_filter = sb.cond_filter
    district_q = sb.district_q
    drops_only = sb.drops_only
    hide_dev = sb.hide_dev
    hide_dups = sb.hide_dups
    max_price = sb.max_price
    min_size = sb.min_size
    req_elevator = sb.req_elevator
    req_furnished = sb.req_furnished
    req_parking = sb.req_parking
    show_demo = sb.show_demo
    show_sro = sb.show_sro
    sources = sb.sources
    # The currency money columns and totals are shown in: the market's own when
    # one is picked, EUR for all of them together.
    VIEW_CUR = markets.get(view_market).currency if view_market else "EUR"

    def in_view(l) -> bool:
        """The listing belongs to the market picked at the top."""
        return view_market is None or markets.of_row(l) == view_market

    def money_col(name: str, help=None):
        """A money column in the view's currency: EUR (the euro format) for
        Slovakia and for all markets together, Kč for Czechia alone."""
        if VIEW_CUR == "EUR":
            return st.column_config.NumberColumn(format="euro", step=1, help=help)
        return st.column_config.NumberColumn(f"{name} ({markets.get(view_market).currency_symbol})",
                                             format="localized", step=1, help=help)

    def in_view_cur(l, v):
        """An amount of row `l` in the view's currency (VIEW_CUR): as stored
        when they match, else converted to EUR. None stays None."""
        if v is None:
            return None
        cur = l.get("_cur") or "EUR"
        return v if cur == VIEW_CUR else markets.to_eur(v, cur)

    # ── Data ──────────────────────────────────────────────────────────────────────
    from database import (
        get_price_history, get_deal_stages, latest_vibes, days_on_market,
    )

    # The listing load is cached (dashboard/listing_cache.py); a pipeline step
    # finished since the last clear makes it read the database again.
    clear_after_finished_job()
    raw_data = load_active()

    using_demo = show_demo or not raw_data
    if using_demo:
        data = DEMO
        if not raw_data:
            st.info("ℹ️ No data in DB yet — showing demo listings. Click ▶ RUN EVERYTHING in "
                    "the sidebar to fill it.")
    else:
        data = raw_data
    # LV-rejected listings never reach the lists; the Rejected tile counts them.
    rejected_rows = [] if using_demo else load_active(rejected=True)
    # The market picked at the top filters everything below.
    data = [_tag_market(l) for l in data if in_view(l)]
    rejected_rows = [_tag_market(l) for l in rejected_rows if in_view(l)]
    # The pasted výpis z LV of each Czech listing on the page (modules/lv_cz), in
    # one query.
    _LV_DOCS = {}
    if not using_demo and any(l.get("_market") == "cz" for l in data):
        from database import get_lv_documents
        _LV_DOCS = get_lv_documents([l["id"] for l in data if l.get("_market") == "cz"])
    if view_market and not data and raw_data and not using_demo:
        st.info(f"ℹ️ No {markets.get(view_market).name} listings yet"
                + (" — its portals are read by ▶ RUN EVERYTHING and the scheduler."
                   if _scheduler.SCRAPERS.get(view_market) else "."))

    # Per-listing context that lives outside the main query: price history, deal
    # stage, latest vibe note, the other portals' copies of the same flat.
    price_hist = get_price_history()
    stages     = get_deal_stages()
    vibes      = latest_vibes()
    dup_members: dict = {}
    for l in data:
        if l.get("dup_group"):
            dup_members.setdefault(l["dup_group"], []).append(l)
    for l in data:
        l["_ph"]      = price_hist.get(l.get("id"))
        l["_stage"]   = stages.get(l.get("id"))
        l["_vibe"]    = vibes.get(l.get("id"))
        l["_copies"]  = dup_members.get(l.get("dup_group"), []) if l.get("dup_group") else []
        l["_portals"] = len({c.get("source") for c in l["_copies"]}) or 1
        # A flat is as old as its oldest copy on any portal.
        seen = [c.get("scraped_at") for c in l["_copies"] + [l] if c.get("scraped_at")]
        l["_dom"]     = days_on_market(min(seen)) if seen else None
    for l in rejected_rows:
        l["_ph"]      = price_hist.get(l.get("id"))

    from engine.financial import is_cashflow_negative

    def _shown_surplus(l):
        """The monthly surplus of the structure on screen (the s.r.o. toggle)."""
        return l.get("surplus_sro") if show_sro else l.get("surplus_personal")

    def _cf_negative(l) -> bool:
        return is_cashflow_negative(_shown_surplus(l), **mkw(l))

    # Apply filters
    district_needle = (district_q or "").strip().lower()

    def passes_filters(l, by_class=True):
        """The sidebar filters. A rejected listing is checked without the
        Classification one: being rejected is all its tile counts."""
        # Max Price € is in EUR whatever the listing's currency.
        return ((l.get("_price_eur") or 0) <= max_price
                and (l.get("size_m2")  or 0) >= min_size
                and (not by_class or not classes or (l.get("classification") or "PENDING") in classes)
                and (not sources or (l.get("source") or "") in sources)
                and (not district_needle or district_needle in (l.get("district") or "").lower())
                and (not cond_filter or (l.get("condition") or "").lower() in cond_filter)
                and (not req_parking or (l.get("has_parking") or 0))
                and (not req_furnished or (l.get("furnished") or "") in ("furnished", "semi"))
                and (not req_elevator or (l.get("has_elevator") or 0))
                and (not drops_only or ((l["_ph"] or {}).get("change_pct") or 0) < 0)
                # Not scored is not positive: there is no surplus to clear the bar.
                and (not cf_positive_only
                     or (_shown_surplus(l) is not None and not _cf_negative(l)))
                and (not hide_dev or not (l.get("is_dev_project") or 0)))

    n_loaded = len(data)
    # Scored listings before the filters: with none at all, an empty table is
    # "nothing scored yet", not "the filters hid it".
    n_scored_loaded = sum(1 for l in data if (l.get("cf_class") or l.get("classification"))
                          in ("GREEN", "YELLOW", "WHITE"))
    data = [l for l in data if passes_filters(l)]
    # One copy per flat, chosen among the copies that passed the filters above.
    if hide_dups:
        from engine.duplicates import one_per_flat
        data = one_per_flat(data)
    # Listings in the database that the sidebar (filters, hidden portal copies)
    # keeps off the page — an empty list then means "widen the filters", not
    # "the database is empty".
    n_hidden = n_loaded - len(data)

    from config import NEAR_FLOOR_DISCOUNT

    def _value_rank(l):
        """Sort key, best first (used with reverse=True): deepest discount to the
        regional median, then the higher yield.

        A discount at NEAR_FLOOR_DISCOUNT or deeper is more often a deposit or an
        "od €X" price than a bargain — the card warns about it — so those rows go
        after every other one, the least extreme first. Judged at the 4 decimals
        the card's warning uses, so the order and the warning always agree."""
        disc = l.get("market_discount") or 0
        gross = l.get("gross_yield") or 0
        if round(disc, 4) >= NEAR_FLOOR_DISCOUNT:
            return (0, -disc, gross)
        return (1, disc, gross)

    greens  = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "GREEN"],
                     key=_value_rank, reverse=True)
    yellows = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "YELLOW"],
                     key=_value_rank, reverse=True)
    whites  = [l for l in data if (l.get("cf_class") or l.get("classification")) == "WHITE"]
    # Listing ids are md5 hex digests, so a prefix test on "d" (meant for the demo
    # rows d1–d3) hid one real listing in sixteen. The demo rows are all scored
    # GREEN/YELLOW and never land here anyway.
    pending = [l for l in data if (l.get("cf_class") or l.get("classification") or "PENDING") == "PENDING"]

    def hidden_note(what="listings"):
        """The empty-state line when the filters, not the database, emptied a list."""
        return (f"No {what} match the sidebar filters — {n_hidden} listing(s) are hidden by "
                f"them (Source, Max price, Classification, …). Widen the filters to see them.")

    def unscored_note():
        """The empty-state line for the scored lists when nothing is scored yet,
        whatever the filters do."""
        return (f"⏳ Nothing is scored yet — {n_loaded} listing(s) are waiting. Click "
                f"💰 CASHFLOW SCORE (or ▶ RUN EVERYTHING) in the sidebar to sort them into "
                f"GREEN / YELLOW / WHITE. A listing with no price or size can't be scored: "
                f"🔎 FILL MISSING DETAILS looks them up.")

    return View(
        market=view_market, cur=VIEW_CUR, using_demo=using_demo, show_sro=show_sro,
        busy=_busy, data=data, rejected_rows=rejected_rows, greens=greens,
        yellows=yellows, whites=whites, pending=pending, n_loaded=n_loaded,
        n_scored_loaded=n_scored_loaded, n_hidden=n_hidden, stages=stages,
        lv_docs=_LV_DOCS, in_view=in_view, in_view_cur=in_view_cur, money_col=money_col,
        cf_negative=_cf_negative, passes_filters=passes_filters,
        hidden_note=hidden_note, unscored_note=unscored_note,
    )

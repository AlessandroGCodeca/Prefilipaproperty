"""
dashboard/overview.py — above the tabs: a failed run's banner, the stats
tiles, and the price cuts of the last 14 days.
"""

import streamlit as st

import markets

from dashboard.fmt import _tag_market, esc, mkw, money


def render(v, sb) -> None:
    """The banners, tiles and price-cut list over the tabs."""
    _OTHER_RUNS = sb.other_runs
    _run_level = sb.run_level
    _run_text = sb.run_text
    data = v.data
    greens = v.greens
    in_view = v.in_view
    n_hidden = v.n_hidden
    n_loaded = v.n_loaded
    passes_filters = v.passes_filters
    pending = v.pending
    rejected_rows = v.rejected_rows
    using_demo = v.using_demo
    view_market = v.market
    whites = v.whites
    yellows = v.yellows
    from database import get_price_drops
    # A failed scheduled run is easy to miss in the sidebar (collapsed on a
    # phone), and everything below is as old as the last run that worked.
    if _run_level == "error":
        st.error(_run_text)
    for _m, (_lvl, _txt) in _OTHER_RUNS.items():
        if _lvl == "error" and (view_market in (None, _m)):
            st.error(f"{_m.upper()} — {_txt}")

    # ── Stats bar ─────────────────────────────────────────────────────────────────
    # The tiles count the listings the page shows, so they move with the sidebar
    # filters: Total = Green + Yellow + White + Pending. Rejected listings are
    # never shown in the lists; their tile counts the ones the same filters
    # (bar Classification) let through, and they are not counted as Pending.
    shown = {
        "total":    len(data),
        "green":    len(greens),
        "yellow":   len(yellows),
        "white":    len(whites),
        "rejected": sum(1 for l in rejected_rows if passes_filters(l, by_class=False)),
        "pending":  len(pending),
    }
    st.markdown(f"""
<div class="sg">
  <div class="sc b"><div class="sn">{shown['total']}</div><div class="sl">Total</div></div>
  <div class="sc g"><div class="sn">{shown['green']}</div><div class="sl">Green</div></div>
  <div class="sc y"><div class="sn">{shown['yellow']}</div><div class="sl">Yellow</div></div>
  <div class="sc w"><div class="sn">{shown['white']}</div><div class="sl">White</div></div>
  <div class="sc r"><div class="sn">{shown['rejected']}</div><div class="sl">Rejected</div></div>
  <div class="sc a"><div class="sn">{shown['pending']}</div><div class="sl">Pending</div></div>
</div>
""", unsafe_allow_html=True)
    # With both markets on the page, how the tiles split between them.
    _per_market = {m: sum(1 for l in data if l.get("_market") == m) for m in markets.MARKET_CODES}
    if view_market is None and sum(1 for n in _per_market.values() if n) > 1:
        st.markdown('<div class="muted" style="margin:-10px 0 14px">'
                    + " · ".join(f'{"🇸🇰" if m == "sk" else "🇨🇿"} {m.upper()} {n}'
                                 for m, n in _per_market.items())
                    + f" · tables compare in EUR at {esc(markets.fx_note())}; each card "
                      f"keeps its own currency</div>", unsafe_allow_html=True)
    if n_hidden:
        st.markdown(f'<div class="muted" style="margin:-10px 0 14px">Showing {len(data)} of '
                    f'{n_loaded} listings · {n_hidden} hidden by the sidebar filters</div>',
                    unsafe_allow_html=True)

    # ── Price-cut alerts ──────────────────────────────────────────────────────────
    _drops = [] if using_demo else [_tag_market(d) for d in get_price_drops(days=14)
                                     if in_view(d)]
    if _drops:
        from engine.financial import below_sanity_floor, class_at_price, discount_to_median
        with st.expander(f"🔻 {len(_drops)} price cut(s) in the last 14 days", expanded=False):
            for d in _drops:
                # The class the new price earns, worked out the way scoring does:
                # "under max YELLOW" alone would call a price below the sanity
                # floor (a misread, not a bargain) a deal.
                my = d.get("max_price_yellow")
                size, district = d.get("size_m2") or 0, d.get("district") or ""
                now_cls = class_at_price(d["price_eur"], size, district, d.get("rooms"), **mkw(d))
                if now_cls in ("GREEN", "YELLOW"):
                    reach = f" · now {now_cls}"
                elif below_sanity_floor(discount_to_median(d["price_eur"], size, district,
                                                           d.get("rooms"), **mkw(d))):
                    reach = " · below the sanity floor — check the price"
                elif my:
                    reach = f" · {d['price_eur'] / my - 1:+.1%} above max YELLOW {money(d, my)}"
                else:
                    reach = ""
                st.markdown(
                    f'<div class="brow"><span class="l">{esc((d.get("title") or d.get("district") or "—")[:60])}</span>'
                    f'<span class="v">{money(d, d["price_eur"])} ({d["last_change_pct"]:+.1%}, '
                    f'{str(d["last_change_at"])[:10]}){reach} · '
                    f'<a href="{esc(d["url"])}" target="_blank">open ↗</a></span></div>',
                    unsafe_allow_html=True)

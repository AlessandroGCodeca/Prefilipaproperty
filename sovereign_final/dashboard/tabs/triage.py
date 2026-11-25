"""
dashboard/tabs/triage.py — TRIAGE TABLE: every scored listing in one flat,
sortable table, to spot the best surplus or yield in one scan instead of
opening each card.

UX5: tick one row and its summary shows under the table (D3); tick several
and STAR, COMPARE or PASS acts on all of them at once.
D22: on a phone (600 px and narrower) the wide table gives way to a list,
two lines a flat, 25 to a page; the page carries both and the stylesheet
shows the one that fits (dashboard/style.py, .st-key-triage_wide/_narrow).
"""

from datetime import datetime

import streamlit as st
from pandas.api.types import is_numeric_dtype

import markets

from dashboard.fmt import _features_label, _lv_state, esc, money

# Always shown, first and pinned; the column chooser hides any other.
PINNED = ("", "Grade", "Title", "Price", "Surplus")


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _defuse(value):
    """A text cell Excel would run as a formula (=, +, -, @ first: an ad's
    title is text a stranger wrote) gets an apostrophe in front, which Excel
    shows as plain text. Numbers are left alone."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def triage_csv(df) -> bytes:
    """The table as a CSV file: every row and column, in the order shown.
    With a byte-order mark, so Excel reads the diacritics."""
    safe = df.drop(columns=[c for c in ("_id",) if c in df.columns]).copy()   # internal
    for col in safe.columns:
        if not is_numeric_dtype(safe[col]):        # object or pandas' str columns
            safe[col] = safe[col].map(_defuse)
    return safe.to_csv(index=False).encode("utf-8-sig")


def render_summary(l, v, ctx: str = "triage") -> None:
    """A picked row's flat: its verdict and three key figures, and a button to
    its full card in ACTIVE SNAG LIST (a card can't be drawn twice on a page:
    its boxes would clash)."""
    from dashboard.fmt import amt, sgn
    from dashboard.verdict import verdict_html
    from engine.financial import compute_deal_score
    score, grade = compute_deal_score(l)
    surplus = v.surplus(l)
    my = l.get("max_price_yellow")
    from dashboard.fmt import czech_words
    cz = czech_words(l)
    struct = "s.r.o." if v.sro(l) else "Personal"
    st.markdown(
        f'<div class="pick-t">{esc((l.get("title") or l.get("district") or "—")[:80])}</div>'
        + verdict_html(grade, score, l.get("market_discount"), surplus, struct,
                       lambda x: amt(l, x), cz)
        + '<div class="pick-k">'
        + f'<div><span>Price</span><b>{amt(l, l.get("price_eur") or 0)}</b></div>'
        + f'<div class="{"neg" if v.cf_negative(l) else ""}"><span>Surplus</span>'
          f'<b>{sgn(l, surplus)}</b></div>'
        + f'<div><span>Max offer</span><b>{amt(l, my) if my else "—"}</b></div></div>',
        unsafe_allow_html=True)
    cls = (l.get("cf_class") or l.get("classification") or "").upper()
    if cls in ("GREEN", "YELLOW"):
        from dashboard.tabs.today import open_card
        st.button("Open its full card", key=f"open_{ctx}", on_click=open_card, args=(l["id"],))
    else:
        st.caption("A WHITE flat has no card: ANALYSIS → WHAT-IF / TAX gives its full breakdown.")


# ── UX5: acting on several flats at once ─────────────────────────────────────
def _new_selection() -> None:
    """Start the table's selection afresh (its key carries a counter)."""
    st.session_state["triage_gen"] = st.session_state.get("triage_gen", 0) + 1


def star_all(ids) -> None:
    from database import set_starred
    for lid in ids:
        set_starred(lid, True)
    _new_selection()
    st.toast(f"★ {len(ids)} starred — TODAY lists them first.")


def pass_all(ids) -> None:
    """Move the flats to PASSED, all but one already CLOSED."""
    from dashboard.listing_cache import clear_listing_cache
    from database import get_deal_stages, set_deal_stage
    stages = get_deal_stages()
    moved = 0
    for lid in ids:
        if (stages.get(lid) or {}).get("stage") != "CLOSED":
            set_deal_stage(lid, "PASSED", "passed from TRIAGE TABLE")
            moved += 1
    clear_listing_cache()
    _new_selection()
    st.toast(f"{moved} moved to PASSED in DEAL PIPELINE.")


def compare(labels) -> None:
    """Put the flats in COMPARE and go there."""
    st.session_state["cmp_pick"] = list(labels)[:4]
    st.query_params["group"] = "analysis"
    st.query_params["tab"] = "COMPARE"
    st.session_state["_tabgen"] = st.session_state.get("_tabgen", 0) + 1
    _new_selection()


def render_bulk(chosen, v) -> None:
    """What can be done with the ticked flats."""
    from dashboard.tabs.compare import MAX_COMPARED, _label
    ids = [l["id"] for l in chosen]
    st.markdown(f'<div class="muted">{len(chosen)} FLATS TICKED</div>', unsafe_allow_html=True)
    demo = v.using_demo
    b1, b2, b3 = st.columns(3)
    with b1:
        st.button(f"★ Star all {len(ids)}", key="bulk_star", on_click=star_all, args=(ids,),
                  disabled=demo, width="stretch",
                  help="Demo flats aren't in the database." if demo else
                       "Starred flats are listed first in TODAY.")
    with b2:
        fits = len(ids) <= MAX_COMPARED
        st.button("Compare them", key="bulk_cmp", on_click=compare,
                  args=([_label(l) for l in chosen],), disabled=not fits, width="stretch",
                  help=("Opens ANALYSIS → COMPARE with these flats side by side." if fits else
                        f"COMPARE takes 2 to {MAX_COMPARED} flats."))
    with b3:
        sure = st.checkbox(f"Pass all {len(ids)}", key="bulk_pass_ok", disabled=demo,
                           help="Moves them to PASSED in DEAL PIPELINE (a CLOSED deal stays).")
        st.button("Pass them", key="bulk_pass", on_click=pass_all, args=(ids,),
                  disabled=demo or not sure, width="stretch", type="primary")


# ── D22: the table as a list on a phone ──────────────────────────────────────
PHONE_PAGE = 25


def _phone_pick(lid) -> None:
    st.session_state["triage_phone_pick"] = (
        None if st.session_state.get("triage_phone_pick") == lid else lid)


def _phone_page(step: int) -> None:
    st.session_state["triage_phone_page"] = max(0, st.session_state.get("triage_phone_page", 0)
                                                + step)


def render_phone_list(df, by_id, v) -> None:
    """Each flat in two lines (class, grade, price and surplus; then its
    title), 25 to a page; Open shows its summary under it."""
    from dashboard.fmt import amt, sgn
    pages = max(1, -(-len(df) // PHONE_PAGE))
    page = min(st.session_state.get("triage_phone_page", 0), pages - 1)
    st.session_state["triage_phone_page"] = page
    pick = st.session_state.get("triage_phone_pick")
    for _, row in df.iloc[page * PHONE_PAGE:(page + 1) * PHONE_PAGE].iterrows():
        l = by_id.get(row["_id"])
        if not l:
            continue
        surplus = v.surplus(l)
        tone = "" if surplus is None else ("bad" if v.cf_negative(l) else "good")
        with st.container(horizontal=True, vertical_alignment="center",
                          key=f"trim_{row['_id']}"):
            st.markdown(
                f'<div class="td-row"><div class="td-m">{esc(row[""])} '
                f'<b>{esc(row["Grade"])}</b> · {esc(amt(l, l.get("price_eur") or 0))} · '
                f'<span class="td-{tone}">{esc(sgn(l, surplus))}</span></div>'
                f'<div class="td-t">{esc(row["Title"])}</div></div>',
                unsafe_allow_html=True, width="stretch")
            st.button("Close" if pick == l["id"] else "Open", key=f"trio_{l['id']}",
                      on_click=_phone_pick, args=(l["id"],))
        if pick == l["id"]:
            render_summary(l, v, ctx="triage_phone")
    if pages > 1:
        with st.container(horizontal=True, vertical_alignment="center", key="trim_pages"):
            st.button("◀", key="trip_prev", on_click=_phone_page, args=(-1,),
                      disabled=page == 0)
            st.markdown(f'<div class="muted">page {page + 1} of {pages}</div>',
                        unsafe_allow_html=True, width="content")
            st.button("▶", key="trip_next", on_click=_phone_page, args=(1,),
                      disabled=page >= pages - 1)


def render(v) -> None:
    """The TRIAGE TABLE tab."""
    v_cur = v.cur
    _cf_negative = v.cf_negative
    greens = v.greens
    hidden_note = v.hidden_note
    in_view_cur = v.in_view_cur
    money_col = v.money_col
    n_hidden = v.n_hidden
    n_loaded = v.n_loaded
    n_scored_loaded = v.n_scored_loaded
    view = v            # the loop below reuses the name v for a money helper
    unscored_note = v.unscored_note
    view_market = v.market
    whites = v.whites
    yellows = v.yellows
    import pandas as pd

    scored = greens + yellows + whites
    if not scored:
        if n_loaded and not n_scored_loaded:
            st.info(unscored_note())
        elif n_hidden:
            st.info(hidden_note("scored listings"))
        else:
            st.info("No flats scored yet. Press RUN EVERYTHING at the top of the sidebar: it "
                    "fetches the portals and scores what it finds, in a few minutes.")
    else:
        from engine.financial import compute_deal_score
        emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪", "PENDING": "⏳"}
        triage_rows = []
        for l in scored:
            cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
            show_sro = view.sro(l)
            surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
            stress = l.get("stress_surplus_sro" if show_sro
                           or l.get("stress_surplus_personal") is None
                           else "stress_surplus_personal")
            score, grade = compute_deal_score(l)
            price = l.get("price_eur") or 0
            my = l.get("max_price_yellow")
            v = lambda x, _l=l: in_view_cur(_l, x)     # noqa: E731 — the view's currency
            irr_v = l.get("irr_sro") if show_sro else l.get("irr_personal")
            ph = l.get("_ph") or {}
            vibe = l.get("_vibe")
            disc = l.get("market_discount")
            triage_rows.append({
                "": emoji_map.get(cls, ""),
                "Grade":    grade,
                "Score":    score,
                "Title":    (l.get("title") or l.get("district") or "—")[:50],
                "District": l.get("district") or "—",
                "Stage":    (l.get("_stage") or {}).get("stage", ""),
                "Mkt":      "🇨🇿 CZ" if l.get("_market") == "cz" else "🇸🇰 SK",
                "Price":    v(price),
                "Native":   money(l, price),
                "Max 🟡":   v(my),
                "Max 🟢":   v(l.get("max_price_green")),
                # The card's "Max offer 🟡 … vs ask" figure: the move from the
                # asking price to the max YELLOW price.
                "To 🟡":    (my / price - 1) * 100 if my and price else None,
                # Blank without a benchmark: 0% would read as "at market".
                "Below%":   disc * 100 if disc is not None else None,
                "Size":     l.get("size_m2")              or 0,
                "Rent":     v(l.get("estimated_rent_eur")   or 0),
                "Surplus":  v(surplus if surplus is not None else 0),
                "CF":       "⛔" if _cf_negative(l) else ("✅" if surplus is not None else ""),
                "+2pp":     v(stress),
                "Gross%":   (l.get("gross_yield")         or 0) * 100,
                "Cap%":     (l.get("cap_rate")            or 0) * 100,
                "IRR%":     irr_v * 100 if irr_v is not None else None,
                "Yield":    (l.get("net_rental_yield")    or 0) * 100,
                "Days":     l.get("_dom"),
                "ΔPrice":   ph["change_pct"] * 100 if ph.get("change_pct") is not None else None,
                "Portals":  l.get("_portals", 1),
                "Features": _features_label(l),
                "Vibe":     vibe[0] if vibe else None,
                "LV":       _lv_state(l)[0].replace(" LV", "")
                            + (f" · {l['lv_risk_level']}" if l.get("lv_risk_level") else ""),
                "Src":      (l.get("source") or "").upper()[:5],
                "URL":      l.get("url") or "",
                "_id":      l.get("id"),               # not shown: the row's listing
            })
        df = pd.DataFrame(triage_rows).sort_values(
            ["Score", "Below%"], ascending=[False, False]
        )
        # The native price only says something when the money columns are
        # converted, i.e. with both markets on the page.
        if view_market is not None or (df["Mkt"] == "🇸🇰 SK").all():
            df = df.drop(columns="Native")
        # A column every row leaves empty (no listing has a benchmark yet) is
        # dropped: a number column shows each missing value as "None".
        df = df.drop(columns=[c for c in ("Max 🟡", "Max 🟢", "To 🟡", "Below%")
                              if df[c].isna().all()])
        st.markdown(
            f'<div class="muted">{len(df)} scored listings — sorted by composite deal '
            f'grade (yield + discount to market + location + energy + condition + '
            f'risk), then discount. Click any header to re-sort.</div>',
            unsafe_allow_html=True,
        )
        # The column chooser and the export. Grade, Title, Price and Surplus
        # always show, first and pinned while the rest scrolls; any other
        # column can be hidden. The choice is kept as the hidden ones, so a
        # column that appears later (Native, with both markets) shows.
        optional = [c for c in df.columns if c not in PINNED]
        st.session_state["triage_hide"] = [c for c in st.session_state.get("triage_hide", [])
                                           if c in optional]
        by_id = {l.get("id"): l for l in view.data}    # `v` is the money helper by now
        # D22: a phone gets the list; the stylesheet hides the one that doesn't fit.
        with st.container(key="triage_narrow"):
            render_phone_list(df, by_id, view)
        wide = st.container(key="triage_wide")
        c_cols, c_csv = wide.columns([5, 1])
        with c_cols:
            hidden = st.multiselect(
                "Hide columns", optional, key="triage_hide", label_visibility="collapsed",
                placeholder="Hide columns — Grade, Title, Price and Surplus always show")
        with c_csv:
            # Built on the click, not on every rerun.
            st.download_button(
                "⬇️ CSV", data=lambda: triage_csv(df), mime="text/csv", width="stretch",
                file_name=f"sovereign_triage_{datetime.now():%Y-%m-%d}.csv", key="triage_csv",
                help=f"Every row and column of this table as filtered — for your bank, "
                     f"adviser or partner. Money in {v_cur}; opens in Excel.")
        picked = wide.dataframe(
            df,
            width="stretch",
            hide_index=True,
            height=min(600, 40 + 35 * len(df)),
            column_order=[c for c in PINNED if c in df.columns]
                         + [c for c in optional if c not in hidden],
            column_config={
                "":        st.column_config.TextColumn(pinned=True),
                "Grade":   st.column_config.TextColumn(pinned=True),
                "Title":   st.column_config.TextColumn(pinned=True),
                "Score":   st.column_config.NumberColumn(format="%d", help="0–100 composite deal score"),
                "Stage":   st.column_config.TextColumn(width="medium"),
                "Mkt":     st.column_config.TextColumn(help="Market: Slovakia or Czechia"),
                "Price":   money_col("Price", pinned=True),
                "Native":  st.column_config.TextColumn(help=f"In the listing's own currency · {markets.fx_note()}"),
                "Max 🟡":  money_col("Max 🟡", help="Highest price that still scores YELLOW"),
                "Max 🟢":  money_col("Max 🟢", help="Highest price that scores GREEN"),
                "To 🟡":   st.column_config.NumberColumn(format="%+.1f%%", help="Change from the asking price to the max YELLOW price, as on the card — the cut you need to negotiate (positive = already inside)"),
                "Size":    st.column_config.NumberColumn(format="%d m²"),
                "Rent":    money_col("Rent"),
                "Surplus": money_col("Surplus", pinned=True),
                "+2pp":    money_col("+2pp", help="s.r.o. surplus at the mortgage rate + 2 pp"),
                "Below%":  st.column_config.NumberColumn(
                    format="%.0f%%", help="Asking €/m² below the regional median "
                                          "(negative = above it; blank = no benchmark)"),
                "Gross%":  st.column_config.NumberColumn(format="%.2f%%"),
                "Cap%":    st.column_config.NumberColumn(format="%.2f%%"),
                "IRR%":    st.column_config.NumberColumn(format="%.1f%%", help="10-year IRR incl. appreciation, exit costs and tax on the gain"),
                "Yield":   st.column_config.NumberColumn(format="%.2f%%", help="Net yield: the yearly cash flow over the price, under the structure recommended for the listing"),
                "CF":      st.column_config.TextColumn(help="⛔ = monthly surplus below CASHFLOW_MIN_SURPLUS: the class is price vs market, not income"),
                "Days":    st.column_config.NumberColumn(format="%d", help="Days tracked: since this dashboard first saw the flat on any portal (not the portal's posting date)"),
                "ΔPrice":  st.column_config.NumberColumn(format="%+.1f%%", help="Price change since first seen"),
                "Portals": st.column_config.NumberColumn(format="%d", help="Portals the same flat is listed on"),
                "Vibe":    st.column_config.NumberColumn(format="%d/10"),
                "URL":     st.column_config.LinkColumn(display_text="open ↗"),
            },
            # D3: a ticked row shows that flat's summary under the table;
            # UX5: several ticked can be starred, compared or passed at once.
            on_select="rerun", selection_mode="multi-row",
            key=f"triage_pick{st.session_state.get('triage_gen', 0)}",
        )
        rows = (picked.selection.rows if picked else []) or []
        chosen = [by_id[df.iloc[r]["_id"]] for r in rows if df.iloc[r]["_id"] in by_id]
        with wide:
            if len(chosen) == 1:
                render_summary(chosen[0], view)
            elif chosen:
                render_bulk(chosen, view)

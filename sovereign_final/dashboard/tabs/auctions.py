"""
dashboard/tabs/auctions.py — AUCTIONS: Slovak real-estate auctions from the
notaries' central register (modules/auctions_sk), with what each
announcement says once Claude has read it.
"""

import streamlit as st

from dashboard.fmt import esc

REGISTER = "https://www.notar.sk/drazba/?actId="


def _money(v) -> str:
    return f"€{v:,.0f}" if v else "—"


def render(v) -> None:
    """The AUCTIONS tab."""
    from database.auctions import get_auctions
    from modules import auctions_sk, doc_reader
    st.markdown('<div class="muted" style="margin-bottom:6px">AUCTIONS — real estate announced '
                'in the notaries\' register (NCRdr). Not scored with the listings: no mortgage '
                'before you bid, a deposit before the auction, one or two set viewings, and the '
                'flat may be occupied. Read the announcement and a lawyer\'s view first.</div>',
                unsafe_allow_html=True)
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("🔄 READ THE REGISTER", key="auct_refresh", width="stretch",
                     disabled=v.using_demo,
                     help="The next six weeks' auctions; the daily run does this too."):
            with st.spinner("Reading the register…"):
                try:
                    got = auctions_sk.refresh()
                    st.success(f"{got['seen']} announcement(s), {got['new']} new, "
                               f"{got['details']} record(s) read.")
                except Exception as e:
                    st.warning(f"The register couldn't be read: {type(e).__name__}: {e}")
    rows = [] if v.using_demo else get_auctions()
    with c2:
        flats_only = st.checkbox("Flats only (once read)", value=False, key="auct_flats")
        town = st.text_input("Town contains", key="auct_town", placeholder="e.g. Trnava")
    if flats_only:
        rows = [r for r in rows if r.get("is_flat")]
    if town.strip():
        rows = [r for r in rows if town.strip().lower() in (r.get("municipality") or "").lower()]
    if not rows:
        st.info("No auction on record yet. 🔄 READ THE REGISTER reads the next six weeks.")
        return
    st.caption(f"{len(rows)} auction(s). Proposer: a bank or a creditor sells a pledge; "
               "an owners' association (vlastníci bytov / SVB) recovers unpaid fees.")
    for r in rows[:60]:
        disc = auctions_sk.discount_to_median(r)
        head = (f'{r.get("auction_date") or "?"} · {esc(r.get("municipality") or "town not read")}'
                + (f' · {r["size_m2"]:.0f} m²' if r.get("size_m2") else "")
                + f' · lowest bid {_money(r.get("min_bid_eur"))}'
                + (f' · {abs(disc) * 100:.0f} % {"under" if disc >= 0 else "over"} the median'
                   if disc is not None else ""))
        with st.expander(head):
            st.markdown(
                f'<div class="brow"><span class="l">Proposer</span><span class="v">'
                f'{esc(r.get("proposer") or "—")}</span></div>'
                f'<div class="brow"><span class="l">Auctioneer</span><span class="v">'
                f'{esc(r.get("auctioneer") or "—")}</span></div>'
                f'<div class="brow"><span class="l">Opens</span><span class="v">'
                f'{esc(r.get("opens_at") or r.get("auction_date") or "—")} · '
                f'{esc(r.get("venue") or "")}</span></div>'
                + (f'<div class="brow"><span class="l">Valuation · deposit</span><span class="v">'
                   f'{_money(r.get("valuation_eur"))} · {_money(r.get("deposit_eur"))}</span></div>'
                   if r.get("read_at") else "")
                + (f'<div class="brow"><span class="l">Viewing</span><span class="v">'
                   f'{esc(r.get("inspection") or "—")}</span></div>' if r.get("read_at") else "")
                + (f'<div class="brow"><span class="l">LV</span><span class="v">'
                   f'{esc(r.get("lv_number") or "—")} · {esc(r.get("cadastral_area") or "")}'
                   f'</span></div>' if r.get("read_at") else ""),
                unsafe_allow_html=True)
            if r.get("notes"):
                st.caption(r["notes"])
            b1, b2 = st.columns(2)
            with b1:
                st.link_button("NCRdr RECORD", REGISTER + r["act_id"], width="stretch")
            with b2:
                if r.get("doc_url") and doc_reader.enabled() and st.button(
                        "📄 READ ANNOUNCEMENT", key=f"auct_read_{r['act_id']}", width="stretch",
                        disabled=v.using_demo,
                        help="Claude reads the published announcement (usually a scan): "
                             "town, size, lowest bid, valuation, deposit, viewings."):
                    with st.spinner("Claude is reading the announcement…"):
                        try:
                            got = auctions_sk.read_announcement(r["act_id"])
                        except Exception as e:
                            got, why = None, f"{type(e).__name__}: {e}"
                        else:
                            why = "not readable"
                    if got:
                        st.rerun()
                    st.warning(f"Not read ({why}).")
                elif r.get("doc_url") and not doc_reader.enabled():
                    st.link_button("ANNOUNCEMENT (PDF)", r["doc_url"], width="stretch")

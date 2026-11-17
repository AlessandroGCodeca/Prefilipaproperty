"""
dashboard/tabs/backtest.py — BACKTEST: does GREEN mean cheap? How fast the
flats of each class left the portals, after what cuts; and the stand-ins for
sold prices (engine/backtest).
"""

import streamlit as st


def render(v) -> None:
    """The BACKTEST tab."""
    import pandas as pd
    from engine import backtest
    market = v.market or "sk"
    st.markdown('<div class="muted" style="margin-bottom:6px">BACKTEST — of the flats each class '
                'held a month or two ago, how many have gone, how fast, after what cuts. If '
                'GREEN goes faster than WHITE, the market agrees it is cheap.</div>',
                unsafe_allow_html=True)
    if v.using_demo:
        st.info("The backtest reads your own history; the demo has none.")
        return
    c1, c2 = st.columns(2)
    with c1:
        frm = st.slider("Flats seen between … days ago", 14, 180, (60, 30), step=1,
                        key="bt_window", help="The cohort's window: older gives the flats more "
                                              "time to go.")
    rows, exact = backtest.run(max(frm), min(frm), market=market)
    if rows:
        st.dataframe(pd.DataFrame(rows).astype(object).fillna("—"), hide_index=True, width="stretch")
        st.caption(("Classes as they were on those days (daily snapshots)." if exact else
                    "Approximate: snapshots don't reach back that far yet, so the cohort is the "
                    "flats first seen in the window with the class they have now.")
                   + f" Gone: off the portals, or unseen for {backtest.GONE_AFTER_DAYS}+ days — "
                     "most are sold, some withdrawn.")
    else:
        st.info("No flats in that window yet.")

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    st.markdown('<div class="muted">SOLD PRICES — no free register publishes them. The last asking '
                'price of flats that left, and the sold prices you know, against the asking '
                'median</div>', unsafe_allow_html=True)
    gap = backtest.asking_vs(market)
    if gap:
        st.dataframe(pd.DataFrame(gap).astype(object).fillna("—"), hide_index=True, width="stretch")
    with st.form("bt_sold", border=False):
        s1, s2, s3, s4 = st.columns(4)
        district = s1.text_input("District", key="bt_d", placeholder="e.g. Petržalka")
        size = s2.number_input("Size m²", min_value=0.0, step=1.0, key="bt_s")
        price = s3.number_input("Sold for", min_value=0.0, step=1000.0, key="bt_p")
        when = s4.text_input("Sold on (YYYY-MM)", key="bt_w")
        source = st.text_input("From whom", key="bt_src", placeholder="agent, notary, your own")
        if st.form_submit_button("💾 ADD A SOLD PRICE"):
            try:
                backtest.add_sold_price(market, district, size, price, when, source=source)
                st.rerun()
            except ValueError as e:
                st.warning(str(e).capitalize() + ".")
    n = len(backtest.sold_prices())
    if n:
        st.caption(f"{n} sold price(s) on record.")

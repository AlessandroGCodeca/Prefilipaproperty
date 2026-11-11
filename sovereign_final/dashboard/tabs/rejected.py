"""
dashboard/tabs/rejected.py — REJECTED: the listings the title-deed (LV)
filter stopped, why, and RE-VERIFY LV.
"""

import pandas as pd
import streamlit as st

from dashboard.fmt import _digest, _lv_state, _quick_cadastre, _tag_market, esc
from dashboard.listing_cache import clear_listing_cache


def render(v) -> None:
    """The REJECTED tab."""
    in_view = v.in_view
    in_view_cur = v.in_view_cur
    money_col = v.money_col
    from database import get_rejected
    rejected = [_tag_market(r_) for r_ in get_rejected() if in_view(r_)]
    st.markdown('<div class="muted">LV REJECTIONS — LISTINGS THE TITLE-DEED FILTER STOPPED, '
                'AND WHY. These never reach the deal lists.</div>', unsafe_allow_html=True)
    # The outcome of the last RE-VERIFY below, carried across its rerun.
    _rej_msg = st.session_state.pop("rej_rv_msg", None)
    if _rej_msg:
        getattr(st, _rej_msg[0])(_rej_msg[1])
    if not rejected:
        st.info("Nothing rejected yet.")
    else:
        # Each row is one rejection decision; "Now" is where the listing stands
        # today. A re-check can have cleared it since — an overturned
        # rejection is history, so it is hidden unless asked for.
        show_overturned = st.toggle("Show rejections a later check overturned", value=False,
                                    key="rej_overturned")
        rej_df = pd.DataFrame([{
            "Flagged":  str(r_.get("flagged_at") or "")[:10],
            "Listing":  (r_.get("title") or r_.get("address_raw") or "—")[:50],
            "District": r_.get("district") or "—",
            "Mkt":      "🇨🇿 CZ" if r_.get("_market") == "cz" else "🇸🇰 SK",
            "Price":    in_view_cur(r_, r_.get("price_eur") or 0),
            "Now":      _lv_state(r_)[0],
            "Reason":   r_.get("reason") or "—",
            "Detail":   (r_.get("detail") or "")[:160],
            "LV risk":  r_.get("lv_risk_level") or "—",
            "By":       r_.get("module") or "—",
            "Active":   "yes" if r_.get("is_active") else "no",
            "URL":      r_.get("url") or "",
            "_still":   (r_.get("lv_status") or "") == "REJECTED",
        } for r_ in rejected])
        reasons = sorted(rej_df["Reason"].unique())
        # A keyed multiselect keeps its selection whatever default= says: the
        # reasons of an earlier render (another market's view, before a new
        # rejection came in) stayed picked and hid the rest. Keyed on the
        # reasons, it starts from all of them again whenever they change.
        pick_reasons = st.multiselect("Reason", reasons, default=reasons,
                                      key=f"rej_reasons_{_digest(reasons)}")
        view = rej_df[rej_df["Reason"].isin(pick_reasons)
                      & (rej_df["_still"] | show_overturned)].drop(columns="_still")
        n_overturned = int((~rej_df["_still"]).sum())
        st.markdown(f'<div class="muted">{len(view)} rejection(s) · '
                    + " · ".join(f"{esc(k)}: {v}" for k, v in view["Reason"].value_counts().items())
                    + (f" · {n_overturned} overturned since"
                       f"{'' if show_overturned else ' (hidden)'}" if n_overturned else "")
                    + '</div>', unsafe_allow_html=True)
        st.dataframe(view, hide_index=True, width="stretch",
                     column_config={"Price": money_col("Price"),
                                    "URL": st.column_config.LinkColumn(display_text="open ↗")})
        rv_opts = {f"{r_.get('title') or r_.get('address_raw') or '?'} [{r_['id'][:6]}]": r_["id"]
                   for r_ in rejected
                   if show_overturned or (r_.get("lv_status") or "") == "REJECTED"}
        if rv_opts:
            rv_pick = st.selectbox("Re-check a rejection (titles change — a lien can be cleared)",
                                   list(rv_opts.keys()), key="rej_pick")
            # A Czech flat is judged on the výpis pasted for it, and its card
            # is no longer shown: a newer (or the right) výpis goes in here.
            rv_id, rv_doc = rv_opts[rv_pick], None
            if next((r_.get("_market") for r_ in rejected if r_["id"] == rv_id), "sk") == "cz":
                from database import get_lv_document
                rv_doc = st.text_area(
                    "Výpis z LV (text)", value=get_lv_document(rv_id) or "",
                    key=f"rej_doc_{rv_id}", height=110,
                    help="Paste a newer výpis z LV of this flat, then RE-VERIFY LV. "
                         "Left blank, the flat has no výpis and rejoins the lists as "
                         "UNVERIFIED.")
            if st.button("RE-VERIFY LV", key="rej_rv", width="stretch"):
                try:
                    from modules.debt_bot import reverify
                    from database import mark_duplicates
                    if rv_doc is not None:
                        from database import get_lv_document, set_lv_document
                        if rv_doc.strip() != (get_lv_document(rv_id) or "").strip():
                            set_lv_document(rv_id, rv_doc)
                            clear_listing_cache()   # even if the check below fails
                    # The listing's own market's short timeout, as on its card:
                    # a Czech flat's lookups go to ČÚZK, not the Slovak cadastre.
                    rv_row = next(r_ for r_ in rejected if r_["id"] == rv_id)
                    with st.spinner("Checking the cadastre..."), _quick_cadastre(rv_row):
                        res = reverify(rv_id)
                    # A copy that is no longer rejected rejoins its group and
                    # lifts "a copy failed LV" from the others (or the reverse).
                    mark_duplicates()
                    clear_listing_cache()
                    if res["status"] == "REJECT":
                        msg = ("error", f"Still rejected: {res.get('detail')}")
                    elif res["status"] == "PASS":
                        msg = ("success", "✅ Now clean — it will be scored on the next run.")
                    elif res["status"] == "UNVERIFIED":
                        # No title deed was read: no longer rejected, but not
                        # clean either — it rejoins the lists as UNVERIFIED.
                        msg = ("warning", f"⚠ No longer rejected, but unverified: {res.get('detail')}")
                    else:
                        msg = ("warning", f"Re-verify: {res.get('detail', res['status'])}")
                except Exception as e:
                    msg = ("warning", f"Re-verify: {e}")
                # Redraw whatever the outcome: the table above, the stats and
                # the deal lists were drawn before the check changed the row.
                st.session_state["rej_rv_msg"] = msg
                st.rerun()

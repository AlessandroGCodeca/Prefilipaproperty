"""
dashboard/tabs/lv_todo.py — LV TO-DO: GREEN and YELLOW deals whose title deed
is not verified, with the flat's own LV number to type in.
"""

import pandas as pd
import streamlit as st

from modules import jobs

from dashboard.fmt import _digest, _tag_market
from dashboard.listing_cache import clear_listing_cache


def _cell(v) -> str:
    """A data-editor cell as text: a cleared cell comes back None or NaN."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def render(v) -> None:
    """The LV TO-DO tab."""
    _busy = v.busy
    in_view = v.in_view
    in_view_cur = v.in_view_cur
    money_col = v.money_col
    view_market = v.market
    from database import get_lv_todo
    st.markdown('<div class="muted">LV TO-DO — GREEN AND YELLOW DEALS WHOSE TITLE DEED IS NOT '
                'VERIFIED. The debt filter verifies a flat only through its own LV number, from '
                "the seller's papers or the agent — the building plot found under the map pin "
                'has a different LV. Type the numbers in below and save them in one go.</div>',
                unsafe_allow_html=True)
    from modules.debt_bot import KEYWORD_ONLY_NOTE, keyword_only
    if keyword_only():
        st.warning(f"🔑 {KEYWORD_ONLY_NOTE}")
    # The outcome of the last save below, carried across its rerun.
    _lv_msg = st.session_state.pop("lv_todo_msg", None)
    if _lv_msg:
        getattr(st, _lv_msg[0])(_lv_msg[1])
    todo = [_tag_market(t) for t in get_lv_todo() if in_view(t)]
    if not todo:
        st.info("Nothing waiting: no GREEN or YELLOW listing is short of a verified title deed.")
    else:
        def _plot_found(t):
            if not t.get("cadastral_number"):
                return "—"
            return (f"parcel {t['cadastral_number']} (k.ú. {t.get('cadastral_area') or '?'})"
                    + (f" · plot LV {t['plot_lv_number']}" if t.get("plot_lv_number") else ""))
        # The browser keeps an editor's edits by row number. With a plain
        # 0..n index and a fixed key, a queue that re-sorted (a re-score, a
        # finished job, the other market's view) kept the same editor, and a
        # typed LV number moved onto whichever flat now sat in that row — and
        # SAVE stored it there. The listing ids are the index, and their order
        # is in the key: when the rows change, the pending edits are dropped.
        todo_df = pd.DataFrame([{
            "id":       t["id"],
            "Class":    t["cf_class"],
            "Listing":  (t.get("title") or t.get("address_raw") or "—")[:50],
            "District": t.get("district") or "—",
            "Mkt":      "🇨🇿 CZ" if t.get("_market") == "cz" else "🇸🇰 SK",
            "Price":    in_view_cur(t, t.get("price_eur") or 0),
            "LV now":   t.get("lv_status") or "PENDING",
            "Last check": (t.get("lv_detail") or "")[:140],
            "Plot found": _plot_found(t),
            "Flat LV no.": t.get("lv_number") or "",
            "Katastrálne územie": t.get("cadastral_area") or "",
            "URL":      t.get("url") or "",
        } for t in todo]).set_index("id")
        editable = ("Flat LV no.", "Katastrálne územie")
        edited = st.data_editor(
            todo_df, key=f"lv_todo_editor_{_digest(todo_df.index)}", hide_index=True,
            width="stretch", disabled=[c for c in todo_df.columns if c not in editable],
            column_config={
                "Price": money_col("Price"),
                "Flat LV no.": st.column_config.TextColumn(
                    help="The flat's own LV — not the plot's — from the seller or agent."),
                "Katastrálne územie": st.column_config.TextColumn(
                    "Katastrální území" if view_market == "cz" else None,
                    help="Name or numeric code of the flat's cadastral unit "
                         "(katastrálne územie / katastrální území)."),
                "URL": st.column_config.LinkColumn(display_text="open ↗"),
            })
        stored = {t["id"]: ((t.get("lv_number") or "").strip(),
                            (t.get("cadastral_area") or "").strip()) for t in todo}
        changed = [(lid, _cell(row["Flat LV no."]), _cell(row["Katastrálne územie"]))
                   for lid, row in edited.iterrows()
                   if lid in stored
                   and (_cell(row["Flat LV no."]), _cell(row["Katastrálne územie"]))
                   != stored[lid]]
        st.caption(f"{len(todo)} listing(s) waiting · {len(changed)} edited")
        b1, b2 = st.columns(2)
        save_lv = b1.button("SAVE LV NUMBERS", key="lv_todo_save", disabled=not changed,
                            width="stretch",
                            help="Store them; the next 🔒 LV DEBT FILTER run checks them.")
        verify_lv = b2.button("SAVE & VERIFY NOW", key="lv_todo_verify",
                              disabled=not changed or _busy, width="stretch",
                              help="Look each one up on the cadastre now, in the "
                                   "background like the pipeline buttons.")
        if save_lv:
            # Storing the numbers is quick and offline; checking them is not.
            from modules.debt_bot import save_flat_lvs
            res = save_flat_lvs(changed)
            clear_listing_cache()
            st.session_state["lv_todo_msg"] = (
                "success", f"✅ Saved {res['saved']} LV number(s) — the next "
                           f"🔒 LV DEBT FILTER run checks them.")
            st.rerun()
        if verify_lv:
            # A cadastre lookup can retry for minutes; a list of them would
            # freeze the page (audit O7). It runs as a job under the pipeline
            # lock, and the sidebar shows its progress and result.
            def _lv_todo_step(progress, entries=tuple(changed)):
                from modules.debt_bot import save_flat_lvs
                from database import mark_duplicates
                res = save_flat_lvs(entries, verify=True, progress_callback=progress)
                mark_duplicates()   # the flat's other copies carry its LV result
                return "success", (f"✅ Checked {res['saved']}: clean {res['PASS']}, "
                                   f"rejected {res['REJECT']}, still unverified "
                                   f"{res['UNVERIFIED']}"
                                   + (f", failed {res['ERROR']}" if res["ERROR"] else "") + ".")
            _why = jobs.start("LV TO-DO VERIFY", _lv_todo_step)
            if _why:
                st.warning(_why)
            else:
                st.session_state["_job_watch"] = jobs.current().id
                st.rerun()

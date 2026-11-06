"""
dashboard/tabs/deal_pipeline.py — DEAL PIPELINE: every listing moved past
NEW, by stage, and each move's history.
"""

import streamlit as st

from database import DEAL_STAGES

from dashboard.cards import _load_stage
from dashboard.fmt import _local_stamp, _tag_market, amt, esc, market_badge


def render(v) -> None:
    """The DEAL PIPELINE tab."""
    data = v.data
    in_view = v.in_view
    stages = v.stages
    using_demo = v.using_demo
    from database import get_tracked_listings, get_deal_stage_history, set_deal_stage
    tracked = [_tag_market(t) for t in get_tracked_listings() if in_view(t)]
    st.markdown('<div class="muted">DEAL PIPELINE — EVERY LISTING YOU HAVE MOVED PAST "NEW". '
                'Move a deal from its card in ACTIVE SNAG LIST, or below.</div>',
                unsafe_allow_html=True)
    board_stages = [s_ for s_ in DEAL_STAGES if s_ != "NEW"]
    if not tracked:
        st.info("No tracked deals yet.")
    else:
        # A rejected listing leaves every deal list, but a tracked deal stays
        # on this board — which then has to say its title deed failed.
        lv_failed = [t for t in tracked
                     if t.get("lv_status") == "REJECTED" and t["stage"] not in ("CLOSED", "PASSED")]
        if lv_failed:
            st.error(f"⛔ {len(lv_failed)} tracked deal(s) failed the LV check: "
                     + ", ".join(f"{(t.get('title') or t.get('district') or '—')[:40]} [{t['stage']}]"
                                 for t in lv_failed)
                     + ". See the REJECTED tab for why.")
        counts = {stg: sum(1 for t in tracked if t["stage"] == stg) for stg in board_stages}
        st.markdown('<div class="muted">' + " · ".join(f"{k} {v}" for k, v in counts.items())
                    + '</div>', unsafe_allow_html=True)
        live_stages = [stg for stg in board_stages if counts[stg]]
        cols = st.columns(max(len(live_stages), 3))
        for col, stg in zip(cols, live_stages):
            items = [t for t in tracked if t["stage"] == stg]
            with col:
                st.markdown(f'<div class="muted">{stg} ({len(items)})</div>', unsafe_allow_html=True)
                for t in items:
                    gone = "" if t.get("is_active") else " · OFF MARKET"
                    if t.get("lv_status") == "REJECTED":
                        gone += " · ⛔ LV REJECTED"
                    maxy = (f" · max🟡 {amt(t, t['max_price_yellow'])}"
                            if t.get("max_price_yellow") else "")
                    note = f'<div class="muted">{esc(t["note"])}</div>' if t.get("note") else ""
                    name = esc((t.get("title") or t.get("district") or "—")[:40])
                    st.markdown(
                        f'<div class="sc" style="margin-bottom:6px;padding:8px">'
                        f'<div class="mono" style="font-size:.7rem;color:#e4eaf5">'
                        f'<a href="{esc(t["url"])}" target="_blank">{name}</a></div>'
                        f'<div class="muted">{market_badge(t)} {amt(t, t.get("price_eur") or 0)}{maxy}'
                        f' · {_local_stamp(t.get("updated_at"))[0][:10]}{gone}</div>{note}</div>',
                        unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    all_opts = {f"{l.get('title') or l.get('district') or '?'} — {amt(l, l.get('price_eur') or 0)}"
                f" [{(l.get('id') or '')[:6]}]": l.get("id") for l in data}
    for t in tracked:
        all_opts.setdefault(f"{t.get('title') or '?'} — {amt(t, t.get('price_eur') or 0)}"
                            f" [{t['id'][:6]}]", t["id"])
    if all_opts:
        p1, p2, p3 = st.columns([3, 1, 2])
        with p1:
            pick_id = all_opts[st.selectbox("Listing", list(all_opts.keys()), key="pipe_pick")]
        with p2:
            cur = (stages.get(pick_id) or {}).get("stage", "NEW")
            _load_stage("pipe_stage", cur, pick_id)
            pick_stage = st.selectbox("Stage", DEAL_STAGES, key="pipe_stage")
        with p3:
            pick_note = st.text_input("Note", key="pipe_note")
        # In demo mode the picker still offers the real tracked deals, and
        # those can move; a demo row isn't in the database.
        demo_pick = using_demo and pick_id not in {t["id"] for t in tracked}
        if st.button("MOVE DEAL", width="stretch", disabled=demo_pick):
            set_deal_stage(pick_id, pick_stage, pick_note)
            st.rerun()
        if demo_pick:
            st.caption("Demo listing — it can't be moved.")
        # Stored in UTC; shown in Bratislava time, as EARLIER DRAFTS is.
        hist = get_deal_stage_history(pick_id)
        if hist:
            st.markdown("".join(
                f'<div class="brow"><span class="l">{_local_stamp(h["changed_at"])[0]}</span>'
                f'<span class="v">{esc(h["stage"])}{" — " + esc(h["note"]) if h.get("note") else ""}</span></div>'
                for h in hist), unsafe_allow_html=True)

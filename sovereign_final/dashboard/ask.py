"""
dashboard/ask.py — ask Claude about one flat (UX7). A box on the card takes a
question ("what if I let it furnished?", "why is the grade C?"); Claude
answers from the card's own figures (card_facts) and lists the figures it
used, so an answer can be checked against the card.

What is sent: the flat's figures as the dashboard modelled them, its title,
district and the ad's text. Never the title deed's text, with its owners'
names. A question is asked only on the button, and the same question about
the same figures is answered from this session's memory, not asked again.
"""

from __future__ import annotations

import hashlib
import json

import streamlit as st

from dashboard.fmt import esc

# The card's figures Claude may use: the listing's own fields by name.
FIELDS = (
    "title", "district", "rooms", "floor", "size_m2", "condition", "energy_class",
    "furnished", "has_balcony", "has_parking", "has_elevator",
    "price_eur", "regional_median_m2", "market_discount", "cf_class",
    "estimated_rent_eur", "rent_source", "hoa_monthly", "property_tax_monthly",
    "vacancy_cost", "maintenance_monthly", "management_monthly",
    "mortgage_monthly", "mortgage_monthly_sro", "income_tax_personal", "income_tax_sro",
    "surplus_personal", "surplus_sro", "stress_surplus_personal", "stress_surplus_sro",
    "optimal_structure", "cap_rate", "cash_on_cash", "gross_yield", "net_rental_yield",
    "irr_personal", "irr_sro", "max_price_yellow", "max_price_green",
    "loan_term_years", "lv_status", "lv_risk_level", "location_score",
)
DESCRIPTION_CHARS = 1500


def card_facts(l: dict, deal_score=None, deal_grade=None) -> dict:
    """The flat as the card shows it, for Claude."""
    from database import get_listing_description
    facts = {k: l[k] for k in FIELDS if l.get(k) not in (None, "")}
    facts["currency"] = l.get("_cur") or "EUR"
    if l.get("price_eur") and l.get("size_m2"):
        facts["price_per_m2"] = round(l["price_eur"] / l["size_m2"])
    if deal_grade:
        facts["deal_grade"], facts["deal_score_of_100"] = deal_grade, deal_score
    if l.get("_dom") is not None:
        facts["days_tracked"] = l["_dom"]
    ph = l.get("_ph") or {}
    if ph.get("change_pct") is not None:
        facts["price_change_since_first_seen"] = ph["change_pct"]
    try:
        text = get_listing_description(l["id"]) or ""
    except Exception:
        text = ""
    if text:
        facts["ad_text"] = text[:DESCRIPTION_CHARS]
    return facts


def _key(lid: str, question: str, facts: dict) -> str:
    raw = json.dumps([lid, question.strip().lower(), facts], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def render(l: dict, demo: bool, cz: bool, deal_score=None, deal_grade=None) -> None:
    """The card's question box (behind a switch). `demo`: the page shows the
    demo data (nothing to ask about)."""
    from modules.llm_enrichment import ask_about_flat, is_enabled
    lid = l["id"]
    if not st.toggle("Zeptat se na tento byt" if cz else "Ask about this flat",
                     key=f"ask_t_{lid}",
                     help=("Claude odpoví z čísel této karty a uvede, která použil."
                           if cz else "Claude answers from this card's figures and lists "
                           "the ones it used.")):
        return
    if not is_enabled():
        st.info("Needs ANTHROPIC_API_KEY in .env (README \"API Keys\").")
        return
    if demo:
        st.info("Not on the demo data.")
        return
    q = st.text_input("Otázka" if cz else "Question", key=f"ask_q_{lid}", max_chars=500,
                      placeholder=("např. Co když ho pronajmu zařízený?" if cz else
                                   "e.g. What if I let it furnished? Why is the grade C?"))
    answers = st.session_state.setdefault("_ask_answers", {})
    facts = card_facts(l, deal_score, deal_grade)
    if st.button("ZEPTAT SE" if cz else "ASK", key=f"ask_b_{lid}", disabled=not q.strip()):
        k = _key(lid, q, facts)
        if k not in answers:
            with st.spinner("Claude čte kartu…" if cz else "Claude is reading the card…"):
                answers[k] = (q.strip(), ask_about_flat(q, facts))
        st.session_state[f"ask_last_{lid}"] = k
    last = answers.get(st.session_state.get(f"ask_last_{lid}", ""))
    if not last:
        return
    asked, got = last
    if not got:
        st.warning("Claude neodpověděl; zkuste to znovu." if cz else
                   "Claude didn't answer; try again in a moment.")
        return
    used = got.get("figures_used") or []
    st.markdown(
        f'<div class="muted">{esc(asked)}</div><div>{esc(got.get("answer") or "")}</div>'
        + ('<div class="muted" style="margin-top:4px">'
           + ("Použitá čísla: " if cz else "Figures used: ")
           + " · ".join(f"{esc(u.get('name'))} = {esc(u.get('value'))}" for u in used[:12])
           + "</div>" if used else ""),
        unsafe_allow_html=True)
    st.caption("Odpověď z čísel modelu, ne finanční, daňová ani právní rada." if cz else
               "An answer from the model's figures, not financial, tax or legal advice.")

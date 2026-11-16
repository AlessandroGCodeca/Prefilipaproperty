"""
dashboard/tabs/alert_rules.py — ALERTS: the saved searches Telegram messages
you about (modules/alerts), and what fits them right now.

A rule is a name and what a listing must be: its market, class, grade,
district, size, price and the least monthly surplus. A listing that fits any
rule that is switched on is announced once (and again when it turns GREEN or
its price is cut). With no rule saved, the built-in one from .env applies.
"""

import streamlit as st

from dashboard.fmt import amt, esc, sgn

_ANY = "any"
_COLUMNS = ["name", "enabled", "market", "classes", "grades", "district",
            "min_size", "max_price_eur", "min_surplus"]


def rules_frame(rules: list[dict]):
    """The rules as the editor's table (a blank market reads "any")."""
    import pandas as pd
    rows = [{**{c: r.get(c) for c in _COLUMNS}, "enabled": bool(r.get("enabled", 1)),
             "market": r.get("market") or _ANY,
             "classes": (r.get("classes") or "").replace(",", ", "),
             "grades": (r.get("grades") or "").replace(",", ", ")} for r in rules]
    return pd.DataFrame(rows, columns=_COLUMNS).astype({"enabled": bool})


def rows_from_editor(frame) -> list[dict]:
    """The editor's table as rule dicts for database.save_alert_rules."""
    out = []
    for row in frame.to_dict("records"):
        row = {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}
        row["market"] = "" if row.get("market") in (None, _ANY) else row["market"]
        row["enabled"] = row.get("enabled") not in (False, None)
        out.append(row)
    return out


def describe_rule(rule: dict) -> str:
    """One rule in words."""
    bits = []
    if rule.get("market"):
        bits.append({"sk": "Slovakia", "cz": "Czechia"}[rule["market"]])
    bits.append((rule.get("classes") or "any class").replace(",", " or "))
    if rule.get("grades"):
        bits.append("grade " + rule["grades"].replace(",", " or "))
    if rule.get("district"):
        bits.append(f"district contains “{rule['district']}”")
    if rule.get("min_size") is not None:
        bits.append(f"at least {rule['min_size']:.0f} m²")
    if rule.get("max_price_eur") is not None:
        bits.append(f"at most €{rule['max_price_eur']:,.0f}")
    if rule.get("min_surplus") is not None:
        bits.append(f"surplus at least €{rule['min_surplus']:+,.0f}/mo")
    return " · ".join(bits)


def render(v) -> None:
    """The ALERTS tab."""
    import database
    from database.alert_rules import clean_rule
    from modules import alerts
    st.markdown('<div class="muted" style="margin-bottom:6px">ALERTS — WHAT TELEGRAM TELLS YOU '
                'ABOUT. A listing that fits any rule switched on is announced once, and again '
                'when it turns GREEN or its price is cut. Money is in euros.</div>',
                unsafe_allow_html=True)
    if not alerts.enabled():
        st.warning("Telegram isn't set up: put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in "
                   ".env (README “Telegram alerts”). Rules can be saved meanwhile.")
    saved = database.get_alert_rules()
    if not saved:
        st.info("No rule saved yet, so the built-in one applies: "
                f"{describe_rule(alerts.builtin_rule())}. Add a line below to replace it — "
                "for example a district you watch, or grade A and B only.")
    edited = st.data_editor(
        rules_frame(saved), num_rows="dynamic", hide_index=True, width="stretch",
        key="alert_rules_editor", disabled=v.using_demo,
        column_config={
            "name": st.column_config.TextColumn("Name", max_chars=60, required=True,
                                                help="Shown in the message."),
            "enabled": st.column_config.CheckboxColumn("On", default=True),
            "market": st.column_config.SelectboxColumn("Market", options=[_ANY, "sk", "cz"],
                                                       default=_ANY, required=True),
            "classes": st.column_config.TextColumn(
                "Classes", help="GREEN, YELLOW, WHITE — separated by commas. Blank: any."),
            "grades": st.column_config.TextColumn(
                "Grades", help="A, B, C, D — separated by commas. Blank: any."),
            "district": st.column_config.TextColumn(
                "District contains", help="Part of the district's name, e.g. Petržalka."),
            "min_size": st.column_config.NumberColumn("Min m²", min_value=0, step=1),
            "max_price_eur": st.column_config.NumberColumn("Max price €", min_value=0,
                                                           step=1000, format="%d"),
            "min_surplus": st.column_config.NumberColumn(
                "Min surplus €/mo", step=10, format="%d",
                help="The least monthly surplus under the recommended structure. May be "
                     "negative: -150 means it may cost you up to €150 a month. Blank: any."),
        })
    rows = rows_from_editor(edited)
    typed = [r for r in (clean_rule(row) for row in rows) if r]
    c1, c2 = st.columns([1, 3])
    with c2:
        only_new = st.checkbox(
            "Tell me only about listings that come in from now on", value=True,
            key="alert_rules_only_new",
            help="On: everything that fits the rules today is noted as already announced. "
                 "Off: the next run messages all of it (ten are listed, the rest counted).")
    with c1:
        if st.button("💾 SAVE RULES", key="alert_rules_save", width="stretch",
                     disabled=v.using_demo):
            n = database.save_alert_rules(rows)
            noted = alerts.note_existing() if only_new else 0
            st.success(f"Saved {n} rule(s)."
                       + (f" {noted} listing(s) that fit them now are noted as announced."
                          if only_new else " The next run messages what fits them now."))
    for r in typed:
        st.markdown(f'<div class="muted">{"🟢" if r["enabled"] else "⚪"} '
                    f'<b>{esc(r["name"])}</b> — {esc(describe_rule(r))}</div>',
                    unsafe_allow_html=True)

    # What fits the rules as typed — read from the database only on request.
    if st.toggle("Show what fits these rules now", key="alert_rules_preview",
                 disabled=v.using_demo):
        rules = [r for r in typed if r["enabled"]] or ([] if typed else [alerts.builtin_rule()])
        deals = alerts.qualifying_deals(rules) if rules else []
        told = alerts._sent("deal")
        fresh = sum(1 for l in deals if alerts._deal_key(l) not in told)
        st.markdown(f'<div class="muted">{len(deals)} listing(s) fit · {fresh} not announced '
                    f'yet</div>', unsafe_allow_html=True)
        html = ""
        for l in deals[:25]:
            html += (f'<div class="brow"><span class="l">{esc((l.get("title") or "—")[:60])} · '
                     f'{esc(l.get("district") or "")}'
                     + (f' · 🔎 {esc(", ".join(l["_rules"]))}' if l.get("_rules") else "")
                     + f'</span><span class="v">{amt(l, l.get("price_eur") or 0)} · '
                       f'{l["_class"]} · {sgn(l, l["_best"])}</span></div>')
        if html:
            st.markdown(html, unsafe_allow_html=True)
        if len(deals) > 25:
            st.caption(f"…and {len(deals) - 25} more.")

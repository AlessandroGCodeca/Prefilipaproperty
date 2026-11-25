"""
dashboard/lv_view.py — "Read part C": the encumbrance section of the title
deed the last LV check read, with what the screen made of each entry.

The screen (modules/lv_screen) reads a deed by the words it knows. This shows
you the text it read: what it blocked on, what it flagged, the bank liens it
let through, and any entry it has no rule for — so reading part C yourself
before an offer is one click, not a trip to the cadastre.
"""

import streamlit as st

from dashboard.fmt import days_since, esc

_MARK_CSS = {"hard": "lvh", "soft": "lvs", "bank": "lvb", "unknown": "lvu"}
LEGEND = ('<span class="lvh">blocks</span> <span class="lvs">flagged, not rejected</span> '
          '<span class="lvb">bank lien</span> <span class="lvu">no rule for this — read it</span>')
LEGEND_CZ = ('<span class="lvh">blokuje</span> <span class="lvs">upozornění</span> '
             '<span class="lvb">zástava banky</span> <span class="lvu">neznámý zápis — přečtěte</span>')


def deed_text(l, lv_docs=None) -> tuple[str, str] | None:
    """(text, when it was fetched) of the listing's own title deed, from what
    is stored — the cadastre is never asked. A Czech listing's is the výpis
    pasted on its card; a Slovak one's the report the last check fetched.
    None when there is none."""
    if l.get("_market") == "cz":
        text = (lv_docs or {}).get(l.get("id")) or ""
        return (text, "") if text.strip() else None
    if not l.get("lv_number"):
        return None
    from kataster_scraper import cached_lv_text
    for area in (l.get("cadastral_unit_code"), l.get("cadastral_area")):
        got = cached_lv_text(area, l["lv_number"])
        if got:
            return got
    return None


def part_c_html(text: str, cz: bool = False) -> str:
    """Part C of a deed as HTML: each piece escaped, the screen's reading as
    coloured marks. "" when the text has no part C heading."""
    if cz:
        from modules.lv_screen import describe
        from modules.lv_screen_cz import part_c_start, screen_lv_cz, unrecognised_entries
        at = part_c_start(text)
        if at is None:
            return ""
        found = [(("lvh" if e["blocking"] else "lvs" if e.get("tier") == "soft" else "lvb"),
                  describe(e)) for e in screen_lv_cz(text)]
        found += [("lvu", u) for u in unrecognised_entries(text)]
        head = "".join(f'<div><span class="{css}">{esc(what)}</span></div>' for css, what in found)
        return f'{head}<div class="lvc">{esc(text[at:])}</div>'
    from modules.lv_screen import part_c_marks
    pieces = part_c_marks(text)
    if not pieces:
        return ""
    body = "".join(f'<span class="{_MARK_CSS[m]}">{esc(t)}</span>' if m else esc(t)
                   for t, m in pieces)
    return f'<div class="lvc">{body}</div>'


def render_part_c(l, lv_docs=None) -> None:
    """The toggle on a card, and under it part C of the deed on file. Built
    only while the toggle is on: it reads the stored deed and screens it."""
    from dashboard.fmt import czech_words
    cz = czech_words(l)
    if not st.toggle("📜 Přečíst část C výpisu z LV" if cz else "📜 Read part C of the title deed",
                     key=f"lvc_{l.get('id')}",
                     help="The encumbrance section of the deed the last LV check read, with "
                          "what the screen made of each entry. Read it before an offer, "
                          "whatever the badge says."):
        return
    got = deed_text(l, lv_docs)
    if got is None:
        st.info("K této jednotce není uložen text výpisu — vložte jej níže a klikněte OVĚŘIT LV."
                if cz else
                "No deed text is on file for this flat. Enter its own LV number above and "
                "click RE-VERIFY LV; the text is kept for "
                "LV_TEXT_RETENTION_DAYS (180 days by default).")
        return
    text, fetched = got
    html = part_c_html(text, cz)
    if not html:
        st.warning("The stored text has no part C heading — not a readable LV. "
                   "Open the deed on the cadastre.")
        return
    age = days_since(fetched)
    when = (f" · fetched {fetched[:10]}" + (f" ({age} days ago)" if age else "")) if fetched else ""
    st.markdown(f'<div class="muted">{LEGEND_CZ if cz else LEGEND}{esc(when)}</div>{html}',
                unsafe_allow_html=True)


def render_erase(l, disabled: bool = False) -> None:
    """🗑 Erase the owners' data of one flat: the deed text, the cadastre's
    answer, Claude's reading and a draft's seller name (database.
    erase_owner_data). For a request from an owner or seller, or a deal you
    dropped; the LV verdict stays."""
    lid = l.get("id")
    # A toggle, not an expander: the card itself is one, and they don't nest.
    if st.toggle("🗑 Erase owners' data for this flat (GDPR)", key=f"erase_t_{lid}"):
        from modules.backup import retention_text
        st.caption("Deletes the stored deed text, the cadastre's answer, Claude's reading of it, "
                   "the execution and court details, and the seller's name in a contract draft. "
                   "The LV verdict stays. Backups keep the old data until they are pruned "
                   f"({retention_text()}). An owner who asks you to erase their data: do "
                   "this, then reply within a month, and say how long the backups keep it.")
        sure = st.checkbox("I want to erase it", key=f"erase_ok_{lid}", disabled=disabled)
        if st.button("ERASE", key=f"erase_{lid}", disabled=disabled or not sure):
            from database import erase_owner_data
            got = erase_owner_data(lid)
            st.success(f"Erased: {sum(got.values())} record(s).")

"""
dashboard/legal.py — the disclaimer under every page, and the imprint, the
privacy notice and the terms of use behind it.

Shown on the login page too: whoever reaches the dashboard can read who runs
it and what happens to data before logging in (the Slovak e-commerce act,
Act 22/2004 § 4, and GDPR Articles 13 and 14 for the people a listing or a
deed names). The operator's details come from .env (OPERATOR_*); a missing
one shows as "not set". These texts are a starting point written for this
code — have a lawyer read them before anyone else uses the dashboard.
"""

from __future__ import annotations

import os

import streamlit as st

from dashboard.fmt import esc

DISCLAIMER = (
    "Estimates for information only, from data published by third parties, which may be "
    "wrong or out of date. Not financial, investment, tax or legal advice and not real-estate "
    "brokerage. Check every figure, the title deed and the contract with a professional "
    "before you decide."
)

FIELDS = (
    ("OPERATOR_NAME", "Operator"),
    ("OPERATOR_ADDRESS", "Address"),
    ("OPERATOR_ID", "Company ID (IČO)"),
    ("OPERATOR_VAT_ID", "VAT ID (IČ DPH)"),
    ("OPERATOR_REGISTER", "Registered in"),
    ("OPERATOR_EMAIL", "E-mail"),
    ("OPERATOR_PHONE", "Phone"),
)
# A VAT ID only if the operator is registered for VAT.
OPTIONAL = {"OPERATOR_VAT_ID", "OPERATOR_PHONE"}


MAPY_LOGO = "https://api.mapy.com/img/api/logo_green.svg"
MAPY_URL = "https://mapy.com/"


def mapy_credit_html(height: int = 24, words: str = "Search by Mapy.com") -> str:
    """Mapy.com's required credit for its geocoder: the logo, clickable, at
    least 20 px high (the green variant; the black one disappears on the dark
    theme), with its words. Empty without a MAPY_API_KEY. Terms and logos:
    developer.mapy.com/rest-api-mapy-cz/atribution/. The logo loads from
    Mapy.com's server, as the terms describe, so the privacy notice names it."""
    if not os.getenv("MAPY_API_KEY"):
        return ""
    return (f'<a href="{MAPY_URL}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:inherit;display:inline-flex;align-items:center;'
            f'gap:8px"><img src="{MAPY_LOGO}" alt="Mapy.com" '
            f'style="height:{max(height, 20)}px;vertical-align:middle">'
            f'<span class="muted" style="font-size:.7rem">{esc(words)}</span></a>')


def operator() -> dict[str, str]:
    return {k: os.getenv(k, "").strip() for k, _ in FIELDS}


def missing() -> list[str]:
    """The required operator details not set in .env."""
    return [k for k, v in operator().items() if not v and k not in OPTIONAL]


def _v(key: str) -> str:
    val = operator()[key]
    return esc(val) if val else f'<span style="color:#f5b84a">not set ({key})</span>'


def imprint_html() -> str:
    rows = "".join(
        f'<div class="brow"><span class="l">{label}</span><span class="v">{_v(k)}</span></div>'
        for k, label in FIELDS if operator()[k] or k not in OPTIONAL)
    return rows + ('<div class="muted" style="margin-top:6px">Supervisory authority for '
                   'consumer protection: Slovak Trade Inspection (SOI), soi.sk. For personal '
                   'data: Úrad na ochranu osobných údajov SR, dataprotection.gov.sk.</div>')


def privacy_md() -> str:
    who = operator()["OPERATOR_NAME"] or "the operator named in the imprint"
    mail = operator()["OPERATOR_EMAIL"] or "the e-mail in the imprint"
    return f"""
**Controller.** {who}, {mail}.

**What is processed, and why.**
- *Property listings* published on Slovak and Czech portals: price, size, address, photos' links
  and the ad's text, which can name an agent or a seller and give a phone number. Purpose:
  comparing flats for sale with their market. Legal basis: legitimate interest (GDPR Art. 6(1)(f)).
- *Title-deed (LV) data* from the cadastre: owners' names, liens, executions and court notes on a
  flat. Purpose: checking that a flat can be bought safely. Legal basis: legitimate interest
  (Art. 6(1)(f)). The people named are not told one by one (Art. 14(5)(b)); this notice is published
  instead.
- *Company register data* (ARES, Register účtovných závierok) about a selling company.
- *Your own entries*: notes, deal stages, uploaded documents, your financing figures. Legal basis:
  providing the service you use (Art. 6(1)(b)).
- *Technical data*: the login, error logs on the server. No analytics and no advertising.

**Who else receives data (processors).**
- Anthropic (USA): an ad's text, an uploaded scan or deed, an auction announcement — to read them.
  Under Anthropic's data processing addendum with the EU Standard Contractual Clauses; not used to
  train models.
- Mapy.com, Seznam.cz, a.s. (Czechia): the address of a listing, to find its coordinates.
  Used only when a Mapy.com key is set. Inside the EU.
- Google Maps Platform (USA): addresses and coordinates, for location, amenities, satellite
  pictures and travel times. Under Google's data processing terms.
- Telegram: alert messages to the operator's own chat.
- Healthchecks.io: only whether the daily run happened, no personal data.
- Apple iCloud (if backups are copied there): encrypted at rest by Apple.

**What your browser loads from others.** Map tiles (CARTO), listing photos from the portals'
servers and, when a Mapy.com key is set, the Mapy.com logo from Mapy.com's server (Seznam.cz,
Czechia — its terms require the logo): they see your IP address, as with any website you open.

**How long.** Deed texts: until the flat has been off the market for LV_TEXT_RETENTION_DAYS
(180 by default) and is not a deal you track. Daily backups: the newest BACKUP_KEEP (14).
Logs: rotated, at most about 30 MB. Listings stay while they are useful for price history.

**Cookies.** One strictly necessary cookie (`_streamlit_xsrf`, protection against forged
requests). No consent is needed for it, and no other cookie is set.

**Your rights.** Access, rectification, erasure, restriction, objection and portability (Art. 15–21):
write to {mail}; we answer within one month. You can complain to the
Úrad na ochranu osobných údajov Slovenskej republiky (dataprotection.gov.sk).
"""


def terms_md() -> str:
    return f"""
**What this is.** A tool that estimates the price, rent, costs and risks of flats from public data.

**What it is not.** {DISCLAIMER}

**Accuracy.** Listings, cadastre extracts, tax tables and market rates come from third parties and
from automated reading (including AI), which makes mistakes. Figures are models with stated
assumptions, not offers or valuations.

**Your use.** Use it lawfully. Don't copy the portals' listings or photos out of it in bulk.
Uploaded documents must be yours to share.

**Liability.** Decisions are yours. Liability for losses from relying on an estimate is excluded as
far as the law allows; nothing here limits liability that cannot be limited (for example intent,
gross negligence, or a consumer's statutory rights).

**Law.** Slovak law. A consumer keeps the protection of the law of the country where they live.
"""


def render_footer() -> None:
    """The disclaimer, and the imprint, privacy notice and terms each in an
    expander, at the foot of the page."""
    st.markdown(f'<hr class="div"><div class="muted" style="font-size:.7rem">'
                f'⚖️ {esc(DISCLAIMER)}</div>', unsafe_allow_html=True)
    credit = mapy_credit_html(words="Powered by Mapy.com · address search")
    if credit:
        st.markdown(f'<div style="margin:6px 0">{credit}</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1, st.expander("Imprint"):
        st.markdown(imprint_html(), unsafe_allow_html=True)
    with c2, st.expander("Privacy notice"):
        st.markdown(privacy_md())
    with c3, st.expander("Terms of use"):
        st.markdown(terms_md())

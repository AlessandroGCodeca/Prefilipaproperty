"""
dashboard/fmt.py — formatting shared by the tabs: escaping, money in a
listing's own currency, badges and labels, a Czech card's Czech words. Pure
functions of a row; nothing here reads the page's state.
"""

from html import escape as _html_escape

import streamlit as st

import markets


# A job's or a step's (level, message) → the box it is shown in.
_SHOW = {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}


def esc(v) -> str:
    """HTML-escape text that came from a portal, an API or a typed note before
    it goes into st.markdown(..., unsafe_allow_html=True). Scraped titles, LV
    details and URLs are written by strangers; unescaped, a "<" garbles the
    page and an <img onerror=…> runs in the dashboard's origin."""
    return _html_escape("" if v is None else str(v), quote=True)


def _tag_market(l: dict) -> dict:
    """Mark a row with its market, its currency and its price in EUR."""
    l["_market"] = markets.of_row(l)
    l["_cur"] = l.get("currency") or markets.get(l["_market"]).currency
    l["_price_eur"] = markets.to_eur(l.get("price_eur") or 0, l["_cur"])
    return l


_CZ_SUFFIX = {"/mo": "/měs.", "/yr": "/rok"}


def money(l, v, suffix: str = "", decimals: int = 0, signed=None) -> str:
    """An amount of listing `l` in its own currency, written the way its
    market writes it: -€41/mo for a Slovak flat (as always), -1 200 Kč/měs.
    for a Czech one."""
    cur = ((l or {}).get("_cur") or (l or {}).get("currency") or "EUR").upper()
    if cur != "EUR":
        suffix = _CZ_SUFFIX.get(suffix, suffix)
    return markets.format_money(v, cur, decimals, suffix=suffix, signed=signed)


def mkw(l) -> dict:
    """{"market": m} for an engine call about a non-Slovak row, {} for a
    Slovak one — the engine's default, so a Slovak row's call is unchanged."""
    m = markets.of_row(l)
    return {} if m == "sk" else {"market": m}


# ── Helpers ───────────────────────────────────────────────────────────────────
def fe(v, prefix="€", suffix="", decimals=0, signed=None):
    """Money with the sign ahead of the symbol: -€41/mo, +€23/mo, €78,000.
    signed (default: on for /mo) adds the + to non-negative amounts."""
    if v is None: return "—"
    if signed is None:
        signed = suffix == "/mo"
    v = round(v, decimals) + 0.0   # + 0.0 turns -0.0 into 0.0: no "-€0"
    sign = "-" if v < 0 else ("+" if signed else "")
    return f"{sign}{prefix}{abs(v):,.{decimals}f}{suffix}"

def fp(v):
    return f"{(v or 0)*100:.1f}%" if v is not None else "—"

def _of100(v):
    """A 0–100 score that may be missing: None shows "—", a real 0 "0/100"."""
    return "—" if v is None else f"{v}/100"

def _digest(items) -> str:
    """A short, stable digest of a sequence, for a widget key that has to
    change when the rows or options behind the widget change."""
    import hashlib
    return hashlib.sha1("\x1f".join(map(str, items)).encode("utf-8")).hexdigest()[:12]

def _local_stamp(iso: str | None) -> tuple[str, str]:
    """A stored UTC timestamp in Bratislava time — the time the draft's own
    "Vygenerované" line carries — as (shown, for a file name). A value that
    isn't ISO is shown as it was stored."""
    from modules.contract_draft import to_local
    raw = (iso or "")[:16]
    ts = to_local(iso)
    if ts is None:
        return raw.replace("T", " "), raw.replace("-", "").replace(":", "").replace("T", "_")
    return ts.strftime("%Y-%m-%d %H:%M"), ts.strftime("%Y%m%d_%H%M")

def badge(cls, text):
    return f'<span class="badge b{cls[0].lower()}">{text}</span>'

def tier_badge(tier):
    m = {"PRIME":"bp","SOLID":"bs","STANDARD":"bw","POOR":"br"}
    return f'<span class="badge {m.get(tier,"bw")}">{tier}</span>'

# Compact summary of the signals parsed from the listing description
# (modules/description_enrichment): parking 🅿️, furnished 🛋️, balcony 🌿, plus a
# short condition label. "—" when nothing was parsed. All .get with defaults so
# it never raises on a row that predates enrichment.
_COND_LABELS = {"new": "New", "renovated": "Renov", "good": "Good",
                "original": "Orig", "poor": "Poor"}

def _features_label(l):
    icons = ""
    if l.get("has_parking"):                          icons += "🅿️"
    if (l.get("furnished") or "") in ("furnished", "semi"): icons += "🛋️"
    if l.get("has_balcony"):                          icons += "🌿"
    if l.get("has_elevator"):                         icons += "🛗"
    if l.get("has_cellar"):                           icons += "📦"
    cond = _COND_LABELS.get((l.get("condition") or "").lower(), "")
    return " ".join(p for p in (icons, _floor_label(l), cond) if p) or "—"


def _floor_label(l):
    """'3/8' (floor of building floors), '3' or '' when unknown."""
    fl = l.get("floor")
    if fl is None:
        return ""
    bf = l.get("building_floors")
    return f"{int(fl)}/{int(bf)}" if bf else f"{int(fl)}"


def _risk_label(v, yes, no="✅ Clear", T=None):
    """A risk flag from modules/risk_data: NULL means nobody could tell."""
    if v is None:
        return T("— unknown") if T else "— unknown"
    return yes if v else no


def market_badge(l) -> str:
    """The market a card or row belongs to."""
    return ('<span class="badge bp">🇨🇿 CZ</span>' if l.get("_market") == "cz"
            else '<span class="badge bs">🇸🇰 SK</span>')


def _rent_fallback(l):
    """"default" / "kraj" when the rent estimate is not the flat's own town's
    (engine.financial.rent_fallback_kind); None otherwise, and for a score
    from before the rent key was stored."""
    key = l.get("rent_key")
    if not key:
        return None
    from engine.financial import rent_fallback_kind
    return rent_fallback_kind(key, **mkw(l))


def _pct_or_dash(v, digits=1, signed=False):
    if v is None:
        return "—"
    return f"{v*100:+.{digits}f}%" if signed else f"{v*100:.{digits}f}%"


def _lv_state(l):
    """(label, badge css) for a listing's LV check. Only PASS — the flat's own
    LV read and clean — earns the tick."""
    status = (l.get("lv_status") or "PENDING").upper()
    if status in ("PASS", "CLEAN"):
        lv_no = l.get("lv_number")
        return (f"✅ LV CLEAN{f' · LV {lv_no}' if lv_no else ''}", "bg")
    if status == "REJECTED":
        return "❌ LV REJECTED", "br"
    if status == "UNVERIFIED":
        return "⚠ LV UNVERIFIED", "by"
    return "⏳ LV PENDING", "bw"


def _lv_link(l):
    """The official LV report when the flat's (or failing that, the plot's)
    LV and cadastral unit code are known; otherwise the cadastre portal. A
    Czech listing links to ČÚZK's nahlížení do katastru."""
    if l.get("_market") == "cz":
        from modules.lv_cz import lv_link
        return lv_link(l)
    ku = l.get("cadastral_unit_code")
    lv_no = l.get("lv_number") or l.get("plot_lv_number")
    if ku and lv_no:
        from kataster_scraper import GENERATE_PRF
        return GENERATE_PRF.format(lv_no=lv_no, ku_code=ku)
    return "https://kataster.skgeodesy.sk/EsriRegistrationWeb/"


# Czech labels for a Czech card (a Slovak card keeps its English ones).
CZ_LABELS = {
    "Price": "Cena", "Size": "Plocha", "Est. Rent": "Odhad nájmu",
    "Total Costs": "Náklady celkem", "Surplus/mo": "Přebytek/měs.",
    "Self-Fund": "Samofinancování", "Cap Rate": "Míra kapitalizace",
    "CoC Return": "Výnos vl. kapitálu", "IRR 10y": "IRR 10 let",
    "Max offer 🟡": "Max. nabídka 🟡", "Max offer 🟢": "Max. nabídka 🟢",
    "vs Market": "vs trh", "Below market": "Pod trhem", "Above market": "Nad trhem",
    "Days tracked": "Sledováno dní", "Location": "Lokalita",
    "s.r.o.": "s.r.o.", "Personal": "Fyzická osoba", "PERSONAL": "FYZICKÁ OSOBA",
    "COST BREAKDOWN": "ROZPAD NÁKLADŮ", "Mortgage": "Hypotéka",
    "HOA (incl. fond opráv)": "SVJ (fond oprav + správa)",
    "Property Tax": "Daň z nemovitosti", "Vacancy 5%": "Neobsazenost 5 %",
    "Owner reserve": "Rezerva vlastníka", "Management": "Správa nájmu",
    "Income Tax": "Daň z příjmů", "Health Levy": "Zdravotní pojištění",
    "s.r.o. running cost": "Provoz s.r.o.", "TOTAL COSTS": "NÁKLADY CELKEM",
    "NET SURPLUS": "ČISTÝ PŘEBYTEK", "FINANCING STRESS (s.r.o.)": "STRESOVÝ TEST (s.r.o.)",
    "Rate +2 pp": "Sazba +2 p. b.", "70% LTV (3rd+ flat)": "LTV 70 % (investiční)",
    "self-funding": "samofinancování", "cash in": "vlastní zdroje",
    "LOCATION IQ": "LOKALITA", "Transit": "MHD", "Amenities": "Vybavenost",
    "Walkability": "Pěší dostupnost", "Industrial": "Průmyslová zóna",
    "Construction": "Stavba v okolí", "Noise": "Hluk", "Flood (Q100)": "Povodeň (Q100)",
    "Geocode": "Geokódování", "Energy Class": "PENB", "Floor": "Podlaží",
    "Building": "Dům", "LV Status": "Stav LV",
    "Deal stage": "Fáze obchodu", "Stage note": "Poznámka k fázi",
    "SAVE STAGE": "ULOŽIT FÁZI", "VIEW LISTING": "INZERÁT", "MAPS": "MAPA",
    "CHECK LV": "NAHLÍŽENÍ DO KN", "RE-VERIFY LV": "OVĚŘIT LV",
    "Flat's own LV no.": "Číslo LV jednotky", "Katastrálne územie": "Katastrální území",
    "LV extract (text)": "Výpis z LV (text)",
    "✅ Clear": "✅ V pořádku", "— unknown": "— neznámo",
    "⚠️ Site nearby": "⚠️ Stavba v okolí", "⚠️ ≥65 dB source": "⚠️ Zdroj ≥65 dB",
    "⚠️ In flood area": "⚠️ V záplavovém území", "✅ YES": "✅ ANO",
    "🛗 elevator": "🛗 výtah", "📦 cellar": "📦 sklep", "🌿 terrace": "🌿 terasa",
    "🌿 loggia": "🌿 lodžie",
}


def _labels(l):
    """The card's label function: English for a Slovak card, Czech for a
    Czech one."""
    if l.get("_market") == "cz":
        return lambda s: CZ_LABELS.get(s, s)
    return lambda s: s


def amt(l, v, suffix: str = "") -> str:
    """An unsigned amount as a Slovak card always wrote it (€1,234/mo); a
    Czech card's in Kč (1 234 Kč/měs.)."""
    if (l.get("_cur") or "EUR") == "EUR":
        return f"€{v:,.0f}{suffix}"
    return money(l, v, suffix, signed=False)


def sgn(l, v, suffix: str = "/mo") -> str:
    """A signed amount: fe() on a Slovak card, Kč on a Czech one."""
    if (l.get("_cur") or "EUR") == "EUR":
        return fe(v, suffix=suffix)
    return money(l, v, suffix)


def _lv_state_t(l):
    """_lv_state, in Czech on a Czech card."""
    label, css = _lv_state(l)
    if l.get("_market") != "cz":
        return label, css
    for en, cz in (("LV CLEAN", "LV ČISTÝ"), ("LV REJECTED", "LV ZAMÍTNUT"),
                   ("LV UNVERIFIED", "LV NEOVĚŘEN"), ("LV PENDING", "LV ČEKÁ")):
        label = label.replace(en, cz)
    return label, css


def _quick_cadastre(l):
    """A short-patience cadastre context for the listing's market."""
    if l.get("_market") == "cz":
        from modules.lv_cz import quick_requests
    else:
        from kataster_scraper import quick_requests
    return quick_requests()

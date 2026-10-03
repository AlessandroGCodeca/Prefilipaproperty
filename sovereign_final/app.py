"""
app.py — Sovereign Investor Dashboard
Slovakia 2026 | Private Use Only
Run: streamlit run app.py
"""

import os, sys
from html import escape as _html_escape
import streamlit as st
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))


def esc(v) -> str:
    """HTML-escape text that came from a portal, an API or a typed note before
    it goes into st.markdown(..., unsafe_allow_html=True). Scraped titles, LV
    details and URLs are written by strangers; unescaped, a "<" garbles the
    page and an <img onerror=…> runs in the dashboard's origin."""
    return _html_escape("" if v is None else str(v), quote=True)


st.set_page_config(
    page_title="Sovereign RE",
    page_icon="🏛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;700&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: #07090e; color: #bcc8e0; }

section[data-testid="stSidebar"] {
    background: #0b0d14 !important;
    border-right: 1px solid #151924;
}

.wordmark {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1rem; font-weight: 700;
    color: #e4eaf5; letter-spacing: 4px; text-transform: uppercase;
}
.sub {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.55rem; color: #2a3450; letter-spacing: 3px;
    text-transform: uppercase; margin-top: 3px;
}

/* Stat grid */
.sg { display:grid; grid-template-columns:repeat(6,1fr); gap:6px; margin-bottom:18px; }
.sc {
    background:#0b0d14; border:1px solid #151924; border-radius:3px;
    padding:12px 14px; position:relative; overflow:hidden;
}
.sc::before { content:''; position:absolute; top:0;left:0;right:0; height:2px; }
.sc.g::before { background:#00e676; } .sc.y::before { background:#ffd740; }
.sc.w::before { background:#37474f; } .sc.r::before { background:#ff5252; }
.sc.b::before { background:#448aff; } .sc.a::before { background:#ff9100; }
.sn { font-family:'IBM Plex Mono',monospace; font-size:1.9rem; font-weight:700; color:#e4eaf5; line-height:1; }
.sc.g .sn { color:#00e676; } .sc.y .sn { color:#ffd740; }
.sc.r .sn { color:#ff5252; } .sc.b .sn { color:#448aff; }
.sl { font-size:0.6rem; text-transform:uppercase; letter-spacing:1.5px; color:#2a3450; margin-top:5px; }

/* Badges */
.badge { display:inline-block; padding:2px 8px; border-radius:2px;
         font-family:'IBM Plex Mono',monospace; font-size:0.62rem; font-weight:700;
         letter-spacing:1px; text-transform:uppercase; }
.bg { background:rgba(0,230,118,.12); color:#00e676; }
.by { background:rgba(255,215,64,.12); color:#ffd740; }
.bw { background:rgba(55,71,79,.15);  color:#607d8b; }
.br { background:rgba(255,82,82,.12); color:#ff5252; }
.bp { background:rgba(68,138,255,.12);color:#448aff; }
.bs { background:rgba(68,138,255,.08);color:#5c8fd6; }
.bo { background:rgba(255,145,0,.12); color:#ff9100; }

/* Breakdown rows */
.brow { display:flex; justify-content:space-between; padding:5px 0;
        border-bottom:1px solid #0e1018;
        font-family:'IBM Plex Mono',monospace; font-size:0.76rem; }
.brow .l { color:#2a3450; } .brow .v { color:#bcc8e0; }
.brow.tot { border-top:1px solid #151924; border-bottom:none; }
.brow.tot .l { color:#6b7a96; } .brow.tot .v { color:#e4eaf5; font-weight:700; }
.brow.pos .v { color:#00e676; } .brow.neg .v { color:#ff5252; }

/* Divider */
.div { border:none; border-top:1px solid #151924; margin:14px 0; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background:transparent; border-bottom:1px solid #151924; gap:0; }
.stTabs [data-baseweb="tab"] {
    background:transparent; border:none; border-bottom:2px solid transparent;
    color:#2a3450; font-family:'IBM Plex Mono',monospace; font-size:0.7rem;
    letter-spacing:1px; text-transform:uppercase; padding:8px 20px; border-radius:0;
}
.stTabs [aria-selected="true"] { background:transparent !important; color:#00e676 !important; border-bottom:2px solid #00e676 !important; }

/* Buttons */
.stButton>button {
    background:#0b0d14; color:#6b7a96; border:1px solid #151924;
    border-radius:3px; font-family:'IBM Plex Mono',monospace;
    font-size:0.68rem; letter-spacing:1px; text-transform:uppercase;
    transition:all .15s;
}
.stButton>button:hover { border-color:#00e676; color:#00e676; background:rgba(0,230,118,.04); }

div[data-testid="stExpander"] { background:#0b0d14; border:1px solid #151924 !important; border-radius:3px; }

.muted { color:#2a3450; font-size:0.7rem; font-family:'IBM Plex Mono',monospace; }
.mono  { font-family:'IBM Plex Mono',monospace; }
</style>
""", unsafe_allow_html=True)

# ── Init ──────────────────────────────────────────────────────────────────────
from database import init_db, get_all_active, get_stats, backfill_dev_project_flags
init_db()

@st.cache_resource
def _startup_backfill():
    # Flag existing rows by URL/title pattern. cache_resource runs this once per
    # session instead of on every Streamlit rerun (every widget interaction).
    return backfill_dev_project_flags()
_startup_backfill()

# ── Demo data (when DB is empty) ──────────────────────────────────────────────
DEMO = [
    {"id":"d1","url":"https://nehnutelnosti.sk/demo1",
     "title":"3-izbový byt, Dúbravka","price_eur":168000,"size_m2":72,
     "district":"Bratislava IV","energy_class":"A","source":"nehnutelnosti",
     "cf_class":"GREEN","surplus_personal":198,"surplus_sro":412,
     "ratio_personal":1.12,"ratio_sro":1.24,"cash_on_cash":0.089,
     "net_rental_yield":0.048,"gross_yield":0.066,"optimal_structure":"SRO",
     "market_discount":0.40,
     "estimated_rent_eur":920,"total_costs_personal":825,"total_costs_sro":742,
     "annual_sro_saving":2568,"sro_break_even_months":12,
     "mortgage_monthly":598,"hoa_monthly":60,"property_tax_monthly":46,
     "vacancy_cost":46,"maintenance_monthly":140,
     "income_tax_personal":95,"health_levy_personal":82,
     "income_tax_sro":112,"health_levy_sro":0,
     "location_score":83,"location_tier":"PRIME","nearest_transit_m":340,
     "walkability_score":78,"industrial_zone":0,"construction_risk":0,"noise_flag":0,
     "amenity_count":5,"lv_status":"UNVERIFIED","lat":48.178,"lng":17.062,
     "primary_image_url":""},
    {"id":"d2","url":"https://nehnutelnosti.sk/demo2",
     "title":"2-izbový byt, Žilina centrum","price_eur":98000,"size_m2":58,
     "district":"Žilina","energy_class":"B","source":"nehnutelnosti",
     "cf_class":"GREEN","surplus_personal":145,"surplus_sro":318,
     "ratio_personal":1.06,"ratio_sro":1.19,"cash_on_cash":0.074,
     "net_rental_yield":0.039,"gross_yield":0.078,"optimal_structure":"SRO",
     "market_discount":0.37,
     "estimated_rent_eur":640,"total_costs_personal":603,"total_costs_sro":537,
     "annual_sro_saving":2076,"sro_break_even_months":15,
     "mortgage_monthly":401,"hoa_monthly":60,"property_tax_monthly":27,
     "vacancy_cost":32,"maintenance_monthly":82,
     "income_tax_personal":65,"health_levy_personal":54,
     "income_tax_sro":78,"health_levy_sro":0,
     "location_score":72,"location_tier":"SOLID","nearest_transit_m":490,
     "walkability_score":66,"industrial_zone":1,"construction_risk":0,"noise_flag":0,
     "amenity_count":4,"lv_status":"UNVERIFIED","lat":49.223,"lng":18.739,
     "primary_image_url":""},
    {"id":"d3","url":"https://nehnutelnosti.sk/demo3",
     "title":"1-izbový byt, Nitra Klokočina","price_eur":82000,"size_m2":38,
     "district":"Nitra","energy_class":"C","source":"bazos",
     "cf_class":"YELLOW","surplus_personal":-42,"surplus_sro":87,
     "ratio_personal":0.94,"ratio_sro":1.09,"cash_on_cash":0.051,
     "net_rental_yield":0.031,"gross_yield":0.066,"optimal_structure":"SRO",
     "market_discount":0.13,
     "estimated_rent_eur":450,"total_costs_personal":479,"total_costs_sro":413,
     "annual_sro_saving":1548,"sro_break_even_months":20,
     "mortgage_monthly":336,"hoa_monthly":35,"property_tax_monthly":23,
     "vacancy_cost":23,"maintenance_monthly":68,
     "income_tax_personal":38,"health_levy_personal":33,
     "income_tax_sro":42,"health_levy_sro":0,
     "location_score":62,"location_tier":"SOLID","nearest_transit_m":680,
     "walkability_score":55,"industrial_zone":1,"construction_risk":0,"noise_flag":0,
     "amenity_count":3,"lv_status":"UNVERIFIED","lat":48.307,"lng":18.085,
     "primary_image_url":""},
]


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="wordmark">SOVEREIGN</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub">Investor Dashboard · Slovakia 2026</div>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("#### PIPELINE")
    c1, c2, c3 = st.columns(3)
    with c1: do_nehnut = st.button("NEHNUT",  use_container_width=True)
    with c2: do_bazos  = st.button("BAZOS",   use_container_width=True)
    with c3: do_topreal= st.button("TOPREAL", use_container_width=True)
    do_lv    = st.button("🔒 LV DEBT FILTER", use_container_width=True)
    do_cf    = st.button("💰 CASHFLOW SCORE", use_container_width=True)
    do_desc  = st.button("📝 PARSE DESC", use_container_width=True,
                         help="Run Claude on un-parsed listing descriptions to "
                              "extract parking / furnished / condition. Needs "
                              "ANTHROPIC_API_KEY. Re-score afterwards to apply the "
                              "parking & furnished rent premiums.")
    do_addr  = st.button("🗺️ NORM ADDR", use_container_width=True,
                         help="Run Claude on listings with a blank district to "
                              "resolve city/district from the raw address, so rent "
                              "stops defaulting to €6.50/m². Needs ANTHROPIC_API_KEY. "
                              "Re-score afterwards to apply.")
    do_rescore = st.button("♻️ RESCORE ALL",  use_container_width=True,
                           help="Clear all cashflow scores and re-run scoring from "
                                "scratch. Use after updating rent/tax assumptions.")
    do_reparse = st.button("📝 RE-PARSE (new fields)", use_container_width=True,
                           help="Re-run description parsing on listings parsed before "
                                "floor / elevator / cellar / terrace were kept. Needs "
                                "ANTHROPIC_API_KEY.")
    do_loc   = st.button("📍 LOCATION IQ",    use_container_width=True,
                         help="Geocode + transit/amenities + real noise/flood/"
                              "construction flags. Google when GOOGLE_PLACES_API_KEY "
                              "is set, OpenStreetMap otherwise.")
    do_risk  = st.button("🌊 RISK BACKFILL", use_container_width=True,
                         help="Give listings located before the real risk data "
                              "existed their noise / flood / construction answers.")
    do_rent  = st.button("🏘️ RENT COMPS", use_container_width=True,
                         help="Scrape prenájom listings, rebuild live €/m² rents per "
                              "district and queue affected listings for re-scoring.")
    do_dupes = st.button("📡 MERGE PORTAL COPIES", use_container_width=True,
                         help="Group the same flat listed on several portals.")
    do_stale = st.button("🧹 CLEAN STALE (21d)", use_container_width=True)
    do_test  = st.button("🔗 TEST SITES",      use_container_width=True)

    st.markdown("---")
    st.markdown("#### FILTERS")
    max_price  = st.slider("Max Price €",  30_000, 600_000, 300_000, 5_000)
    min_size   = st.slider("Min Size m²",  20, 150, 25, 5)
    classes    = st.multiselect(
        "Classification",
        ["GREEN", "YELLOW", "WHITE", "PENDING", "REJECTED"],
        default=["GREEN", "YELLOW", "WHITE", "PENDING"],
    )
    sources    = st.multiselect(
        "Source",
        ["nehnutelnosti", "bazos", "topreality"],
        default=["nehnutelnosti", "bazos", "topreality"],
    )
    district_q = st.text_input(
        "District contains",
        placeholder="e.g. Bratislava, Petržalka, Košice",
        help="Case-insensitive substring match. Leave blank to show all.",
    )
    cond_filter = st.multiselect(
        "Condition",
        ["new", "renovated", "good", "original", "poor"],
        default=[],
        help="Renovation state parsed from the description. "
             "Empty = show all (including unparsed/unknown).",
    )
    req_parking = st.toggle(
        "🅿️ Parking only", value=False,
        help="Show only listings with a garage or parking spot "
             "(parsed from the description).",
    )
    req_furnished = st.toggle(
        "🛋️ Furnished only", value=False,
        help="Show only fully or semi-furnished listings.",
    )
    req_elevator = st.toggle(
        "🛗 Elevator only", value=False,
        help="Show only listings whose description mentions an elevator.",
    )
    drops_only = st.toggle(
        "🔻 Price cuts only", value=False,
        help="Show only listings whose asking price has been cut.",
    )
    hide_dev   = st.toggle(
        "Hide dev projects",
        value=True,
        help='Dev-project listings (novostavba/developersky-projekt/etc.) quote "od €X" '
             'starting prices for the cheapest unit and distort cashflow scoring.',
    )
    hide_dups  = st.toggle(
        "Hide portal copies", value=True,
        help="Show the same flat once even when it is listed on several portals "
             "(the cheapest copy is kept; the others are linked from its card).",
    )
    show_sro   = st.toggle("Show s.r.o. figures", value=True)
    show_demo  = st.toggle("Demo data (no DB)",   value=False)

    from engine.financial import default_ltv as _default_ltv
    from config import PROPERTIES_OWNED as _OWNED
    st.markdown(
        f'<div class="muted">Scoring LTV {_default_ltv()*100:.0f}% · '
        f'PROPERTIES_OWNED={_OWNED}'
        f'{" (3rd+ property → 70% cap)" if _default_ltv() < 0.8 else ""}</div>',
        unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="muted">Private use. Verify all data.<br>Notárska úschova always.</div>', unsafe_allow_html=True)


# ── Pipeline actions ──────────────────────────────────────────────────────────
def run_step(label, fn, *args, **kwargs):
    with st.spinner(f"{label}..."):
        try:
            result = fn(*args, **kwargs)
            st.success(f"✅ Done: {result}")
            st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")

def _run_scraper_subprocess(script_name: str) -> tuple[int, str]:
    """Run a scraper as a fresh subprocess — bypasses Python module cache."""
    import subprocess, json as _json
    _dir = os.path.dirname(__file__)
    wrapper = f"""
import sys, os, json
sys.path.insert(0, {repr(_dir)})
try:
    import importlib
    mod = importlib.import_module('scraper.{script_name}')
    n = mod.run(max_pages=10)
    print(json.dumps({{"ok": True, "n": n}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", wrapper],
        capture_output=True, text=True, timeout=300
    )
    for line in (proc.stdout + proc.stderr).strip().splitlines():
        try:
            data = _json.loads(line)
            if data.get("ok"):
                return data["n"], ""
            else:
                return 0, data.get("error", "Unknown error")
        except Exception:
            continue
    stderr = proc.stderr.strip()
    return 0, stderr or "Scraper produced no output"


if do_nehnut:
    with st.spinner("Scraping Nehnutelnosti..."):
        n, err = _run_scraper_subprocess("nehnutelnosti")
        if err:
            st.error(f"❌ Nehnutelnosti: {err}")
        else:
            from modules.address_enrichment import run_address_enrichment
            run_address_enrichment()
            from modules.description_enrichment import run_description_enrichment
            run_description_enrichment()
            from modules.cashflow_runner import run_scoring as _run_cf
            scored = _run_cf()
            from database import mark_duplicates
            mark_duplicates()
            st.success(f"✅ Scraped {n} listings, scored {scored}.")
            st.rerun()

if do_bazos:
    with st.spinner("Scraping Bazos..."):
        n, err = _run_scraper_subprocess("bazos")
        if err:
            st.error(f"❌ Bazos: {err}")
        else:
            from modules.address_enrichment import run_address_enrichment
            run_address_enrichment()
            from modules.description_enrichment import run_description_enrichment
            run_description_enrichment()
            from modules.cashflow_runner import run_scoring as _run_cf
            scored = _run_cf()
            from database import mark_duplicates
            mark_duplicates()
            st.success(f"✅ Scraped {n} listings, scored {scored}.")
            st.rerun()

if do_topreal:
    with st.spinner("Scraping Topreality..."):
        n, err = _run_scraper_subprocess("topreality")
        if err:
            st.error(f"❌ Topreality: {err}")
        else:
            from modules.address_enrichment import run_address_enrichment
            run_address_enrichment()
            from modules.description_enrichment import run_description_enrichment
            run_description_enrichment()
            from modules.cashflow_runner import run_scoring as _run_cf
            scored = _run_cf()
            from database import mark_duplicates
            mark_duplicates()
            st.success(f"✅ Scraped {n} listings, scored {scored}.")
            st.rerun()

if do_lv:
    bar = st.progress(0)
    txt = st.empty()
    def lv_cb(i, n, a=""): bar.progress(i/n); txt.text(f"LV {i}/{n}: {a}")
    from modules.debt_bot import run_debt_filter
    p, r, u = run_debt_filter(progress_callback=lv_cb)
    bar.empty(); txt.empty()
    st.success(f"✅ LV done — Clean: {p}, Rejected: {r}, ⚠ Unverified: {u}")
    st.rerun()

if do_cf:
    bar = st.progress(0)
    def cf_cb(i, n): bar.progress(i/n)
    from modules.cashflow_runner import run_scoring
    n = run_scoring(progress_callback=cf_cb)
    bar.empty(); st.success(f"✅ Scored {n} listings"); st.rerun()

if do_desc:
    bar = st.progress(0)
    def desc_cb(i, n): bar.progress(i / n)
    from modules.description_enrichment import run_description_enrichment
    n = run_description_enrichment(progress_callback=desc_cb)
    bar.empty()
    if n:
        st.success(f"✅ Parsed {n} descriptions. Re-score to apply rent premiums.")
    else:
        st.info("ℹ️ Nothing parsed — set ANTHROPIC_API_KEY, or no new descriptions "
                "to parse.")
    st.rerun()

if do_addr:
    bar = st.progress(0)
    def addr_cb(i, n): bar.progress(i / n)
    from modules.address_enrichment import run_address_enrichment
    n = run_address_enrichment(progress_callback=addr_cb)
    bar.empty()
    if n:
        st.success(f"✅ Resolved {n} blank districts. Re-score to apply rent rates.")
    else:
        st.info("ℹ️ Nothing normalized — set ANTHROPIC_API_KEY, or no blank "
                "districts with an address to resolve.")
    st.rerun()

if do_rescore:
    from database import clear_cashflow_scores
    from modules.cashflow_runner import run_scoring
    cleared = clear_cashflow_scores()
    bar = st.progress(0)
    def rescore_cb(i, n): bar.progress(i/n)
    n = run_scoring(progress_callback=rescore_cb)
    bar.empty()
    st.success(f"✅ Cleared {cleared} old scores, re-scored {n} listings")
    st.rerun()

if do_loc:
    bar = st.progress(0); txt = st.empty()
    def loc_cb(i, n, a=""): bar.progress(i/n); txt.text(f"Location {i}/{n}: {a}")
    from modules.location_iq import run_location_scoring
    n = run_location_scoring(progress_callback=loc_cb)
    bar.empty(); txt.empty(); st.success(f"✅ Location scored {n}"); st.rerun()

if do_reparse:
    from database import requeue_descriptions_missing_extras
    from modules.description_enrichment import run_description_enrichment
    q = requeue_descriptions_missing_extras()
    bar = st.progress(0)
    n = run_description_enrichment(progress_callback=lambda i, t: bar.progress(i / t))
    bar.empty()
    st.success(f"✅ Re-queued {q}, parsed {n} descriptions.")
    st.rerun()

if do_risk:
    bar = st.progress(0); txt = st.empty()
    def risk_cb(i, n, a=""): bar.progress(i/n); txt.text(f"Risk {i}/{n}: {a}")
    from modules.location_iq import run_risk_backfill
    n = run_risk_backfill(progress_callback=risk_cb)
    bar.empty(); txt.empty(); st.success(f"✅ Risk data added to {n} listings"); st.rerun()

if do_rent:
    with st.spinner("Scraping prenájom listings and rebuilding rent comps..."):
        from scraper.rentals import run as _run_rentals
        from modules.cashflow_runner import run_scoring as _run_cf
        summary = _run_rentals(max_pages=5)
        scored = _run_cf()
    st.success(f"✅ {summary.get('rentals', 0)} rentals across {summary.get('keys', 0)} "
               f"districts · {len(summary.get('changed', []))} rates moved · "
               f"re-scored {scored}.")
    st.rerun()

if do_dupes:
    from database import mark_duplicates
    n = mark_duplicates()
    st.success(f"✅ {n} listings are copies of a flat listed more than once.")
    st.rerun()

if do_stale:
    from database import deactivate_stale_listings
    n = deactivate_stale_listings(days=21)
    if n:
        st.success(f"✅ Deactivated {n} stale listings (last seen > 21 days ago)")
    else:
        st.info("ℹ️ No stale listings — all active rows seen within the last 21 days")
    st.rerun()

if do_test:
    from scraper._http import get as _http_get, SCRAPER_API_KEY as _sak
    _proxy_mode = bool(_sak)
    st.info(f"Proxy mode: {'✅ ScraperAPI' if _proxy_mode else '⚠️ Direct (no SCRAPER_API_KEY set)'}")
    for label, url in [
        ("nehnutelnosti.sk", "https://www.nehnutelnosti.sk/slovensko/byty/predaj/?p[page]=1"),
        ("bazos.sk",          "https://reality.bazos.sk/predaj/byt/"),
        ("topreality.sk",     "https://www.topreality.sk/vyhladavanie/byty/predaj?page=1"),
    ]:
        try:
            _r = _http_get(url, timeout=12)
            snippet = _r.text[:80].strip().replace("\n", " ")
            icon = "✅" if _r.status_code == 200 else "❌"
            st.info(f"{icon} **{label}** → HTTP {_r.status_code} | `{snippet}`")
        except Exception as _e:
            st.error(f"❌ **{label}** → {_e}")


# ── Data ──────────────────────────────────────────────────────────────────────
from database import (
    get_price_history, get_price_drops, get_deal_stages, latest_vibes,
    days_on_market, DEAL_STAGES,
)

stats    = get_stats()
raw_data = get_all_active()

using_demo = show_demo or not raw_data
if using_demo:
    data = DEMO
    if not raw_data:
        st.info("ℹ️ No data in DB yet — showing demo listings. Run the pipeline to populate.")
else:
    data = raw_data

# Per-listing context that lives outside the main query: price history, deal
# stage, latest vibe note, the other portals' copies of the same flat.
price_hist = get_price_history()
stages     = get_deal_stages()
vibes      = latest_vibes()
dup_members: dict = {}
for l in data:
    if l.get("dup_group"):
        dup_members.setdefault(l["dup_group"], []).append(l)
for l in data:
    l["_ph"]      = price_hist.get(l.get("id"))
    l["_stage"]   = stages.get(l.get("id"))
    l["_vibe"]    = vibes.get(l.get("id"))
    l["_copies"]  = dup_members.get(l.get("dup_group"), []) if l.get("dup_group") else []
    l["_portals"] = len({c.get("source") for c in l["_copies"]}) or 1
    # A flat is as old as its oldest copy on any portal.
    seen = [c.get("scraped_at") for c in l["_copies"] + [l] if c.get("scraped_at")]
    l["_dom"]     = days_on_market(min(seen)) if seen else None

# Apply filters
district_needle = (district_q or "").strip().lower()
data = [l for l in data
        if (l.get("price_eur") or 0) <= max_price
        and (l.get("size_m2")  or 0) >= min_size
        and (not classes or (l.get("classification") or "PENDING") in classes)
        and (not sources or (l.get("source") or "") in sources)
        and (not district_needle or district_needle in (l.get("district") or "").lower())
        and (not cond_filter or (l.get("condition") or "").lower() in cond_filter)
        and (not req_parking or (l.get("has_parking") or 0))
        and (not req_furnished or (l.get("furnished") or "") in ("furnished", "semi"))
        and (not req_elevator or (l.get("has_elevator") or 0))
        and (not drops_only or ((l["_ph"] or {}).get("change_pct") or 0) < 0)
        and (not hide_dev or not (l.get("is_dev_project") or 0))
        and (not hide_dups or not l.get("dup_group") or l["dup_group"] == l.get("id"))]


# ── Stats bar ─────────────────────────────────────────────────────────────────
# The counts describe the listings below. `x or demo_count` used to fill in a
# real zero (no YELLOW deals yet) with the demo rows' count; the demo counts
# belong only to the demo rows.
if using_demo:
    shown = {
        "total":    len(DEMO),
        "green":    sum(1 for d in DEMO if d["cf_class"] == "GREEN"),
        "yellow":   sum(1 for d in DEMO if d["cf_class"] == "YELLOW"),
        "white":    sum(1 for d in DEMO if d["cf_class"] == "WHITE"),
        "rejected": 0, "pending": 0,
    }
else:
    shown = stats
st.markdown(f"""
<div class="sg">
  <div class="sc b"><div class="sn">{shown['total']}</div><div class="sl">Total</div></div>
  <div class="sc g"><div class="sn">{shown['green']}</div><div class="sl">Green</div></div>
  <div class="sc y"><div class="sn">{shown['yellow']}</div><div class="sl">Yellow</div></div>
  <div class="sc w"><div class="sn">{shown['white']}</div><div class="sl">White</div></div>
  <div class="sc r"><div class="sn">{shown['rejected']}</div><div class="sl">Rejected</div></div>
  <div class="sc a"><div class="sn">{shown['pending']}</div><div class="sl">Pending</div></div>
</div>
""", unsafe_allow_html=True)


# ── Price-cut alerts ──────────────────────────────────────────────────────────
_drops = get_price_drops(days=14)
if _drops:
    with st.expander(f"🔻 {len(_drops)} price cut(s) in the last 14 days", expanded=False):
        for d in _drops:
            my = d.get("max_price_yellow")
            reach = ""
            if my:
                reach = (" · now within YELLOW" if d["price_eur"] <= my
                         else f" · {d['price_eur'] / my - 1:+.1%} above max YELLOW €{my:,.0f}")
            st.markdown(
                f'<div class="brow"><span class="l">{esc((d.get("title") or d.get("district") or "—")[:60])}</span>'
                f'<span class="v">€{d["price_eur"]:,.0f} ({d["last_change_pct"]:+.1%}, '
                f'{str(d["last_change_at"])[:10]}){reach} · '
                f'<a href="{esc(d["url"])}" target="_blank">open ↗</a></span></div>',
                unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def fe(v, prefix="€", suffix="", decimals=0):
    if v is None: return "—"
    sign = "+" if (suffix == "/mo" and v >= 0) else ""
    return f"{prefix}{sign}{v:,.{decimals}f}{suffix}"

def fp(v):
    return f"{(v or 0)*100:.1f}%" if v is not None else "—"

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


def _risk_label(v, yes, no="✅ Clear"):
    """A risk flag from modules/risk_data: NULL means nobody could tell."""
    if v is None:
        return "— unknown"
    return yes if v else no


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
    LV and cadastral unit code are known; otherwise the cadastre portal."""
    ku = l.get("cadastral_unit_code")
    lv_no = l.get("lv_number") or l.get("plot_lv_number")
    if ku and lv_no:
        from kataster_scraper import GENERATE_PRF
        return GENERATE_PRF.format(lv_no=lv_no, ku_code=ku)
    return "https://kataster.skgeodesy.sk/EsriRegistrationWeb/"


def render_card(l):
    cls      = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
    css_cls  = {"GREEN":"g","YELLOW":"y","WHITE":"w","PENDING":"w"}.get(cls,"w")
    emoji    = {"GREEN":"🟢","YELLOW":"🟡","WHITE":"⚪"}.get(cls,"")

    surplus  = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
    ratio    = l.get("ratio_sro")   if show_sro else l.get("ratio_personal")
    total_c  = l.get("total_costs_sro") if show_sro else l.get("total_costs_personal")
    struct   = "s.r.o." if show_sro else "Personal"
    rent     = l.get("estimated_rent_eur", 0) or 0
    price    = l.get("price_eur", 0) or 0
    size     = l.get("size_m2", 0) or 0
    district = l.get("district","—")
    title    = l.get("title") or district
    loc_tier = l.get("location_tier","—")
    transit  = l.get("nearest_transit_m")
    ind      = l.get("industrial_zone", 0)
    opt      = l.get("optimal_structure","—")
    saving   = l.get("annual_sro_saving", 0) or 0
    bev      = l.get("sro_break_even_months")
    ph       = l.get("_ph")
    stage    = l.get("_stage")

    disc     = l.get("market_discount")
    below    = (f"{abs(disc)*100:.0f}% {'below' if disc >= 0 else 'above'} market"
                if disc is not None else "no benchmark")
    cut = f"   ·   🔻{ph['change_pct']:+.0%}" if ph and (ph.get("change_pct") or 0) < 0 else ""
    stage_tag = f"   ·   [{stage['stage']}]" if stage else ""
    header = (f"{emoji}  {title[:60]}   ·   €{price:,.0f}   ·   {below}   ·   "
              f"{fe(surplus,'€','',0)}/mo{cut}{stage_tag}")

    with st.expander(header):
        # Row 1: key metrics
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1:
            st.metric("Price",    f"€{price:,.0f}")
            st.metric("Size",     f"{size:.0f} m²")
        with c2:
            st.metric("Est. Rent",  f"€{rent:,.0f}/mo",
                      help="Live prenájom comps" if l.get("rent_source") == "live"
                      else "Published baseline €/m² (config.RENT_PER_M2)")
            st.metric("Total Costs",f"€{total_c:,.0f}/mo" if total_c else "—")
        with c3:
            surplus_str = f"€{surplus:+,.0f}/mo" if surplus is not None else "—"
            st.metric("Surplus/mo",   surplus_str)
            st.metric("Self-Fund",    fp(ratio))
        with c4:
            st.metric("Cap Rate",   fp(l.get("cap_rate")))
            st.metric("CoC Return", fp(l.get("cash_on_cash")))
            st.metric("IRR 10y",    _pct_or_dash(l.get("irr_sro") if show_sro else l.get("irr_personal")),
                      help="Hold-period IRR with appreciation, exit costs and tax on the "
                           "gain — see the WHAT-IF tab.")
        with c5:
            my, mg = l.get("max_price_yellow"), l.get("max_price_green")
            st.metric("Max offer 🟡", f"€{my:,.0f}" if my else "—",
                      delta=(f"{my / price - 1:+.1%} vs ask" if my and price else None),
                      help="Highest price at which this is still YELLOW "
                           "(≥10% below the regional median €/m²).")
            st.metric("Max offer 🟢", f"€{mg:,.0f}" if mg else "—",
                      help="Highest price at which this is GREEN "
                           "(≥20% below the regional median €/m²).")
        with c6:
            median_m2 = l.get("regional_median_m2")
            st.metric("vs Market", below,
                      help=(f"Asking €/m² vs the regional median €{median_m2:,.0f}/m² "
                            f"(≈ €{median_m2 * size:,.0f} for {size:.0f} m²)")
                      if median_m2 and size else "No regional median for this district.")
            st.metric("Days listed", "—" if l.get("_dom") is None else f"{l['_dom']}",
                      help="Days since first seen on any portal.")
            st.metric("Location",   f"{l.get('location_score','—')}/100")

        # Composite deal grade (financial + location + energy + risk)
        from engine.financial import compute_deal_score
        deal_score, deal_grade = compute_deal_score(l)
        grade_css = {"A": "bg", "B": "bs", "C": "by", "D": "bw"}.get(deal_grade, "bw")

        # Badges
        lv_risk = (l.get("lv_risk_level") or "").upper()
        lv_css  = {"LOW": "bg", "MEDIUM": "by", "HIGH": "br"}.get(lv_risk, "bw")
        lv_label, lv_badge_css = _lv_state(l)
        badges = (
            badge(css_cls, cls) + " " +
            (f'<span class="badge {grade_css}">GRADE {deal_grade} · {deal_score}</span> '
             if deal_grade != "—" else "") +
            f'<span class="badge bo">{"s.r.o." if opt=="SRO" else "PERSONAL"}</span>' + " " +
            tier_badge(loc_tier) +
            (' <span class="badge bg">⚙️ INDUSTRIAL</span>' if ind else "") +
            f' <span class="badge {lv_badge_css}">{lv_label}</span>' +
            (f' <span class="badge {lv_css}">⚖️ LV {lv_risk}</span>' if lv_risk else "") +
            (f' <span class="badge bp">📡 {l["_portals"]} PORTALS</span>' if l.get("_portals", 1) > 1 else "") +
            (' <span class="badge br">🌊 FLOOD Q100</span>' if l.get("flood_zone") else "") +
            (f' <span class="badge bs">{stage["stage"]}</span>' if stage else "")
        )
        st.markdown(badges, unsafe_allow_html=True)
        for lv_note in (l.get("lv_detail"), l.get("lv_summary")):
            if lv_note:
                st.markdown(
                    f'<div class="muted" style="margin-top:6px">⚖️ LV: {esc(lv_note)}</div>',
                    unsafe_allow_html=True,
                )
        if ph:
            steps = " → ".join(f"€{p:,.0f} ({str(w)[:10]})" for w, p in ph["history"])
            st.markdown(f'<div class="muted" style="margin-top:6px">📉 Price: {steps} '
                        f'[{ph["change_pct"]:+.1%}]</div>', unsafe_allow_html=True)
        if len(l.get("_copies") or []) > 1:
            links = " · ".join(
                f'<a href="{esc(c.get("url"))}" target="_blank">{esc((c.get("source") or "").upper())} '
                f'€{(c.get("price_eur") or 0):,.0f}</a>'
                for c in sorted(l["_copies"], key=lambda c: c.get("price_eur") or 0))
            st.markdown(f'<div class="muted" style="margin-top:6px">📡 Same flat on: {links}</div>',
                        unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Cost breakdown + Location IQ side by side
        bc1, bc2 = st.columns(2)

        with bc1:
            st.markdown(f'<div class="muted">COST BREAKDOWN — {struct}</div>', unsafe_allow_html=True)
            rows = [
                ("Mortgage",        l.get("mortgage_monthly")),
                ("HOA (incl. fond opráv)", l.get("hoa_monthly")),
                ("Property Tax",    l.get("property_tax_monthly")),
                ("Vacancy 5%",      l.get("vacancy_cost")),
                ("Owner reserve",   l.get("maintenance_monthly")),
                ("Management",      l.get("management_monthly")),
                ("Income Tax",      l.get("income_tax_sro") if show_sro else l.get("income_tax_personal")),
                ("Health Levy",     l.get("health_levy_sro") if show_sro else l.get("health_levy_personal")),
            ]
            html = ""
            for lbl, val in rows:
                html += f'<div class="brow"><span class="l">{lbl}</span><span class="v">€{val:,.0f}/mo</span></div>' if val is not None else ""
            html += f'<div class="brow tot"><span class="l">TOTAL COSTS</span><span class="v">€{total_c:,.0f}/mo</span></div>' if total_c else ""
            surplus_cls = "pos" if (surplus or 0) >= 0 else "neg"
            html += f'<div class="brow tot {surplus_cls}"><span class="l">NET SURPLUS</span><span class="v">€{surplus:+,.0f}/mo</span></div>' if surplus is not None else ""
            st.markdown(html, unsafe_allow_html=True)

            if saving and saving > 0:
                st.markdown(f'<div class="muted" style="margin-top:8px">s.r.o. saves €{saving:,.0f}/yr vs personal{f" · break-even {bev}mo" if bev else ""}</div>', unsafe_allow_html=True)

            # Financing stress: +2 pp rate, and the 70% investor LTV cap.
            if price and size and rent:
                from engine.financial import analyse as _an
                from config import LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA, LOAN_TERM_YEARS
                inv = _an(price, size, district or "", rent_override=rent,
                          ltv=LTV_RATIO_INVESTOR,
                          rate=l.get("mortgage_rate_used") or MORTGAGE_RATE_PA,
                          term_years=int(l.get("loan_term_years") or LOAN_TERM_YEARS))
                sts = l.get("stress_surplus_sro")
                html = '<div class="muted" style="margin-top:10px">FINANCING STRESS (s.r.o.)</div>'
                if sts is not None:
                    html += (f'<div class="brow {"pos" if sts >= 0 else "neg"}"><span class="l">Rate +2 pp</span>'
                             f'<span class="v">€{sts:+,.0f}/mo · self-funding '
                             f'{fp(l.get("stress_ratio_sro"))}</span></div>')
                html += (f'<div class="brow {"pos" if inv.surplus_sro >= 0 else "neg"}"><span class="l">70% LTV (3rd+ flat)</span>'
                         f'<span class="v">€{inv.surplus_sro:+,.0f}/mo · self-funding {fp(inv.ratio_sro)} · '
                         f'cash in €{inv.total_cash_invested:,.0f}</span></div>')
                st.markdown(html, unsafe_allow_html=True)

        with bc2:
            st.markdown('<div class="muted">LOCATION IQ</div>', unsafe_allow_html=True)
            precision = l.get("geo_precision")
            loc_rows = [
                ("Transit",        f"{transit:.0f}m {'✅' if (transit or 9999) <= 560 else '⚠️'}" if transit else "—"),
                ("Amenities",      f"{l.get('amenity_count','—')} {'✅' if (l.get('amenity_count') or 0) >= 3 else '⚠️'}"),
                ("Walkability",    f"{l.get('walkability_score','—')}/100"),
                ("Industrial",     "✅ YES" if ind else "—"),
                ("Construction",   _risk_label(l.get("construction_risk"), "⚠️ Site nearby")),
                ("Noise",          _risk_label(l.get("noise_flag"), "⚠️ ≥65 dB source")),
                ("Flood (Q100)",   _risk_label(l.get("flood_zone"), "⚠️ In flood area")),
                ("Geocode",        precision or "—"),
                ("Energy Class",   l.get("energy_class","?")),
                ("Floor",          _floor_label(l) or "—"),
                ("Building",       " ".join(x for x, c in (("🛗 elevator", "has_elevator"),
                                                           ("📦 cellar", "has_cellar"),
                                                           ("🌿 terrace", "has_terrace"),
                                                           ("🌿 loggia", "has_loggia"))
                                            if l.get(c)) or "—"),
                ("LV Status",      _lv_state(l)[0]),
            ]
            html = ""
            for lbl, val in loc_rows:
                html += f'<div class="brow"><span class="l">{lbl}</span><span class="v">{val}</span></div>'
            st.markdown(html, unsafe_allow_html=True)
            details = [d for d in (l.get("construction_detail"), l.get("noise_detail"),
                                   l.get("flood_detail")) if d]
            if details:
                st.markdown('<div class="muted" style="margin-top:6px">' +
                            "<br>".join(esc(d) for d in details) + "</div>", unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Deal stage + vibe notes
        s1, s2 = st.columns([1, 1])
        lid = l.get("id", "")
        with s1:
            cur = (stage or {}).get("stage", "NEW")
            new_stage = st.selectbox("Deal stage", DEAL_STAGES,
                                     index=DEAL_STAGES.index(cur) if cur in DEAL_STAGES else 0,
                                     key=f"stg_{lid}")
            stage_note = st.text_input("Stage note", value=(stage or {}).get("note") or "",
                                       key=f"stgn_{lid}", placeholder="e.g. viewing Sat 10:00")
            if st.button("SAVE STAGE", key=f"stgb_{lid}", use_container_width=True):
                from database import set_deal_stage
                set_deal_stage(lid, new_stage, stage_note)
                st.rerun()
        with s2:
            v = l.get("_vibe")
            if v:
                score, note, n = v
                st.markdown(f'<div class="muted">VIBE {score or "—"}/10 · {n} note(s)</div>'
                            f'<div class="mono" style="font-size:.75rem">{esc(note)}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="muted">No vibe notes yet — add one in SATELLITE VIEWER.</div>',
                            unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Action buttons
        a1,a2,a3,a4,a5 = st.columns(5)
        with a1: st.link_button("VIEW LISTING", l.get("url","#"), use_container_width=True)
        with a2:
            lat, lng = l.get("lat"), l.get("lng")
            if lat and lng:
                st.link_button("MAPS", f"https://www.google.com/maps?q={lat},{lng}&z=15", use_container_width=True)
        with a3:
            st.link_button("CHECK LV", _lv_link(l), use_container_width=True)
        with a4:
            verify = st.button("RE-VERIFY LV", key=f"rv_{lid}", use_container_width=True)
        with a5:
            render_memo_button(l, key=f"memo_{lid}")

        # The flat's own LV — the only thing that can verify it. The building
        # plot found from the map pin is a different LV (see modules/debt_bot).
        v1, v2 = st.columns(2)
        with v1:
            flat_lv = st.text_input(
                "Flat's own LV no.", value=l.get("lv_number") or "",
                key=f"lvno_{lid}", placeholder="e.g. 4321",
                help="From the seller's papers or the agent. The building "
                     "plot's LV is not the flat's.")
        with v2:
            flat_ku = st.text_input(
                "Katastrálne územie", value=l.get("cadastral_area") or "",
                key=f"lvku_{lid}", placeholder="e.g. Petržalka",
                help="Name or numeric code of the cadastral unit.")
        if verify:
            try:
                from modules.debt_bot import reverify
                lv_in = flat_lv.strip()
                ku_in = flat_ku.strip()
                changed = (lv_in != (l.get("lv_number") or "")
                           or ku_in != (l.get("cadastral_area") or ""))
                r = reverify(lid, lv_number=lv_in if changed else None,
                             cadastral_area=ku_in if changed else "")
                if r["status"] == "REJECT":
                    st.error(f"❌ REJECTED: {r['detail']}")
                elif r["status"] == "PASS":
                    st.success(f"✅ Clean: {r['detail']}")
                elif r["status"] == "UNVERIFIED":
                    st.warning(f"⚠ Unverified: {r['detail']}")
                else:
                    st.warning(f"Re-verify: {r.get('detail', r['status'])}")
            except Exception as e:
                st.warning(f"Re-verify: {e}")

        st.markdown(f'<div class="muted">Source: {esc((l.get("source") or "").upper())} · First seen: {esc((l.get("scraped_at") or "")[:10])}</div>', unsafe_allow_html=True)


def render_memo_button(l, key):
    """Two-step PDF memo: building every card's PDF on each rerun would be
    slow, so the first click builds this one and swaps in the download."""
    ready = st.session_state.get("memo_ready", {})
    if key in ready:
        st.download_button("⬇️ MEMO PDF", ready[key],
                           file_name=f"memo_{(l.get('id') or 'x')[:8]}_{datetime.now():%Y%m%d}.pdf",
                           mime="application/pdf", key=f"{key}_dl", use_container_width=True)
    elif st.button("📄 MEMO", key=key, use_container_width=True):
        from modules.memo import build_memo_pdf
        from database import get_annotations
        try:
            pdf = build_memo_pdf(l, price_history={l.get("id"): l.get("_ph")} if l.get("_ph") else None,
                                 notes=get_annotations(l.get("id")), stage=l.get("_stage"),
                                 portals=l.get("_copies"))
            st.session_state.setdefault("memo_ready", {})[key] = pdf
            st.rerun()
        except Exception as e:
            st.warning(f"Memo: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(t0, t1, t_map, t_whatif, t_pipe, t2, t_rej, t_comps, t3) = st.tabs([
    "TRIAGE TABLE",
    "ACTIVE SNAG LIST",
    "MAP",
    "WHAT-IF / TAX",
    "DEAL PIPELINE",
    "SATELLITE VIEWER",
    "REJECTED",
    "RENT COMPS",
    "ONE-CLICK CLOSE",
])

def _value_rank(l):
    """Deepest discount to the regional median first, then the higher yield."""
    return (l.get("market_discount") or 0, l.get("gross_yield") or 0)


greens  = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "GREEN"],
                 key=_value_rank, reverse=True)
yellows = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "YELLOW"],
                 key=_value_rank, reverse=True)
whites  = [l for l in data if (l.get("cf_class") or l.get("classification")) == "WHITE"]
# Listing ids are md5 hex digests, so a prefix test on "d" (meant for the demo
# rows d1–d3) hid one real listing in sixteen. The demo rows are all scored
# GREEN/YELLOW and never land here anyway.
pending = [l for l in data if (l.get("cf_class") or l.get("classification") or "PENDING") == "PENDING"]


# ── Tab 0: Triage Table ───────────────────────────────────────────────────────
# Flat, sortable view of every scored listing so you can spot the best
# surplus / yield in one scan instead of expanding each card individually.
with t0:
    import pandas as pd

    scored = greens + yellows + whites
    if not scored:
        st.info("No scored listings yet — run the pipeline (NEHNUT / BAZOS / TOPREAL → 💰 CASHFLOW SCORE) to populate this view.")
    else:
        from engine.financial import compute_deal_score
        emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪", "PENDING": "⏳"}
        triage_rows = []
        for l in scored:
            cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
            surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
            score, grade = compute_deal_score(l)
            price = l.get("price_eur") or 0
            my = l.get("max_price_yellow")
            irr_v = l.get("irr_sro") if show_sro else l.get("irr_personal")
            ph = l.get("_ph") or {}
            vibe = l.get("_vibe")
            triage_rows.append({
                "": emoji_map.get(cls, ""),
                "Grade":    grade,
                "Score":    score,
                "Title":    (l.get("title") or l.get("district") or "—")[:50],
                "District": l.get("district") or "—",
                "Stage":    (l.get("_stage") or {}).get("stage", ""),
                "Price":    price,
                "Max 🟡":   my,
                "Max 🟢":   l.get("max_price_green"),
                "Ask vs 🟡": (price / my - 1) * 100 if my and price else None,
                "Below%":   (l.get("market_discount") or 0) * 100,
                "Size":     l.get("size_m2")              or 0,
                "Rent":     l.get("estimated_rent_eur")   or 0,
                "Surplus":  surplus if surplus is not None else 0,
                "+2pp":     l.get("stress_surplus_sro"),
                "Gross%":   (l.get("gross_yield")         or 0) * 100,
                "Cap%":     (l.get("cap_rate")            or 0) * 100,
                "IRR%":     irr_v * 100 if irr_v is not None else None,
                "Yield":    (l.get("net_rental_yield")    or 0) * 100,
                "Days":     l.get("_dom"),
                "ΔPrice":   ph["change_pct"] * 100 if ph.get("change_pct") is not None else None,
                "Portals":  l.get("_portals", 1),
                "Features": _features_label(l),
                "Vibe":     vibe[0] if vibe else None,
                "LV":       _lv_state(l)[0].replace(" LV", "")
                            + (f" · {l['lv_risk_level']}" if l.get("lv_risk_level") else ""),
                "Src":      (l.get("source") or "").upper()[:5],
                "URL":      l.get("url") or "",
            })
        df = pd.DataFrame(triage_rows).sort_values(
            ["Score", "Below%"], ascending=[False, False]
        )
        st.markdown(
            f'<div class="muted">{len(df)} scored listings — sorted by composite deal '
            f'grade (yield + discount to market + location + energy + condition + '
            f'risk), then discount. Click any header to re-sort.</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=min(600, 40 + 35 * len(df)),
            column_config={
                "Score":   st.column_config.NumberColumn(format="%d", help="0–100 composite deal score"),
                "Price":   st.column_config.NumberColumn(format="€%d"),
                "Max 🟡":  st.column_config.NumberColumn(format="€%d", help="Highest price that still scores YELLOW"),
                "Max 🟢":  st.column_config.NumberColumn(format="€%d", help="Highest price that scores GREEN"),
                "Ask vs 🟡": st.column_config.NumberColumn(format="%+.1f%%", help="Asking price vs max YELLOW price — the discount you need to negotiate (negative = already inside)"),
                "Size":    st.column_config.NumberColumn(format="%d m²"),
                "Rent":    st.column_config.NumberColumn(format="€%d"),
                "Surplus": st.column_config.NumberColumn(format="€%+d"),
                "+2pp":    st.column_config.NumberColumn(format="€%+d", help="s.r.o. surplus at the mortgage rate + 2 pp"),
                "Below%":  st.column_config.NumberColumn(
                    format="%.0f%%", help="Asking €/m² below the regional median "
                                          "(negative = above it)"),
                "Gross%":  st.column_config.NumberColumn(format="%.2f%%"),
                "Cap%":    st.column_config.NumberColumn(format="%.2f%%"),
                "IRR%":    st.column_config.NumberColumn(format="%.1f%%", help="10-year IRR incl. appreciation, exit costs and tax on the gain"),
                "Yield":   st.column_config.NumberColumn(format="%.2f%%"),
                "Days":    st.column_config.NumberColumn(format="%d", help="Days since first seen on any portal"),
                "ΔPrice":  st.column_config.NumberColumn(format="%+.1f%%", help="Price change since first seen"),
                "Portals": st.column_config.NumberColumn(format="%d", help="Portals the same flat is listed on"),
                "Vibe":    st.column_config.NumberColumn(format="%d/10"),
                "URL":     st.column_config.LinkColumn(display_text="open ↗"),
            },
        )


# ── Tab 1: Snag List ──────────────────────────────────────────────────────────
with t1:
    if not greens and not yellows and not whites and not pending:
        st.info("No listings in DB yet — click NEHNUT, BAZOS, or TOPREAL in the sidebar to scrape.")
    else:
        if not greens and not yellows and not whites and pending:
            st.info(f"⏳ {len(pending)} listing(s) scraped and pending scoring. Click 💰 CASHFLOW SCORE in the sidebar to classify them.")
        if greens:
            st.markdown(f'<div class="muted" style="margin:14px 0 8px">🟢 GREEN — ≥20% BELOW MARKET ({len(greens)})</div>', unsafe_allow_html=True)
            for l in greens:
                render_card(l)
        if yellows:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">🟡 YELLOW — 10–20% BELOW MARKET ({len(yellows)})</div>', unsafe_allow_html=True)
            for l in yellows:
                render_card(l)
        if whites:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">⚪ WHITE — AT MARKET OR NO BENCHMARK ({len(whites)})</div>', unsafe_allow_html=True)
            for l in whites:
                render_card(l)
        if pending:
            with st.expander(f"⏳ PENDING SCORING ({len(pending)} listings scraped, not yet classified)"):
                for l in pending:
                    title = l.get("title") or l.get("address_raw") or l.get("district") or "—"
                    price = l.get("price_eur") or 0
                    size  = l.get("size_m2") or 0
                    src   = (l.get("source") or "").upper()
                    st.markdown(f'<div class="brow"><span class="l">{esc(title[:60])}</span><span class="v">€{price:,.0f} · {size:.0f}m² · {esc(src)}</span></div>', unsafe_allow_html=True)


# ── Map ───────────────────────────────────────────────────────────────────────
with t_map:
    mapped = [l for l in data if l.get("lat") and l.get("lng")]
    if not mapped:
        st.info("No coordinates yet — run 📍 LOCATION IQ (works without a Google key: "
                "it falls back to OpenStreetMap).")
    else:
        import pydeck as pdk
        palette = {"GREEN": [0, 230, 118], "YELLOW": [255, 215, 64],
                   "WHITE": [96, 125, 139], "PENDING": [68, 138, 255]}
        pts = []
        for l in mapped:
            cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
            surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
            approx = (l.get("geo_precision") or "") == "area"
            pts.append({
                "lat": l["lat"], "lng": l["lng"],
                "color": palette.get(cls, [96, 125, 139]) + ([110] if approx else [220]),
                "radius": 60 if cls in ("GREEN", "YELLOW") else 35,
                "title": (l.get("title") or l.get("district") or "—")[:60],
                "price": f"€{(l.get('price_eur') or 0):,.0f}",
                "cls": cls,
                "surplus": "—" if surplus is None else f"€{surplus:+,.0f}/mo",
                "maxy": f"€{l['max_price_yellow']:,.0f}" if l.get("max_price_yellow") else "—",
                "where": "approximate (area centroid)" if approx else (l.get("geo_precision") or ""),
            })
        st.markdown(f'<div class="muted">{len(pts)} of {len(data)} filtered listings have '
                    f'coordinates. Faded dots are geocoded to an area, not a street.</div>',
                    unsafe_allow_html=True)
        st.pydeck_chart(pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=sum(p["lat"] for p in pts) / len(pts),
                longitude=sum(p["lng"] for p in pts) / len(pts),
                zoom=7 if len(pts) > 1 else 13),
            layers=[pdk.Layer(
                "ScatterplotLayer", data=pts, get_position="[lng, lat]",
                get_fill_color="color", get_radius="radius",
                radius_min_pixels=4, radius_max_pixels=14, pickable=True)],
            tooltip={"html": "<b>{title}</b><br/>{price} · {cls}<br/>surplus {surplus}"
                             "<br/>max YELLOW {maxy}<br/><i>{where}</i>"},
        ))


# ── What-if / tax toggle calculator ───────────────────────────────────────────
with t_whatif:
    from engine.financial import (
        analyse, default_ltv, max_offer_price, project_irr, get_rent_estimate,
        base_rent_rate,
    )
    from engine.rent_comps import load_live_rates
    from config import (
        MORTGAGE_RATE_PA, LOAN_TERM_YEARS, LTV_RATIO, LTV_RATIO_INVESTOR,
        HOLD_YEARS, APPRECIATION_RATE, RENT_GROWTH_RATE, EXIT_COST_RATE,
    )
    st.markdown('<div class="muted">WHAT-IF — RE-RUN ANY DEAL WITH YOUR OWN FINANCING, '
                'RENT AND HOLD ASSUMPTIONS · PERSONAL vs s.r.o.</div>', unsafe_allow_html=True)

    live_rates = load_live_rates()
    opts = {"✏️ Custom property": None}
    opts.update({f"{l.get('title') or l.get('district') or '?'} — €{(l.get('price_eur') or 0):,.0f}"
                 f" [{(l.get('id') or '')[:6]}]": l for l in data})
    pick = opts[st.selectbox("Property", list(opts.keys()), key="wi_pick")]
    # Widget keys carry the pick so choosing another listing reloads its values.
    pk = (pick or {}).get("id") or "custom"

    w1, w2, w3 = st.columns(3)
    with w1:
        st.markdown("**PROPERTY**")
        wi_price = st.number_input("Price €", 10_000, 5_000_000,
                                   min(max(int((pick or {}).get("price_eur") or 120_000), 10_000), 5_000_000),
                                   1_000, key=f"wi_price_{pk}")
        wi_size = st.number_input("Size m²", 10.0, 500.0,
                                  min(max(float((pick or {}).get("size_m2") or 60.0), 10.0), 500.0),
                                  1.0, key=f"wi_size_{pk}")
        wi_district = st.text_input("District", (pick or {}).get("district") or "Bratislava II",
                                    key=f"wi_dist_{pk}")
        wi_rooms = st.number_input("Rooms (0 = unknown)", 0, 6,
                                   min(int((pick or {}).get("rooms") or 0), 6),
                                   key=f"wi_rooms_{pk}")
    est_rent = get_rent_estimate(wi_district, wi_size, wi_rooms or None,
                                 (pick or {}).get("has_parking"), (pick or {}).get("furnished"),
                                 (pick or {}).get("has_balcony"), rates=live_rates)
    rate_used, rent_key, rent_src = base_rent_rate(wi_district, live_rates)
    with w2:
        st.markdown("**FINANCING**")
        investor = st.toggle("3rd+ property (NBS 70% LTV cap)", value=default_ltv() < LTV_RATIO,
                             key="wi_inv",
                             help="From 1 Oct 2026 banks may lend at most 70% on a 3rd-and-"
                                  "subsequent residential property.")
        cap = LTV_RATIO_INVESTOR if investor else LTV_RATIO
        wi_ltv = st.slider("LTV %", 0, 90, int(cap * 100), 5, key=f"wi_ltv_{investor}") / 100
        if wi_ltv > cap + 1e-9:
            st.warning(f"Above the {cap:.0%} NBS cap for this purchase — a bank won't lend this.")
        wi_rate = st.slider("Mortgage rate %", 1.0, 9.0, MORTGAGE_RATE_PA * 100, 0.1, key="wi_rate") / 100
        wi_term = st.slider("Term (years)", 5, 30, LOAN_TERM_YEARS, 1, key="wi_term")
    with w3:
        st.markdown("**RENT & HOLD**")
        st.caption(f"Estimate €{est_rent:,.0f}/mo · {rate_used:.2f} €/m² for '{rent_key}' "
                   f"({'live comps' if rent_src == 'live' else 'baseline table'})")
        wi_rent = st.number_input("Rent €/mo (override)", 0, 20_000, int(round(est_rent)), 10,
                                  key=f"wi_rent_{pk}_{wi_district}_{wi_size}_{wi_rooms}")
        wi_hold = st.slider("Hold (years)", 1, 30, HOLD_YEARS, key="wi_hold")
        wi_app = st.slider("Price growth % p.a.", -3.0, 10.0, APPRECIATION_RATE * 100, 0.5, key="wi_app") / 100
        wi_rg = st.slider("Rent growth % p.a.", -3.0, 10.0, RENT_GROWTH_RATE * 100, 0.5, key="wi_rg") / 100
        wi_exit = st.slider("Exit costs %", 0.0, 8.0, EXIT_COST_RATE * 100, 0.5, key="wi_exit") / 100

    fin = dict(rent_override=wi_rent or None, ltv=wi_ltv, rate=wi_rate, term_years=wi_term,
               rooms=wi_rooms or None)
    r = analyse(wi_price, wi_size, wi_district, **fin)
    irr_kw = dict(rent=r.estimated_rent, ltv=wi_ltv, rate=wi_rate, term_years=wi_term,
                  hold_years=wi_hold, appreciation=wi_app, rent_growth=wi_rg,
                  exit_cost_rate=wi_exit)
    irr_p = project_irr(wi_price, wi_size, wi_district, structure="PERSONAL", **irr_kw)
    irr_s = project_irr(wi_price, wi_size, wi_district, structure="SRO", **irr_kw)
    # The class is the discount to the regional median, so the max offer
    # depends on size and district only — financing moves cashflow, not class.
    max_y = max_offer_price(wi_size, wi_district, "YELLOW")
    max_g = max_offer_price(wi_size, wi_district, "GREEN")

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Class", r.classification,
              help=(f"{r.market_discount:+.0%} vs the regional median €/m² · "
                    f"s.r.o. self-funding {r.ratio_sro:.0%}")
              if r.market_discount is not None else "No regional median for this district.")
    k2.metric("Best structure", "s.r.o." if r.optimal_structure == "SRO" else "Personal",
              delta=f"€{r.annual_sro_saving:+,.0f}/yr s.r.o. vs personal")
    k3.metric("Cash in", f"€{r.total_cash_invested:,.0f}")
    k4.metric("Cap rate", f"{r.cap_rate:.2%}")
    k5.metric("Max offer 🟡", f"€{max_y:,.0f}" if max_y else "—",
              delta=f"{max_y / wi_price - 1:+.1%} vs price" if max_y else None)
    k6.metric("Max offer 🟢", f"€{max_g:,.0f}" if max_g else "—")

    rows = [
        ("Rent", r.estimated_rent, r.estimated_rent),
        ("Mortgage (interest + principal)", r.mortgage_monthly, r.mortgage_monthly),
        ("HOA + property tax", r.hoa_monthly + r.property_tax_monthly,
         r.hoa_monthly + r.property_tax_monthly),
        ("Vacancy + reserve + mgmt", r.vacancy_cost + r.maintenance_monthly + r.management_monthly,
         r.vacancy_cost + r.maintenance_monthly + r.management_monthly),
        ("Income tax", r.income_tax_personal, r.income_tax_sro),
        ("Total costs", r.total_costs_personal, r.total_costs_sro),
        ("Net surplus", r.surplus_personal, r.surplus_sro),
    ]
    cmp_df = pd.DataFrame(
        [{"€ / month": a, "Personal (FO)": p, "s.r.o.": s_} for a, p, s_ in rows]
        + [{"€ / month": "Self-funding ratio %", "Personal (FO)": r.ratio_personal * 100,
            "s.r.o.": r.ratio_sro * 100},
           {"€ / month": f"IRR over {wi_hold}y %", "Personal (FO)": (irr_p.irr or 0) * 100,
            "s.r.o.": (irr_s.irr or 0) * 100},
           {"€ / month": "Equity multiple ×", "Personal (FO)": irr_p.equity_multiple or 0,
            "s.r.o.": irr_s.equity_multiple or 0},
           {"€ / month": "Tax caused by the sale €", "Personal (FO)": irr_p.exit_tax,
            "s.r.o.": irr_s.exit_tax},
           {"€ / month": "Total profit €", "Personal (FO)": irr_p.total_profit,
            "s.r.o.": irr_s.total_profit}])
    c_left, c_right = st.columns([3, 2])
    with c_left:
        st.markdown('<div class="muted">TAX TOGGLE — PERSONAL vs s.r.o.</div>', unsafe_allow_html=True)
        st.dataframe(cmp_df, hide_index=True, use_container_width=True,
                     column_config={"Personal (FO)": st.column_config.NumberColumn(format="%.2f"),
                                    "s.r.o.": st.column_config.NumberColumn(format="%.2f")})
        st.caption("Personal: §6(3) passive rental, €500 exempt, no health levy, interest not "
                   "deductible; sale exempt after 5 years. s.r.o.: interest deductible, corporate "
                   "+ 10% dividend tax; the sale is taxed whenever it happens. Confirm with an účtovník.")
    with c_right:
        st.markdown('<div class="muted">RATE SHOCK (s.r.o.)</div>', unsafe_allow_html=True)
        shock_rows = []
        for bump in (0.0, 0.01, 0.02, 0.03):
            x = analyse(wi_price, wi_size, wi_district, **{**fin, "rate": wi_rate + bump})
            shock_rows.append({"Rate": f"{(wi_rate + bump) * 100:.1f}%",
                               "Surplus €/mo": x.surplus_sro,
                               "Self-funding %": x.ratio_sro * 100})
        st.dataframe(pd.DataFrame(shock_rows), hide_index=True, use_container_width=True,
                     column_config={"Surplus €/mo": st.column_config.NumberColumn(format="€%+d"),
                                    "Self-funding %": st.column_config.NumberColumn(format="%.1f%%")})
        st.markdown('<div class="muted">EQUITY CASH FLOWS (s.r.o.)</div>', unsafe_allow_html=True)
        st.bar_chart(pd.DataFrame({"Year": list(range(len(irr_s.cash_flows))),
                                   "€": irr_s.cash_flows}).set_index("Year"), height=180)


# ── Deal pipeline ─────────────────────────────────────────────────────────────
with t_pipe:
    from database import get_tracked_listings, get_deal_stage_history, set_deal_stage
    tracked = get_tracked_listings()
    st.markdown('<div class="muted">DEAL PIPELINE — EVERY LISTING YOU HAVE MOVED PAST "NEW". '
                'Move a deal from its card in ACTIVE SNAG LIST, or below.</div>',
                unsafe_allow_html=True)
    board_stages = [s_ for s_ in DEAL_STAGES if s_ != "NEW"]
    if not tracked:
        st.info("No tracked deals yet.")
    else:
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
                    maxy = (f" · max🟡 €{t['max_price_yellow']:,.0f}"
                            if t.get("max_price_yellow") else "")
                    note = f'<div class="muted">{esc(t["note"])}</div>' if t.get("note") else ""
                    name = esc((t.get("title") or t.get("district") or "—")[:40])
                    st.markdown(
                        f'<div class="sc" style="margin-bottom:6px;padding:8px">'
                        f'<div class="mono" style="font-size:.7rem;color:#e4eaf5">'
                        f'<a href="{esc(t["url"])}" target="_blank">{name}</a></div>'
                        f'<div class="muted">€{(t.get("price_eur") or 0):,.0f}{maxy}'
                        f' · {str(t.get("updated_at"))[:10]}{gone}</div>{note}</div>',
                        unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    all_opts = {f"{l.get('title') or l.get('district') or '?'} — €{(l.get('price_eur') or 0):,.0f}"
                f" [{(l.get('id') or '')[:6]}]": l.get("id") for l in data}
    for t in tracked:
        all_opts.setdefault(f"{t.get('title') or '?'} — €{(t.get('price_eur') or 0):,.0f}"
                            f" [{t['id'][:6]}]", t["id"])
    if all_opts:
        p1, p2, p3 = st.columns([3, 1, 2])
        with p1:
            pick_id = all_opts[st.selectbox("Listing", list(all_opts.keys()), key="pipe_pick")]
        with p2:
            cur = (stages.get(pick_id) or {}).get("stage", "NEW")
            pick_stage = st.selectbox("Stage", DEAL_STAGES, index=DEAL_STAGES.index(cur), key="pipe_stage")
        with p3:
            pick_note = st.text_input("Note", key="pipe_note")
        if st.button("MOVE DEAL", use_container_width=True):
            set_deal_stage(pick_id, pick_stage, pick_note)
            st.rerun()
        hist = get_deal_stage_history(pick_id)
        if hist:
            st.markdown("".join(
                f'<div class="brow"><span class="l">{str(h["changed_at"])[:16].replace("T", " ")}</span>'
                f'<span class="v">{esc(h["stage"])}{" — " + esc(h["note"]) if h.get("note") else ""}</span></div>'
                for h in hist), unsafe_allow_html=True)


# ── Rejected ──────────────────────────────────────────────────────────────────
with t_rej:
    from database import get_rejected
    rejected = get_rejected()
    st.markdown('<div class="muted">LV REJECTIONS — LISTINGS THE TITLE-DEED FILTER STOPPED, '
                'AND WHY. These never reach the deal lists.</div>', unsafe_allow_html=True)
    if not rejected:
        st.info("Nothing rejected yet.")
    else:
        rej_df = pd.DataFrame([{
            "Flagged":  str(r_.get("flagged_at") or "")[:10],
            "Listing":  (r_.get("title") or r_.get("address_raw") or "—")[:50],
            "District": r_.get("district") or "—",
            "Price":    r_.get("price_eur") or 0,
            "Reason":   r_.get("reason") or "—",
            "Detail":   (r_.get("detail") or "")[:160],
            "LV risk":  r_.get("lv_risk_level") or "—",
            "By":       r_.get("module") or "—",
            "Active":   "yes" if r_.get("is_active") else "no",
            "URL":      r_.get("url") or "",
        } for r_ in rejected])
        reasons = sorted(rej_df["Reason"].unique())
        pick_reasons = st.multiselect("Reason", reasons, default=reasons, key="rej_reasons")
        view = rej_df[rej_df["Reason"].isin(pick_reasons)]
        st.markdown(f'<div class="muted">{len(view)} rejection(s) · '
                    + " · ".join(f"{esc(k)}: {v}" for k, v in view["Reason"].value_counts().items())
                    + '</div>', unsafe_allow_html=True)
        st.dataframe(view, hide_index=True, use_container_width=True,
                     column_config={"Price": st.column_config.NumberColumn(format="€%d"),
                                    "URL": st.column_config.LinkColumn(display_text="open ↗")})
        rv_opts = {f"{r_.get('title') or r_.get('address_raw') or '?'} [{r_['id'][:6]}]": r_["id"]
                   for r_ in rejected}
        rv_pick = st.selectbox("Re-check a rejection (titles change — a lien can be cleared)",
                               list(rv_opts.keys()), key="rej_pick")
        if st.button("RE-VERIFY LV", key="rej_rv", use_container_width=True):
            try:
                from modules.debt_bot import reverify
                res = reverify(rv_opts[rv_pick])
                if res["status"] == "REJECT":
                    st.error(f"Still rejected: {res.get('detail')}")
                else:
                    st.success("✅ Now clean — it will be scored on the next run.")
                    st.rerun()
            except Exception as e:
                st.warning(f"Re-verify: {e}")


# ── Rent comps ────────────────────────────────────────────────────────────────
with t_comps:
    from engine.rent_comps import comps_table
    st.markdown('<div class="muted">LIVE RENT COMPS — €/m² FROM REAL PRENÁJOM LISTINGS, '
                'NORMALISED TO A BARE-RENT UNFURNISHED 2-IZB FLAT AND BLENDED WITH THE '
                'BASELINE TABLE BY SAMPLE SIZE</div>', unsafe_allow_html=True)
    ct = comps_table()
    if not ct:
        st.info("No rental comps yet — click 🏘️ RENT COMPS in the sidebar. Until then every "
                "rent comes from config.RENT_PER_M2.")
    else:
        comps_df = pd.DataFrame(ct)
        comps_df["Δ vs baseline %"] = (comps_df["In use €/m²"] / comps_df["Baseline €/m²"] - 1) * 100
        st.dataframe(comps_df, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.2f")
                                    for c in ("Live median €/m²", "Baseline €/m²", "In use €/m²")}
                     | {"Δ vs baseline %": st.column_config.NumberColumn(format="%+.1f%%")})
        from config import RENT_COMP_MIN_SAMPLE, RENT_COMP_PRIOR_WEIGHT, RENT_COMP_ASKING_HAIRCUT
        st.caption(f"A district needs {RENT_COMP_MIN_SAMPLE}+ rentals; its live median is cut "
                   f"{(1 - RENT_COMP_ASKING_HAIRCUT):.0%} (asking → achieved) and weighted against "
                   f"the baseline as if the baseline were {RENT_COMP_PRIOR_WEIGHT} comps.")


# ── Tab 2: Satellite Viewer ───────────────────────────────────────────────────
with t2:
    GMAPS_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
    st.markdown('<div class="muted">SATELLITE + STREET VIEW VERIFICATION — VIBE CHECK</div>', unsafe_allow_html=True)
    st.markdown("")

    if not data:
        st.info("No listings loaded.")
    else:
        opts = {f"{l.get('title') or '?'} — €{l.get('price_eur') or 0:,.0f} [{(l.get('id') or '')[:6]}]": l
                for l in data}
        sel  = opts[st.selectbox("Select listing", list(opts.keys()), label_visibility="collapsed")]

        lat, lng = sel.get("lat"), sel.get("lng")
        c1, c2   = st.columns(2)

        with c1:
            st.markdown('<div class="muted">LISTING PHOTO</div>', unsafe_allow_html=True)
            img = sel.get("primary_image_url","")
            if img and img.startswith("http"):
                st.image(img, use_container_width=True)
            else:
                st.markdown('<div style="background:#0b0d14;border:1px solid #151924;height:260px;display:flex;align-items:center;justify-content:center;color:#151924;font-family:IBM Plex Mono,monospace;font-size:0.7rem;letter-spacing:2px">NO IMAGE</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="muted">SATELLITE VIEW</div>', unsafe_allow_html=True)
            if lat and lng and GMAPS_KEY:
                sat = (f"https://maps.googleapis.com/maps/api/staticmap"
                       f"?center={lat},{lng}&zoom=17&size=640x400&maptype=satellite"
                       f"&markers=color:red%7C{lat},{lng}&key={GMAPS_KEY}")
                st.image(sat, use_container_width=True)
            elif lat and lng:
                st.link_button("📡 OPEN SATELLITE (Google Maps)",
                               f"https://www.google.com/maps?q={lat},{lng}&z=17&t=k",
                               use_container_width=True)
                st.markdown('<div class="muted">Add GOOGLE_PLACES_API_KEY to .env for inline satellite.</div>', unsafe_allow_html=True)
            else:
                st.info("No coordinates for this listing.")

        if lat and lng:
            sv1, sv2 = st.columns(2)
            with sv1:
                st.link_button("🚶 STREET VIEW",
                               f"https://www.google.com/maps?q=&layer=c&cbll={lat},{lng}",
                               use_container_width=True)
            with sv2:
                st.link_button("🗺️ FULL MAP",
                               f"https://www.google.com/maps?q={lat},{lng}&z=15",
                               use_container_width=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('<div class="muted">VIBE CHECK</div>', unsafe_allow_html=True)
        vibe = st.slider("Score (1–10)", 1, 10, 5)
        note = st.text_input("Note", placeholder="e.g. Great location, needs new windows...")
        if st.button("SAVE ANNOTATION", use_container_width=True):
            from database import add_annotation
            add_annotation(sel["id"], note, vibe)
            st.success(f"✅ Vibe {vibe}/10 saved.")

        # Saved notes for this listing, newest first.
        from database import get_annotations
        notes = get_annotations(sel["id"])
        if notes:
            st.markdown(f'<div class="muted" style="margin-top:12px">SAVED NOTES ({len(notes)})</div>',
                        unsafe_allow_html=True)
            html = ""
            for n in notes:
                html += (f'<div class="brow"><span class="l">{str(n.get("created_at"))[:16].replace("T", " ")}'
                         f' · {n.get("vibe_score") or "—"}/10</span>'
                         f'<span class="v">{esc(n.get("note"))}</span></div>')
            st.markdown(html, unsafe_allow_html=True)



# ── Tab 3: One-Click Close ────────────────────────────────────────────────────
with t3:
    st.markdown('<div class="muted">ONE-CLICK CLOSE — NOTARY CONTRACT DRAFT GENERATOR</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted" style="color:#ff5252;margin-bottom:16px">⚠️ DRAFT ONLY — no legal validity until executed before a licensed Slovak notár</div>', unsafe_allow_html=True)

    if not data:
        st.info("No listings loaded.")
    else:
        opts = {f"{l.get('title') or '?'} — €{l.get('price_eur') or 0:,.0f} [{(l.get('id') or '')[:6]}]": l
                for l in data}
        sel3 = opts[st.selectbox("Select listing", list(opts.keys()), key="close_sel")]

        f1, f2 = st.columns(2)
        with f1:
            st.markdown("**BUYER**")
            buyer_name = st.text_input("Full Name / s.r.o. Name")
            buyer_ico  = st.text_input("IČO (if s.r.o., leave blank if personal)")
            ownership  = st.radio("Structure", ["Personal", "s.r.o."], horizontal=True)
        with f2:
            st.markdown("**DEAL**")
            agreed     = st.number_input("Agreed Price €", value=int(sel3.get("price_eur",0)), step=500)
            notary     = st.text_input("Notár Name")
            escrow     = st.checkbox("Notárska úschova (escrow hold)", value=True)
            deposit    = st.number_input("Deposit € (earnest money)", 0, 50000, 2000, 500)

        if st.button("GENERATE CONTRACT DRAFT", use_container_width=True):
            if not buyer_name.strip():
                st.error("Enter buyer name first.")
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                # Pre-format optional numeric fields — an f-string format spec
                # can't contain a conditional, so build these strings first.
                _surplus = sel3.get("surplus_sro")
                _saving  = sel3.get("annual_sro_saving")
                surplus_str = f"€{_surplus:,.0f}" if isinstance(_surplus, (int, float)) else "—"
                saving_str  = f"€{_saving:,.0f}"  if isinstance(_saving,  (int, float)) else "—"
                draft = f"""
╔══════════════════════════════════════════════════════════╗
║         KÚPNA ZMLUVA — DRAFT / NÁVRH ZMLUVY             ║
╚══════════════════════════════════════════════════════════╝

Vygenerované:  {now_str}
Stav:          DRAFT — vyžaduje notariálne vyhotovenie
Verzia:        Sovereign RE Dashboard v2026

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§ 1. PREDMET ZMLUVY

Nehnuteľnosť: {sel3.get('title','—')}
Adresa:       {sel3.get('address_raw','—')}
Okres:        {sel3.get('district','—')}
Výmera:       {sel3.get('size_m2','?')} m²
Energetická trieda: {sel3.get('energy_class','—')}

Katastrálne územie: {sel3.get('cadastral_area','[Doplniť]')}
Číslo parcely:      {sel3.get('cadastral_number','[Doplniť]')}
List vlastníctva:   [Overiť na Katastri pred podpisom]
LV Status:          {sel3.get('lv_status','PENDING')} (stav k dátumu generovania)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§ 2. ZMLUVNÉ STRANY

KUPUJÚCI (Buyer):
  Meno / Spoločnosť: {buyer_name}
  IČO:               {buyer_ico if buyer_ico else 'N/A — fyzická osoba'}
  Forma vlastníctva: {ownership}

PREDÁVAJÚCI (Seller):
  [Doplniť notárom — overiť totožnosť a vlastníctvo]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§ 3. KÚPNA CENA

Dohodnutá cena:    €{agreed:,.2f}
Záloha (depozit):  €{deposit:,.2f}
Zostatok:          €{agreed - deposit:,.2f}

Platobný mechanizmus:
  {'✅ Notárska úschova — odporúčané' if escrow else '⚠️ Priamy prevod — neodporúčané'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§ 4. PODMIENKY

1. Zmluva nadobúda platnosť podpisom oboch strán pred notárom.
2. Prevod vlastníctva nastáva zápisom do katastra nehnuteľností.
3. Predávajúci zaručuje, že nehnuteľnosť je bez právnych vád.
4. Kupujúci vyhlasuje, že je oboznámený so stavom nehnuteľnosti.
5. {'Finančné plnenie cez Notársku úschovu dle § 56a Notárskeho poriadku.' if escrow else 'Finančné plnenie na účet predávajúceho po podpise zmluvy.'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§ 5. NOTÁR

Notár:   {notary if notary else '[Prideliť notára]'}
Dátum:   [Doplniť]
Miesto:  [Doplniť]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FINANČNÁ ANALÝZA (pre interné účely):

s.r.o. surplus/mo:  {surplus_str}
Ročná úspora s.r.o.: {saving_str}
Net Yield:           {(sel3.get('net_rental_yield',0) or 0)*100:.2f}%
LV overenie:        {sel3.get('lv_status','PENDING')} — OVERIŤ 48H PRED PODPISOM

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  PRÁVNE UPOZORNENIE

Tento dokument je počítačom generovaný NÁVRH bez právnej záväznosti.
Nemá žiadnu právnu platnosť bez vyhotovenia a overenia licencovaným
slovenským notárom. Vždy overte LV bezprostredne pred podpisom.
Finálny prevod vyžaduje zápis na Katastri nehnuteľností SR.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated by Sovereign RE Dashboard · Private Use Only
                """.strip()

                st.text_area("CONTRACT DRAFT", draft, height=500)
                fname = f"contract_{sel3['id'][:8]}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
                st.download_button(
                    "⬇️ DOWNLOAD DRAFT",
                    draft,
                    file_name=fname,
                    mime="text/plain",
                    use_container_width=True,
                )
                st.markdown('<div class="muted">Next: Send to your notár. Use Notárska úschova for all funds. Re-verify LV 48h before signing.</div>', unsafe_allow_html=True)
                if using_demo:
                    st.caption("Demo listing — this draft is not saved.")
                else:
                    from database import save_contract_draft
                    save_contract_draft(sel3["id"], ownership, agreed,
                                        buyer_name.strip(), buyer_ico.strip(),
                                        notary.strip(), draft)
                    st.caption("Draft saved — it stays listed under EARLIER DRAFTS below.")

        # Every generated draft is kept, so the exact text sent to the notár can
        # be found again after the page reloads.
        if not using_demo:
            from database import get_contract_drafts
            earlier = get_contract_drafts(sel3["id"])
            if earlier:
                with st.expander(f"EARLIER DRAFTS ({len(earlier)})"):
                    for d in earlier:
                        stamp = (d["generated_at"] or "")[:16]
                        st.caption(
                            f'{stamp.replace("T", " ")} · {d["buyer_name"]} · '
                            f'{d["ownership_type"]} · €{d["agreed_price"] or 0:,.0f}')
                        st.download_button(
                            "⬇️ DOWNLOAD",
                            d["draft_text"] or "",
                            file_name=f"contract_{sel3['id'][:8]}_"
                                      f"{stamp.replace('-', '').replace(':', '').replace('T', '_')}.txt",
                            mime="text/plain",
                            key=f"draft_{d['id']}",
                        )

"""
app.py — Sovereign Investor Dashboard
Slovakia 2026 | Private Use Only
Run: streamlit run app.py
"""

import os, sys
import streamlit as st
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

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
from database import init_db, get_all_active, get_rejected, get_stats
init_db()

# ── Demo data (when DB is empty) ──────────────────────────────────────────────
DEMO = [
    {"id":"d1","url":"https://nehnutelnosti.sk/demo1",
     "title":"3-izbový byt, Dúbravka","price_eur":168000,"size_m2":72,
     "district":"Bratislava IV","energy_class":"A","source":"nehnutelnosti",
     "cf_class":"GREEN","surplus_personal":198,"surplus_sro":412,
     "ratio_personal":1.12,"ratio_sro":1.24,"cash_on_cash":0.089,
     "net_rental_yield":0.048,"gross_yield":0.066,"optimal_structure":"SRO",
     "estimated_rent_eur":920,"total_costs_personal":825,"total_costs_sro":742,
     "annual_sro_saving":2568,"sro_break_even_months":12,
     "mortgage_monthly":598,"hoa_monthly":60,"property_tax_monthly":46,
     "vacancy_cost":46,"maintenance_monthly":140,
     "income_tax_personal":95,"health_levy_personal":82,
     "income_tax_sro":112,"health_levy_sro":0,
     "location_score":83,"location_tier":"PRIME","nearest_transit_m":340,
     "walkability_score":78,"industrial_zone":0,"construction_risk":0,"noise_flag":0,
     "amenity_count":5,"lv_status":"PASS","lat":48.178,"lng":17.062,
     "primary_image_url":""},
    {"id":"d2","url":"https://nehnutelnosti.sk/demo2",
     "title":"2-izbový byt, Žilina centrum","price_eur":98000,"size_m2":58,
     "district":"Žilina","energy_class":"B","source":"nehnutelnosti",
     "cf_class":"GREEN","surplus_personal":145,"surplus_sro":318,
     "ratio_personal":1.06,"ratio_sro":1.19,"cash_on_cash":0.074,
     "net_rental_yield":0.039,"gross_yield":0.078,"optimal_structure":"SRO",
     "estimated_rent_eur":640,"total_costs_personal":603,"total_costs_sro":537,
     "annual_sro_saving":2076,"sro_break_even_months":15,
     "mortgage_monthly":401,"hoa_monthly":60,"property_tax_monthly":27,
     "vacancy_cost":32,"maintenance_monthly":82,
     "income_tax_personal":65,"health_levy_personal":54,
     "income_tax_sro":78,"health_levy_sro":0,
     "location_score":72,"location_tier":"SOLID","nearest_transit_m":490,
     "walkability_score":66,"industrial_zone":1,"construction_risk":0,"noise_flag":0,
     "amenity_count":4,"lv_status":"PASS","lat":49.223,"lng":18.739,
     "primary_image_url":""},
    {"id":"d3","url":"https://nehnutelnosti.sk/demo3",
     "title":"1-izbový byt, Nitra Klokočina","price_eur":82000,"size_m2":38,
     "district":"Nitra","energy_class":"C","source":"bazos",
     "cf_class":"YELLOW","surplus_personal":-42,"surplus_sro":87,
     "ratio_personal":0.94,"ratio_sro":1.09,"cash_on_cash":0.051,
     "net_rental_yield":0.031,"gross_yield":0.066,"optimal_structure":"SRO",
     "estimated_rent_eur":450,"total_costs_personal":479,"total_costs_sro":413,
     "annual_sro_saving":1548,"sro_break_even_months":20,
     "mortgage_monthly":336,"hoa_monthly":35,"property_tax_monthly":23,
     "vacancy_cost":23,"maintenance_monthly":68,
     "income_tax_personal":38,"health_levy_personal":33,
     "income_tax_sro":42,"health_levy_sro":0,
     "location_score":62,"location_tier":"SOLID","nearest_transit_m":680,
     "walkability_score":55,"industrial_zone":1,"construction_risk":0,"noise_flag":0,
     "amenity_count":3,"lv_status":"PASS","lat":48.307,"lng":18.085,
     "primary_image_url":""},
]


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="wordmark">SOVEREIGN</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub">Investor Dashboard · Slovakia 2026</div>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("#### PIPELINE")
    c1, c2 = st.columns(2)
    with c1: do_nehnut = st.button("NEHNUT",  use_container_width=True)
    with c2: do_bazos  = st.button("BAZOS",   use_container_width=True)
    do_lv   = st.button("🔒 LV DEBT FILTER", use_container_width=True)
    do_cf   = st.button("💰 CASHFLOW SCORE", use_container_width=True)
    do_loc  = st.button("📍 LOCATION IQ",    use_container_width=True)

    st.markdown("---")
    st.markdown("#### FILTERS")
    max_price  = st.slider("Max Price €",  30_000, 600_000, 300_000, 5_000)
    min_size   = st.slider("Min Size m²",  20, 150, 25, 5)
    show_sro   = st.toggle("Show s.r.o. figures", value=True)
    show_demo  = st.toggle("Demo data (no DB)",   value=False)

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

if do_nehnut:
    from scraper.nehnutelnosti import run as _scrape_nehnut
    from modules.cashflow_runner import run_scoring as _run_cf
    with st.spinner("Scraping Nehnutelnosti..."):
        try:
            n = _scrape_nehnut(max_pages=10)
            if n == 0:
                st.warning("⚠️ Nehnutelnosti returned 0 listings — the site may have blocked this request or changed its layout. Try again or check your network.")
            else:
                scored = _run_cf()
                st.success(f"✅ Scraped {n} listings, scored {scored}.")
                st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")

if do_bazos:
    from scraper.bazos import run as _scrape_bazos
    from modules.cashflow_runner import run_scoring as _run_cf
    with st.spinner("Scraping Bazos..."):
        try:
            n = _scrape_bazos(max_pages=10)
            if n == 0:
                st.warning("⚠️ Bazos returned 0 listings — the site may have blocked this request or changed its layout. Try again or check your network.")
            else:
                scored = _run_cf()
                st.success(f"✅ Scraped {n} listings, scored {scored}.")
                st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")

if do_lv:
    bar = st.progress(0)
    txt = st.empty()
    def lv_cb(i, n, a=""): bar.progress(i/n); txt.text(f"LV {i}/{n}: {a}")
    from modules.debt_bot import run_debt_filter
    p, r = run_debt_filter(progress_callback=lv_cb)
    bar.empty(); txt.empty()
    st.success(f"✅ LV done — Passed: {p}, Rejected: {r}")
    st.rerun()

if do_cf:
    bar = st.progress(0)
    def cf_cb(i, n): bar.progress(i/n)
    from modules.cashflow_runner import run_scoring
    n = run_scoring(progress_callback=cf_cb)
    bar.empty(); st.success(f"✅ Scored {n} listings"); st.rerun()

if do_loc:
    bar = st.progress(0); txt = st.empty()
    def loc_cb(i, n, a=""): bar.progress(i/n); txt.text(f"Location {i}/{n}: {a}")
    from modules.location_iq import run_location_scoring
    n = run_location_scoring(progress_callback=loc_cb)
    bar.empty(); txt.empty(); st.success(f"✅ Location scored {n}"); st.rerun()


# ── Data ──────────────────────────────────────────────────────────────────────
stats    = get_stats()
raw_data = get_all_active()

if show_demo or not raw_data:
    data = DEMO
    if not raw_data:
        st.info("ℹ️ No data in DB yet — showing demo listings. Run the pipeline to populate.")
else:
    data = raw_data

# Apply filters
data = [l for l in data
        if (l.get("price_eur") or 0) <= max_price
        and (l.get("size_m2")  or 0) >= min_size]


# ── Stats bar ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="sg">
  <div class="sc b"><div class="sn">{stats['total'] or len(DEMO)}</div><div class="sl">Total</div></div>
  <div class="sc g"><div class="sn">{stats['green']  or sum(1 for d in DEMO if d['cf_class']=='GREEN')}</div><div class="sl">Green</div></div>
  <div class="sc y"><div class="sn">{stats['yellow'] or sum(1 for d in DEMO if d['cf_class']=='YELLOW')}</div><div class="sl">Yellow</div></div>
  <div class="sc w"><div class="sn">{stats['white']}</div><div class="sl">White</div></div>
  <div class="sc r"><div class="sn">{stats['rejected']}</div><div class="sl">Rejected</div></div>
  <div class="sc a"><div class="sn">{stats['pending']}</div><div class="sl">Pending</div></div>
</div>
""", unsafe_allow_html=True)


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

    header = f"{emoji}  {title[:60]}   ·   €{price:,.0f}   ·   {fe(surplus,'€','',0)}/mo"

    with st.expander(header):
        # Row 1: key metrics
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1:
            st.metric("Price",    f"€{price:,.0f}")
            st.metric("Size",     f"{size:.0f} m²")
        with c2:
            st.metric("Est. Rent",  f"€{rent:,.0f}/mo")
            st.metric("Total Costs",f"€{total_c:,.0f}/mo" if total_c else "—")
        with c3:
            surplus_str = f"€{surplus:+,.0f}/mo" if surplus is not None else "—"
            st.metric("Surplus/mo",   surplus_str)
            st.metric("Self-Fund",    fp(ratio))
        with c4:
            st.metric("CoC Return", fp(l.get("cash_on_cash")))
            st.metric("Net Yield",  fp(l.get("net_rental_yield")))
        with c5:
            st.metric("Location",   f"{l.get('location_score','—')}/100")
            st.metric("Transit",    f"{transit:.0f}m" if transit else "—")

        # Badges
        badges = (
            badge(css_cls, cls) + " " +
            f'<span class="badge bo">{"s.r.o." if opt=="SRO" else "PERSONAL"}</span>' + " " +
            tier_badge(loc_tier) +
            (f' <span class="badge bg">⚙️ INDUSTRIAL</span>' if ind else "") +
            (f' <span class="badge bg">🏭 NITRA/ŽILINA</span>' if ind and "nitra" in district.lower() or "žilina" in district.lower() else "")
        )
        st.markdown(badges, unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Cost breakdown + Location IQ side by side
        bc1, bc2 = st.columns(2)

        with bc1:
            st.markdown(f'<div class="muted">COST BREAKDOWN — {struct}</div>', unsafe_allow_html=True)
            rows = [
                ("Mortgage",      l.get("mortgage_monthly")),
                ("HOA",           l.get("hoa_monthly")),
                ("Property Tax",  l.get("property_tax_monthly")),
                ("Vacancy 5%",    l.get("vacancy_cost")),
                ("Maintenance",   l.get("maintenance_monthly")),
                ("Income Tax",    l.get("income_tax_sro") if show_sro else l.get("income_tax_personal")),
                ("Health Levy",   l.get("health_levy_sro") if show_sro else l.get("health_levy_personal")),
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

        with bc2:
            st.markdown('<div class="muted">LOCATION IQ</div>', unsafe_allow_html=True)
            loc_rows = [
                ("Transit",        f"{transit:.0f}m {'✅' if (transit or 9999) <= 560 else '⚠️'}" if transit else "—"),
                ("Amenities",      f"{l.get('amenity_count','—')} {'✅' if (l.get('amenity_count') or 0) >= 3 else '⚠️'}"),
                ("Walkability",    f"{l.get('walkability_score','—')}/100"),
                ("Industrial",     "✅ YES" if ind else "—"),
                ("Construction",   "⚠️ Risk" if l.get("construction_risk") else "✅ Clear"),
                ("Noise",          "⚠️ >65dB" if l.get("noise_flag") else "✅ Clear"),
                ("Energy Class",   l.get("energy_class","?")),
                ("LV Status",      "✅ CLEAN" if l.get("lv_status") in ("PASS","CLEAN") else l.get("lv_status","—")),
            ]
            html = ""
            for lbl, val in loc_rows:
                html += f'<div class="brow"><span class="l">{lbl}</span><span class="v">{val}</span></div>'
            st.markdown(html, unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Action buttons
        a1,a2,a3,a4 = st.columns(4)
        with a1: st.link_button("VIEW LISTING", l.get("url","#"), use_container_width=True)
        with a2:
            lat, lng = l.get("lat"), l.get("lng")
            if lat and lng:
                st.link_button("MAPS", f"https://www.google.com/maps?q={lat},{lng}&z=15", use_container_width=True)
        with a3:
            st.link_button("CHECK LV", "https://kataster.skgeodesy.sk/EsriRegistrationWeb/", use_container_width=True)
        with a4:
            if st.button("RE-VERIFY LV", key=f"rv_{l['id']}", use_container_width=True):
                try:
                    from modules.debt_bot import reverify
                    r = reverify(l["id"])
                    if r["status"] == "REJECT":
                        st.error(f"❌ NOW REJECTED: {r['detail']}")
                        st.rerun()
                    else:
                        st.success("✅ Still clean.")
                except Exception as e:
                    st.warning(f"Re-verify: {e}")

        st.markdown(f'<div class="muted">Source: {(l.get("source") or "").upper()} · Scraped: {(l.get("scraped_at") or "")[:10]}</div>', unsafe_allow_html=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
t1, t2, t3 = st.tabs([
    "ACTIVE SNAG LIST",
    "SATELLITE VIEWER",
    "ONE-CLICK CLOSE",
])

greens  = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "GREEN"],
                 key=lambda x: x.get("surplus_sro") or 0, reverse=True)
yellows = sorted([l for l in data if (l.get("cf_class") or l.get("classification")) == "YELLOW"],
                 key=lambda x: x.get("surplus_sro") or 0, reverse=True)
whites  = [l for l in data if (l.get("cf_class") or l.get("classification")) == "WHITE"]
pending = [l for l in data if (l.get("cf_class") or l.get("classification") or "PENDING") == "PENDING"
           and l.get("id","").startswith("d") is False
           and l.get("id") not in ("d1","d2","d3")]


# ── Tab 1: Snag List ──────────────────────────────────────────────────────────
with t1:
    if not greens and not yellows and not whites and not pending:
        st.info("No listings in DB yet — click NEHNUT or BAZOS in the sidebar to scrape.")
    else:
        if not greens and not yellows and not whites and pending:
            st.info(f"⏳ {len(pending)} listing(s) scraped and pending scoring. Click 💰 CASHFLOW SCORE in the sidebar to classify them.")
        if greens:
            st.markdown(f'<div class="muted" style="margin:14px 0 8px">🟢 GREEN — ALPHA HOLDS ({len(greens)})</div>', unsafe_allow_html=True)
            for l in greens:
                render_card(l)
        if yellows:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">🟡 YELLOW — YIELD PLAYS ({len(yellows)})</div>', unsafe_allow_html=True)
            for l in yellows:
                render_card(l)
        if whites:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">⚪ WHITE — MARKET / FLIP ({len(whites)})</div>', unsafe_allow_html=True)
            for l in whites:
                render_card(l)
        if pending:
            with st.expander(f"⏳ PENDING SCORING ({len(pending)} listings scraped, not yet classified)"):
                for l in pending:
                    title = l.get("title") or l.get("address_raw") or l.get("district") or "—"
                    price = l.get("price_eur") or 0
                    size  = l.get("size_m2") or 0
                    src   = (l.get("source") or "").upper()
                    st.markdown(f'<div class="brow"><span class="l">{title[:60]}</span><span class="v">€{price:,.0f} · {size:.0f}m² · {src}</span></div>', unsafe_allow_html=True)


# ── Tab 2: Satellite Viewer ───────────────────────────────────────────────────
with t2:
    GMAPS_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
    st.markdown('<div class="muted">SATELLITE + STREET VIEW VERIFICATION — VIBE CHECK</div>', unsafe_allow_html=True)
    st.markdown("")

    if not data:
        st.info("No listings loaded.")
    else:
        opts = {f"{l.get('title','?')} — €{l.get('price_eur',0):,.0f}": l for l in data}
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
            import uuid as _uuid
            conn = __import__("database").get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO annotations (id, listing_id, note, vibe_score, created_at) VALUES (?,?,?,?,?)",
                (str(_uuid.uuid4()), sel["id"], note, vibe,
                 __import__("datetime").datetime.utcnow().isoformat())
            )
            conn.commit(); conn.close()
            st.success(f"✅ Vibe {vibe}/10 saved.")



# ── Tab 3: One-Click Close ────────────────────────────────────────────────────
with t3:
    st.markdown('<div class="muted">ONE-CLICK CLOSE — NOTARY CONTRACT DRAFT GENERATOR</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted" style="color:#ff5252;margin-bottom:16px">⚠️ DRAFT ONLY — no legal validity until executed before a licensed Slovak notár</div>', unsafe_allow_html=True)

    if not data:
        st.info("No listings loaded.")
    else:
        opts = {f"{l.get('title','?')} — €{l.get('price_eur',0):,.0f}": l for l in data}
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

s.r.o. surplus/mo:  €{sel3.get('surplus_sro','—'):,.0f if isinstance(sel3.get('surplus_sro'),float) else '—'}
Ročná úspora s.r.o.: €{sel3.get('annual_sro_saving','—'):,.0f if isinstance(sel3.get('annual_sro_saving'),float) else '—'}
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

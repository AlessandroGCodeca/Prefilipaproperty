"""
dashboard/style.py — the page's dark theme (.streamlit/config.toml sets
Streamlit's own to match).
"""

import streamlit as st


CSS = """
<style>
/* No web-font import: it asked fonts.googleapis.com on every page view and fell
   back silently when offline. IBM Plex is used if installed locally. */
:root {
    --mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Consolas, Menlo, monospace;
    --sans: 'IBM Plex Sans', system-ui, 'Segoe UI', sans-serif;
}
html, body, [class*="css"] { font-family: var(--sans); }
.stApp { background: #07090e; color: #bcc8e0; }

section[data-testid="stSidebar"] {
    background: #0b0d14 !important;
    border-right: 1px solid #151924;
}

.wordmark {
    font-family: var(--mono);
    font-size: 1rem; font-weight: 700;
    color: #e4eaf5; letter-spacing: 4px; text-transform: uppercase;
}
.sub {
    font-family: var(--mono);
    font-size: 0.55rem; color: #7a89a8; letter-spacing: 3px;
    text-transform: uppercase; margin-top: 3px;
}

/* Stat grid */
.sg { display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:6px; margin-bottom:18px; }
.sc {
    background:#0b0d14; border:1px solid #151924; border-radius:3px;
    padding:12px 14px; position:relative; overflow:hidden;
}
.sc::before { content:''; position:absolute; top:0;left:0;right:0; height:2px; }
.sc.g::before { background:#00e676; } .sc.y::before { background:#ffd740; }
.sc.w::before { background:#37474f; } .sc.r::before { background:#ff5252; }
.sc.b::before { background:#448aff; } .sc.a::before { background:#ff9100; }
.sn { font-family:var(--mono); font-size:1.9rem; font-weight:700; color:#e4eaf5; line-height:1; }
.sc.g .sn { color:#00e676; } .sc.y .sn { color:#ffd740; }
.sc.r .sn { color:#ff5252; } .sc.b .sn { color:#448aff; }
.sl { font-size:0.6rem; text-transform:uppercase; letter-spacing:1.5px; color:#7a89a8; margin-top:5px; }

/* Badges */
.badge { display:inline-block; padding:2px 8px; border-radius:2px;
         font-family:var(--mono); font-size:0.62rem; font-weight:700;
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
        font-family:var(--mono); font-size:0.76rem; }
.brow .l { color:#7a89a8; } .brow .v { color:#bcc8e0; }
.brow.tot { border-top:1px solid #151924; border-bottom:none; }
.brow.tot .l { color:#8a98b5; } .brow.tot .v { color:#e4eaf5; font-weight:700; }
.brow.pos .v { color:#00e676; } .brow.neg .v { color:#ff5252; }

/* Portal health strip: one chip per portal */
.ph { display:flex; flex-wrap:wrap; gap:6px; margin:-8px 0 14px; }
.phc { font-family:var(--mono); font-size:0.66rem; color:#8a98b5; white-space:nowrap;
       padding:3px 8px; border:1px solid #151924; border-radius:3px; background:#0b0d14; }
.phc b { color:#e4eaf5; }
.phc .spk { color:#448aff; letter-spacing:1px; }
.phc.bad { border-color:#ff5252; color:#ff8a80; } .phc.bad .spk { color:#ff5252; }
.phc.old { border-color:#ffd740; color:#ffd740; }
.phc.none { color:#566380; }
/* On a phone: a long chip wraps, and the portals with no run yet are left out. */
@media (max-width: 640px) {
    .phc { white-space:normal; }
    .phc.none { display:none; }
}

/* Compact cards (ACTIVE SNAG LIST on a phone): title, price, class, surplus, one button */
.cc { background:#0b0d14; border:1px solid #151924; border-left:3px solid #37474f;
      border-radius:3px; padding:10px 12px; margin-bottom:8px; }
.cc.g { border-left-color:#00e676; } .cc.y { border-left-color:#ffd740; }
.cc .cct { color:#e4eaf5; font-size:0.9rem; line-height:1.25; }
.cc .ccm { font-family:var(--mono); font-size:0.74rem; color:#8a98b5; margin:5px 0 8px; }
.cc .ccm .pos { color:#00e676; } .cc .ccm .neg { color:#ff5252; }
.cc a.ccb { display:block; text-align:center; padding:9px 0; border:1px solid #2a3350;
            border-radius:3px; font-family:var(--mono); font-size:0.72rem; letter-spacing:1px;
            color:#bcc8e0; text-decoration:none; }
.cc a.ccb:hover { border-color:#00e676; color:#00e676; }

/* Divider */
.div { border:none; border-top:1px solid #151924; margin:14px 0; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background:transparent; border-bottom:1px solid #151924; gap:0; }
.stTabs [data-baseweb="tab"] {
    background:transparent; border:none; border-bottom:2px solid transparent;
    color:#7a89a8; font-family:var(--mono); font-size:0.7rem;
    letter-spacing:1px; text-transform:uppercase; padding:8px 20px; border-radius:0;
}
.stTabs [aria-selected="true"] { background:transparent !important; color:#00e676 !important; border-bottom:2px solid #00e676 !important; }

/* Buttons — descendant selector: a button with help= sits inside a tooltip
   wrapper, so .stButton>button missed it and it fell back to the light theme. */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
    background:#0b0d14; color:#8a98b5; border:1px solid #151924;
    border-radius:3px; font-family:var(--mono);
    font-size:0.68rem; letter-spacing:1px; text-transform:uppercase;
    transition:all .15s;
}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {
    border-color:#00e676; color:#00e676; background:rgba(0,230,118,.04);
}
/* The one primary button (▶ RUN EVERYTHING) stands out from the step buttons. */
.stButton button[data-testid="stBaseButton-primary"] {
    border-color:#00e676; color:#00e676; background:rgba(0,230,118,.08);
}
.stButton button[data-testid="stBaseButton-primary"]:disabled { opacity:.4; }

div[data-testid="stExpander"] { background:#0b0d14; border:1px solid #151924 !important; border-radius:3px; }
div[data-testid="stExpander"] summary { color:#bcc8e0; }
div[data-testid="stExpander"] summary:hover { background:#11141d; color:#e4eaf5; }

/* Text areas (the contract draft): monospace keeps the draft's ╔══╗ frame and
   columns aligned. */
.stTextArea textarea { font-family:var(--mono); font-size:0.75rem; }

/* Metrics sit six to a row on the listing card; at the default 2.25rem
   "€168,000" and "€920/mo" were cut to "€168,…". */
div[data-testid="stMetricValue"] { font-size:1.45rem; }

.muted { color:#7a89a8; font-size:0.7rem; font-family:var(--mono); }
.mono  { font-family:var(--mono); }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)

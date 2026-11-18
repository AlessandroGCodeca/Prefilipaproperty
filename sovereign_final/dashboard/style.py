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
    --bg: #07090e;
    --panel: #0b0d14;
    --surface: #0d1019;
    --hover: #11141d;
    --line-soft: #131827;
    --line: #1b2132;
    --line-strong: #2a3350;
    --text: #e4eaf5;
    --body: #bcc8e0;
    --muted: #8b97b0;
    --faint: #7a859c;
    --good: #3ddc97;
    --caution: #f5b84a;
    --bad: #ff8a8a;
    --info: #6ea8ff;
    --bad-line: #4a2326;
}
:root {
    --mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Consolas, Menlo, monospace;
    --sans: 'IBM Plex Sans', system-ui, 'Segoe UI', sans-serif;
}
html, body, [class*="css"] { font-family: var(--sans); }
.stApp { background: var(--bg); color: var(--body); }

section[data-testid="stSidebar"] {
    background: var(--panel) !important;
    border-right: 1px solid var(--line);
}

.wordmark {
    font-family: var(--mono);
    font-size: 1rem; font-weight: 700;
    color: var(--text); letter-spacing: 4px; text-transform: uppercase;
}
.sub {
    font-family: var(--mono);
    font-size: 0.55rem; color: var(--muted); letter-spacing: 3px;
    text-transform: uppercase; margin-top: 3px;
}

/* Stat grid */
.sg { display:grid; grid-template-columns:repeat(auto-fit,minmax(78px,1fr)); gap:6px; margin-bottom:8px; }
.sc {
    background:var(--panel); border:1px solid var(--line); border-radius:3px;
    padding:8px 10px; position:relative; overflow:hidden;
}
/* Less empty space over the page: the tabs start higher (finding 21). */
[data-testid="stMainBlockContainer"], section.main .block-container { padding-top:2.2rem; }
.sc::before { content:''; position:absolute; top:0;left:0;right:0; height:2px; }
.sc.g::before { background:var(--good); } .sc.y::before { background:var(--caution); }
.sc.w::before { background:var(--line-strong); } .sc.r::before { background:var(--bad); }
.sc.b::before { background:var(--info); } .sc.a::before { background:var(--caution); }
.sn { font-family:var(--mono); font-size:1.45rem; font-weight:700; color:var(--text); line-height:1; }
.sc.g .sn { color:var(--good); } .sc.y .sn { color:var(--caution); }
.sc.r .sn { color:var(--bad); } .sc.b .sn { color:var(--info); }
.sl { font-size:0.6rem; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); margin-top:5px; }

/* Badges */
.badge { display:inline-block; padding:2px 8px; border-radius:2px;
         font-family:var(--mono); font-size:0.62rem; font-weight:700;
         letter-spacing:1px; text-transform:uppercase; }
.bg { background:rgba(61,220,151,.12); color:var(--good); }
.by { background:rgba(245,184,74,.12); color:var(--caution); }
.bw { background:rgba(139,151,176,.14);  color:var(--muted); }
.br { background:rgba(255,138,138,.12); color:var(--bad); }
.bp { background:rgba(110,168,255,.12);color:var(--info); }
.bs { background:rgba(110,168,255,.08);color:var(--info); }
.bo { background:rgba(245,184,74,.12); color:var(--caution); }

/* Breakdown rows */
.brow { display:flex; justify-content:space-between; padding:6px 0;
        border-bottom:1px solid var(--line-soft);
        font-family:var(--sans); font-size:0.84rem; }
.brow .l { color:var(--muted); } .brow .v { color:var(--body); font-family:var(--mono); }
.brow.tot { border-top:1px solid var(--line); border-bottom:none; }
.brow.tot .l { color:var(--muted); } .brow.tot .v { color:var(--text); font-weight:700; }
.brow.pos .v { color:var(--good); } .brow.neg .v { color:var(--bad); }

/* Portal health strip: one chip per portal */
.ph { display:flex; flex-wrap:wrap; gap:4px; margin:0 0 8px; }
.phc { font-family:var(--mono); font-size:0.66rem; color:var(--muted); white-space:nowrap;
       padding:3px 8px; border:1px solid var(--line); border-radius:3px; background:var(--panel); }
.phc b { color:var(--text); }
.phc .spk { color:var(--info); letter-spacing:1px; }
.phc.bad { border-color:var(--bad); color:var(--bad); } .phc.bad .spk { color:var(--bad); }
.phc.old { border-color:var(--caution); color:var(--caution); }
.phc.none { color:var(--faint); }
.ph-sum { display:none; }
/* On a phone: the healthy portals fold into one summary chip; only a failed or
   late one gets its own, and a long chip wraps. */
@media (max-width: 640px) {
    .phc { white-space:normal; }
    .phc.none, .phc.ok { display:none; }
    .ph-sum { display:inline-block; }
}

/* Compact cards (ACTIVE SNAG LIST on a phone): title, price, class, surplus, one button */
.lvc { font-family:var(--mono); font-size:0.72rem; line-height:1.7; color:var(--body);
       background:var(--panel); border:1px solid var(--line); border-radius:3px; padding:10px 12px;
       margin-top:6px; max-height:420px; overflow:auto; white-space:pre-wrap; word-break:break-word; }
.lvh { background:#5c1f1f; color:#ffb4ab; padding:0 3px; border-radius:2px; }
.lvs { background:#4d3f00; color:#ffe082; padding:0 3px; border-radius:2px; }
.lvb { background:#12381f; color:#a5d6a7; padding:0 3px; border-radius:2px; }
.lvu { background:#2a2350; color:#d1c4e9; padding:0 3px; border-radius:2px; outline:1px dashed #7e57c2; }
.cc { background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--line-strong);
      border-radius:3px; padding:10px 12px; margin-bottom:8px; }
.cc.g { border-left-color:var(--good); } .cc.y { border-left-color:var(--caution); }
.cc .cct { color:var(--text); font-size:0.9rem; line-height:1.25; }
.cc .ccm { font-family:var(--mono); font-size:0.74rem; color:var(--muted); margin:5px 0 8px; }
.cc .ccm .pos { color:var(--good); } .cc .ccm .neg { color:var(--bad); }
.cc a.ccb { display:block; text-align:center; padding:9px 0; border:1px solid var(--line-strong);
            border-radius:3px; font-family:var(--mono); font-size:0.72rem; letter-spacing:1px;
            color:var(--body); text-decoration:none; }
.cc a.ccb:hover { border-color:var(--good); color:var(--good); }

/* Divider */
.div { border:none; border-top:1px solid var(--line); margin:14px 0; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { background:transparent; border-bottom:1px solid var(--line); gap:0; }
.stTabs [data-baseweb="tab"] {
    background:transparent; border:none; border-bottom:2px solid transparent;
    color:var(--muted); font-family:var(--sans); font-size:0.78rem; font-weight:500;
    letter-spacing:0.8px; text-transform:uppercase; padding:8px 20px; border-radius:0;
}
.stTabs [aria-selected="true"] { background:transparent !important; color:var(--good) !important; border-bottom:2px solid var(--good) !important; }

/* Buttons — descendant selector: a button with help= sits inside a tooltip
   wrapper, so .stButton>button missed it and it fell back to the light theme. */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
    background:var(--panel); color:var(--muted); border:1px solid var(--line);
    border-radius:6px; font-family:var(--sans);
    font-size:0.8rem; font-weight:500; letter-spacing:0.3px;
    transition:all .15s;
}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {
    border-color:var(--good); color:var(--good); background:rgba(61,220,151,.04);
}
/* The one primary button (▶ RUN EVERYTHING) stands out from the step buttons. */
.stButton button[data-testid="stBaseButton-primary"] {
    border-color:var(--good); color:var(--good); background:rgba(61,220,151,.08);
}
.stButton button[data-testid="stBaseButton-primary"]:disabled { opacity:.4; }

div[data-testid="stExpander"] { background:var(--panel); border:1px solid var(--line) !important; border-radius:3px; }
div[data-testid="stExpander"] summary { color:var(--body); }
div[data-testid="stExpander"] summary:hover { background:var(--hover); color:var(--text); }

/* Text areas (the contract draft): monospace keeps the draft's ╔══╗ frame and
   columns aligned. */
.stTextArea textarea { font-family:var(--mono); font-size:0.75rem; }

/* Metrics sit six to a row on the listing card; at the default 2.25rem
   "€168,000" and "€920/mo" were cut to "€168,…". */
div[data-testid="stMetricValue"] { font-size:1.45rem; }

/* Verdict band (dashboard/verdict.py): the grade and one sentence, first. */
.vd { display:flex; gap:20px; align-items:center; background:var(--surface);
      border:1px solid var(--line); border-radius:10px; padding:18px 22px; margin:2px 0 14px; }
.vd-grade { flex:none; width:68px; height:68px; border-radius:12px; border:2px solid var(--line-strong);
            display:flex; flex-direction:column; align-items:center; justify-content:center;
            color:var(--muted); }
.vd-grade b { font-family:var(--mono); font-size:1.9rem; font-weight:600; line-height:1; }
.vd-grade span { font-family:var(--mono); font-size:0.62rem; letter-spacing:1px; margin-top:4px; }
.vd-g .vd-grade { border-color:var(--good); color:var(--good); }
.vd-b .vd-grade { border-color:var(--info); color:var(--info); }
.vd-y .vd-grade { border-color:var(--caution); color:var(--caution); }
.vd-text { min-width:0; }
.vd-head { font-size:1.2rem; font-weight:600; color:var(--text); line-height:1.3; }
.vd-sub { font-size:0.88rem; color:var(--muted); margin-top:6px; line-height:1.5; }
@media (max-width: 640px) {
    .vd { padding:14px; gap:14px; }
    .vd-grade { width:56px; height:56px; } .vd-head { font-size:1.05rem; }
}

/* Key figures: price, surplus, max offer — big; the rest quieter. */
[class*="st-key-kf"] div[data-testid="stMetric"] {
    background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 18px;
}
@media (min-width: 641px) {      /* the same height with or without the delta chip */
    [class*="st-key-kf"] div[data-testid="stMetric"] { min-height:7.6rem; }
}
[class*="st-key-kf"] div[data-testid="stMetricValue"] {
    font-family:var(--mono); font-size:2rem; font-weight:600; letter-spacing:-1px; color:var(--text);
}
[class*="st-key-kf"] div[data-testid="stMetricLabel"] { color:var(--muted); font-size:0.78rem; }
[class*="st-key-kfneg"] div[data-testid="stMetric"] { border-color:var(--bad-line); }
[class*="st-key-kfneg"] div[data-testid="stMetricValue"] { color:var(--bad); }
[class*="st-key-kfpos"] div[data-testid="stMetricValue"] { color:var(--good); }
[class*="st-key-sf"] div[data-testid="stMetricValue"] {
    font-family:var(--mono); font-size:1.1rem; font-weight:500; color:var(--text);
}
[class*="st-key-sf"] div[data-testid="stMetricLabel"] { color:var(--muted); font-size:0.74rem; }
/* A long label wraps instead of ending in "…" ("CoC Ret…"). */
[class*="st-key-sf"] div[data-testid="stMetricLabel"] p,
[class*="st-key-kf"] div[data-testid="stMetricLabel"] p { white-space:normal; overflow:visible; text-overflow:clip; }
/* On a phone the secondary figures sit two to a row instead of in one tall column. */
@media (max-width: 640px) {
    [class*="st-key-sf"] [data-testid="stColumn"] {
        min-width:calc(50% - 1rem) !important; flex:1 1 calc(50% - 1rem) !important;
    }
}

.muted { color:var(--muted); font-size:0.78rem; font-family:var(--sans); line-height:1.5; }
.mono  { font-family:var(--mono); }

/* Keyboard users: every control shows where the focus is (D13). */
.stButton button:focus-visible, .stDownloadButton button:focus-visible,
.stFormSubmitButton button:focus-visible, .stLinkButton a:focus-visible,
.stTabs [data-baseweb="tab"]:focus-visible, div[data-testid="stExpander"] summary:focus-visible,
a:focus-visible, input:focus-visible, textarea:focus-visible, [role="radio"]:focus-visible,
[role="checkbox"]:focus-visible, [role="switch"]:focus-visible {
    outline:2px solid var(--info) !important; outline-offset:2px;
}
.skip { position:absolute; left:-9999px; top:0; }
.skip:focus { left:12px; top:12px; z-index:1000; background:var(--surface); color:var(--text);
              padding:10px 14px; border:2px solid var(--info); border-radius:8px; }

/* ── Phone (≤640 px): touch-sized, tighter, tabs nearer the top ───────────── */
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"], section.main .block-container {
        padding-top:3.8rem;      /* clear of Streamlit's fixed header bar */
        padding-left:0.9rem; padding-right:0.9rem;
    }
    /* The header's sidebar button was 28 px. */
    [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"] button {
        min-width:44px; min-height:44px;
    }
    /* Six stat tiles as 3 × 2, not 4 + 2. */
    .sg { grid-template-columns:repeat(3,minmax(0,1fr)); }
    .sn { font-size:1.3rem; }
    /* At least 44 px to tap: buttons, tabs, expander headers, toggles, inputs. */
    .stButton button, .stDownloadButton button, .stFormSubmitButton button,
    .stLinkButton a { min-height:44px; }
    .stTabs [data-baseweb="tab"] { min-height:44px; padding:8px 12px; font-size:0.72rem; }
    div[data-testid="stExpander"] summary { min-height:44px; }
    .stToggle label, .stCheckbox label, .stRadio label { min-height:44px; align-items:center; }
    /* The wide letter-spaced wordmark wrapped in the narrow sidebar. */
    .sub { letter-spacing:1px; }
    .wordmark { letter-spacing:3px; }
    .muted { font-size:0.8rem; }
}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)

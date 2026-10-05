"""
modules/memo.py — one-listing PDF "investment memo".

Everything the dashboard knows about a deal on two or three printable pages:
verdict, price vs market and max offer, the cashflow under both ownership
structures, financing and the +2 pp stress test, the hold-period IRR with
exit costs, location risk, title deed, price history, notes and deal stage.

build_memo_pdf(listing) takes a row shaped like database.get_all_active()'s
and returns the PDF as bytes for st.download_button. It recomputes nothing
the score already holds; only the year-by-year IRR cash flows are rebuilt
(the score stores the IRR, not the flows) on the score's own rent and
financing.

Slovak text needs a Unicode font. DejaVu Sans (Linux, the Docker image) or
Arial (Windows/macOS) is used when found; failing both, the memo falls back
to Helvetica with diacritics folded away rather than not printing.
"""

from __future__ import annotations

import os
from datetime import datetime

from fpdf import FPDF

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]

_ASCII = str.maketrans({"€": "EUR", "—": "-", "−": "-", "–": "-", "·": "|", "≥": ">=",
                        "≤": "<=", "²": "2", "→": "->", "×": "x", "“": '"',
                        "”": '"', "„": '"', "’": "'"})


class _Memo(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_auto_page_break(True, margin=15)
        self.set_margins(15, 15, 15)
        self.memo_unicode = False
        for regular, bold in _FONT_CANDIDATES:
            if os.path.exists(regular):
                self.add_font("memo", "", regular)
                self.add_font("memo", "B", bold if os.path.exists(bold) else regular)
                self.memo_unicode = True
                break
        self.memo_font = "memo" if self.memo_unicode else "helvetica"

    def txt(self, s) -> str:
        s = "" if s is None else str(s)
        if self.memo_unicode:
            return s
        from scraper.textparse import strip_diacritics
        return strip_diacritics(s.translate(_ASCII)).encode("latin-1", "replace").decode("latin-1")

    def footer(self):
        self.set_y(-12)
        self.set_font(self.memo_font, "", 7)
        self.set_text_color(130)
        self.cell(0, 5, self.txt(f"Sovereign RE · investment memo · page {self.page_no()} · "
                                 "data scoring only, not investment advice"), align="C")

    def h1(self, text):
        self.set_font(self.memo_font, "B", 15)
        self.set_text_color(20)
        self.multi_cell(0, 7, self.txt(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def h2(self, text):
        self.ln(3)
        self.set_font(self.memo_font, "B", 10.5)
        self.set_text_color(20)
        self.cell(0, 6, self.txt(text.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)

    def para(self, text, size=8.5, color=60):
        self.set_font(self.memo_font, "", size)
        self.set_text_color(color)
        self.multi_cell(0, 4.4, self.txt(text), new_x="LMARGIN", new_y="NEXT")

    def kv(self, rows, cols=2):
        """Label/value pairs laid out in `cols` columns."""
        width = (self.w - self.l_margin - self.r_margin) / cols
        for i in range(0, len(rows), cols):
            for label, value in rows[i:i + cols]:
                self.set_font(self.memo_font, "", 8)
                self.set_text_color(110)
                self.cell(width * 0.48, 5, self.txt(label))
                self.set_font(self.memo_font, "B", 8.5)
                self.set_text_color(20)
                self.cell(width * 0.52, 5, self.txt(value))
            self.ln(5)

    def table(self, header, rows, widths):
        self.set_font(self.memo_font, "B", 7.5)
        self.set_fill_color(235)
        self.set_text_color(40)
        for h, w in zip(header, widths):
            self.cell(w, 5, self.txt(h), border=0, fill=True, align="R" if h != header[0] else "L")
        self.ln(5)
        self.set_font(self.memo_font, "", 7.5)
        for row in rows:
            for j, (v, w) in enumerate(zip(row, widths)):
                self.cell(w, 4.6, self.txt(v), align="L" if j == 0 else "R")
            self.ln(4.6)


def _eur(v, signed=False) -> str:
    if v is None:
        return "—"
    if signed:
        return f"{'+' if v >= 0 else '−'}€{abs(v):,.0f}"
    return f"€{v:,.0f}"


def _pct(v, digits=1) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def _flag(v, yes: str, no: str) -> str:
    return "unknown" if v is None else (yes if v else no)


def build_memo_pdf(l: dict, *, price_history: dict | None = None,
                   notes: list[dict] | None = None, stage: dict | None = None,
                   portals: list[dict] | None = None) -> bytes:
    from engine.financial import compute_deal_score, project_irr
    from database import days_on_market

    pdf = _Memo()
    pdf.add_page()

    price = l.get("price_eur") or 0
    size = l.get("size_m2") or 0
    cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
    score, grade = compute_deal_score(l)

    pdf.h1(l.get("title") or l.get("district") or "Listing")
    pdf.para(f"{l.get('address_raw') or l.get('district') or ''}\n"
             f"{(l.get('source') or '').upper()} · {l.get('url') or ''}\n"
             f"Memo generated {datetime.now():%Y-%m-%d %H:%M}", size=8, color=110)

    pdf.h2("Verdict")
    verdict = (f"{cls} · deal grade {grade} ({score}/100) · best structure "
               f"{'s.r.o.' if l.get('optimal_structure') == 'SRO' else 'personal'}")
    pdf.set_font(pdf.memo_font, "B", 11)
    pdf.set_text_color(20)
    pdf.multi_cell(0, 6, pdf.txt(verdict), new_x="LMARGIN", new_y="NEXT")
    my, mg = l.get("max_price_yellow"), l.get("max_price_green")
    if my or mg:
        gap = ""
        if my and price:
            d = (price / my - 1) * 100
            gap = (f" — asking is {d:.1f}% above the YELLOW price" if d > 0
                   else f" — asking is already {-d:.1f}% under it")
        pdf.para(f"Max offer to stay YELLOW: {_eur(my)} · to make GREEN: {_eur(mg)}{gap}.")

    pdf.h2("Price & market")
    disc = l.get("market_discount")
    median_m2 = l.get("regional_median_m2")
    # As on the card: a flat is as old as its oldest copy on any portal.
    seen = [c.get("scraped_at") for c in (portals or []) + [l] if c.get("scraped_at")]
    first_seen = min(seen) if seen else None
    dom = days_on_market(first_seen)
    pdf.kv([
        ("Asking price", _eur(price)),
        ("Size", f"{size:.0f} m²" if size else "—"),
        ("Price / m²", _eur(price / size) if size else "—"),
        ("Regional median", f"{_eur(median_m2)}/m²" if median_m2 else "—"),
        ("Vs market", "—" if disc is None else
         (f"{disc * 100:.1f}% below" if disc >= 0 else f"{-disc * 100:.1f}% above")),
        ("Days on market", "—" if dom is None else f"{dom} (first seen {str(first_seen)[:10]})"),
    ])
    ph = (price_history or {}).get(l.get("id"))
    if ph:
        steps = " → ".join(f"{_eur(p)} ({str(w)[:10]})" for w, p in ph["history"])
        pdf.para(f"Price history: {steps}  [{_pct(ph['change_pct'])} overall]")
    if portals and len(portals) > 1:
        pdf.para("Also listed: " + "; ".join(
            f"{(p.get('source') or '').upper()} {_eur(p.get('price_eur'))} {p.get('url')}"
            for p in portals))

    pdf.h2("Monthly cashflow")
    rent_src = l.get("rent_source")
    pdf.para(f"Estimated rent {_eur(l.get('estimated_rent_eur'))}/mo "
             f"({'live prenájom comps' if rent_src == 'live' else 'published baseline €/m²'}).")
    rows = [
        ("Mortgage", l.get("mortgage_monthly"), l.get("mortgage_monthly")),
        ("HOA (incl. fond opráv)", l.get("hoa_monthly"), l.get("hoa_monthly")),
        ("Property tax", l.get("property_tax_monthly"), l.get("property_tax_monthly")),
        ("Vacancy", l.get("vacancy_cost"), l.get("vacancy_cost")),
        ("Owner reserve", l.get("maintenance_monthly"), l.get("maintenance_monthly")),
        ("Management", l.get("management_monthly"), l.get("management_monthly")),
        ("Income tax", l.get("income_tax_personal"), l.get("income_tax_sro")),
        ("Total costs", l.get("total_costs_personal"), l.get("total_costs_sro")),
        ("Net surplus", l.get("surplus_personal"), l.get("surplus_sro")),
        ("Self-funding ratio", l.get("ratio_personal"), l.get("ratio_sro")),
    ]
    table_rows = []
    for label, p, s in rows:
        if label == "Self-funding ratio":
            table_rows.append((label, _pct(p), _pct(s)))
        else:
            signed = label == "Net surplus"
            table_rows.append((label, _eur(p, signed), _eur(s, signed)))
    pdf.table(["€ / month", "Personal", "s.r.o."], table_rows, [80, 50, 50])
    pdf.ln(1)
    pdf.kv([
        ("Cap rate (unlevered)", _pct(l.get("cap_rate"), 2)),
        ("Cash-on-cash", _pct(l.get("cash_on_cash"), 2)),
        ("Gross yield", _pct(l.get("gross_yield"), 2)),
        ("Net yield", _pct(l.get("net_rental_yield"), 2)),
    ])

    pdf.h2("Financing & stress test")
    ltv = l.get("ltv_used")
    rate = l.get("mortgage_rate_used")
    term = l.get("loan_term_years")
    pdf.kv([
        ("LTV", _pct(ltv, 0)),
        ("Rate / term", f"{_pct(rate, 2)} / {term or '—'} y"),
        ("Cash in (deposit + costs)", _eur(l.get("total_cash_invested"))),
        ("Principal paydown", f"{_eur(l.get('principal_paydown_monthly'))}/mo"),
        ("At rate +2 pp: surplus", f"{_eur(l.get('stress_surplus_sro'), True)}/mo"),
        ("At rate +2 pp: self-funding", _pct(l.get("stress_ratio_sro"))),
    ])

    if price and size and l.get("estimated_rent_eur"):
        pdf.h2("Hold-period return (IRR)")
        kw = dict(rent=l.get("estimated_rent_eur"), ltv=ltv, rate=rate or None,
                  term_years=term or None)
        kw = {k: v for k, v in kw.items() if v is not None}
        res = {s: project_irr(price, size, l.get("district") or "", structure=s, **kw)
               for s in ("PERSONAL", "SRO")}
        p, s = res["PERSONAL"], res["SRO"]
        from config import APPRECIATION_RATE, RENT_GROWTH_RATE, EXIT_COST_RATE
        pdf.para(f"Buy, hold {p.hold_years} years, sell. Assumes {_pct(APPRECIATION_RATE)} "
                 f"price growth, {_pct(RENT_GROWTH_RATE)} rent growth and "
                 f"{_pct(EXIT_COST_RATE)} selling costs.")
        pdf.table(["", "Personal", "s.r.o."], [
            ("IRR on equity", _pct(p.irr), _pct(s.irr)),
            ("Equity multiple", f"{p.equity_multiple or 0:.2f}×", f"{s.equity_multiple or 0:.2f}×"),
            ("Sale price", _eur(p.sale_price), _eur(s.sale_price)),
            ("Exit costs", _eur(p.exit_costs), _eur(s.exit_costs)),
            ("Loan repaid at exit", _eur(p.loan_balance_exit), _eur(s.loan_balance_exit)),
            ("Tax caused by the sale", _eur(p.exit_tax), _eur(s.exit_tax)),
            ("Total profit", _eur(p.total_profit, True), _eur(s.total_profit, True)),
        ], [80, 50, 50])
        pdf.ln(1)
        flows = "  ".join(f"y{t}: {_eur(c)}" for t, c in enumerate(s.cash_flows))
        pdf.para(f"s.r.o. cash flows — {flows}", size=7)

    pdf.h2("Location & risk")
    precision = l.get("geo_precision")
    pdf.kv([
        ("Location score", f"{l.get('location_score') or '—'}/100 {l.get('location_tier') or ''}"),
        ("Nearest transit", f"{l['nearest_transit_m']:.0f} m" if l.get("nearest_transit_m") else "—"),
        ("Energy class", l.get("energy_class") or "—"),
        ("Geocode", precision or "—"),
    ])
    pdf.para(
        f"Construction: {_flag(l.get('construction_risk'), 'YES', 'no')} — {l.get('construction_detail') or 'not checked'}\n"
        f"Noise: {_flag(l.get('noise_flag'), 'YES', 'no')} — {l.get('noise_detail') or 'not checked'}\n"
        f"Flood (Q100): {_flag(l.get('flood_zone'), 'YES', 'no')} — {l.get('flood_detail') or 'not checked'}")
    facts = []
    if l.get("floor") is not None:
        facts.append(f"floor {l['floor']}" + (f"/{l['building_floors']}" if l.get("building_floors") else ""))
    for col, label in (("has_elevator", "elevator"), ("has_cellar", "cellar"),
                       ("has_balcony", "balcony"), ("has_terrace", "terrace"),
                       ("has_loggia", "loggia"), ("has_parking", "parking")):
        if l.get(col):
            facts.append(label)
    if l.get("condition") and l["condition"] != "unknown":
        facts.append(f"condition: {l['condition']}")
    if l.get("furnished") and l["furnished"] != "unknown":
        facts.append(f"furnishing: {l['furnished']}")
    if facts:
        pdf.para("Flat: " + ", ".join(facts))

    pdf.h2("Title deed (LV)")
    # The flat's own LV is the only one that can verify it (the building
    # plot's LV is not); lv_detail is why the last check came out as it did.
    lv_no = l.get("lv_number")
    pdf.para(f"Status: {l.get('lv_status') or 'PENDING'}"
             + (f" · risk {l['lv_risk_level']}" if l.get("lv_risk_level") else "")
             + (f"\nFlat's LV: {lv_no}"
                + (f", k.ú. {l['cadastral_area']}" if l.get("cadastral_area") else "")
                if lv_no else "\nFlat's LV: not known — ask the seller or agent")
             + (f"\nLast check: {l['lv_detail']}"
                + (f" ({str(l['lv_checked_at'])[:10]})" if l.get("lv_checked_at") else "")
                if l.get("lv_detail") else "")
             # A check Claude decided has "[Claude LEVEL] <summary>" as its
             # detail; the summary again would repeat it.
             + (f"\n{l['lv_summary']}"
                if l.get("lv_summary") and l["lv_summary"] not in (l.get("lv_detail") or "")
                else "")
             + "\nRe-verify the LV 48 hours before signing.")

    if stage or notes:
        pdf.h2("Deal notes")
        if stage:
            pdf.para(f"Stage: {stage.get('stage')} (since {str(stage.get('updated_at'))[:10]})"
                     + (f" — {stage['note']}" if stage.get("note") else ""))
        for n in (notes or [])[:8]:
            pdf.para(f"{str(n.get('created_at'))[:10]} · vibe {n.get('vibe_score') or '—'}/10 · "
                     f"{n.get('note') or ''}")

    pdf.h2("Caveats")
    pdf.para("Rent, market value and risk flags are estimates from public data; the "
             "regional median is for older 3-room flats. Tax treatment (§6(3) personal "
             "rental, s.r.o. corporate + dividend tax, 5-year exemption on a personal "
             "sale) must be confirmed with an účtovník. Use notárska úschova for funds.",
             size=7.5, color=110)
    return bytes(pdf.output())

"""
modules/offer_sheet.py — the one-page offer sheet to take to a viewing: the
most you should pay and the figures that back an offer below the ask.

  - the ask against the regional median €/m² and against the flats like it
    listed now (same benchmark area, similar size), with those flats listed;
  - the max offer that keeps the flat YELLOW and GREEN, and how far each is
    from the ask;
  - how long the flat has been on offer and every price change.

build_offer_sheet(listing, comparables) returns the PDF as bytes. Its
figures are the score's own; comparables() picks the flats from the active
listings. Data from asking prices only — a negotiation aid, not a valuation.
"""

from __future__ import annotations

import statistics

from modules.memo import _Memo

COMPARABLES_SHOWN = 8
SIZE_BAND = 0.25          # a comparable's floor area is within ±25 %


class _Sheet(_Memo):
    def footer(self):
        self.set_y(-12)
        self.set_font(self.memo_font, "", 7)
        self.set_text_color(130)
        self.cell(0, 5, self.txt("Sovereign RE · offer sheet · asking prices, not sales — a "
                                 "negotiation aid, not a valuation"), align="C")


def _per_m2(row) -> float | None:
    price, size = row.get("price_eur") or 0, row.get("size_m2") or 0
    return price / size if price > 0 and size > 0 else None


def comparables(l: dict, rows: list[dict]) -> list[dict]:
    """The listings like `l`: the same market and benchmark area (the place
    its median is for), a floor area within SIZE_BAND, a price; one copy per
    flat, the closest in size first."""
    import markets
    from engine.regional_prices import median_source
    mkt = markets.of_row(l)
    mk = {} if mkt == "sk" else {"market": mkt}
    size = l.get("size_m2") or 0
    if not size:
        return []
    area = median_source(l.get("district") or "", **mk)[1]
    out, groups = [], set()
    for r in rows:
        if r.get("id") == l.get("id") or markets.of_row(r) != mkt or not _per_m2(r):
            continue
        if l.get("dup_group") and r.get("dup_group") == l.get("dup_group"):
            continue
        if abs((r.get("size_m2") or 0) - size) > size * SIZE_BAND:
            continue
        if median_source(r.get("district") or "", **mk)[1] != area or not area:
            continue
        g = r.get("dup_group") or r.get("id")
        if g in groups:
            continue
        groups.add(g)
        out.append(r)
    out.sort(key=lambda r: abs((r.get("size_m2") or 0) - size))
    return out


def build_offer_sheet(l: dict, comps: list[dict], *, price_history: dict | None = None,
                      days_listed: int | None = None, generated_at=None) -> bytes:
    from database import days_on_market
    from modules.contract_draft import doc_stamp
    import markets
    mkt = markets.of_row(l)
    cur = markets.get(mkt).currency

    def money(v, signed=False):
        return "—" if v is None else markets.format_money(v, cur, signed=signed)

    pdf = _Sheet()
    pdf.add_page()
    price, size = l.get("price_eur") or 0, l.get("size_m2") or 0
    ask_m2 = _per_m2(l)
    pdf.h1(f"Offer sheet — {l.get('title') or l.get('district') or 'listing'}")
    pdf.para(f"{l.get('address_raw') or l.get('district') or ''} · {size:.0f} m²"
             + (f" · {l['rooms']} rooms" if l.get("rooms") else "")
             + f"\n{(l.get('source') or '').upper()} · {l.get('url') or ''}"
             f"\nPrepared {doc_stamp(generated_at)}", size=8, color=110)

    pdf.h2("Your ceiling")
    my, mg = l.get("max_price_yellow"), l.get("max_price_green")
    pdf.kv([
        ("Asking price", money(price)),
        ("Asking per m²", money(ask_m2) + "/m²" if ask_m2 else "—"),
        ("Max offer (stays YELLOW)", money(my) + (f"  ({my / price - 1:+.1%} vs ask)"
                                                  if my and price else "")),
        ("Max offer (GREEN)", money(mg) + (f"  ({mg / price - 1:+.1%} vs ask)"
                                           if mg and price else "")),
        ("Regional median per m²", money(l.get("regional_median_m2")) + "/m²"
         if l.get("regional_median_m2") else "—"),
        ("Below the median", f"{l['market_discount'] * 100:.0f} %"
         if l.get("market_discount") is not None else "no benchmark"),
    ])

    pdf.h2("Flats like it on offer now")
    comps = comps[:COMPARABLES_SHOWN]
    m2s = [_per_m2(c) for c in comps]
    if comps:
        med = statistics.median(m2s)
        pdf.para(f"{len(comps)} listing(s) in the same benchmark area, {size * (1 - SIZE_BAND):.0f}–"
                 f"{size * (1 + SIZE_BAND):.0f} m²: median {money(med)}/m²"
                 + (f" — this one asks {ask_m2 / med - 1:+.1%} against it." if ask_m2 else "."))
        pdf.table(["Listing", "m²", "Rooms", "Price", "Per m²", "Days listed"],
                  [[(c.get("title") or c.get("district") or "—")[:44], f"{c.get('size_m2') or 0:.0f}",
                    str(c.get("rooms") or "—"), money(c.get("price_eur")), money(_per_m2(c)),
                    str(days_on_market(c.get("scraped_at")) if c.get("scraped_at") else "—")]
                   for c in comps],
                  [74, 14, 14, 28, 26, 24])
    else:
        pdf.para("No other listing of a similar size in the same area is on file.")

    pdf.h2("Time on the market and price changes")
    days = days_listed if days_listed is not None else (
        days_on_market(l.get("scraped_at")) if l.get("scraped_at") else None)
    lines = [f"First seen by the dashboard {days} days ago (on any portal)." if days is not None
             else "First seen: unknown."]
    ph = (price_history or {}).get(l.get("id")) if price_history else l.get("_ph")
    if ph and ph.get("history"):
        steps = " → ".join(f"{money(p)} ({str(w)[:10]})" for w, p in ph["history"])
        lines.append(f"Asking prices: {steps}"
                     + (f" — {ph['change_pct']:+.1%} in all." if ph.get("change_pct") else "."))
    else:
        lines.append("No price change seen.")
    pdf.para("\n".join(lines))

    pdf.h2("Points for the conversation")
    points = []
    if ask_m2 and comps:
        points.append(f"Similar flats here ask {money(statistics.median(m2s))}/m²; this one "
                      f"{money(ask_m2)}/m².")
    if days and days >= 30:
        points.append(f"On offer for {days} days.")
    if ph and (ph.get("change_pct") or 0) < 0:
        points.append(f"Already cut by {-ph['change_pct']:.0%}.")
    if my and price and my < price:
        points.append(f"Your ceiling is {money(my)}, {1 - my / price:.0%} under the ask.")
    if l.get("lv_soft_flags"):
        points.append(f"Title deed carries: {l['lv_soft_flags'][:160]}.")
    points.append("Costs the seller will mention are in the card: HOA, property tax, repairs "
                  "to come (ask the správca).")
    pdf.para("\n".join(f"• {p}" for p in points))
    return bytes(pdf.output())

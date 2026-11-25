"""
dashboard/verdict.py — the card's opening words: what the flat is, in plain
sentences, before any figure. A flat can be cheap and still lose money (grade
A, surplus −€123 a month), which a row of equal tiles hides, so the headline
says both in one line and a short paragraph gives the facts behind it.

The style is the one chosen on the design canvas (card B): a headline that
reads like a person talking ("A good price on a flat that doesn't pay for
itself."), then a paragraph with the numbers. Pure text: nothing here reads
the database.
"""

from __future__ import annotations

from datetime import date

from dashboard.fmt import esc

# A flat within this share of its market median is "about at its market".
NEAR_MARKET = 0.05

GRADE_TONE = {"A": "g", "B": "b", "C": "y", "D": "w"}


def _price_state(disc) -> str:
    """"cheap", "fair", "dear" or "none" (no benchmark)."""
    if disc is None:
        return "none"
    if disc >= NEAR_MARKET:
        return "cheap"
    if disc <= -NEAR_MARKET:
        return "dear"
    return "fair"


HEADLINES_EN = {
    ("cheap", False): "A good price on a flat that doesn't pay for itself.",
    ("cheap", True):  "A good price, and the flat pays for itself.",
    ("fair", False):  "A fair price, but the flat doesn't pay for itself.",
    ("fair", True):   "A fair price on a flat that pays for itself.",
    ("dear", False):  "Priced above its market, and it doesn't pay for itself.",
    ("dear", True):   "Priced above its market, though the rent covers the costs.",
    ("none", False):  "No market benchmark here, and the flat doesn't pay for itself.",
    ("none", True):   "No market benchmark here, but the flat pays for itself.",
}
HEADLINES_CZ = {
    ("cheap", False): "Dobrá cena u bytu, který se nezaplatí sám.",
    ("cheap", True):  "Dobrá cena a byt se zaplatí sám.",
    ("fair", False):  "Férová cena, ale byt se nezaplatí sám.",
    ("fair", True):   "Férová cena u bytu, který se zaplatí sám.",
    ("dear", False):  "Cena nad trhem a byt se nezaplatí sám.",
    ("dear", True):   "Cena nad trhem, přesto nájem pokryje náklady.",
    ("none", False):  "Bez srovnání s trhem a byt se nezaplatí sám.",
    ("none", True):   "Bez srovnání s trhem, ale byt se zaplatí sám.",
}


def headline(disc, surplus, cz: bool = False) -> str:
    """One sentence: the price against the market, and whether the flat pays
    for itself. `disc` is the discount to the market median (0.4 = 40 %
    under; None: no benchmark), `surplus` the monthly surplus (None: only
    the price is said)."""
    state = _price_state(disc)
    if surplus is None:
        words = {"cheap": ("A good price.", "Dobrá cena."),
                 "fair": ("A fair price.", "Férová cena."),
                 "dear": ("Priced above its market.", "Cena nad trhem."),
                 "none": ("No market benchmark for this district.", "Bez srovnání s trhem.")}
        return words[state][1 if cz else 0]
    return (HEADLINES_CZ if cz else HEADLINES_EN)[(state, surplus >= 0)]


def _cut_clause(cut_pct, cut_days, cz: bool) -> str:
    """"the price has already come down 7% in 9 days" — or nothing."""
    if not cut_pct or cut_pct >= 0:
        return ""
    n = f"{abs(cut_pct) * 100:.0f}"
    if n == "0":
        return ""
    if cz:
        return (f"cena už klesla o {n} % za {cut_days} dní" if cut_days
                else f"cena už klesla o {n} %")
    return (f"the price has already come down {n}% in {cut_days} days" if cut_days
            else f"the price has already come down {n}%")


def body(disc, surplus, struct: str, money, cz: bool = False,
         cut_pct=None, cut_days=None) -> str:
    """The paragraph under the headline: the numbers behind it."""
    state = _price_state(disc)
    clause = _cut_clause(cut_pct, cut_days, cz)
    cut = (f", a {clause}" if cz else f", and {clause}") if clause else ""
    parts = []
    if state != "none":
        n = f"{abs(disc) * 100:.0f}"
        if cz:
            where = {"cheap": f"{n} % pod mediánem trhu", "fair": "zhruba na mediánu trhu",
                     "dear": f"{n} % nad mediánem trhu"}[state]
            parts.append(f"Nabízí se {where}{cut}.")
        else:
            where = {"cheap": f"{n}% under its market median", "fair": "about at its market median",
                     "dear": f"{n}% over its market median"}[state]
            parts.append(f"It is listed {where}{cut}.")
    elif clause:
        parts.append(f"{clause[0].upper()}{clause[1:]}.")
    if surplus is not None:
        x = money(abs(surplus))
        if cz:
            parts.append(f"Při struktuře {struct} nájem pokryje všechny náklady a zbyde {x} měsíčně."
                         if surplus >= 0 else
                         f"Při struktuře {struct} stojí byt měsíčně o {x} víc, než přinese nájem.")
        else:
            who = "As an s.r.o." if struct == "s.r.o." else f"Under the {struct} structure"
            parts.append(f"{who} the rent covers every cost, with {x} a month left over."
                         if surplus >= 0 else
                         f"{who} it still costs {x} more each month than the rent brings in.")
    return " ".join(parts)


def days_between(first, last) -> int | None:
    """Whole days between two "YYYY-MM-DD…" dates; None when either is missing
    or unreadable."""
    try:
        a, b = date.fromisoformat(str(first)[:10]), date.fromisoformat(str(last)[:10])
    except ValueError:
        return None
    return max((b - a).days, 0)


def verdict_html(grade: str, score, disc, surplus, struct: str, money, cz: bool = False,
                 cut_pct=None, cut_days=None) -> str:
    """The verdict band: the grade as a square, the headline and the paragraph.
    Everything dynamic is escaped (the structure's name and the amounts come
    from the database and the formatters)."""
    tone = GRADE_TONE.get(grade, "w")
    letter = esc(grade if grade in GRADE_TONE else "–")
    pts = f"{esc(score)}/100" if grade in GRADE_TONE and score is not None else ""
    text = body(disc, surplus, struct, money, cz, cut_pct, cut_days)
    return (f'<div class="vd vd-{tone}">'
            f'<div class="vd-grade"><b>{letter}</b><span>{pts}</span></div>'
            f'<div class="vd-text"><div class="vd-head">{esc(headline(disc, surplus, cz))}</div>'
            + (f'<div class="vd-sub">{esc(text)}</div>' if text else "")
            + "</div></div>")


# ── D18: where the price sits among flats like it ─────────────────────────────
# Fewer comparable flats than this and a "cheapest to dearest" bar says little.
BAND_MIN_COMPS = 3


def price_band_html(per_m2: float | None, comps_per_m2, money_m2, area: str = "",
                    cz: bool = False) -> str:
    """A thin bar from the cheapest to the dearest price per m² of the flats
    like this one (offer_sheet.comparables: same market and benchmark area,
    a similar size), with their median and this flat marked, and the same in
    words, so the colour is never the only signal. "" with fewer than
    BAND_MIN_COMPS of them or no price per m². `money_m2(v)` formats a price
    per m² in the flat's currency."""
    others = sorted(float(c) for c in (comps_per_m2 or []) if c)
    if not per_m2 or len(others) < BAND_MIN_COMPS:
        return ""
    import statistics
    med = statistics.median(others)
    lo, hi = min(others[0], per_m2), max(others[-1], per_m2)
    span = (hi - lo) or 1.0

    def at(v):
        return f"{(v - lo) / span * 100:.1f}%"
    cheaper = sum(1 for o in others if o > per_m2)
    tone = ("good" if per_m2 <= med * (1 - NEAR_MARKET) else
            "bad" if per_m2 >= med * (1 + NEAR_MARKET) else "caution")
    where = f" ({esc(area)})" if area else ""
    if cz:
        words = (f"{esc(money_m2(per_m2))} — levnější než {cheaper} z {len(others)} podobných "
                 f"bytů{where}: {esc(money_m2(others[0]))} až {esc(money_m2(others[-1]))}, "
                 f"medián {esc(money_m2(med))}.")
    else:
        words = (f"{esc(money_m2(per_m2))} — cheaper than {cheaper} of {len(others)} similar "
                 f"flats{where}: {esc(money_m2(others[0]))} to {esc(money_m2(others[-1]))}, "
                 f"median {esc(money_m2(med))}.")
    return (f'<div class="pband" role="img" aria-label="{words}">'
            f'<div class="pband-track">'
            f'<span class="pband-med" style="left:{at(med)}"></span>'
            f'<span class="pband-me {tone}" style="left:{at(per_m2)}"></span></div>'
            f'<div class="pband-words">{words}</div></div>')

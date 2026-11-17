"""
modules/yearly.py — the jobs that come back every year, said inside the tool
instead of in an audit nobody re-reads.

The tax tables (config.TAX_YEAR_RULES, markets.CZ_TAX_YEAR_RULES) hold one
table per year. From 1 December, a market with no table for the coming year
gets a reminder to collect the figures; from 1 January, one with no table for
the new year gets a warning that scoring still uses last year's. The
dashboard shows them over the tabs; the Telegram message carries each once.
"""

from __future__ import annotations

from datetime import date

import markets

STEPS = (
    "1–10 December: on slov-lex.sk open Act 595/2003 as it reads from 1 January; note the "
    "tax bands, the subsistence minimum, the corporate and dividend rates and the minimum tax.",
    "nbs.sk and cnb.cz: the loan-to-value caps for the new year.",
    "Czechia: the inflation coefficient for property tax and the average wage that sets the "
    "23 % band (financnisprava.cz, zakonyprolidi.cz).",
    "Hand the figures, with their sources, to whoever maintains the code: the new year's "
    "table goes into config.TAX_YEAR_RULES (Slovakia) or markets.CZ_TAX_YEAR_RULES.",
    "2–10 January: 🏛️ UPDATE TAX RATES, review doubtful readings, then ♻️ RESCORE ALL.",
)


def _has_table(market: str, year: int) -> bool:
    try:
        return markets.tax_rules(year, market)["year"] == year
    except LookupError:
        return False


def reminders(today: date | None = None) -> list[dict]:
    """due() for today."""
    return due(today or date.today())


def due(today: date) -> list[dict]:
    """[{"key", "level", "market", "text"}] for each market's tax table that
    needs you on `today`: "info" in December for next year's, "warning" in
    January to March while this year's is missing."""
    out = []
    for m in markets.MARKET_CODES:
        name = markets.get(m).name
        if today.month == 12 and not _has_table(m, today.year + 1):
            out.append({"key": f"tax-table:{m}:{today.year + 1}:dec", "level": "info", "market": m,
                        "text": f"📅 December: collect the {today.year + 1} tax figures for "
                                f"{name} — on 1 January the tax tables run out."})
        elif not _has_table(m, today.year) and today.month <= 3:
            out.append({"key": f"tax-table:{m}:{today.year}:jan", "level": "warning", "market": m,
                        "text": f"📅 No {name} tax table for {today.year} yet: every score "
                                f"still uses {today.year - 1}'s bands and limits."})
    return out

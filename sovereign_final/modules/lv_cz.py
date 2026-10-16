"""
modules/lv_cz.py — the title-deed (LV, list vlastnictví) check for a Czech
listing. Same three verdicts as modules/debt_bot: PASS, REJECTED, UNVERIFIED.

Until the Czech cadastre (ČÚZK) lookup is wired in, every Czech listing is
UNVERIFIED — no title deed was read — never PASS.
"""

from __future__ import annotations

from contextlib import contextmanager

NAHLIZENI_URL = "https://nahlizenidokn.cuzk.gov.cz/"


def check_listing(row: dict) -> dict:
    return {"status": "UNVERIFIED", "raw": {},
            "detail": "No title deed read — the Czech cadastre (ČÚZK) check is "
                      "not wired in yet."}


def lv_link(listing: dict) -> str:
    """Where to read the flat's LV by hand: ČÚZK's nahlížení do katastru."""
    return NAHLIZENI_URL


@contextmanager
def quick_requests():
    yield

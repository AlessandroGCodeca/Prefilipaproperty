"""
scraper/rentals_cz.py — Czech rental (pronájem) listings for live rent comps.

Placeholder until the Czech rent sources are wired: it reads nothing, and
engine.rent_comps_cz has no live rate, so every Czech listing keeps the
baseline rent (engine.rent_cz).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def run(max_pages: int = 5) -> dict:
    log.info("ℹ️ Czech rent comps: no rental source wired yet — baseline rents apply.")
    return {"rentals": 0, "keys": 0, "changed": [], "rescored": 0}

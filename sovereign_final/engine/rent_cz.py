"""
engine/rent_cz.py — the Czech baseline rent table (Kč/m²/month) and how a
district resolves to one of its keys.

engine.financial delegates here for a Czech listing (market="cz"): the
Slovak RENT_PER_M2 keys and matching rules don't apply to Czech places.

The table is empty until a citable source fills it (see RENT_SOURCE). With
no entry for a place, and no "default", there is no rent to estimate: the
engine raises rather than guess, and the listing stays unscored.
"""

from __future__ import annotations

import re
import unicodedata

# Kč per m² per month for a bare (no services) unfurnished 2-room flat.
RENT_PER_M2_CZ: dict[str, float] = {}

RENT_SOURCE = {
    "source": "UNVERIFIED — no Czech rent table yet",
    "checked": None,
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _keys_by_specificity() -> list[str]:
    return sorted((k for k in RENT_PER_M2_CZ if k != "default"), key=len, reverse=True)


def match_rent_key(district: str) -> str:
    """The table key a Czech district string resolves to — the longest key
    found in it as whole words, with or without diacritics — or "default"."""
    folded = _fold(district or "").strip()
    if not folded:
        return "default"
    for key in _keys_by_specificity():
        if re.search(rf"(?<!\w){re.escape(_fold(key))}(?!\w)", folded):
            return key
    return "default"


def baseline_rent(key: str) -> float | None:
    """Kč/m² for a key, else the table's default; None when there is none."""
    return RENT_PER_M2_CZ.get(key) or RENT_PER_M2_CZ.get("default")


def rent_fallback_kind(key: str) -> str | None:
    """"default" when the rent is not the place's own figure, else None."""
    if not key or key == "default" or key not in RENT_PER_M2_CZ:
        return "default"
    return None

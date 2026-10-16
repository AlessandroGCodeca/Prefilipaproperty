"""
modules/risk_data_cz.py — Czech flood and noise sources for Location IQ.

modules/risk_data asks OpenStreetMap about construction and noise sources in
both markets; the flood map is national. Until a Czech flood source is wired
in, a Czech flat's flood answer is None ("unknown") — never a guessed "no".
"""

from __future__ import annotations


def check_flood(lat: float, lng: float) -> tuple[bool | None, str]:
    return None, "no Czech flood source configured yet"


def refine_noise(lat: float, lng: float, osm: dict) -> dict:
    """Nothing beyond the OpenStreetMap proxy yet."""
    return {}

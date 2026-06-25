"""
modules/llm_enrichment.py — Optional Claude-powered listing enrichment.

Three helpers that turn unstructured Slovak listing text into structured signals
the rest of the pipeline can use:

  1. parse_description()  — pull balcony/parking/floor/condition/furnished out of
                            a free-text description the scrapers already store.
  2. normalize_address()  — resolve a messy address_raw into {city, district, kraj}
                            so blank-district listings stop defaulting to €6.50/m².
  3. analyze_lv()         — structured, schema-validated LV title-deed risk read,
                            a more reliable replacement for the substring match in
                            modules/debt_bot.py.

Design rules:
  - The API key is read from config.ANTHROPIC_API_KEY, which loads it from the
    gitignored .env. It is never hard-coded and never logged or printed here.
  - Every helper degrades gracefully: if no key is set, or the `anthropic`
    package is missing, or the call fails, it returns None and the caller keeps
    its existing behaviour. Enrichment is additive, never load-bearing.
  - Structured outputs (output_config.format) guarantee the model returns JSON
    matching our schema, so callers can trust the shape without defensive parsing.

Run once per listing and cache the result — these fields don't change.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

# Lazily-constructed singleton client. Kept module-private so the key object
# never leaves this file.
_client = None


def is_enabled() -> bool:
    """True when a key is configured and the anthropic SDK is importable."""
    if not ANTHROPIC_API_KEY:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _get_client():
    """Return a cached Anthropic client, or None when enrichment is disabled.

    The key is passed straight from config to the SDK constructor and is never
    printed or returned anywhere in this module.
    """
    global _client
    if _client is not None:
        return _client
    if not is_enabled():
        return None
    import anthropic
    _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _ask_json(system: str, user: str, schema: dict, max_tokens: int = 1024) -> dict | None:
    """Single structured-output call. Returns the parsed dict, or None on any
    failure (disabled, network error, refusal, malformed output)."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            return None
        return json.loads(text)
    except Exception as e:
        # Never surface the key or raw client internals; a one-line note is enough.
        print(f"    ↳ llm_enrichment call failed: {type(e).__name__}")
        return None


# ── 1. Description feature extraction ─────────────────────────────────────────
_DESCRIPTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "balcony":   {"type": "boolean"},
        "terrace":   {"type": "boolean"},
        "loggia":    {"type": "boolean"},
        "parking":   {"type": "boolean"},  # garage OR dedicated parking spot
        "cellar":    {"type": "boolean"},
        "elevator":  {"type": "boolean"},
        "furnished": {"type": "string", "enum": ["furnished", "semi", "unfurnished", "unknown"]},
        "condition": {"type": "string",
                      "enum": ["new", "renovated", "good", "original", "poor", "unknown"]},
        # -1 means "not stated in the text" (JSON-schema integers can't be null here).
        "floor":           {"type": "integer"},
        "building_floors": {"type": "integer"},
        "rooms":           {"type": "integer"},  # 0 = not stated
    },
    "required": [
        "balcony", "terrace", "loggia", "parking", "cellar", "elevator",
        "furnished", "condition", "floor", "building_floors", "rooms",
    ],
}

_DESCRIPTION_SYSTEM = (
    "You extract structured facts from Slovak real-estate listing descriptions. "
    "Only report what the text states or clearly implies; never invent details. "
    "Use 'unknown' / -1 / 0 when a field is not mentioned. "
    "parking is true for any garage (garáž) or dedicated parking spot (parkovacie miesto). "
    "condition maps Slovak terms: novostavba=new, po rekonštrukcii=renovated, "
    "pôvodný stav=original, čiastočná rekonštrukcia/dobrý=good."
)


def parse_description(description: str) -> dict | None:
    """Extract structured features from a free-text (Slovak) description.

    Returns a dict matching _DESCRIPTION_SCHEMA, or None if disabled/failed.
    """
    description = (description or "").strip()
    if not description:
        return None
    return _ask_json(_DESCRIPTION_SYSTEM, f"DESCRIPTION:\n{description[:4000]}",
                     _DESCRIPTION_SCHEMA)


# ── 2. Address / district normalisation ───────────────────────────────────────
_ADDRESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "city":     {"type": "string"},   # "" if not determinable
        "district": {"type": "string"},   # municipal district / suburb, "" if none
        "kraj":     {"type": "string",
                     "enum": ["BA", "TT", "TN", "NR", "ZA", "BB", "PO", "KE", ""]},
    },
    "required": ["city", "district", "kraj"],
}

_ADDRESS_SYSTEM = (
    "You normalise messy Slovak property addresses into structured location data. "
    "Given a raw address string, return the city, the municipal district or suburb "
    "(e.g. Bratislava sub-districts like 'Ružinov', or '' if none), and the Slovak "
    "kraj (region) as a two-letter code: BA=Bratislavský, TT=Trnavský, TN=Trenčiansky, "
    "NR=Nitriansky, ZA=Žilinský, BB=Banskobystrický, PO=Prešovský, KE=Košický. "
    "Use '' for any field you cannot determine. Never guess a kraj from a postcode you "
    "are unsure about."
)


def normalize_address(address_raw: str) -> dict | None:
    """Resolve a raw address string into {city, district, kraj}.

    Returns a dict matching _ADDRESS_SCHEMA, or None if disabled/failed.
    """
    address_raw = (address_raw or "").strip()
    if not address_raw:
        return None
    return _ask_json(_ADDRESS_SYSTEM, f"RAW ADDRESS:\n{address_raw[:500]}",
                     _ADDRESS_SCHEMA, max_tokens=256)


# ── 3. LV title-deed risk analysis ────────────────────────────────────────────
_LV_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "risk_level":         {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]},
        "is_safe_to_proceed": {"type": "boolean"},
        "flags":              {"type": "array", "items": {"type": "string"}},
        "summary":            {"type": "string"},
    },
    "required": ["risk_level", "is_safe_to_proceed", "flags", "summary"],
}

_LV_SYSTEM = (
    "You are a Slovak real-estate legal analyst reviewing List Vlastníctva (LV) "
    "title-deed data. Identify encumbrances, liens, executions, lawsuits, or other "
    "legal risks. A záložné právo (lien) registered in favour of a recognised bank is "
    "normal for a mortgaged property and is LOW risk. A lien in favour of a private "
    "person/company (fyzická/právnická osoba), an exekúcia, konkurz, or súdny spor is "
    "HIGH risk. List each concrete issue in 'flags'. Set is_safe_to_proceed=false for "
    "any HIGH-risk non-bank encumbrance. Keep 'summary' concise and factual."
)


def analyze_lv(lv_text: str) -> dict | None:
    """Structured risk read of an LV title-deed document.

    Returns a dict matching _LV_SCHEMA, or None if disabled/failed. Intended as a
    more reliable, schema-validated alternative to the substring scan in debt_bot.
    """
    lv_text = (lv_text or "").strip()
    if not lv_text:
        return None
    return _ask_json(_LV_SYSTEM, f"LV DATA:\n{lv_text[:6000]}", _LV_SCHEMA)


if __name__ == "__main__":
    # Smoke test — prints whether enrichment is wired up, without revealing the key.
    print(f"llm_enrichment enabled: {is_enabled()}  model: {ANTHROPIC_MODEL}")
    if is_enabled():
        demo = parse_description(
            "3-izbový byt po kompletnej rekonštrukcii, 2. poschodie, s balkónom a "
            "pivnicou, výťah v dome, čiastočne zariadený."
        )
        print("demo parse_description ->", demo)

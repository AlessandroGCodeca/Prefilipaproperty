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
                            modules/debt_bot.py. It is sent part C (the
                            encumbrances) whole — see lv_text_for_claude().

Design rules:
  - The API key is read from config.ANTHROPIC_API_KEY, which loads it from the
    gitignored .env. It is never hard-coded and never logged or printed here.
  - Every helper degrades gracefully: if no key is set, or the `anthropic`
    package is missing, or the call fails, it returns None and the caller keeps
    its existing behaviour. Enrichment is additive, never load-bearing.
  - Structured outputs (output_config.format) guarantee the model returns JSON
    matching our schema, so callers can trust the shape without defensive parsing.
  - One model per task (config.ANTHROPIC_MODEL_BULK / ANTHROPIC_MODEL_LV): the
    bulk extraction runs at low effort on the small model, the LV read at high
    effort on the most capable one, with server-side refusal fallbacks.

Run once per listing and cache the result — these fields don't change.

In the daily run, many reads go out together through ask_json_many(): one
Message Batch at half the price (EF3, ANTHROPIC_BATCH). A batch can't carry
the LV read's refusal fallback, so a read the batch doesn't answer (refused,
failed, or still waiting after ANTHROPIC_BATCH_WAIT_MIN minutes, when the
batch is cancelled) is asked again on its own, exactly as before.
"""

import logging
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    ANTHROPIC_API_KEY, ANTHROPIC_BATCH, ANTHROPIC_BATCH_MIN, ANTHROPIC_BATCH_WAIT_MIN,
    ANTHROPIC_MODEL_ASK, ANTHROPIC_MODEL_BULK, ANTHROPIC_MODEL_LV, LV_SOFT_FLAGS_REJECT,
)

log = logging.getLogger(__name__)

# How much of an LV's parts A and B (the property and its owners) goes to
# Claude ahead of part C. A whole building's LV can list hundreds of
# co-owners; the encumbrances that decide anything are all in part C, which
# is always sent whole.
LV_HEAD_CHARS = 3000

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


def _params(system: str, user: str, schema: dict, model: str, effort: str,
            max_tokens: int) -> dict:
    """One request's Messages API parameters (without the refusal fallback)."""
    return dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
    )


def _answer(message) -> dict | None:
    """The JSON a reply carries; None for a refusal or no text."""
    if message.stop_reason == "refusal":
        return None
    text = next((b.text for b in message.content if b.type == "text"), None)
    return json.loads(text) if text else None


def _ask_json(system: str, user: str, schema: dict, *, model: str = ANTHROPIC_MODEL_BULK,
              effort: str = "low", max_tokens: int = 4096,
              fallbacks: bool = False) -> dict | None:
    """Single structured-output call. Returns the parsed dict, or None on any
    failure (disabled, network error, refusal, malformed output).

    max_tokens leaves room for the model's thinking ahead of the JSON.
    fallbacks=True lets the API re-run a request the model declines on its
    recommended fallback model (server-side, Claude API only); a decline that
    still stands comes back as a refusal and returns None like any failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        kwargs = _params(system, user, schema, model, effort, max_tokens)
        if fallbacks:
            resp = client.beta.messages.create(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resp = client.messages.create(**kwargs)
        return _answer(resp)
    except Exception as e:
        # Never surface the key or raw client internals; a one-line note is enough.
        log.warning(f"    ↳ llm_enrichment call failed: {type(e).__name__}")
        return None


# ── Many reads at once: a Message Batch (EF3) ─────────────────────────────────
BATCH_POLL_S = 20
# How long a cancelled batch gets to wind down before its answers are read.
BATCH_CANCEL_WAIT_S = 120
_sleep, _clock = time.sleep, time.monotonic       # replaced in tests


def _ask_each(requests: list[dict]) -> list:
    return [_ask_json(**r) for r in requests]


def ask_json_many(requests: list[dict], batch: bool = True) -> list:
    """_ask_json for each of `requests` (dicts of its arguments), answers in
    the same order. With `batch` (and ANTHROPIC_BATCH on, and at least
    ANTHROPIC_BATCH_MIN of them) they go out as one Message Batch at half the
    price, and the call waits for it, at most ANTHROPIC_BATCH_WAIT_MIN
    minutes; a batch still running then is cancelled (requests it hadn't
    started aren't billed). Whatever the batch doesn't answer (an error, a
    cancel, an expiry, or a refused read that has a fallback) is asked on its
    own, so the answers are what one-by-one calls would give."""
    client = _get_client()
    if client is None:
        return [None] * len(requests)
    if not (batch and ANTHROPIC_BATCH) or len(requests) < max(ANTHROPIC_BATCH_MIN, 1):
        return _ask_each(requests)
    began = _clock()
    try:
        made = client.messages.batches.create(requests=[
            {"custom_id": f"r{i}",
             "params": _params(r["system"], r["user"], r["schema"],
                               r.get("model", ANTHROPIC_MODEL_BULK), r.get("effort", "low"),
                               r.get("max_tokens", 4096))}
            for i, r in enumerate(requests)])
        deadline = began + ANTHROPIC_BATCH_WAIT_MIN * 60
        status = made.processing_status
        cancelled = False
        while status != "ended":
            now = _clock()
            if not cancelled and now >= deadline:
                client.messages.batches.cancel(made.id)
                cancelled, deadline = True, now + BATCH_CANCEL_WAIT_S
            elif cancelled and now >= deadline:
                raise TimeoutError("the cancelled batch didn't wind down")
            _sleep(min(BATCH_POLL_S, max(deadline - now, 1)))
            status = client.messages.batches.retrieve(made.id).processing_status
        answers: list = [None] * len(requests)
        again = set(range(len(requests)))
        for item in client.messages.batches.results(made.id):
            i = int(item.custom_id[1:])
            if item.result.type != "succeeded":
                continue                                   # asked again below
            message = item.result.message
            if message.stop_reason == "refusal" and requests[i].get("fallbacks"):
                continue                                   # with its fallback, below
            try:
                answers[i] = _answer(message)
            except ValueError:
                continue
            again.discard(i)
    except Exception as e:
        log.warning(f"    ↳ batch failed ({type(e).__name__}): asking one by one")
        return _ask_each(requests)
    for i in sorted(again):
        answers[i] = _ask_json(**requests[i])
    took = (_clock() - began) / 60
    log.info(f"    ↳ batch of {len(requests)} at half price: {len(requests) - len(again)} "
             f"answered in {took:.0f} min"
             + (f", {len(again)} asked one by one" if again else ""))
    return answers


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


# A Czech listing (market "cz") is described in Czech, with Czech terms for
# the same facts.
_DESCRIPTION_SYSTEM_CZ = (
    "You extract structured facts from Czech real-estate listing descriptions. "
    "Only report what the text states or clearly implies; never invent details. "
    "Use 'unknown' / -1 / 0 when a field is not mentioned. "
    "parking is true for any garage (garáž) or dedicated parking space "
    "(parkovací stání, parkovací místo). rooms is the number before '+' in a "
    "Czech layout (2+kk and 2+1 are both 2). "
    "condition maps Czech terms: novostavba=new, po rekonstrukci=renovated, "
    "původní stav=original, velmi dobrý/dobrý stav/částečná rekonstrukce=good, "
    "před rekonstrukcí/špatný stav=poor."
)


def description_request(description: str, market: str = "sk") -> dict | None:
    """parse_description's request (ask_json_many takes a list); None for an
    empty description."""
    description = (description or "").strip()
    if not description:
        return None
    system = _DESCRIPTION_SYSTEM if market == "sk" else _DESCRIPTION_SYSTEM_CZ
    return {"system": system, "user": f"DESCRIPTION:\n{description[:4000]}",
            "schema": _DESCRIPTION_SCHEMA}


def parse_description(description: str, market: str = "sk") -> dict | None:
    """Extract structured features from a free-text (Slovak, or for market
    "cz" Czech) description.

    Returns a dict matching _DESCRIPTION_SCHEMA, or None if disabled/failed.
    """
    request = description_request(description, market)
    return _ask_json(**request) if request else None


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


def _address_schema_cz() -> dict:
    from engine.regional_prices_cz import KRAJ_NAMES
    return {**_ADDRESS_SCHEMA, "properties": {
        **_ADDRESS_SCHEMA["properties"],
        "kraj": {"type": "string", "enum": [*KRAJ_NAMES, ""]}}}


def _address_system_cz() -> str:
    from engine.regional_prices_cz import KRAJ_NAMES
    return (
        "You normalise messy Czech property addresses into structured location data. "
        "Given a raw address string, return the municipality (obec), the city part or "
        "district (e.g. 'Praha 2', 'Brno-střed', 'Ostrava-Poruba', or '' if none), and "
        "the Czech kraj (region) as a code: "
        + ", ".join(f"{code}={name}" for code, name in KRAJ_NAMES.items())
        + ". Use '' for any field you cannot determine. Never guess a kraj from a "
          "postcode you are unsure about.")


def address_request(address_raw: str, market: str = "sk") -> dict | None:
    """normalize_address's request; None for an empty address."""
    address_raw = (address_raw or "").strip()
    if not address_raw:
        return None
    if market != "sk":
        return {"system": _address_system_cz(), "user": f"RAW ADDRESS:\n{address_raw[:500]}",
                "schema": _address_schema_cz(), "max_tokens": 2048}
    return {"system": _ADDRESS_SYSTEM, "user": f"RAW ADDRESS:\n{address_raw[:500]}",
            "schema": _ADDRESS_SCHEMA, "max_tokens": 2048}


def normalize_address(address_raw: str, market: str = "sk") -> dict | None:
    """Resolve a raw address string into {city, district, kraj} — a Slovak
    one, or for market "cz" a Czech one (Czech kraj codes).

    Returns a dict matching _ADDRESS_SCHEMA, or None if disabled/failed.
    """
    request = address_request(address_raw, market)
    return _ask_json(**request) if request else None


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

_SOFT_POLICY = (
    "Treat them as HIGH risk and set is_safe_to_proceed=false: the owner rejects "
    "every easement and pre-emption right."
    if LV_SOFT_FLAGS_REJECT else
    "List them in 'flags' and rate them no higher than MEDIUM; on their own they "
    "do not make the purchase unsafe."
)
_LV_SYSTEM = (
    "You are a Slovak real-estate legal analyst reviewing List Vlastníctva (LV) "
    "title-deed data for someone buying the flat to let it. Identify encumbrances, "
    "liens, executions, lawsuits, or other legal risks; part C (ŤARCHY) and the "
    "notes after it are given in full, parts A and B may be shortened. A záložné "
    "právo (lien) registered in favour of a recognised bank is normal for a "
    "mortgaged property and is LOW risk. A lien in favour of a private "
    "person/company (fyzická/právnická osoba), an exekúcia, konkurz, or súdny spor is "
    "HIGH risk. So is a vecné bremeno giving someone a lifetime right to use or live "
    "in the flat (doživotné právo užívania / bývania), and a predkupné právo held by "
    "a private person or company. A technical vecné bremeno (utility lines, pipes, "
    "access or right of way) and a predkupné právo of the state or a municipality "
    f"are soft issues. {_SOFT_POLICY} List each concrete issue in 'flags'. Set "
    "is_safe_to_proceed=false for any HIGH-risk encumbrance. Keep 'summary' concise "
    "and factual."
)


_LV_SYSTEM_CZ = (
    "You are a Czech real-estate legal analyst reviewing a výpis z listu "
    "vlastnictví (LV) from the Czech katastr nemovitostí for someone buying the "
    "flat to let it. Identify encumbrances and legal risks. Part C (věcná práva "
    "zatěžující nemovitosti, formerly omezení vlastnického práva) and part D "
    "(poznámky) are given in full; part B1 lists rights that BENEFIT this flat, "
    "not burdens on it. A zástavní právo, or a zákaz zcizení nebo zatížení, in "
    "favour of a recognised bank or stavební spořitelna is normal for a mortgaged "
    "flat and is LOW risk. A zástavní právo in favour of a private person or "
    "company, an exekuce, an insolvence / úpadek, a výkon rozhodnutí, or a "
    "poznámka spornosti / soudní spor is HIGH risk. So is a věcné břemeno "
    "(služebnost) giving someone a lifetime right to use or live in the flat "
    "(doživotní užívání, výměnek), and a předkupní právo held by a private person "
    "or company. So are a registered nájem or pacht, a výhrada zpětné koupě, a "
    "výhrada vlastnického práva or práva lepšího kupce, a koupě na zkoušku, an "
    "užívací právo, and a zajišťovací převod práva or a zákaz zcizení nebo "
    "zatížení not in favour of a bank. A technical věcné břemeno (utility lines, "
    "pipes, access or right of way) and a předkupní právo of the state, a kraj or "
    f"a municipality are soft issues. {_SOFT_POLICY} A plomba (a change of rights "
    "pending in the cadastre) "
    "is at least MEDIUM. List each concrete issue in 'flags'. Set "
    "is_safe_to_proceed=false for any HIGH-risk encumbrance. Keep 'summary' concise "
    "and factual."
)


def lv_text_for_claude(lv_text, market: str = "sk") -> tuple[str, bool]:
    """(the LV text analyze_lv sends, whether it holds all of part C).

    The report lists the encumbrances (ťarchy, part C) last, so the old
    6,000-character cut left Claude reading owners and parcels on any long LV.
    Now part C and everything after it go whole; parts A and B before it are
    shortened to LV_HEAD_CHARS when the text is long. Without a recognisable
    part C heading the whole text goes. The text holds all of part C unless the
    cadastre report was itself cut at the scraper's cap — and only then may a
    "safe" from Claude not overrule the screen (modules/debt_bot._decide_lv).
    """
    from kataster_scraper import LV_TEXT_MAX_CHARS
    if market == "sk":
        from modules.lv_screen import part_c_start
        raw = str(lv_text or "")
    else:
        from modules.lv_screen_cz import part_c_start, parts_c_d_whole, _norm
        raw = _norm(lv_text)
    # Judged before stripping: a report cut at the cap just after a space is
    # still a cut report. A Czech výpis is pasted by hand — it holds parts C–D
    # whole only if it runs on to part E's heading (page 1 of 2 does not).
    complete = (len(raw) < LV_TEXT_MAX_CHARS if market == "sk"
                else parts_c_d_whole(raw))
    text = raw.strip()
    start = part_c_start(text)
    if start is not None and start > LV_HEAD_CHARS:
        text = text[:LV_HEAD_CHARS] + "\n[… parts A and B shortened …]\n" + text[start:]
    return text, complete


def lv_request(lv_text: str, market: str = "sk") -> dict | None:
    """analyze_lv's request; None for an empty text."""
    lv_text = (lv_text or "").strip()
    if not lv_text:
        return None
    excerpt, _ = lv_text_for_claude(lv_text, market)
    return {"system": _LV_SYSTEM if market == "sk" else _LV_SYSTEM_CZ,
            "user": f"LV DATA:\n{excerpt}", "schema": _LV_SCHEMA,
            "model": ANTHROPIC_MODEL_LV, "effort": "high", "max_tokens": 16000,
            "fallbacks": True}


def analyze_lv(lv_text: str, market: str = "sk") -> dict | None:
    """Structured risk read of an LV title-deed document.

    Returns a dict matching _LV_SCHEMA, or None if disabled/failed. Intended as a
    more reliable, schema-validated alternative to the substring scan in debt_bot.
    """
    request = lv_request(lv_text, market)
    return _ask_json(**request) if request else None


# ── 4. A question about one flat (UX7) ───────────────────────────────────────
_ASK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "figures_used": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
            "required": ["name", "value"]}},
        "answerable": {"type": "boolean"},
    },
    "required": ["answer", "figures_used", "answerable"],
}

_ASK_SYSTEM = (
    "You answer a property investor's question about one flat for sale, using only the "
    "figures and the ad text in the JSON you are given: the dashboard's own model of the flat "
    "(money is in the 'currency' given, monthly unless a name says otherwise). Work out what "
    "the figures allow, show the arithmetic in a sentence, and say plainly when they don't "
    "answer the question (answerable false) instead of guessing. Three to six sentences, in "
    "the language of the question. List every figure you used, by its name in the JSON and "
    "its value. You are not giving financial, tax or legal advice: where the question needs "
    "an adviser, say which one."
)


def ask_about_flat(question: str, facts: dict) -> dict | None:
    """Claude's answer to `question` from one flat's `facts` (the card's own
    figures): {answer, figures_used: [{name, value}], answerable}, or None
    when disabled, refused or failed."""
    question = (question or "").strip()[:500]
    if not question:
        return None
    return _ask_json(_ASK_SYSTEM,
                     "FLAT:\n" + json.dumps(facts, ensure_ascii=False, default=str)
                     + "\n\nQUESTION:\n" + question,
                     _ASK_SCHEMA, model=ANTHROPIC_MODEL_ASK, effort="medium",
                     max_tokens=8000, fallbacks=True)


if __name__ == "__main__":
    # Smoke test — prints whether enrichment is wired up, without revealing the key.
    print(f"llm_enrichment enabled: {is_enabled()}  models: bulk {ANTHROPIC_MODEL_BULK}, "
          f"LV {ANTHROPIC_MODEL_LV}")
    if is_enabled():
        demo = parse_description(
            "3-izbový byt po kompletnej rekonštrukcii, 2. poschodie, s balkónom a "
            "pivnicou, výťah v dome, čiastočne zariadený."
        )
        print("demo parse_description ->", demo)

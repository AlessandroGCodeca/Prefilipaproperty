"""
modules/doc_reader.py — documents with no text layer, read by Claude: a
scanned PDF (a town's tax ordinance, an auction announcement) or a photo (an
LV the agent sent from a phone).

Claude reads PDF pages and images directly (a base64 "document" or "image"
block). Each call goes through modules/llm_enrichment's structured-output
helper, so it needs ANTHROPIC_API_KEY and does nothing without it. A call is
made only for a document that has no text of its own, and for one you asked
for (an upload, a button) — except the automated tax-ordinance runs, which
read scans only when TAX_SCANS_WITH_CLAUDE=1 (it costs a few cents a page).

Files over MAX_BYTES are not sent: the request limit is 32 MB, and base64
grows a file by a third.
"""

from __future__ import annotations

import base64
import logging
import os

log = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"GIF8": "image/gif"}


def enabled() -> bool:
    from modules.llm_enrichment import is_enabled
    return is_enabled()


def scans_in_automated_runs() -> bool:
    """TAX_SCANS_WITH_CLAUDE=1: the daily and button-started tax-rate runs
    also send scanned ordinances to Claude."""
    return (os.getenv("TAX_SCANS_WITH_CLAUDE") or "").strip().lower() in ("1", "true", "yes")


def media_type(content: bytes) -> str | None:
    """The file's type as Claude takes it: a PDF or a JPEG/PNG/GIF/WebP
    image; None for anything else (HEIC from an iPhone included — export it
    as JPEG)."""
    if content[:5] == b"%PDF-":
        return "application/pdf"
    for magic, kind in IMAGE_TYPES.items():
        if content.startswith(magic):
            return kind
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _block(content: bytes, kind: str) -> dict:
    data = base64.standard_b64encode(content).decode("ascii")
    return {"type": "document" if kind == "application/pdf" else "image",
            "source": {"type": "base64", "media_type": kind, "data": data}}


def ask(content: bytes, system: str, instruction: str, schema: dict,
        max_tokens: int = 16000) -> dict | None:
    """Send the file with `instruction` and get JSON matching `schema` back;
    None when Claude is off, the file is not a PDF or image, too large, or
    the call failed."""
    kind = media_type(content)
    if not kind or len(content) > MAX_BYTES or not enabled():
        return None
    from config import ANTHROPIC_MODEL_LV
    from modules.llm_enrichment import _ask_json
    return _ask_json(system, [_block(content, kind), {"type": "text", "text": instruction}],
                     schema, model=ANTHROPIC_MODEL_LV, effort="medium",
                     max_tokens=max_tokens, fallbacks=True)


_TEXT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"readable": {"type": "boolean"}, "text": {"type": "string"}},
    "required": ["readable", "text"],
}
_TRANSCRIBE_SYSTEM = (
    "You transcribe scanned Slovak and Czech official documents into plain text. Copy the "
    "text exactly as written, in its own language, with its numbers, units and section "
    "numbers; keep tables row by row. Do not translate, summarise or correct anything. "
    "If the document cannot be read, set readable to false.")


def transcribe(content: bytes, what: str = "an official document") -> str | None:
    """The document's text, copied by Claude; None when it couldn't be read."""
    got = ask(content, _TRANSCRIBE_SYSTEM, f"Transcribe this scan of {what}.", _TEXT_SCHEMA)
    if not got or not got.get("readable") or not (got.get("text") or "").strip():
        return None
    return got["text"]


_LV_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "is_title_deed": {"type": "boolean"},
        "lv_number": {"type": "string"},
        "cadastral_area": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["is_title_deed", "lv_number", "cadastral_area", "text"],
}
_LV_SYSTEM = (
    "You read photos and scans of Slovak and Czech title deeds (list vlastníctva / list "
    "vlastnictví, LV). Transcribe the whole deed exactly, in its own language, keeping its "
    "parts (A, B, C, D) and entry numbers; do not summarise, translate or correct. Give the "
    "LV number and the cadastral area (katastrálne územie / katastrální území) as printed, "
    "or an empty string when not shown. If it is not a title deed, set is_title_deed to "
    "false.")


def read_title_deed(content: bytes) -> dict | None:
    """{"text", "lv_number", "cadastral_area"} from a photo or scan of an LV;
    None when Claude is off or it is not an LV."""
    got = ask(content, _LV_SYSTEM, "Read this title deed.", _LV_SCHEMA)
    if not got or not got.get("is_title_deed") or not (got.get("text") or "").strip():
        return None
    return {k: (got.get(k) or "").strip() for k in ("text", "lv_number", "cadastral_area")}

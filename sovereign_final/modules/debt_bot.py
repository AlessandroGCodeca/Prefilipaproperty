"""
modules/debt_bot.py — Sovereign Investor Dashboard
Module D: LV (List Vlastníctva) Debt-Bot

Hard stop: any non-bank lien, execution, or lawsuit = instant REJECTED.

Decision layers (most reliable first):
  1. Claude analyze_lv() — schema-validated risk read, authoritative when an
     ANTHROPIC_API_KEY is set and real LV text is available. It reliably tells a
     normal bank záložné právo apart from a private lien / exekúcia / konkurz,
     which the substring scan often gets wrong.
  2. Substring scan (query_lv_api/_parse_lv) — the always-on baseline and the
     fallback whenever Claude is disabled, has no LV text, or is unsure.
Optional: DMR (Mistral) for a fully-local plain-language summary.
"""

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    LV_REJECT_FLAGS, LV_BANK_NAMES, DMR_ENDPOINT, LLM_MODEL,
)
from database import (
    get_pending_lv, set_lv_status, set_lv_analysis, reset_demo_rejections,
    get_conn, init_db,
)
from kataster_scraper import enrich_parcel
from modules.llm_enrichment import is_enabled as claude_enabled, analyze_lv as claude_analyze_lv


# ── Cadastre lookup (unofficial scraper — no API/key exists) ─────────────────
def query_lv_api(cadastral_id: str, area: str = "") -> dict:
    """
    Fetch and screen the LV (list vlastníctva) for a parcel via the unofficial
    skgeodesy.sk scraper (kataster_scraper.enrich_parcel). There is NO official
    ÚGKK SR API and no API key — the scraper reads the cadastre portal's OData
    backend directly, throttles and retries internally, caches results in the
    cadastre_cache table, and may break if the portal changes.

    When the check CANNOT run (listing has no cadastral area / parcel number —
    scrapers don't provide them — or the portal is unreachable or the parcel
    isn't found), the listing PASSES as "unverified" rather than being
    rejected. The old behaviour fabricated demo rejections here; because every
    parcel-less listing shared the same fallback hash seed, one scheduler run
    marked EVERY listing REJECTED and emptied the dashboard. Never fabricate a
    title-deed verdict.
    """
    if not cadastral_id or not area:
        return {
            "status": "PASS", "unverified": True,
            "detail": "LV unverified — listing has no cadastral area / parcel "
                      "number. Verify the title deed manually before purchase.",
            "raw": {},
        }

    result = enrich_parcel(area, cadastral_id)

    if result["status"] != "OK":
        return {
            "status": "PASS", "unverified": True,
            "detail": f"LV unverified — cadastre lookup "
                      f"{result['status'].lower()}: {result['detail']} "
                      f"Verify the title deed manually before purchase.",
            "raw": {},
        }

    lv_text = result.get("lv_text")
    if not lv_text:
        # Parcel exists but no LV text (e.g. no folio attached) — nothing to
        # screen, so pass unverified rather than invent a verdict.
        return {
            "status": "PASS", "unverified": True,
            "detail": f"LV unverified — {result['detail']}. Verify the title "
                      f"deed manually before purchase.",
            "raw": {},
        }

    decision = _parse_lv(lv_text)
    lv_no = (result.get("lv") or {}).get("no")
    if lv_no is not None:
        decision["detail"] = f"LV {lv_no}: {decision['detail']}"
    return decision


def _parse_lv(lv_text) -> dict:
    """Substring-scan LV text (or any raw payload) for reject flags. `raw`
    carries the scanned payload through to _decide_lv, where Claude reads it."""
    raw = str(lv_text).lower()
    for flag in LV_REJECT_FLAGS:
        if flag in raw:
            is_bank = any(b in raw for b in LV_BANK_NAMES)
            if not is_bank:
                return {"status": "REJECT", "flag": flag,
                        "detail": f"LV encumbrance detected: '{flag}'",
                        "raw": lv_text}
    return {"status": "PASS", "detail": "Clean title — no non-bank encumbrances",
            "raw": lv_text}


# ── DMR LLM Analysis ──────────────────────────────────────────────────────────
def llm_analyse_lv(lv_text: str) -> dict:
    """
    Use local Mistral (Docker Model Runner) to analyse LV document text.
    Returns plain-language summary and risk level.
    Data stays fully local — never sent externally.

    Optional, privacy-first alternative to the Claude path in _decide_lv: the
    PASS/REJECT decision uses Claude when ANTHROPIC_API_KEY is set, but callers
    that must keep sensitive LV data on-prem can use this for a local summary.
    """
    try:
        resp = requests.post(
            f"{DMR_ENDPOINT}/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "You are a Slovak real estate legal analyst. "
                        "Analyse the following List Vlastníctva (LV) title deed data. "
                        "Identify any encumbrances, liens, executions, or legal risks. "
                        "Respond in JSON with keys: summary (string), risk_level (LOW/MEDIUM/HIGH), "
                        "flags (array of strings). Be concise and precise."
                    )},
                    {"role": "user", "content": f"LV DATA:\n{lv_text[:3000]}"},
                ],
                "max_tokens": 400,
            },
            timeout=30,
        )
        content = resp.json()["choices"][0]["message"]["content"]
        import json
        try:
            parsed = json.loads(content)
            return {
                "llm_analysis":   parsed.get("summary", content),
                "llm_risk_level": parsed.get("risk_level", "MEDIUM"),
            }
        except json.JSONDecodeError:
            return {"llm_analysis": content, "llm_risk_level": "MEDIUM"}
    except Exception as e:
        return {"llm_analysis": f"DMR unavailable: {e}", "llm_risk_level": "UNKNOWN"}


# ── Unified LV decision (Claude-authoritative, substring fallback) ────────────
def _decide_lv(api_result: dict) -> dict:
    """Refine a raw query_lv_api result with Claude's structured LV analysis.

    The substring scan in `api_result` is the baseline. When Claude enrichment
    is enabled AND we have real LV text (`raw`), its schema-validated read is
    authoritative: it can both REJECT something the substring scan missed and
    PASS a normal bank lien the substring scan would wrongly flag. Claude's
    summary/risk_level/flags are merged in for transparency.

    Degrades gracefully — returns the original substring decision untouched when
    Claude is disabled, there's no LV text, the call fails, or it returns an
    UNKNOWN risk level. So the hard-stop safety net is never weaker than before.
    """
    if not claude_enabled():
        return api_result
    raw = api_result.get("raw")
    if not raw:
        return api_result

    analysis = claude_analyze_lv(str(raw))
    if not analysis or analysis.get("risk_level") == "UNKNOWN":
        return api_result  # fall back to the substring decision

    flags = analysis.get("flags") or []
    summary = (analysis.get("summary") or "").strip()
    level = analysis.get("risk_level")
    note = f"[Claude {level}] {summary}".strip()

    decided = {
        "raw": raw,
        "llm_risk_level": level,
        "llm_analysis": summary,
        "llm_flags": flags,
    }
    if not analysis.get("is_safe_to_proceed") or level == "HIGH":
        decided.update({
            "status": "REJECT",
            "flag": flags[0] if flags else "LV_RISK",
            "detail": note or api_result.get("detail", "LV risk flagged by Claude"),
        })
    else:
        decided.update({
            "status": "PASS",
            "detail": note or api_result.get("detail", "Clean title"),
        })
    return decided


# ── Main Runner ───────────────────────────────────────────────────────────────
def run_debt_filter(progress_callback=None) -> tuple[int, int]:
    # Heal rows the old demo mode fabricated: "[DEMO]" rejections hid real
    # listings behind invented liens. Reset them to PENDING so they get an
    # honest re-check below. Idempotent — a clean DB is a no-op.
    healed = reset_demo_rejections()
    if healed:
        print(f"♻️  Reset {healed} fabricated [DEMO] rejections back to PENDING.")

    pending = get_pending_lv()
    if not pending:
        print("✅ No pending LV checks.")
        return 0, 0

    print(f"🔒 Running LV debt filter on {len(pending)} listings...")
    passed = rejected = unverified = 0

    for i, row in enumerate(pending):
        lid   = row["id"]
        cid   = row.get("cadastral_number", "")
        area  = row.get("cadastral_area", "")
        addr  = row.get("address_raw", "")[:55]

        if progress_callback:
            progress_callback(i + 1, len(pending), addr)

        result = query_lv_api(cid, area)
        # Claude-authoritative refinement (no-op when disabled / no LV text).
        result = _decide_lv(result)

        # Persist Claude's risk read (when it ran) for the dashboard.
        if result.get("llm_risk_level"):
            set_lv_analysis(lid, result["llm_risk_level"], result.get("llm_analysis", ""))

        if result["status"] == "REJECT":
            set_lv_status(lid, "REJECTED", result.get("flag","DEBT_FLAG"), result["detail"])
            rejected += 1
            print(f"  ❌ {addr} — {result['detail']}")
        else:
            set_lv_status(lid, "PASS")
            passed += 1
            if result.get("unverified"):
                unverified += 1
            else:
                print(f"  ✅ {addr}")

        # No pause needed here — kataster_scraper throttles its own requests
        # (CADASTRAL_DELAY_SEC) and cache hits shouldn't wait at all.

    if unverified:
        print(f"  ℹ️  {unverified} passed UNVERIFIED (no cadastral key/parcel) — "
              f"verify title deeds manually before purchase.")
    print(f"\n✅ LV filter complete. Passed: {passed} | Rejected: {rejected}\n")
    return passed, rejected


def reverify(listing_id: str) -> dict:
    """Force re-check single listing LV. Call before committing to purchase."""
    conn = get_conn()
    row  = conn.execute(
        "SELECT cadastral_number, cadastral_area FROM listings WHERE id=?",
        (listing_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"status": "ERROR", "detail": "Not found"}
    result = query_lv_api(row[0] or "", row[1] or "")
    result = _decide_lv(result)
    if result.get("llm_risk_level"):
        set_lv_analysis(listing_id, result["llm_risk_level"], result.get("llm_analysis", ""))
    status = "REJECTED" if result["status"] == "REJECT" else "PASS"
    set_lv_status(listing_id, status,
                  result.get("flag",""), result.get("detail",""),
                  module="debt_bot_reverify")
    return result


if __name__ == "__main__":
    init_db()
    run_debt_filter()

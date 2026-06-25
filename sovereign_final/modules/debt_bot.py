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

import time, uuid, random
from datetime import datetime, timezone

import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    CADASTRAL_API_KEY, CADASTRAL_DELAY_SEC, CADASTRAL_BACKOFF_MAX,
    LV_REJECT_FLAGS, LV_BANK_NAMES, DMR_ENDPOINT, LLM_MODEL,
)
from database import get_pending_lv, set_lv_status, set_lv_analysis, get_conn, init_db
from modules.llm_enrichment import is_enabled as claude_enabled, analyze_lv as claude_analyze_lv

CADASTRAL_BASE = "https://kataster.skgeodesy.sk/PortalOGC/rest/services/vgi_kn"


# ── Cadastral API ─────────────────────────────────────────────────────────────
def query_lv_api(cadastral_id: str, area: str = "") -> dict:
    """
    Query Slovak Cadastral API for LV data.
    Falls back to DEMO mode if no API key configured.
    Register at: https://www.skgeodesy.sk/en/ugkk/cadastral-portal/
    """
    if not CADASTRAL_API_KEY or not cadastral_id:
        return _demo_lv(cadastral_id)

    url     = f"{CADASTRAL_BASE}/lv/{cadastral_id}"
    headers = {"Authorization": f"Bearer {CADASTRAL_API_KEY}",
               "Accept": "application/json"}
    backoff = 2

    for attempt in range(5):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                wait = min(backoff + random.uniform(0, 1), CADASTRAL_BACKOFF_MAX)
                print(f"    Rate limited. Waiting {wait:.1f}s...")
                time.sleep(wait)
                backoff = min(backoff * 2, CADASTRAL_BACKOFF_MAX)
                continue
            resp.raise_for_status()
            return _parse_lv(resp.json())
        except requests.RequestException as e:
            print(f"    LV API error (attempt {attempt+1}): {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, CADASTRAL_BACKOFF_MAX)

    return {"status": "UNKNOWN", "detail": "API unavailable"}


def _parse_lv(data: dict) -> dict:
    raw = str(data).lower()
    for flag in LV_REJECT_FLAGS:
        if flag in raw:
            is_bank = any(b in raw for b in LV_BANK_NAMES)
            if not is_bank:
                return {"status": "REJECT", "flag": flag,
                        "detail": f"LV encumbrance detected: '{flag}'",
                        "raw": data}
    return {"status": "PASS", "detail": "Clean title — no non-bank encumbrances",
            "raw": data}


def _demo_lv(cadastral_id: str) -> dict:
    """Deterministic demo results — 30% rejection rate."""
    seed = sum(ord(c) for c in (cadastral_id or "demo_seed_1234"))
    if seed % 10 < 3:
        flags = [
            ("záložné právo",  "Non-bank lien detected — private creditor"),
            ("exekúcia",       "Court execution order registered on title"),
            ("predkupné právo","3rd-party pre-emption right registered"),
        ]
        flag, detail = flags[seed % 3]
        return {"status": "REJECT", "flag": flag,
                "detail": f"[DEMO] {detail}", "raw": {}}
    return {"status": "PASS", "detail": "[DEMO] Clean title — no encumbrances", "raw": {}}


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
    pending = get_pending_lv()
    if not pending:
        print("✅ No pending LV checks.")
        return 0, 0

    print(f"🔒 Running LV debt filter on {len(pending)} listings...")
    passed = rejected = 0

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
            print(f"  ✅ {addr}")

        time.sleep(CADASTRAL_DELAY_SEC)

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

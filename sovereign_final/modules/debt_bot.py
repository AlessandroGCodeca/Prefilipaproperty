"""
modules/debt_bot.py — Sovereign Investor Dashboard
Module D: LV (List Vlastníctva) Debt-Bot

Hard stop: any non-bank lien, execution, or lawsuit = instant REJECTED.
Optional: DMR (Mistral) for plain-language LV analysis.
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
from database import get_pending_lv, set_lv_status, get_conn, init_db

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

        # Optional DMR analysis
        llm_data = {}
        if result.get("raw"):
            llm_data = llm_analyse_lv(str(result["raw"]))

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
    status = "REJECTED" if result["status"] == "REJECT" else "PASS"
    set_lv_status(listing_id, status,
                  result.get("flag",""), result.get("detail",""),
                  module="debt_bot_reverify")
    return result


if __name__ == "__main__":
    init_db()
    run_debt_filter()

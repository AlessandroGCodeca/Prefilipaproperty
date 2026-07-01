"""Tests for modules/debt_bot.py::_decide_lv — the unified LV decision that lets
Claude's schema-validated analyze_lv refine the substring scan's PASS/REJECT,
while degrading gracefully to the substring decision when Claude is unavailable.

All Claude calls are monkeypatched — these tests never hit the network."""


import modules.debt_bot as debt_bot


# Raw substring-scan results as query_lv_api would return them.
SUBSTRING_PASS = {"status": "PASS", "detail": "Clean title", "raw": {"lv": "text"}}
SUBSTRING_REJECT = {"status": "REJECT", "flag": "záložné právo",
                    "detail": "LV encumbrance detected", "raw": {"lv": "text"}}


def _patch_claude(monkeypatch, enabled, analysis):
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: enabled)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda _text: analysis)


class TestFallback:
    def test_disabled_returns_substring_result(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=False, analysis=None)
        assert debt_bot._decide_lv(SUBSTRING_REJECT) == SUBSTRING_REJECT
        assert debt_bot._decide_lv(SUBSTRING_PASS) == SUBSTRING_PASS

    def test_no_raw_text_skips_claude(self, monkeypatch):
        # No LV text → nothing for Claude to read → keep substring decision.
        called = {"n": 0}
        def _boom(_t):
            called["n"] += 1
            return {"risk_level": "HIGH", "is_safe_to_proceed": False}
        monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
        monkeypatch.setattr(debt_bot, "claude_analyze_lv", _boom)
        result = debt_bot._decide_lv({"status": "PASS", "detail": "x", "raw": {}})
        assert result["status"] == "PASS"
        assert called["n"] == 0

    def test_claude_failure_falls_back(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis=None)
        assert debt_bot._decide_lv(SUBSTRING_PASS)["status"] == "PASS"

    def test_claude_unknown_falls_back(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True,
                      analysis={"risk_level": "UNKNOWN", "is_safe_to_proceed": True,
                                "flags": [], "summary": "could not read"})
        # Substring said REJECT; UNKNOWN must not override it.
        assert debt_bot._decide_lv(SUBSTRING_REJECT)["status"] == "REJECT"


class TestClaudeAuthoritative:
    def test_high_risk_rejects_even_if_substring_passed(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis={
            "risk_level": "HIGH", "is_safe_to_proceed": False,
            "flags": ["exekúcia"], "summary": "Execution order on title.",
        })
        out = debt_bot._decide_lv(SUBSTRING_PASS)
        assert out["status"] == "REJECT"
        assert out["flag"] == "exekúcia"
        assert "exekúcia" in out["flag"] or "Execution" in out["detail"]
        assert out["llm_risk_level"] == "HIGH"

    def test_not_safe_rejects(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis={
            "risk_level": "MEDIUM", "is_safe_to_proceed": False,
            "flags": [], "summary": "Private lien.",
        })
        out = debt_bot._decide_lv(SUBSTRING_PASS)
        assert out["status"] == "REJECT"
        assert out["flag"] == "LV_RISK"  # default when no flags listed

    def test_safe_bank_lien_clears_substring_false_positive(self, monkeypatch):
        # Substring flagged a záložné právo, but Claude recognises it as a normal
        # bank mortgage and clears it.
        _patch_claude(monkeypatch, enabled=True, analysis={
            "risk_level": "LOW", "is_safe_to_proceed": True,
            "flags": [], "summary": "Standard mortgage lien for Tatra banka.",
        })
        out = debt_bot._decide_lv(SUBSTRING_REJECT)
        assert out["status"] == "PASS"
        assert "Tatra banka" in out["detail"]
        assert out["llm_risk_level"] == "LOW"

    def test_decision_preserves_run_filter_contract(self, monkeypatch):
        # run_debt_filter reads result["status"], result["detail"] and
        # result.get("flag", ...) — every branch must supply those keys.
        for analysis in (
            {"risk_level": "HIGH", "is_safe_to_proceed": False, "flags": [], "summary": "s"},
            {"risk_level": "LOW", "is_safe_to_proceed": True, "flags": [], "summary": "s"},
        ):
            _patch_claude(monkeypatch, enabled=True, analysis=analysis)
            out = debt_bot._decide_lv(SUBSTRING_PASS)
            assert "status" in out and "detail" in out
            assert out.get("flag", "DEBT_FLAG")  # never empty/missing

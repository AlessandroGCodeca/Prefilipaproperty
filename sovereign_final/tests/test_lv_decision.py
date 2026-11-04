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


class TestDistressStaysRejected:
    """Claude may clear a lien the screen couldn't attribute to a bank, but an
    exekúcia / konkurz / súdny spor hit on the flat's LV stays REJECTED."""

    SAFE = {"risk_level": "LOW", "is_safe_to_proceed": True,
            "flags": [], "summary": "Looks fine."}

    def test_claude_cannot_clear_an_exekucia(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        screened = debt_bot._parse_lv("Exekúcia EX 55/2021 na podiel vlastníka")
        out = debt_bot._decide_lv(screened)
        assert out["status"] == "REJECT"
        assert out["flag"] == "exekúcia"
        assert out["llm_risk_level"] == "LOW"     # Claude's read is still recorded

    def test_claude_can_clear_an_unattributed_lien(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        screened = debt_bot._parse_lv("Záložné právo zapísané V 12/2010.")
        assert screened["status"] == "REJECT"
        assert debt_bot._decide_lv(screened)["status"] == "PASS"

    def test_unverified_never_reaches_claude(self, monkeypatch):
        def _boom(_t):
            raise AssertionError("Claude must not read a plot LV")
        monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
        monkeypatch.setattr(debt_bot, "claude_analyze_lv", _boom)
        res = {"status": "UNVERIFIED", "detail": "plot only", "raw": "LV text"}
        assert debt_bot._decide_lv(res) == res


class TestClaudeSawOnlyAPrefix:
    """An LV lists its encumbrances (part C) last. analyze_lv() used to send only
    the first 6,000 characters, so on a long LV Claude's "safe" was a read of
    owners and parcels. It is now sent part C whole (lv_text_for_claude), so a
    long LV is judged like a short one — except one the cadastre report was cut
    short on (the scraper's LV_TEXT_MAX_CHARS cap), where Claude's "safe" still
    cannot clear what the screen found. It can always reject."""

    SAFE = {"risk_level": "LOW", "is_safe_to_proceed": True,
            "flags": [], "summary": "Nothing wrong in what I was shown."}

    @staticmethod
    def _long_lv_with_private_lien():
        filler = "Vlastník: Ján Novák, Hlavná 1, Žilina. " * 300   # well past the cap
        return filler + "Časť C: ŤARCHY Záložné právo v prospech Ján Škrabák, Nitra."

    def test_a_long_lv_is_sent_with_part_c_whole(self):
        from modules.llm_enrichment import lv_text_for_claude, LV_HEAD_CHARS
        lv = self._long_lv_with_private_lien()
        assert len(lv) > 6_000
        sent, complete = lv_text_for_claude(lv)
        assert complete
        assert sent.endswith("Záložné právo v prospech Ján Škrabák, Nitra.")
        assert "parts A and B shortened" in sent
        assert len(sent) < LV_HEAD_CHARS + 200

    def test_claude_can_clear_a_lien_on_a_long_lv_it_read_part_c_of(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        screened = debt_bot._parse_lv(self._long_lv_with_private_lien())
        assert screened["status"] == "REJECT"
        assert screened["claude_may_clear"] is True      # a lien, not distress
        assert debt_bot._decide_lv(screened)["status"] == "PASS"

    def test_claude_cannot_clear_a_lien_on_an_lv_cut_short(self, monkeypatch):
        from kataster_scraper import LV_TEXT_MAX_CHARS
        lv = ("Časť C: ŤARCHY Záložné právo v prospech Ján Škrabák, Nitra. "
              + "Poznámka. " * LV_TEXT_MAX_CHARS)[:LV_TEXT_MAX_CHARS]
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        screened = debt_bot._parse_lv(lv)
        assert screened["status"] == "REJECT"
        out = debt_bot._decide_lv(screened)
        assert out["status"] == "REJECT"
        assert "cut short" in out["detail"]
        assert out["llm_risk_level"] == "LOW"            # the read is still recorded

    def test_the_same_lien_on_a_short_lv_can_still_be_cleared(self, monkeypatch):
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        screened = debt_bot._parse_lv("Časť C: ŤARCHY Záložné právo v prospech Ján Škrabák.")
        assert screened["status"] == "REJECT"
        assert debt_bot._decide_lv(screened)["status"] == "PASS"

    def test_claude_can_still_reject_a_long_lv_the_screen_passed(self, monkeypatch):
        long_clean = "Vlastník: Ján Novák, Hlavná 1, Žilina. " * 300
        _patch_claude(monkeypatch, enabled=True, analysis={
            "risk_level": "HIGH", "is_safe_to_proceed": False,
            "flags": ["vecné bremeno"], "summary": "Easement."})
        screened = debt_bot._parse_lv(long_clean)
        assert screened["status"] == "PASS"
        assert debt_bot._decide_lv(screened)["status"] == "REJECT"

    def test_a_long_clean_lv_still_passes(self, monkeypatch):
        long_clean = "Vlastník: Ján Novák, Hlavná 1, Žilina. " * 300
        _patch_claude(monkeypatch, enabled=True, analysis=self.SAFE)
        assert debt_bot._decide_lv(debt_bot._parse_lv(long_clean))["status"] == "PASS"

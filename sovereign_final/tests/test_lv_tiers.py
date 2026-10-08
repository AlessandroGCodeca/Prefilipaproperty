"""Audit A10 / A11 / A9: easements and pre-emption rights in two tiers, the
part C the Claude read is given, the per-task models — and the fixture LVs
in tests/fixtures/lv/ run through the whole screen."""

import json
import os

import pytest

import modules.debt_bot as debt_bot
import modules.llm_enrichment as llm
from modules.lv_screen import part_c_start, screen_lv

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "lv")


def _tiers(text):
    return [(e["flag"], e["tier"]) for e in screen_lv(text)]


class TestEasementTiers:
    @pytest.mark.parametrize("text", [
        "Zriadenie vecného bremena — právo prechodu",
        "Vecné bremeno in rem spočívajúce v práve prechodu a prejazdu cez pozemok",
        "Vecné bremeno in personam v prospech Západoslovenská distribučná, a.s. — "
        "právo uloženia elektrického vedenia",
        "Vecné bremeno — právo uloženia inžinierskych sietí a vodovodnej prípojky",
    ])
    def test_a_utility_or_access_easement_is_a_soft_flag(self, text):
        assert _tiers(text) == [("vecné bremeno", "soft")]
        res = debt_bot._parse_lv(text)
        assert res["status"] == "PASS"
        assert res["soft_flags"] and "soft flag" in res["detail"]

    @pytest.mark.parametrize("text", [
        "Vecné bremeno doživotného užívania bytu v prospech Mária Nováková",
        "Vecné bremeno — právo bývania v byte č. 12 v prospech Ján Novák",
        # A lifetime right wins over a technical word in the same entry.
        "Vecné bremeno doživotného užívania bytu a prechodu cez pozemok",
        # A kind that can't be read stays a hard stop.
        "Vecné bremeno v prospech Ján Novák",
    ])
    def test_a_personal_or_unreadable_easement_is_a_hard_stop(self, text):
        assert _tiers(text) == [("vecné bremeno", "hard")]
        assert debt_bot._parse_lv(text)["status"] == "REJECT"

    def test_a_municipalitys_pre_emption_right_is_soft(self):
        for holder in ("Mesto Nitra", "Obec Svätý Jur", "Mestská časť Bratislava-Ružinov",
                       "Slovenská republika"):
            assert _tiers(f"Predkupné právo v prospech {holder}") == [("predkupné právo", "soft")]

    def test_a_private_pre_emption_right_is_a_hard_stop(self):
        # "Nové Mesto" in the holder's address is not a municipality.
        text = "Predkupné právo v prospech Ján Novák, Hlavná 1, Nové Mesto nad Váhom"
        assert _tiers(text) == [("predkupné právo", "hard")]
        assert debt_bot._parse_lv(text)["status"] == "REJECT"

    def test_two_easements_are_two_entries(self):
        # A soft one first must not hide a hard one in the next entry.
        text = ("1 V 100/2015 - Vecné bremeno - právo prechodu "
                "2 V 200/2016 - Vecné bremeno v prospech Ján Novák")
        assert _tiers(text) == [("vecné bremeno", "soft"), ("vecné bremeno", "hard")]
        assert debt_bot._parse_lv(text)["status"] == "REJECT"

    def test_the_same_easement_named_twice_is_one_entry(self):
        text = ("V 300/2014 - Vecné bremeno podľa zmluvy o zriadení vecného bremena "
                "- právo uloženia vodovodnej prípojky")
        assert _tiers(text) == [("vecné bremeno", "soft")]

    def test_the_next_entry_cannot_soften_this_one(self):
        text = ("V 100/2015 - Vecné bremeno v prospech Ján Novák "
                "V 101/2015 - Iné: vodovodná prípojka")
        assert _tiers(text) == [("vecné bremeno", "hard")]

    def test_soft_flags_can_be_set_to_reject(self, monkeypatch):
        import modules.lv_screen as screen
        monkeypatch.setattr(screen, "LV_SOFT_FLAGS_REJECT", True)
        res = debt_bot._parse_lv("Zriadenie vecného bremena — právo prechodu")
        assert res["status"] == "REJECT"

    def test_distress_still_blocks_beside_a_soft_flag(self):
        res = debt_bot._parse_lv("Vecné bremeno - právo prechodu; Exekúcia EX 1/2020")
        assert res["status"] == "REJECT" and res["flag"] == "exekúcia"
        assert res["claude_may_clear"] is False


class TestSoftFlagsAreStored:
    def test_a_clean_lv_with_a_soft_flag_records_it(self, full_db, monkeypatch):
        import database as db
        from tests.conftest import make_listing
        db.upsert_listing(make_listing("f1"))
        db.set_flat_lv("f1", "4321", "Nitra")
        monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv: {
            "status": "OK", "detail": "",
            "lv_text": "ČASŤ C: ŤARCHY Vecné bremeno - právo uloženia plynovej prípojky"})
        monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
        res = debt_bot.reverify("f1")
        assert res["status"] == "PASS"
        c = full_db()
        row = c.execute("SELECT lv_status, lv_soft_flags FROM listings WHERE id='f1'").fetchone()
        assert row["lv_status"] == "PASS" and "utility / access easement" in row["lv_soft_flags"]
        # The next check replaces it.
        monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv: {
            "status": "OK", "detail": "", "lv_text": "ČASŤ C: ŤARCHY: Bez zápisu."})
        debt_bot.reverify("f1")
        row = c.execute("SELECT lv_soft_flags FROM listings WHERE id='f1'").fetchone()
        c.close()
        assert row["lv_soft_flags"] is None


class TestPartC:
    @pytest.mark.parametrize("heading", ["ČASŤ C: ŤARCHY", "Časť C - Ťarchy",
                                         "CAST C TARCHY", "C. ŤARCHY"])
    def test_the_heading_is_found(self, heading):
        text = "ČASŤ A: MAJETKOVÁ PODSTATA ... " + heading + " Bez zápisu."
        assert text[part_c_start(text):].startswith(heading)

    def test_no_heading(self):
        assert part_c_start("Vlastník: Ján Novák") is None

    def test_a_short_lv_goes_whole(self):
        text = "ČASŤ A: byt č. 12 ČASŤ C: ŤARCHY Bez zápisu."
        assert llm.lv_text_for_claude(text) == (text, True)

    def test_without_a_heading_the_whole_text_goes(self):
        text = "Vlastník: Ján Novák. " * 2_000
        sent, complete = llm.lv_text_for_claude(text)
        assert sent == text.strip() and complete


class TestModelPerTask:
    """The calls themselves are stubbed: which model, effort and fallbacks each
    task asks for."""

    class _Client:
        def __init__(self):
            self.calls = []
            outer = self

            class _Msgs:
                def __init__(self, beta):
                    self.beta = beta

                def create(self, **kw):
                    outer.calls.append((self.beta, kw))

                    class _Block:
                        type = "text"
                        text = json.dumps({"risk_level": "LOW", "is_safe_to_proceed": True,
                                           "flags": [], "summary": "ok"})

                    class _Resp:
                        stop_reason = "end_turn"
                        content = [_Block()]
                    return _Resp()

            self.messages = _Msgs(False)
            self.beta = type("B", (), {"messages": _Msgs(True)})()

    def test_the_lv_read_uses_the_capable_model_with_fallbacks(self, monkeypatch):
        client = self._Client()
        monkeypatch.setattr(llm, "_get_client", lambda: client)
        assert llm.analyze_lv("ČASŤ C: ŤARCHY Bez zápisu.")["risk_level"] == "LOW"
        beta, kw = client.calls[-1]
        assert beta and kw["fallbacks"] == "default"
        assert kw["betas"] == ["server-side-fallback-2026-07-01"]
        assert kw["model"] == llm.ANTHROPIC_MODEL_LV == "claude-opus-5-5"
        assert kw["output_config"]["effort"] == "high"
        assert kw["output_config"]["format"]["type"] == "json_schema"

    def test_bulk_extraction_uses_the_small_model_at_low_effort(self, monkeypatch):
        client = self._Client()
        monkeypatch.setattr(llm, "_get_client", lambda: client)
        llm.parse_description("2-izbový byt s balkónom")
        llm.normalize_address("Hlavná 1, Žilina")
        for beta, kw in client.calls:
            assert not beta and "fallbacks" not in kw
            assert kw["model"] == llm.ANTHROPIC_MODEL_BULK == "claude-haiku-5-5"
            assert kw["output_config"]["effort"] == "low"

    def test_a_refusal_is_no_answer(self, monkeypatch):
        client = self._Client()
        monkeypatch.setattr(llm, "_get_client", lambda: client)

        class _Refused:
            stop_reason = "refusal"
            content = []
        client.beta.messages.create = lambda **kw: _Refused()
        assert llm.analyze_lv("ČASŤ C: ŤARCHY Bez zápisu.") is None


# ── A9: fixture LVs ───────────────────────────────────────────────────────────
def _fixtures():
    if not os.path.isdir(FIXTURES):
        return []
    return sorted(f for f in os.listdir(FIXTURES) if f.endswith(".txt"))


@pytest.mark.parametrize("name", _fixtures())
def test_fixture_lv(name):
    """Every LV text in tests/fixtures/lv/ against its .expected.json:
    {"status": "PASS" | "REJECT", "flags": [...], "soft": [...]} — see the
    README there for how to add a real, anonymised one."""
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        text = fh.read()
    with open(os.path.join(FIXTURES, name[:-4] + ".expected.json"), encoding="utf-8") as fh:
        want = json.load(fh)
    res = debt_bot._parse_lv(text)
    assert res["status"] == want["status"], res["detail"]
    hard = sorted({e["flag"] for e in res["entries"] if e["blocking"]})
    soft = sorted({e["flag"] for e in res["entries"]
                   if e.get("tier") == "soft" and not e["blocking"]})
    assert hard == sorted(want.get("flags", []))
    assert soft == sorted(want.get("soft", []))
    assert part_c_start(text) is not None or want.get("no_part_c")

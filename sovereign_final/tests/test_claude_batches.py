"""EF3: the daily run's Claude reads go out as one Message Batch per step, at
half the price. The answers must be what one-by-one calls would give: a read
the batch doesn't answer is asked again on its own, the title-deed read with
its refusal fallback."""

import json
from types import SimpleNamespace as NS

import pytest

from modules import llm_enrichment as llm


def _message(answer=None, refusal=False):
    return NS(stop_reason="refusal" if refusal else "end_turn",
              content=[] if refusal else [NS(type="text", text=json.dumps(answer))])


class FakeClient:
    """messages.create, beta.messages.create and messages.batches, recorded.
    `outcomes[i]` is what the batch says for request i: ("ok", answer),
    ("refusal",), ("errored",) or ("expired",). `ends_after` polls end it;
    None never does until a cancel."""

    def __init__(self, outcomes, ends_after=1, one_by_one=None):
        self.outcomes, self.ends_after = outcomes, ends_after
        self.one_by_one = one_by_one or {}
        self.created, self.polls, self.cancelled = [], 0, False
        self.single, self.with_fallback = [], []
        client = self

        class Batches:
            def create(self, requests):
                client.created.append(requests)
                return NS(id="msgbatch_1", processing_status="in_progress")

            def retrieve(self, batch_id):
                client.polls += 1
                done = client.ends_after is not None and client.polls >= client.ends_after
                return NS(processing_status="ended" if done else "in_progress")

            def cancel(self, batch_id):
                client.cancelled = True
                client.ends_after = client.polls + 1
                return NS(processing_status="canceling")

            def results(self, batch_id):
                for i, out in enumerate(client.outcomes):
                    kind = "canceled" if client.cancelled and out[0] == "late" else out[0]
                    if kind == "ok":
                        yield NS(custom_id=f"r{i}", result=NS(type="succeeded",
                                                              message=_message(out[1])))
                    elif kind == "refusal":
                        yield NS(custom_id=f"r{i}", result=NS(type="succeeded",
                                                              message=_message(refusal=True)))
                    else:
                        yield NS(custom_id=f"r{i}", result=NS(type=kind))

        def create(**kw):
            client.single.append(kw)
            return _message(client.one_by_one.get(kw["messages"][0]["content"], {"one": "by one"}))

        def beta_create(**kw):
            client.with_fallback.append(kw)
            return _message({"fallback": kw["messages"][0]["content"]})

        self.messages = NS(create=create, batches=Batches())
        self.beta = NS(messages=NS(create=beta_create))


@pytest.fixture
def claude(monkeypatch):
    """Install a fake client; no real sleeping or waiting."""
    monkeypatch.setattr(llm, "ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(llm, "ANTHROPIC_BATCH", True)
    monkeypatch.setattr(llm, "ANTHROPIC_BATCH_MIN", 2)
    monkeypatch.setattr(llm, "ANTHROPIC_BATCH_WAIT_MIN", 20)
    now = [0.0]
    monkeypatch.setattr(llm, "_clock", lambda: now[0])
    monkeypatch.setattr(llm, "_sleep", lambda s: now.__setitem__(0, now[0] + s))

    def install(client):
        monkeypatch.setattr(llm, "_client", client)
        return client
    return install


def _asks(n, **extra):
    return [{"system": "S", "user": f"text {i}", "schema": {"type": "object"}, **extra}
            for i in range(n)]


def test_many_reads_go_as_one_batch_with_the_same_parameters(claude):
    client = claude(FakeClient([("ok", {"n": i}) for i in range(3)], ends_after=3))
    assert llm.ask_json_many(_asks(3)) == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert len(client.created) == 1 and not client.single
    sent = client.created[0]
    assert [r["custom_id"] for r in sent] == ["r0", "r1", "r2"]
    p = sent[0]["params"]
    assert p["model"] == llm.ANTHROPIC_MODEL_BULK and p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in p and "betas" not in p          # a batch can't carry them


def test_what_the_batch_does_not_answer_is_asked_one_by_one(claude):
    client = claude(FakeClient([("ok", {"n": 0}), ("errored",), ("expired",),
                                ("refusal",)]))
    got = llm.ask_json_many(_asks(4))
    assert got[0] == {"n": 0}
    assert got[1] == got[2] == {"one": "by one"}
    assert got[3] is None                     # refused, and no fallback to ask
    assert [k["messages"][0]["content"] for k in client.single] == ["text 1", "text 2"]


def test_a_refused_deed_is_asked_again_with_its_fallback(claude):
    client = claude(FakeClient([("ok", {"risk": "LOW"}), ("refusal",)]))
    got = llm.ask_json_many(_asks(2, fallbacks=True))
    assert got == [{"risk": "LOW"}, {"fallback": "text 1"}]
    assert len(client.with_fallback) == 1 and not client.single


def test_a_batch_still_running_at_the_limit_is_cancelled_and_the_rest_asked(claude):
    client = claude(FakeClient([("ok", {"n": 0}), ("late",)], ends_after=None))
    got = llm.ask_json_many(_asks(2))
    assert client.cancelled
    assert got == [{"n": 0}, {"one": "by one"}]


def test_a_batch_that_cannot_be_made_falls_back_to_one_by_one(claude):
    client = claude(FakeClient([]))

    def refuse(requests):
        raise RuntimeError("batches unavailable")
    client.messages.batches.create = refuse
    assert llm.ask_json_many(_asks(2)) == [{"one": "by one"}] * 2


def test_one_read_or_batching_off_asks_straight_away(claude, monkeypatch):
    client = claude(FakeClient([("ok", {"n": 0})]))
    assert llm.ask_json_many(_asks(1)) == [{"one": "by one"}]
    monkeypatch.setattr(llm, "ANTHROPIC_BATCH", False)
    assert llm.ask_json_many(_asks(3)) == [{"one": "by one"}] * 3
    assert llm.ask_json_many(_asks(3), batch=True) == [{"one": "by one"}] * 3
    assert not client.created


def test_the_lv_request_keeps_its_model_effort_and_fallback():
    r = llm.lv_request("ČASŤ C: Ťarchy\nBez zápisu")
    assert r["model"] == llm.ANTHROPIC_MODEL_LV and r["effort"] == "high" and r["fallbacks"]
    assert llm.lv_request("  ") is None and llm.description_request("") is None


# ── The steps ────────────────────────────────────────────────────────────────
def test_the_description_step_sends_one_batch_and_stores_each_answer(claude, monkeypatch):
    from modules import description_enrichment as de
    rows = [{"id": "a", "description": "byt s balkónom", "market": "sk"},
            {"id": "b", "description": "", "market": "sk"},
            {"id": "c", "description": "byt s garážou", "market": "sk"}]
    monkeypatch.setattr(de, "get_unparsed_descriptions", lambda limit, **kw: rows)
    stored = {}
    monkeypatch.setattr(de, "update_description_features", lambda lid, f: stored.update({lid: f}))
    parsed = {"balcony": True, "terrace": False, "loggia": False, "parking": False,
              "cellar": False, "elevator": False, "furnished": "unknown",
              "condition": "unknown", "floor": -1, "building_floors": -1, "rooms": 0}
    client = claude(FakeClient([("ok", parsed), ("ok", {**parsed, "parking": True})]))
    assert de.run_description_enrichment(batch=True) == 2
    assert len(client.created) == 1 and len(client.created[0]) == 2   # the empty one skipped
    assert set(stored) == {"a", "c"} and not client.single


def test_the_address_step_sends_one_batch(claude, monkeypatch):
    from modules import address_enrichment as ae
    rows = [{"id": "a", "address_raw": "Obchodná 5, Bratislava", "market": "sk"},
            {"id": "b", "address_raw": "Vinohradská 12, Praha 2", "market": "cz"}]
    monkeypatch.setattr(ae, "get_unnormalized_addresses", lambda limit, **kw: rows)
    stored = {}
    monkeypatch.setattr(ae, "update_address", lambda lid, d, c: stored.update({lid: (d, c)}))
    client = claude(FakeClient([("ok", {"city": "Bratislava", "district": "Staré Mesto",
                                        "kraj": "BA"}),
                                ("ok", {"city": "Praha", "district": "Praha 2", "kraj": "PHA"})]))
    assert ae.run_address_enrichment(batch=True) == 2
    assert len(client.created) == 1 and stored["b"][1] == "Praha"


def _lv_world(monkeypatch, decided_by):
    """Three pending flats: a clean screen Claude rejects, one with no deed,
    a lien the screen rejected and Claude clears. Returns what was stored."""
    from modules import debt_bot
    rows = [{"id": i, "address_raw": f"Street {i}", "lv_status": "PENDING"} for i in "abc"]
    checks = {
        "a": {"status": "PASS", "raw": "LV a", "detail": "Clean title"},
        "b": {"status": "UNVERIFIED", "raw": None, "detail": "no LV of the flat"},
        "c": {"status": "REJECT", "raw": "LV c", "flag": "LIEN", "detail": "záložné právo",
              "claude_may_clear": True},
    }
    reads = {"LV a": {"risk_level": "HIGH", "is_safe_to_proceed": False,
                      "flags": ["EXECUTION"], "summary": "an execution"},
             "LV c": {"risk_level": "LOW", "is_safe_to_proceed": True,
                      "flags": [], "summary": "a bank's mortgage"}}
    monkeypatch.setattr(debt_bot, "reset_demo_rejections", lambda: 0)
    monkeypatch.setattr(debt_bot, "get_pending_lv", lambda **kw: rows)
    monkeypatch.setattr(debt_bot, "check_listing", lambda row, refresh=False: dict(checks[row["id"]]))
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    asked = []
    if decided_by == "batch":
        def many(requests, batch=True):
            asked.append(len(requests))
            return [reads[r["user"].split("\n", 1)[1]] for r in requests]
        monkeypatch.setattr(debt_bot, "ask_json_many", many)
        monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda *a, **k: pytest.fail("asked one by one"))
    else:
        monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda text, market="sk": reads[text])
    stored = {}
    monkeypatch.setattr(debt_bot, "set_lv_analysis", lambda *a, **k: None)
    monkeypatch.setattr(debt_bot, "set_lv_status",
                        lambda lid, status, flag, detail, **k: stored.update({lid: (status, flag)}))
    return debt_bot, stored, asked


def test_the_deeds_are_read_in_one_batch_with_the_same_verdicts(monkeypatch):
    debt_bot, one_by_one, _ = _lv_world(monkeypatch, "one by one")
    expected = debt_bot.run_debt_filter()
    debt_bot, batched, asked = _lv_world(monkeypatch, "batch")
    assert debt_bot.run_debt_filter(batch=True) == expected == (1, 1, 1)
    assert batched == one_by_one
    assert batched["a"][0] == "REJECTED" and batched["c"][0] == "PASS"
    assert asked == [2]                                    # the deed-less flat not sent


def test_the_daily_run_asks_for_batches_and_the_buttons_do_not(monkeypatch):
    import inspect

    import scheduler
    from dashboard import actions
    src = inspect.getsource(scheduler._market_steps)
    assert "run_debt_filter(market=market, batch=True)" in src
    assert "run_address_enrichment(market=market, batch=True)" in src
    assert "run_description_enrichment(market=market, batch=True)" in src
    assert "batch=True" not in inspect.getsource(actions)

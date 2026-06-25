"""Tests for backfill_enrichment.main — the one-shot orchestration that enriches
then rescores. The four steps are monkeypatched, so this verifies the ordering
and the returned summary without touching the DB or the network."""

import backfill_enrichment as bf


def test_runs_enrichers_before_rescore_and_summarises(monkeypatch):
    calls = []

    monkeypatch.setattr(bf, "init_db", lambda: calls.append("init"))
    monkeypatch.setattr(bf, "run_address_enrichment",
                        lambda limit=1000: (calls.append(("addr", limit)), 3)[1])
    monkeypatch.setattr(bf, "run_description_enrichment",
                        lambda limit=1000: (calls.append(("desc", limit)), 5)[1])
    monkeypatch.setattr(bf, "clear_cashflow_scores",
                        lambda: (calls.append("clear"), 7)[1])
    monkeypatch.setattr(bf, "run_scoring",
                        lambda: (calls.append("score"), 9)[1])

    summary = bf.main(limit=250)

    # Enrichment must precede clearing+rescoring, and init_db must be first.
    assert calls == ["init", ("addr", 250), ("desc", 250), "clear", "score"]
    assert summary == {"addresses": 3, "descriptions": 5, "cleared": 7, "scored": 9}


def test_limit_defaults_to_1000(monkeypatch):
    seen = {}
    monkeypatch.setattr(bf, "init_db", lambda: None)
    monkeypatch.setattr(bf, "run_address_enrichment",
                        lambda limit=1000: seen.setdefault("addr", limit) or 0)
    monkeypatch.setattr(bf, "run_description_enrichment",
                        lambda limit=1000: seen.setdefault("desc", limit) or 0)
    monkeypatch.setattr(bf, "clear_cashflow_scores", lambda: 0)
    monkeypatch.setattr(bf, "run_scoring", lambda: 0)

    bf.main()
    assert seen == {"addr": 1000, "desc": 1000}

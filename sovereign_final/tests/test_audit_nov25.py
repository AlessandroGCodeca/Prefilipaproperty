"""Checks from the 25 Nov audit."""

import tests.test_app_smoke as smoke

db = smoke.db
populated_db = smoke.populated_db


def test_on_1_january_2027_scoring_runs_on_the_2026_tables_and_says_so(populated_db, monkeypatch):
    """No 2027 tax table exists yet (finding 3): scoring and the page carry on
    with 2026's, and the sidebar says which year it used."""
    import config
    import markets
    from modules.cashflow_runner import run_scoring
    monkeypatch.setattr(config, "TAX_YEAR", 2027)
    for m in ("sk", "cz"):
        rules = markets.tax_rules(market=m)
        assert rules["requested"] == 2027 and rules["year"] == 2026 and rules["stale"]
    run_scoring()
    at = smoke.run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert any("No tax table for 2027 yet" in w.value for w in at.sidebar.warning)

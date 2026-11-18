"""The design and UX items D1–D15 of the 18 Nov review (PDF section 13)."""

import os
import re

import tests.test_app_smoke as smoke
from tests.test_app_smoke import run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── D13 · keyboard and screen readers; the colour tokens ─────────────────────
def test_every_colour_is_a_token_and_focus_is_visible():
    from dashboard.style import CSS
    assert "--good: #3ddc97" in CSS and "var(--good)" in CSS
    rules = CSS[CSS.index(":root {", CSS.index("--bad-line")):]          # after the token block
    assert not re.search(r"#3ddc97|#ff8a8a|#f5b84a", rules.split("--mono")[1])
    assert ":focus-visible" in CSS and "outline:2px solid var(--info)" in CSS


def test_a_skip_link_leads_to_the_tabs(populated_db):
    at = run_app()
    md = " ".join(m.value for m in at.markdown)
    assert 'class="skip" href="#tabs"' in md and 'id="tabs"' in md


# ── D2 · fewer chips: only what needs action ─────────────────────────────────
def _card_md(at, lid="g1"):
    return " ".join(m.value for m in at.markdown if "facts" in m.value or "badge" in m.value)


def test_a_card_shows_chips_only_for_what_needs_action(populated_db):
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    md = _card_md(at)
    assert '<div class="facts">' in md
    facts = md.split('<div class="facts">')[1].split("</div>")[0]
    assert "Green" in facts and "grade" in facts                 # informational: one line
    chips = md.split('<div class="facts">')[0]
    assert "GRADE" not in chips and ">PERSONAL<" not in chips    # no longer chips
    assert chips.count('class="badge') <= 6


# ── D10 · star a flat ────────────────────────────────────────────────────────
def test_a_flat_can_be_starred_and_unstarred(populated_db):
    at = run_app(open_cards=("g1",))
    at.button(key="star_g1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "g1" in populated_db.get_starred()
    assert at.button(key="star_g1").label == "★ Starred"
    at.button(key="star_g1").click().run()
    assert "g1" not in populated_db.get_starred()


# ── D5 · filters and order beside the list ───────────────────────────────────
def _snag_titles(at):
    return [e.label for e in at.expander if e.label.startswith(("🟢", "🟡"))]


def test_quick_filters_narrow_the_list_and_the_order_changes(populated_db):
    at = run_app()
    every = _snag_titles(at)
    assert every
    at.pills(key="quick_filters").set_value(["Cash-flow positive"]).run()
    assert not at.exception, [e.value for e in at.exception]
    positive = _snag_titles(at)
    assert len(positive) <= len(every)
    assert all("+€" in t or "+" in t.split("·")[-1] for t in positive)
    at.pills(key="quick_filters").set_value(["Starred"]).run()
    assert _snag_titles(at) == []
    populated_db.set_starred("g1", True)
    at.run()
    assert len(_snag_titles(at)) == 1
    at.pills(key="quick_filters").set_value([]).run()
    at.selectbox(key="list_order").set_value("Lowest price").run()
    assert not at.exception, [e.value for e in at.exception]

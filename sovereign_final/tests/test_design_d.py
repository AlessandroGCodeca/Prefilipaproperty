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

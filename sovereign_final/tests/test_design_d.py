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

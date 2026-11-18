"""The card's opening words (dashboard/verdict.py): the style chosen on the
design canvas — a plain headline, then a paragraph with the numbers."""

import pytest

from dashboard import verdict as v

money = lambda x: f"€{x:,.0f}"  # noqa: E731


@pytest.mark.parametrize("disc, surplus, text", [
    (0.40, -123, "A good price on a flat that doesn't pay for itself."),
    (0.40, 50, "A good price, and the flat pays for itself."),
    (0.02, -10, "A fair price, but the flat doesn't pay for itself."),
    (-0.02, 10, "A fair price on a flat that pays for itself."),
    (-0.30, -10, "Priced above its market, and it doesn't pay for itself."),
    (-0.30, 10, "Priced above its market, though the rent covers the costs."),
    (None, -10, "No market benchmark here, and the flat doesn't pay for itself."),
    (0.40, None, "A good price."),
    (None, None, "No market benchmark for this district."),
])
def test_headline(disc, surplus, text):
    assert v.headline(disc, surplus) == text


def test_the_threshold_is_five_percent():
    assert v.headline(0.05, 1).startswith("A good price")
    assert v.headline(0.049, 1).startswith("A fair price")
    assert v.headline(-0.05, 1).startswith("Priced above")


def test_body_gives_the_numbers_in_plain_sentences():
    out = v.body(0.40, -123, "s.r.o.", money, cut_pct=-0.07, cut_days=9)
    assert out == ("It is listed 40% under its market median, and the price has already "
                   "come down 7% in 9 days. As an s.r.o. it still costs €123 more each month "
                   "than the rent brings in.")
    assert v.body(0.40, 50, "Personal", money) == (
        "It is listed 40% under its market median. Under the Personal structure the rent "
        "covers every cost, with €50 a month left over.")
    assert v.body(None, -5, "s.r.o.", money, cut_pct=-0.03) == (
        "The price has already come down 3%. As an s.r.o. it still costs €5 more each month "
        "than the rent brings in.")
    assert v.body(0.4, None, "s.r.o.", money) == "It is listed 40% under its market median."


def test_a_price_that_did_not_fall_says_nothing_about_a_cut():
    assert "come down" not in v.body(0.4, 1, "s.r.o.", money, cut_pct=0.05, cut_days=3)
    assert "come down" not in v.body(0.4, 1, "s.r.o.", money, cut_pct=0.0)
    assert "come down 7% in" not in v.body(0.4, 1, "s.r.o.", money, cut_pct=-0.07)


def test_czech_listings_get_czech_text():
    assert v.headline(0.4, -10, cz=True) == "Dobrá cena u bytu, který se nezaplatí sám."
    out = v.body(0.4, -10, "s.r.o.", money, cz=True, cut_pct=-0.07, cut_days=9)
    assert "Nabízí se 40 % pod mediánem trhu, a cena už klesla o 7 % za 9 dní." in out
    assert "o €10 víc, než přinese nájem" in out


def test_days_between():
    assert v.days_between("2026-11-03T08:00:00", "2026-11-12") == 9
    assert v.days_between("2026-11-12", "2026-11-03") == 0
    assert v.days_between(None, "2026-11-12") is None
    assert v.days_between("nonsense", "2026-11-12") is None


def test_the_band_escapes_what_it_is_given_and_marks_the_tone():
    html = v.verdict_html("A", 80, 0.4, -123, "<b>x</b>", money, cut_pct=-0.07, cut_days=9)
    assert 'class="vd vd-g"' in html and "<b>A</b>" in html and "80/100" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>x</b>" not in html
    assert 'vd-y' in v.verdict_html("C", 55, 0.1, 1, "s.r.o.", money)
    assert 'vd-w' in v.verdict_html("—", None, None, None, "s.r.o.", money)
    assert "<b>–</b>" in v.verdict_html("—", None, None, None, "s.r.o.", money)


def test_the_portal_strip_folds_healthy_portals_into_one_chip_for_phones():
    from datetime import datetime, timezone
    from dashboard.overview import portal_strip
    import scheduler
    now = datetime.now(timezone.utc)
    run = lambda n, err="": {"run_at": now.isoformat(), "listings": n, "error": err}  # noqa: E731
    health = {("sk", scheduler.source_of(m)): {"daily": [5] * 7, "last": run(5), "last_good_at": None}
              for _, m in scheduler.SCRAPERS["sk"]}
    html = portal_strip(health, "sk", now=now)
    assert "ph-sum" in html and "portals · all ran" in html
    first = list(health)[0]
    health[first] = {"daily": [0] * 7, "last": run(0, "HTTP 403"), "last_good_at": None}
    assert "1 failed" in portal_strip(health, "sk", now=now)


def test_the_stylesheet_has_a_phone_section_with_44px_targets():
    from dashboard.style import CSS
    phone = CSS[CSS.index("Phone (≤640 px)"):]
    assert "min-height:44px" in phone and "repeat(3,minmax(0,1fr))" in phone
    assert "padding-top:3.8rem" in phone            # clear of Streamlit's fixed header
    assert ".phc.none, .phc.ok { display:none; }" in CSS

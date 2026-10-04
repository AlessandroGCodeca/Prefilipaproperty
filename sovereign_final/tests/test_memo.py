"""Tests for the PDF investment memo (modules/memo.py)."""

import pytest

import modules.memo as memo
from engine.financial import analyse, result_to_db_dict, deal_extras


def _full_row():
    r = analyse(98_000, 58, "Žilina", listing_id="x1", ltv=0.8)
    return {
        **result_to_db_dict(r), **deal_extras(r),
        "id": "x1", "title": "2-izbový byt, Žilina – Hliny", "district": "Žilina",
        "price_eur": 98_000, "size_m2": 58, "source": "bazos", "url": "https://example.sk/x",
        "scraped_at": "2026-08-01T10:00:00+00:00", "cf_class": r.classification,
        "lv_status": "PASS", "lv_summary": "Záložné právo v prospech VÚB — bežná hypotéka.",
        "noise_flag": 1, "noise_detail": "primary road ≤30 m (Vysokoškolákov)",
        "flood_zone": None, "flood_detail": "flood service unreachable",
        "floor": 3, "building_floors": 8, "has_elevator": 1, "has_cellar": 1,
        "condition": "renovated", "rent_source": "live",
    }


def test_full_memo_is_a_pdf():
    pdf = memo.build_memo_pdf(
        _full_row(),
        price_history={"x1": {"history": [("2026-08-01", 105_000), ("2026-09-10", 98_000)],
                              "change_pct": -0.0667}},
        notes=[{"created_at": "2026-09-12", "vibe_score": 7, "note": "Pekný výhľad"}],
        stage={"stage": "VIEWING", "updated_at": "2026-09-13", "note": "obhliadka"},
        portals=[{"source": "bazos", "price_eur": 98_000, "url": "https://a"},
                 {"source": "topreality", "price_eur": 99_000, "url": "https://b"}])
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000


def test_a_bare_listing_still_prints():
    pdf = memo.build_memo_pdf({"id": "y", "title": "Byt", "price_eur": 0, "size_m2": 0})
    assert pdf.startswith(b"%PDF")


def test_without_a_unicode_font_diacritics_are_folded(monkeypatch):
    monkeypatch.setattr(memo, "_FONT_CANDIDATES", [])
    pdf = memo.build_memo_pdf(_full_row())
    assert pdf.startswith(b"%PDF")


def _memo_text(monkeypatch, row, **kw) -> str:
    """Every string the memo prints (the PDF stream itself is compressed)."""
    printed = []
    real = memo._Memo.txt

    def spy(self, s):
        out = real(self, s)
        printed.append(out)
        return out
    monkeypatch.setattr(memo._Memo, "txt", spy)
    memo.build_memo_pdf(row, **kw)
    return "\n".join(printed)


def test_the_lv_section_says_why_and_which_lv(monkeypatch):
    row = {**_full_row(), "lv_status": "UNVERIFIED", "lv_number": "4321",
           "cadastral_area": "Žilina", "lv_checked_at": "2026-09-20T08:00:00+00:00",
           "lv_detail": "Building plot found, but the flat's own LV was not read."}
    text = _memo_text(monkeypatch, row)
    assert "Flat's LV: 4321, k.ú. Žilina" in text
    assert "Last check: Building plot found, but the flat's own LV was not read. (2026-09-20)" in text


def test_an_unknown_flat_lv_is_said_so(monkeypatch):
    text = _memo_text(monkeypatch, {**_full_row(), "lv_number": None})
    assert "Flat's LV: not known" in text


def test_days_listed_match_the_card(monkeypatch):
    # The card counts from the oldest copy on any portal; so does the memo.
    from datetime import datetime, timedelta, timezone
    from database import days_on_market
    now = datetime.now(timezone.utc)
    mine = (now - timedelta(days=5)).isoformat()
    older = (now - timedelta(days=20)).isoformat()
    row = {**_full_row(), "scraped_at": mine}
    copies = [{"source": "bazos", "price_eur": 98_000, "url": "https://a", "scraped_at": mine},
              {"source": "topreality", "price_eur": 99_000, "url": "https://b", "scraped_at": older}]
    card_dom = days_on_market(min(c["scraped_at"] for c in copies + [row]))
    text = _memo_text(monkeypatch, row, portals=copies)
    assert card_dom == 20
    assert f"{card_dom} (first seen {older[:10]})" in text


@pytest.mark.parametrize("v,signed,out", [
    (1234.4, False, "€1,234"), (-50, True, "−€50"), (12, True, "+€12"), (None, False, "—"),
])
def test_money_format(v, signed, out):
    assert memo._eur(v, signed) == out

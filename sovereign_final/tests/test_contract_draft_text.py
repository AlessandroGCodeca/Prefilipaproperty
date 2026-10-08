"""modules/contract_draft — the text ONE-CLICK CLOSE tells you to send to the
notár. It printed "Katastrálne územie: None" for a NULL column, never the
flat's LV number, US-style amounts (€50,500.00), and carried your surplus and
yield in a "FINANČNÁ ANALÝZA (pre interné účely)" block."""

from datetime import datetime

from modules.contract_draft import (
    build_contract_draft, build_internal_analysis, sk_eur, sk_number,
)

NBSP = " "
NOW = datetime(2026, 10, 8, 9, 30)


def _listing(**over):
    row = {
        "id": "abc123", "title": "1-izbový byt, Fončorda", "address_raw": None,
        "district": "Banská Bystrica", "size_m2": 35.0, "energy_class": "D",
        "cadastral_area": None, "cadastral_number": None, "lv_number": None,
        "floor": None, "lv_status": "PASS", "surplus_sro": 23.4,
        "annual_sro_saving": 193.0, "net_rental_yield": 0.0054,
    }
    row.update(over)
    return row


def _draft(listing=None, **kw):
    args = dict(buyer_name="Filip Test", agreed_price=50_500, deposit=2_000,
                generated_at=NOW)
    args.update(kw)
    return build_contract_draft(listing or _listing(), **args)


def test_slovak_number_and_money_format():
    assert sk_number(1_234_567.5, 2) == f"1{NBSP}234{NBSP}567,50"
    assert sk_eur(50_500) == f"50{NBSP}500,00{NBSP}€"
    assert sk_eur(-41, 0) == f"−41{NBSP}€"
    assert sk_eur(23.4, 0, signed=True) == f"+23{NBSP}€"
    assert sk_eur(None) == "—"


def test_blank_columns_print_a_placeholder_not_none():
    draft = _draft()
    assert "None" not in draft
    assert "Katastrálne územie:   [Doplniť]" in draft
    assert "Parcela pod domom:    [Doplniť]" in draft
    assert "Adresa:       [Doplniť]" in draft


def test_unknown_energy_class_and_size_are_placeholders():
    draft = _draft(_listing(energy_class="UNKNOWN", size_m2=None))
    assert "Energetická trieda: [Doplniť]" in draft
    assert "Výmera:       [Doplniť]" in draft


def test_the_flats_lv_number_and_cadastral_data_are_printed():
    draft = _draft(_listing(lv_number="4321", cadastral_area="Banská Bystrica",
                            cadastral_number="1234/5", floor=4))
    assert "List vlastníctva:     č. 4321 (overiť na Katastri pred podpisom)" in draft
    assert "Katastrálne územie:   Banská Bystrica" in draft
    assert "Parcela pod domom:    1234/5" in draft
    assert "Vchod / poschodie:    [Doplniť] / 4" in draft


def test_without_an_lv_number_the_line_asks_for_it():
    assert "List vlastníctva:     [Doplniť] — overiť na Katastri" in _draft()


def test_amounts_are_written_the_slovak_way():
    draft = _draft()
    assert f"Dohodnutá cena:    50{NBSP}500,00{NBSP}€" in draft
    assert f"Záloha (depozit):  2{NBSP}000,00{NBSP}€" in draft
    assert f"Zostatok:          48{NBSP}500,00{NBSP}€" in draft
    assert "€50,500" not in draft
    assert f"Výmera:       35{NBSP}m²" in draft
    assert f"35,5{NBSP}m²" in _draft(_listing(size_m2=35.5))


def test_the_flat_lines_a_transfer_names_are_there_to_fill():
    draft = _draft()
    for line in ("Súpisné číslo domu:", "Číslo bytu:", "Vchod / poschodie:",
                 "Podiel na pozemku:", "a zariadeniach domu:"):
        assert line in draft


def test_the_deal_analysis_is_not_in_the_draft():
    draft = _draft()
    for internal in ("FINANČNÁ ANALÝZA", "surplus", "Net Yield", "úspora", "LV Status", "PASS"):
        assert internal not in draft


def test_the_analysis_carries_the_numbers():
    text = build_internal_analysis(_listing(), agreed_price=50_500, generated_at=NOW)
    assert "NEPOSIELAŤ NOTÁROVI" in text
    assert f"s.r.o. surplus/mes.: +23{NBSP}€" in text
    assert f"Ročná úspora s.r.o.: 193{NBSP}€" in text
    assert f"Net Yield:           0,54{NBSP}%" in text
    assert "LV overenie:         PASS" in text
    assert f"Net Yield:           −0,44{NBSP}%" in build_internal_analysis(
        _listing(net_rental_yield=-0.0044), generated_at=NOW)
    assert "None" not in build_internal_analysis(
        _listing(surplus_sro=None, annual_sro_saving=None, net_rental_yield=None,
                 lv_status=None), generated_at=NOW)


def test_ico_placeholder_follows_the_structure():
    assert "IČO:               — (fyzická osoba)" in _draft(ownership="Personal")
    assert "IČO:               [Doplniť]" in _draft(ownership="s.r.o.")
    assert "IČO:               12345678" in _draft(ownership="s.r.o.", buyer_ico=" 12345678 ")


def test_escrow_choice_sets_payment_and_condition():
    assert "§ 56a Notárskeho poriadku" in _draft(escrow=True)
    no_escrow = _draft(escrow=False)
    assert "Priamy prevod" in no_escrow and "§ 56a" not in no_escrow

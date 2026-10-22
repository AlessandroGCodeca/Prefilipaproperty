"""
modules/contract_draft.py — the ONE-CLICK CLOSE purchase-contract draft.

build_contract_draft(listing, ...) returns the text the dashboard tells you to
send to the notár; build_internal_analysis(listing, ...) returns the deal's
numbers as a separate note that stays with you. They used to be one text, so
your surplus and yield went to the notár inside the draft.

A blank field prints a "[Doplniť]" placeholder, never "None": a row's
`.get(key, default)` returns the stored NULL, not the default, so the draft
used to read "Katastrálne územie: None". Amounts are written the Slovak way
(50 500,00 €), not €50,500.00.

The flat's lines a transfer contract has to name that no listing carries
(flat number, entrance, súpisné číslo, the shares in the building and the
land) are placeholders for the notár to fill and confirm.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytz

FILL = "[Doplniť]"
_NBSP = " "
_RULE = "━" * 58

# One clock for every document the dashboard writes (this draft, the Czech
# one, the internal note, the PDF memo, their file names and EARLIER DRAFTS):
# Bratislava time, the zone the scheduler runs on. The host's own clock is UTC
# in Docker and local time on a laptop, and the database stores UTC, so one
# draft used to show two different times. pytz carries its own zone data
# (zoneinfo would need the tzdata package on Windows).
LOCAL_TZ = pytz.timezone("Europe/Bratislava")


def local_now() -> datetime:
    """Now, in Bratislava time (timezone-aware)."""
    return datetime.now(LOCAL_TZ)


def to_local(stamp) -> datetime | None:
    """A stored timestamp — ISO text or a datetime — in Bratislava time. One
    without an offset is UTC, which is what the database writes. None when
    there is nothing to read."""
    if isinstance(stamp, str):
        try:
            stamp = datetime.fromisoformat(stamp.strip())
        except ValueError:
            return None
    if not isinstance(stamp, datetime):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(LOCAL_TZ)


def doc_stamp(generated_at: datetime | None = None) -> str:
    """'YYYY-MM-DD HH:MM' for a document's "generated" line: an aware time in
    Bratislava time, a naive one as given, none → now in Bratislava."""
    when = generated_at or local_now()
    if when.tzinfo is not None:
        when = when.astimezone(LOCAL_TZ)
    return when.strftime("%Y-%m-%d %H:%M")


def figures_at_price(listing: dict, price: float) -> dict | None:
    """The internal note's figures — s.r.o. surplus, the s.r.o.'s yearly
    difference, net yield — worked out again at `price` on the stored score's
    own rent, financing, s.r.o. terms and tax year. The stored score is at the
    asking price; the note prints the price in the draft. None when the
    listing has no score to rework or the engine cannot price it."""
    l = listing
    rent, size = l.get("estimated_rent_eur"), l.get("size_m2")
    if not rent or not size or not price or price <= 0:
        return None
    import markets
    from engine.financial import analyse
    mkt = markets.of_row(l)
    rate = l.get("mortgage_rate_used")
    kw = dict(rent_override=rent, ltv=l.get("ltv_used"), rate=rate,
              term_years=l.get("loan_term_years"), rooms=l.get("rooms"),
              tax_year=l.get("tax_year"), sro_ltv=l.get("sro_ltv_used"),
              sro_rate_premium=(l["sro_rate_used"] - rate
                                if l.get("sro_rate_used") is not None and rate is not None
                                else None),
              sro_running_cost=(l["sro_running_cost_monthly"] * 12
                                if l.get("sro_running_cost_monthly") is not None else None))
    kw = {k: v for k, v in kw.items() if v is not None}
    if mkt != "sk":
        kw["market"] = mkt
    try:
        r = analyse(float(price), float(size), l.get("district") or "", **kw)
    except Exception:
        return None
    return {"surplus_sro": r.surplus_sro, "annual_sro_saving": r.annual_sro_saving,
            "net_rental_yield": r.net_rental_yield}


_NOTE_KEYS = ("surplus_sro", "annual_sro_saving", "net_rental_yield")


def note_figures(listing: dict, agreed_price: float) -> tuple[dict, str | None]:
    """(row, how) for the internal note. When the price in the draft is not
    the asking price, the figures are reworked at it (how = "reworked"); if
    they cannot be, the stored ones stay and how = "asking", so the note can
    say which price they belong to. how is None when the prices match or
    there are no figures to show."""
    asking = listing.get("price_eur")
    if (not agreed_price or not asking or abs(agreed_price - asking) < 1
            or all(listing.get(k) is None for k in _NOTE_KEYS)):
        return listing, None
    at = figures_at_price(listing, agreed_price)
    if at is None:
        return listing, "asking"
    return {**listing, **at}, "reworked"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in ("", "UNKNOWN"))


def _text(v, fallback: str = FILL) -> str:
    return fallback if _blank(v) else str(v).strip()


def sk_number(v: float, decimals: int = 0) -> str:
    """1234567.5 → '1 234 567,50' at decimals=2: a no-break space groups the
    thousands and a comma marks the decimals."""
    return f"{v:,.{decimals}f}".replace(",", _NBSP).replace(".", ",")


def sk_eur(v, decimals: int = 2, signed: bool = False) -> str:
    """50500 → '50 500,00 €'. None → '—'."""
    if v is None:
        return "—"
    sign = ("+" if v >= 0 else "−") if signed else ("−" if v < 0 else "")
    return f"{sign}{sk_number(abs(v), decimals)}{_NBSP}€"


def _size(v) -> str:
    if _blank(v):
        return FILL
    v = float(v)
    return f"{sk_number(v, 0 if v.is_integer() else 1)}{_NBSP}m²"


def build_contract_draft(listing: dict, *, buyer_name: str, buyer_ico: str = "",
                         ownership: str = "Personal", agreed_price: float = 0,
                         deposit: float = 0, notary: str = "", escrow: bool = True,
                         generated_at: datetime | None = None) -> str:
    """The draft for the notár: the flat, the parties, the price and the
    conditions. Nothing from the deal analysis goes in it."""
    now = doc_stamp(generated_at)
    l = listing
    lv_no = l.get("lv_number")
    lv_line = (f"č. {str(lv_no).strip()} (overiť na Katastri pred podpisom)"
               if not _blank(lv_no) else f"{FILL} — overiť na Katastri pred podpisom")
    floor = l.get("floor")
    floor = FILL if floor is None else f"{int(floor)}"
    ico = (buyer_ico or "").strip() or (FILL if ownership == "s.r.o." else "— (fyzická osoba)")
    if escrow:
        payment, term5 = ("✅ Notárska úschova — odporúčané",
                          "Finančné plnenie cez Notársku úschovu dle § 56a Notárskeho poriadku.")
    else:
        payment, term5 = ("⚠️ Priamy prevod — neodporúčané",
                          "Finančné plnenie na účet predávajúceho po podpise zmluvy.")

    return f"""\
╔══════════════════════════════════════════════════════════╗
║         KÚPNA ZMLUVA — DRAFT / NÁVRH ZMLUVY             ║
╚══════════════════════════════════════════════════════════╝

Vygenerované:  {now}
Stav:          DRAFT — vyžaduje notariálne vyhotovenie
Verzia:        Sovereign RE Dashboard v2026

{_RULE}

§ 1. PREDMET ZMLUVY

Nehnuteľnosť: {_text(l.get('title'), '—')}
Adresa:       {_text(l.get('address_raw'))}
Okres:        {_text(l.get('district'))}
Výmera:       {_size(l.get('size_m2'))}
Energetická trieda: {_text(l.get('energy_class'))}

Katastrálne územie:   {_text(l.get('cadastral_area'))}
List vlastníctva:     {lv_line}
Parcela pod domom:    {_text(l.get('cadastral_number'))}
Súpisné číslo domu:   {FILL}
Číslo bytu:           {FILL}
Vchod / poschodie:    {FILL} / {floor}
Spoluvlastnícky podiel na spoločných častiach
  a zariadeniach domu: {FILL}
Podiel na pozemku:    {FILL}
(Náležitosti zmluvy o prevode bytu doplní a overí notár.)

{_RULE}

§ 2. ZMLUVNÉ STRANY

KUPUJÚCI (Buyer):
  Meno / Spoločnosť: {buyer_name}
  IČO:               {ico}
  Forma vlastníctva: {ownership}

PREDÁVAJÚCI (Seller):
  [Doplniť notárom — overiť totožnosť a vlastníctvo]

{_RULE}

§ 3. KÚPNA CENA

Dohodnutá cena:    {sk_eur(agreed_price)}
Záloha (depozit):  {sk_eur(deposit)}
Zostatok:          {sk_eur(agreed_price - deposit)}

Platobný mechanizmus:
  {payment}

{_RULE}

§ 4. PODMIENKY

1. Zmluva nadobúda platnosť podpisom oboch strán pred notárom.
2. Prevod vlastníctva nastáva zápisom do katastra nehnuteľností.
3. Predávajúci zaručuje, že nehnuteľnosť je bez právnych vád.
4. Kupujúci vyhlasuje, že je oboznámený so stavom nehnuteľnosti.
5. {term5}

{_RULE}

§ 5. NOTÁR

Notár:   {(notary or '').strip() or '[Prideliť notára]'}
Dátum:   {FILL}
Miesto:  {FILL}

{_RULE}

⚠️  PRÁVNE UPOZORNENIE

Tento dokument je počítačom generovaný NÁVRH bez právnej záväznosti.
Nemá žiadnu právnu platnosť bez vyhotovenia a overenia licencovaným
slovenským notárom. Vždy overte LV bezprostredne pred podpisom.
Finálny prevod vyžaduje zápis na Katastri nehnuteľností SR.

{_RULE}
Generated by Sovereign RE Dashboard · Private Use Only"""


def build_internal_analysis(listing: dict, *, agreed_price: float = 0,
                            generated_at: datetime | None = None) -> str:
    """The deal's numbers and the dashboard's LV verdict — for you, not for
    the notár. The stored score is at the asking price; when the draft's
    price differs, the figures are worked out again at it (note_figures), or
    the note says they are the asking price's."""
    now = doc_stamp(generated_at)
    l, how = note_figures(listing, agreed_price)
    nry = l.get("net_rental_yield")
    yield_str = ("—" if nry is None
                 else f"{'−' if nry < 0 else ''}{sk_number(abs(nry) * 100, 2)}{_NBSP}%")
    asking = ""
    if how:
        asking = (f"\nPonuková cena:       {sk_eur(l.get('price_eur'))} — "
                  + ("čísla nižšie sú prepočítané na cenu v návrhu" if how == "reworked"
                     else "čísla nižšie sú pri ponukovej cene"))
    return f"""\
FINANČNÁ ANALÝZA — INTERNÉ, NEPOSIELAŤ NOTÁROVI
{_text(l.get('title'), '—')} · {_text(l.get('district'), '—')}
Vygenerované:        {now}

Cena v návrhu:       {sk_eur(agreed_price)}{asking}
s.r.o. surplus/mes.: {sk_eur(l.get('surplus_sro'), 0, signed=True)}
Ročná úspora s.r.o.: {sk_eur(l.get('annual_sro_saving'), 0)}
Net Yield:           {yield_str}
LV overenie:         {_text(l.get('lv_status'), 'PENDING')} — OVERIŤ 48H PRED PODPISOM"""

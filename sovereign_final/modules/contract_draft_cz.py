"""
modules/contract_draft_cz.py — the ONE-CLICK CLOSE draft for a Czech flat:
a kupní smlouva NÁVRH (draft) for a Czech advokát (or notář) to review and
complete. It is not legal advice and binds no one: the dashboard writes what
the listing knows, and leaves every line a listing cannot know as a
"[Doplnit]" placeholder for the lawyer.

What it is built on, kept general on purpose: a purchase contract under the
civil code (zákon č. 89/2012 Sb., § 2079 a násl.); ownership passes on the
entry (vklad) into the katastr nemovitostí (zákon č. 256/2013 Sb.); the
price is usually held in escrow (advokátní, notářská or bankovní úschova)
until the vklad is made. A unit (jednotka) in a building of an SVJ comes
with its share in the common parts, which the lawyer fills in from the LV.

build_internal_analysis_cz() is the deal's numbers — for you, never sent with
the draft (as modules/contract_draft keeps them apart for Slovakia).
"""

from __future__ import annotations

from datetime import datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import markets

FILL = "[Doplnit]"
_NBSP = " "
_RULE = "━" * 58


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in ("", "UNKNOWN"))


def _text(v, fallback: str = FILL) -> str:
    return fallback if _blank(v) else str(v).strip()


def czk(v, decimals: int = 0, signed: bool = False) -> str:
    """4500000 → '4 500 000 Kč'. None → '—'."""
    if v is None:
        return "—"
    return markets.format_money(v, "CZK", decimals=decimals, signed=signed)


def _size(v) -> str:
    if _blank(v):
        return FILL
    v = float(v)
    s = f"{v:,.{0 if v.is_integer() else 1}f}".replace(",", _NBSP).replace(".", ",")
    return f"{s}{_NBSP}m²"


def build_contract_draft_cz(listing: dict, *, buyer_name: str, buyer_ico: str = "",
                            ownership: str = "Personal", agreed_price: float = 0,
                            deposit: float = 0, lawyer: str = "", escrow: bool = True,
                            generated_at: datetime | None = None) -> str:
    """The draft for the Czech lawyer: the unit, the parties, the price and
    the conditions. Nothing from the deal analysis goes in it."""
    now = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    l = listing
    lv_no = l.get("lv_number")
    lv_line = (f"č. {str(lv_no).strip()} (ověřit výpisem z KN před podpisem)"
               if not _blank(lv_no) else f"{FILL} — ověřit výpisem z KN před podpisem")
    floor = l.get("floor")
    floor = FILL if floor is None else f"{int(floor)}"
    sro = ownership in ("s.r.o.", "SRO")
    ico = (buyer_ico or "").strip() or (FILL if sro else "— (fyzická osoba)")
    if escrow:
        payment = ("✅ Úschova kupní ceny (advokátní / notářská / bankovní) do provedení "
                   "vkladu vlastnického práva — doporučeno")
        term5 = ("Kupní cena bude složena do úschovy a vyplacena prodávajícímu po "
                 "provedení vkladu vlastnického práva kupujícího do katastru nemovitostí "
                 "bez dalších zápisů, které by kupujícího omezovaly.")
    else:
        payment = "⚠️ Přímá platba prodávajícímu — nedoporučeno"
        term5 = "Kupní cena bude uhrazena na účet prodávajícího po podpisu smlouvy."

    return f"""\
╔══════════════════════════════════════════════════════════╗
║        KUPNÍ SMLOUVA — NÁVRH / DRAFT (ČESKÁ REPUBLIKA)   ║
╚══════════════════════════════════════════════════════════╝

Vygenerováno:  {now}
Stav:          NÁVRH k posouzení a dopracování advokátem — není právní rada
Verze:         Sovereign RE Dashboard v2026

{_RULE}

Čl. 1. PŘEDMĚT KOUPĚ

Nemovitost:   {_text(l.get('title'), '—')}
Adresa:       {_text(l.get('address_raw'))}
Lokalita:     {_text(l.get('district'))}
Podlahová plocha: {_size(l.get('size_m2'))}
Energetická náročnost (PENB): {_text(l.get('energy_class'))}

Katastrální území:    {_text(l.get('cadastral_area'))}
List vlastnictví:     {lv_line}
Jednotka č.:          {FILL}
Budova č. p.:         {FILL}, na pozemku parc. č. {_text(l.get('cadastral_number'))}
Podlaží:              {floor}
Podíl na společných částech nemovité věci: {FILL}
Druh vlastnictví:     {FILL} (osobní / družstevní — u družstevního bytu
                      jde o převod družstevního podílu, ne o tuto smlouvu)
(Údaje o jednotce doplní a podle výpisu z katastru ověří advokát.)

{_RULE}

Čl. 2. SMLUVNÍ STRANY

KUPUJÍCÍ:
  Jméno / firma:     {buyer_name}
  IČO:               {ico}
  Forma:             {"s.r.o." if sro else "fyzická osoba"}

PRODÁVAJÍCÍ:
  {FILL} — ověří advokát (totožnost a vlastnické právo podle LV)

{_RULE}

Čl. 3. KUPNÍ CENA

Sjednaná kupní cena:  {czk(agreed_price)}
Záloha / rezervace:   {czk(deposit)}
Doplatek:             {czk(agreed_price - deposit)}

Způsob úhrady:
  {payment}

{_RULE}

Čl. 4. PODMÍNKY (k posouzení advokátem)

1. Smlouva se uzavírá podle § 2079 a násl. zákona č. 89/2012 Sb.,
   občanský zákoník; podpisy stran budou úředně ověřeny.
2. Vlastnické právo přechází vkladem do katastru nemovitostí; návrh na
   vklad podají strany po podpisu (zákon č. 256/2013 Sb.).
3. Prodávající prohlašuje, že jednotka nemá právní vady ani zápisy, o nichž
   by kupujícího neinformoval — zejména zástavní právo, exekuci, věcné
   břemeno, předkupní právo či poznámku spornosti; případné zástavní právo
   banky bude z kupní ceny vyplaceno a vymazáno.
4. Prodávající doloží potvrzení správce domu (SVJ) o dluzích spojených
   s jednotkou a předá průkaz energetické náročnosti budovy.
5. {term5}

{_RULE}

Čl. 5. ADVOKÁT / NOTÁŘ

Zpracovatel:  {(lawyer or '').strip() or '[Určit advokáta / notáře]'}
Datum:        {FILL}
Místo:        {FILL}

{_RULE}

⚠️  PRÁVNÍ UPOZORNĚNÍ

Tento dokument je počítačem vygenerovaný NÁVRH bez právní závaznosti a
nejde o právní radu. Před použitím jej musí posoudit, doplnit a upravit
advokát nebo notář s oprávněním v České republice. Vždy si bezprostředně
před podpisem opatřete aktuální výpis z listu vlastnictví.

{_RULE}
Generated by Sovereign RE Dashboard · Private Use Only"""


def build_internal_analysis_cz(listing: dict, *, agreed_price: float = 0,
                               generated_at: datetime | None = None) -> str:
    """The deal's numbers and the dashboard's LV verdict — for you, not for
    the lawyer."""
    now = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    l = listing
    nry = l.get("net_rental_yield")
    yield_str = ("—" if nry is None else
                 f"{'−' if nry < 0 else ''}{abs(nry) * 100:.2f}".replace(".", ",") + f"{_NBSP}%")
    return f"""\
FINANČNÍ ANALÝZA — INTERNÍ, NEPOSÍLAT ADVOKÁTOVI
{_text(l.get('title'), '—')} · {_text(l.get('district'), '—')}
Vygenerováno:        {now}

Cena v návrhu:       {czk(agreed_price)}
Přebytek s.r.o./měs.: {czk(l.get('surplus_sro'), signed=True)}
Roční rozdíl s.r.o.: {czk(l.get('annual_sro_saving'), signed=True)}
Čistý výnos:         {yield_str}
Ověření LV:          {_text(l.get('lv_status'), 'PENDING')} — VÝPIS Z LV OVĚŘIT 48 H PŘED PODPISEM"""

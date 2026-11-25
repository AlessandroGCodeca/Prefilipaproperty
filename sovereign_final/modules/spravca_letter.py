"""
modules/spravca_letter.py — the letter to the building's manager (správca /
spoločenstvo vlastníkov; in Czechia the SVJ or its správce) asking what the
title deed never shows: whether the flat owes the building anything, the
repair fund's balance, the building's loans and the works coming.

build_letter(listing) returns the text in the listing's own language, the
facts the dashboard has filled in and the rest left as "[____]" to complete.
A draft to adapt and send, not legal advice.
"""

from __future__ import annotations

FILL = "[____]"


def _v(value) -> str:
    text = str(value or "").strip()
    return text if text else FILL


def build_letter(l: dict, buyer: str = "", contact: str = "", today: str = "") -> str:
    """The letter for one listing row (database.get_all_active()'s shape)."""
    from datetime import date
    today = today or date.today().strftime("%d.%m.%Y")
    if (l.get("market") or l.get("_market") or "sk") == "cz":
        return _cz(l, buyer, contact, today)
    return _sk(l, buyer, contact, today)


def _sk(l: dict, buyer: str, contact: str, today: str) -> str:
    return f"""{_v(buyer)}
{_v(contact)}

Správca bytového domu / Spoločenstvo vlastníkov bytov
{_v(l.get('address_raw') or l.get('district'))}

V {FILL}, dňa {today}

Vec: Žiadosť o potvrdenie o bezdlžnosti a o informácie o dome — byt č. {FILL}

Vážená pani / Vážený pán,

som záujemca o kúpu bytu č. {FILL} v dome {_v(l.get('address_raw') or l.get('district'))}
(list vlastníctva č. {_v(l.get('lv_number'))}, katastrálne územie {_v(l.get('cadastral_area'))}),
ktorého vlastníkom je {FILL}. Pred podpisom kúpnej zmluvy Vás prosím o:

1. potvrdenie, že vlastník bytu nemá voči správcovi alebo spoločenstvu žiadne
   nedoplatky na zálohových platbách za služby ani na príspevkoch do fondu
   prevádzky, údržby a opráv, ku dňu vydania (potvrdenie o bezdlžnosti);
2. aktuálny zostatok fondu prevádzky, údržby a opráv domu a mesačný príspevok
   pripadajúci na tento byt;
3. informáciu, či dom spláca úver (banke alebo ŠFRB), v akej výške a do kedy;
4. opravy, rekonštrukcie a mimoriadne príspevky schválené alebo navrhnuté na
   najbližšie tri roky;
5. posledné ročné vyúčtovanie služieb za byt a výšku mesačného predpisu záloh;
6. kópie posledných revízií výťahu, plynu a elektroinštalácie, ak ich máte;
7. informáciu, či sa voči vlastníkovi bytu vymáha pohľadávka domu, prípadne
   či sa uplatňuje záložné právo podľa § 15 zákona č. 182/1993 Z. z.

Potvrdenie o bezdlžnosti sa vydáva vlastníkovi bytu. Ak je potrebný jeho
súhlas, predávajúci túto žiadosť podpíše spolu so mnou.

Ďakujem za odpoveď na adresu uvedenú vyššie.

S pozdravom

{_v(buyer)}


Súhlas vlastníka bytu (predávajúceho) s poskytnutím údajov:

................................................
{FILL}, vlastník bytu č. {FILL}

---
NÁVRH vytvorený dashboardom MFC PROPERTY — doplňte údaje v {FILL} a pred
odoslaním ho skontrolujte. Nejde o právnu radu.
"""


def _cz(l: dict, buyer: str, contact: str, today: str) -> str:
    return f"""{_v(buyer)}
{_v(contact)}

Společenství vlastníků jednotek / správce domu
{_v(l.get('address_raw') or l.get('district'))}

V {FILL} dne {today}

Věc: Žádost o potvrzení o dluzích a informace o domě — jednotka č. {FILL}

Vážená paní / Vážený pane,

mám zájem koupit jednotku č. {FILL} v domě {_v(l.get('address_raw') or l.get('district'))}
(list vlastnictví č. {_v(l.get('lv_number'))}, katastrální území {_v(l.get('cadastral_area'))}),
jejímž vlastníkem je {FILL}. Před podpisem kupní smlouvy Vás prosím o:

1. potvrzení osoby odpovědné za správu domu o tom, zda a jaké dluhy
   vlastníka jednotky vůči společenství nebo správci existují (potvrzení
   o bezdlužnosti), ke dni vydání;
2. aktuální zůstatek fondu oprav a měsíční příspěvek připadající na jednotku;
3. informaci, zda dům splácí úvěr, v jaké výši a do kdy;
4. opravy, rekonstrukce a mimořádné příspěvky schválené nebo navržené na
   nejbližší tři roky;
5. poslední roční vyúčtování služeb za jednotku a výši měsíčních záloh;
6. kopie posledních revizí výtahu, plynu a elektroinstalace, máte-li je;
7. informaci, zda se vůči vlastníkovi vymáhá dluh vůči domu.

Potvrzení se vydává vlastníkovi jednotky. Je-li potřeba jeho souhlas,
prodávající tuto žádost podepíše spolu se mnou.

Děkuji za odpověď na adresu uvedenou výše.

S pozdravem

{_v(buyer)}


Souhlas vlastníka jednotky (prodávajícího) s poskytnutím údajů:

................................................
{FILL}, vlastník jednotky č. {FILL}

---
NÁVRH vytvořený dashboardem MFC PROPERTY — doplňte údaje v {FILL} a před
odesláním jej zkontrolujte. Nejde o právní radu.
"""

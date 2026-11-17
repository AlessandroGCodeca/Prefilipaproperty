"""
modules/seller_check.py — who sells the flat, and whether the registers know
something about them that the title deed doesn't show yet: an insolvency
opened last week, a company being wound up. A seller in insolvency can't sell
(the administrator does); an execution can reach the flat before the deed
records it.

  owners(text, market)   — the owners named in the deed: part B of a Slovak
                           LV, part A of a Czech výpis; each with the IČO
                           when it is a company.
  check_company(ico, market) — a company in the free registers:
      Czechia: ARES (ares.gov.cz) — name, dissolution, and whether the
               insolvency register (ISIR) lists it.
      Slovakia: Register účtovných závierok (registeruz.sk) — name, founded,
               dissolved. Slovak insolvency has no public API: a link.
  links(market)          — the registers to search by hand, for a person:
                           insolvency (free) and executions (a small fee).

Persons are never looked up automatically: their names stay in your
database, and the searches are yours to make.
"""

from __future__ import annotations

import re

from modules.lv_screen import fold

ARES = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
RUZ_IDS = "https://www.registeruz.sk/cruz-public/api/uctovne-jednotky"
RUZ_ONE = "https://www.registeruz.sk/cruz-public/api/uctovna-jednotka"
TIMEOUT_S = 20

LINKS = {
    "sk": (
        ("Insolvency register (free)", "https://replik.justice.sk/ru-verejnost-web/"),
        ("Executions — Centrálny register exekúcií (a fee per lookup)", "https://www.cre.sk/"),
        ("Companies — Obchodný register", "https://www.orsr.sk/"),
        ("Insolvency notices — Obchodný vestník", "https://obchodnyvestnik.justice.gov.sk/"),
    ),
    "cz": (
        ("Insolvency register ISIR (free)", "https://isir.justice.cz/isir/common/index.do"),
        ("Executions — Centrální evidence exekucí (a fee per lookup)", "https://www.ceecr.cz/"),
        ("Companies — Veřejný rejstřík", "https://or.justice.cz/ias/ui/rejstrik"),
    ),
}

_ICO_RE = re.compile(r"I[ČC]O\s*:?\s*(\d{8})(?!\d)|I[ČC]O\s*:?\s*(\d{2}\s?\d{3}\s?\d{3})(?!\d)")
_COMPANY_RE = re.compile(r"\b(?:s\.\s?r\.\s?o\.|spol\.\s?s\s?r\.\s?o\.|a\.\s?s\.|k\.\s?s\.|"
                         r"v\.\s?o\.\s?s\.|družstvo|j\.\s?s\.\s?a\.)", re.I)


def owner_part(text: str, market: str = "sk") -> str:
    """The deed's owners: part B of a Slovak LV (up to part C), part A of a
    Czech výpis (up to part B)."""
    if not text:
        return ""
    folded = fold(text)
    if market == "cz":
        start = re.search(r"(?<!\w)a\s+vlastnik", folded)
        end = re.search(r"(?<!\w)b\s+(?:nemovitosti|jiny\s+opravneny|nemovitost)|(?<!\w)b1?\s+jina\s+prava"
                        r"|(?<!\w)c\s+(?:zatizeni|omezeni)", folded[start.end():]) if start else None
    else:
        start = re.search(r"cast\s*b\b", folded)
        end = re.search(r"cast\s*c\b", folded[start.end():]) if start else None
    if not start:
        return ""
    stop = start.end() + end.start() if end else len(text)
    return text[start.start():stop].strip()


def owners(text: str, market: str = "sk") -> list[dict]:
    """[{"name", "ico", "company"}] for each owner the deed names. A name is
    best-effort (the deed's layout varies); an IČO is exact."""
    part = owner_part(text, market)
    if not part:
        return []
    if market == "cz":
        # One owner a line, under "Vlastnické právo" / "SJM" headings.
        body = re.sub(r"^\s*A\s+Vlastník,\s*jiný\s+oprávněný", "", part, count=1, flags=re.I)
        entries = [ln for ln in body.splitlines()
                   if "," in ln and not re.match(r"\s*(?:Identifikátor|Podíl|Vlastnické právo\s*$)",
                                                 ln, re.I)] or [body]
    else:
        body = re.sub(r"^ČASŤ\s*B\s*:?\s*(?:VLASTN\w*(?:\s+A\s+INÉ\s+OPRÁVNENÉ\s+OSOBY)?)?", "",
                      part, count=1, flags=re.I)
        # Slovak entries are numbered: "1 Novák Ján, ..." / "2 XYZ s.r.o., ...".
        chunks = re.split(r"(?:^|\s)(\d{1,3})\s+(?=[A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ\[])", body)
        entries = [c for c in chunks if c and not c.isdigit()] if len(chunks) > 1 else [body]
    out, seen = [], set()
    for e in entries:
        e = e.strip()
        ico = _ICO_RE.search(e)
        ico = re.sub(r"\s", "", (ico.group(1) or ico.group(2))) if ico else ""
        name = re.split(r",|\s(?:nar\.|r\.\s?č\.|dátum narodenia|Spoluvlastnícky|IČO)", e,
                        maxsplit=1)[0].strip(" ;:")
        name = re.sub(r"^(?:Vlastnické právo|SJM|Spoluvlastnictví)\s+", "", name)
        if not name or len(name) > 120 or name.lower().startswith(("titul", "poznámka", "iné")):
            continue
        key = ico or name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "ico": ico, "company": bool(ico or _COMPANY_RE.search(e))})
    return out


def check_company(ico: str, market: str = "sk", get=None) -> dict:
    """{"ico", "name", "status", "warnings": [...], "source"} from the free
    register of the company's country. "warnings" is empty when nothing is
    wrong; an unreachable register says so in "status"."""
    import requests
    get = get or requests.get
    ico = re.sub(r"\D", "", ico or "")
    out = {"ico": ico, "name": "", "status": "", "warnings": [], "source": ""}
    try:
        if market == "cz":
            out["source"] = "ARES"
            r = get(ARES.format(ico=ico), timeout=TIMEOUT_S, headers={"Accept": "application/json"})
            if r.status_code == 404:
                out["status"] = "not in ARES"
                out["warnings"].append("ARES doesn't know this IČO — check the number on the deed.")
                return out
            r.raise_for_status()
            d = r.json()
            out["name"] = d.get("obchodniJmeno") or ""
            regs = d.get("seznamRegistraci") or {}
            if regs.get("stavZdrojeIr") == "AKTIVNI":
                out["warnings"].append("Listed in the insolvency register (ISIR): a company in "
                                       "insolvency can't sell on its own — open ISIR.")
            if d.get("datumZaniku"):
                out["warnings"].append(f"Dissolved on {d['datumZaniku']}.")
            if regs.get("stavZdrojeVr") not in (None, "AKTIVNI") and not d.get("datumZaniku"):
                out["warnings"].append("Not active in the commercial register.")
            out["status"] = "checked"
        else:
            out["source"] = "Register účtovných závierok"
            r = get(RUZ_IDS, timeout=TIMEOUT_S, params={"zmenene-od": "2000-01-01", "ico": ico})
            r.raise_for_status()
            ids = r.json().get("id") or []
            if not ids:
                out["status"] = "not in the register"
                out["warnings"].append("The register of financial statements doesn't know this "
                                       "IČO — check it in the Obchodný register.")
                return out
            r = get(RUZ_ONE, timeout=TIMEOUT_S, params={"id": ids[-1]})
            r.raise_for_status()
            d = r.json()
            out["name"] = d.get("nazovUJ") or ""
            if d.get("datumZrusenia"):
                out["warnings"].append(f"Dissolved on {d['datumZrusenia']}.")
            out["status"] = "checked (no insolvency data: search the register by hand)"
    except Exception as e:
        out["status"] = f"register not reachable ({type(e).__name__})"
    return out


def links(market: str = "sk") -> tuple[tuple[str, str], ...]:
    return LINKS["cz" if market == "cz" else "sk"]

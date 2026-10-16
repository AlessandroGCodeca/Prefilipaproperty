"""
scraper/czech_cases.py — the locative case of Czech place names.

A Czech listing says where the flat is in the locative, after "v" / "ve" (or
"na" for some places): "byt v Praze", "v Brně", "v Ostravě", "v Plzni",
"v Pardubicích", "ve Zlíně", "v Hradci Králové", "v Ústí nad Labem", "na
Kladně". Matching only the nominative ("Praha") missed all of them. As with
scraper/slovak_cases (whose rules are Slovak and not reused here), only the
locative is generated: "do Prahy", "u Brna", "za Prahou" say where the flat
is NOT.

The rules cover the paradigms of the place names this app matches (the
okresy and city parts in engine/regional_prices_cz — RÚIAN's names); the
irregular words are listed outright. Where a hard-consonant masculine can go
either way ("v Mostě" / "v Mostu") both forms are generated: a form that
never occurs costs nothing.
"""

from __future__ import annotations

_IRREGULAR = {
    "praha":   ("praze",),
    "brno":    ("brně",),
    "plzeň":   ("plzni",),
    "olomouc": ("olomouci",),
    "nymburk": ("nymburce",),
    "vary":    ("varech",),           # Karlovy Vary → v Karlových Varech
    "karlovy": ("karlových",),
    "králové": ("králové",),          # Hradec Králové: a genitive, unchanged
    "ústí":    ("ústí",),
    "karviná": ("karviné",),
    "hora":    ("hoře",),             # Kutná Hora → v Kutné Hoře
    "lípa":    ("lípě",),             # Česká Lípa → v České Lípě
    "boleslav": ("boleslavi",),       # Mladá Boleslav → v Mladé Boleslavi
    "svitavy": ("svitavách",),
    "semily":  ("semilech",),
    "louny":   ("lounech",),
    "klatovy": ("klatovech",),
    "rokycany": ("rokycanech",),
    "tábor":   ("táboře",),
    "cheb":    ("chebu",),
    "most":    ("mostě", "mostu"),
    "jeseník": ("jeseníku",),
    "pole":    ("poli",),             # Královo Pole → v Králově Poli
    "královo": ("králově",),
}
# Soft finals: masculine and feminine nouns ending in them take -i.
_SOFT = ("c", "č", "ř", "š", "ž", "j", "ť", "ď", "ň")
_DEHACEK = {"ť": "t", "ď": "d", "ň": "n"}
# Hard stem consonant + -ě/-e (feminine -a, neuter -o, masculine -ov/-ín …).
_E_AFTER = {"d": "dě", "t": "tě", "n": "ně", "b": "bě", "p": "pě", "v": "vě",
            "f": "fě", "m": "mě", "r": "ře", "l": "le", "s": "se", "z": "ze"}


def _hard_e(stem: str) -> str:
    """stem + the locative -ě / -e, the stem's last consonant softened:
    Ostrav-a → Ostravě, Jihlav-a → Jihlavě, Kladn-o → Kladně."""
    last = stem[-1]
    if last in ("h", "g"):
        return stem[:-1] + "ze"
    if last == "k":
        return stem[:-1] + "ce"
    if stem.endswith("ch"):
        return stem[:-2] + "še"
    return stem[:-1] + _E_AFTER.get(last, last + "e")


def locative(word: str) -> tuple[str, ...]:
    """Locative form(s) of one word of a Czech place name, lower-cased."""
    w = word.lower()
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    if w in ("a", "") or w.isdigit() or not w[-1].isalpha():
        return (w,)                               # "Praha 2", "… a Obřany"
    if "-" in w:                                  # Frýdek-Místek → Frýdku-Místku
        parts = [locative(p) for p in w.split("-")]
        return tuple("-".join(c) for c in _product(parts))
    # Adjectives: Nový / Český → Novém / Českém; Mladá / Kutná → Mladé /
    # Kutné; Uherské (neuter) → Uherském; Jindřichův → Jindřichově.
    if w.endswith("ý"):
        return (w[:-1] + "ém",)
    if w.endswith("á"):
        return (w[:-1] + "é",)
    if w.endswith("é"):
        return (w + "m",)
    if w.endswith("ův"):
        return (w[:-2] + "ově",)
    # Plurals: Pardubice / Teplice → Pardubicích / Teplicích.
    if w.endswith("ice") or w.endswith("ce"):
        return (w[:-1] + "ích",)
    if w.endswith("y"):                           # Klatovy-type, both genders
        return (w[:-1] + "ech", w[:-1] + "ách")
    # Neuter -iště / -ště → -išti / -šti; -í stays (Ústí).
    if w.endswith("ště"):
        return (w[:-1] + "i",)
    if w.endswith("í"):
        return (w,)
    if w.endswith("a"):
        stem = w[:-1]
        if stem.endswith(_SOFT):
            return (stem + "i",)
        return (_hard_e(stem),)
    if w.endswith("o"):
        stem = w[:-1]
        if stem.endswith("k"):                    # Blansko → Blansku
            return (stem + "u",)
        return (_hard_e(stem),)
    # Mobile -e-: Liberec → Liberci, Písek → Písku, Frýdek → Frýdku, Líšeň → Líšni.
    if w.endswith("eň"):
        return (w[:-2] + "ni",)
    if w.endswith("ec"):
        return (w[:-2] + "ci",)
    if w.endswith("ek"):
        return (w[:-2] + "ku",)
    if w.endswith(_SOFT):                         # Třebíč → Třebíči, Kroměříž → Kroměříži
        return (w[:-1] + _DEHACEK.get(w[-1], w[-1]) + "i",)
    if w.endswith(("slav", "clav")) or w.endswith(("im", "am")):
        return (w + "i",)                         # Břeclav → Břeclavi, Chrudim → Chrudimi
    if w.endswith(("ov", "ín", "ýn")):
        return (w + "ě",)                         # Sokolov → Sokolově, Zlín → Zlíně
    if w.endswith("k"):
        return (w + "u",)                         # Šumperk → Šumperku, Mělník → Mělníku
    if w.endswith(("h", "ch", "g")):
        return (w + "u",)
    # Any other hard consonant: Beroun → Berouně, Náchod → Náchodě, Bruntál →
    # Bruntále, Brod → Brodě — and the -u form some take.
    return (w[:-1] + _E_AFTER.get(w[-1], w[-1] + "e"), w + "u")


def _product(parts):
    out = [()]
    for alts in parts:
        out = [o + (a,) for o in out for a in alts]
    return out


def locative_words(name: str) -> list[tuple[str, ...]]:
    """Per-word locative alternatives for a place name. Words from "nad",
    "pod" or "u" on ("Ústí nad Labem", "Žďár nad Sázavou") stay as written."""
    out: list[tuple[str, ...]] = []
    words = name.split()
    for i, word in enumerate(words):
        if i and word.lower() in ("nad", "pod", "u"):
            out.extend((w.lower(),) for w in words[i:])
            break
        nxt = words[i + 1].lower() if i + 1 < len(words) else ""
        w = word.lower()
        if w.endswith(("é", "á", "ý")) and nxt.endswith(("ice", "ce", "y")) \
                and w not in _IRREGULAR:
            # An adjective before a plural noun: České Budějovice → Českých
            # Budějovicích, Moravské Budějovice → Moravských Budějovicích.
            out.append((w[:-1] + "ých",))
            continue
        out.append(locative(word))
    return out


def locative_phrases(name: str) -> list[str]:
    """Every whole locative form of a place name ("Hradec Králové" →
    ["hradci králové"])."""
    return [" ".join(p) for p in _product(locative_words(name))]

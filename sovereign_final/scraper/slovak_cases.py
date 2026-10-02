"""
scraper/slovak_cases.py — the locative case of Slovak place names.

Listings say where a flat is in the locative: "byt v Nitre", "v Žiline",
"v Košiciach", "v Petržalke", "v Banskej Bystrici". Matching only the
nominative ("Nitra") missed all of them.

Only the locative is generated, and scraper.nehnutelnosti only accepts it
after "v"/"vo" — the case that says the flat is IN the place. The genitive and
instrumental forms mostly say where it is NOT: "20 min do Bratislavy",
"blízko Nitry", "za Bratislavou". Matching those would send a Senec flat
advertised as "20 min do Bratislavy" to Bratislava.

The rules cover the paradigms of the place names the scrapers know; a few
irregular words are listed outright.
"""

# ď ť ň ľ lose their háček before e/i: Vrakuňa → Vrakuni, Šaľa → Šali.
_SOFTENED = {"ň": "n", "ľ": "l", "ť": "t", "ď": "d"}
# Soft-stem consonants: feminines in -a take -i (Bystrica → Bystrici),
# masculines take -i (Lamač → Lamači).
_SOFT_FINALS = ("c", "č", "ň", "ľ", "ť", "ď", "j", "š", "ž")

_IRREGULAR = {
    "ves":       ("vsi",),           # Karlova Ves → Karlovej Vsi (vowel drops)
    "žiar":      ("žiari",),         # Žiar nad Hronom → v Žiari nad Hronom
    "karlova":   ("karlovej",),      # possessive adjective
    "revúca":    ("revúcej",),       # declines like an adjective
    "malacky":   ("malackách",),
    "zámky":     ("zámkoch",),
    "vajnory":   ("vajnoroch",),
    "piešťany":  ("piešťanoch",),
    "topoľčany": ("topoľčanoch",),
}


def locative(word: str) -> tuple[str, ...]:
    """Locative form(s) of one word of a place name, lower-cased."""
    w = word.lower()
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    # Adjectives: Liptovský, Banská, Devínska, Nové / Staré / Zlaté, Partizánske
    if w.endswith("ý"):
        return (w[:-1] + "om",)
    if w.endswith("á") or w.endswith(("ska", "cka")):
        return (w[:-1] + "ej",)
    if w.endswith("é"):
        # neuter singular (Nové Mesto → Novom Meste) or plural
        # (Nové Zámky → Nových Zámkoch)
        return (w[:-1] + "om", w[:-1] + "ých")
    if w.endswith(("ske", "cke")):
        return (w[:-1] + "om",)
    # Plurals in -ce / -ice: Košice → Košiciach, Michalovce → Michalovciach
    if w.endswith("ce"):
        return (w[:-1] + "iach",)
    # Mobile vowel: Senec → Senci, Pezinok → Pezinku
    if w.endswith("ec"):
        return (w[:-2] + "ci",)
    if w.endswith("ok"):
        return (w[:-2] + "ku",)
    if w.endswith("a"):
        stem = w[:-1]
        if stem.endswith(_SOFT_FINALS):
            return (stem[:-1] + _SOFTENED.get(stem[-1], stem[-1]) + "i",)
        return (stem + "e",)                     # Žilina → Žiline
    if w.endswith("o"):
        return (w[:-1] + "e",)                   # Mesto → Meste, Komárno → Komárne
    if w.endswith(_SOFT_FINALS):
        return (w + "i",)                        # Lamač → Lamači, Mikuláš → Mikuláši
    return (w + "e",)                            # Prešov → Prešove, Poprad → Poprade


def locative_words(name: str) -> list[tuple[str, ...]]:
    """Per-word locative alternatives for a place name. Words from "nad" on
    ("nad Váhom", "nad Hronom") are already instrumental and stay as written."""
    out: list[tuple[str, ...]] = []
    words = name.split()
    for i, word in enumerate(words):
        if word.lower() == "nad":
            out.extend((w,) for w in words[i:])
            break
        out.append(locative(word))
    return out

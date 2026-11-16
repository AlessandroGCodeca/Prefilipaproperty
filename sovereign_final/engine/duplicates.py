"""
engine/duplicates.py — the same flat listed on several portals.

An agency puts one flat on nehnutelnosti, topreality and bazos at once, and a
seller often reposts it on the same portal through a second agency. Each copy
is its own row, scored on its own, so one flat can fill three slots of the
shortlist. group_duplicates() finds the copies; database.mark_duplicates()
stores the grouping so the dashboard can show one row with "listed on 3
portals" and links to every copy.

Two listings are the same flat when all of these hold:
  - they are in the same market (a Slovak and a Czech listing never match);
  - the district resolves to the same rent key (engine.financial.match_rent_key),
    with a Bratislava city part counted as its administrative district —
    or, when that key is only the "default" fallback, the raw district
    strings are equal;
  - the floor areas are within SIZE_TOLERANCE_M2 (or SIZE_TOLERANCE_PCT);
  - the asking prices are within PRICE_TOLERANCE_PCT (portals lag each other
    on price cuts, so exact equality would miss real copies);
  - the room counts agree whenever both listings state one;
  - the floors agree whenever both listings state one;
  - nothing else says they differ: map pins more than PIN_SAME_M apart, or
    two different streets;
  - and something says they are one: map pins within PIN_SAME_M, the same
    street, the same first photo — or, with none of these to go by, floor
    areas within EXACT_SIZE_M2 (two portals' rounding of one figure).
A panel-built district is full of flats of the same floor area at near the
same price; without the last two rules three of them on floors 2, 7 and
"unknown" came out as one flat (audit of 12 Nov 2026, finding 6).

Copies are grouped transitively — portals lag each other on price cuts, so
A ~ B and B ~ C group all three — but never through a member that
contradicts another: a flat on floor 7 and one on floor 2 are never in one
group, whatever sits between them.

The group's primary listing — the one the dashboard shows — is the copy
whose title deed was verified (LV PASS), then the cheapest (a buyer wants the
lowest asking price on offer), then the one seen first. An LV-rejected copy
is never the primary; see database.mark_duplicates for what it does instead.
"""

from __future__ import annotations

import re
import unicodedata

SIZE_TOLERANCE_M2   = 1.0
SIZE_TOLERANCE_PCT  = 0.015
PRICE_TOLERANCE_PCT = 0.03
# Map pins of one building lie within this of each other (a portal's pin may
# be on the entrance, another's on the roof's centre).
PIN_SAME_M          = 150.0
# With no pin, street or photo to go by, the floor areas must agree to this.
EXACT_SIZE_M2       = 0.5


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _same_size(a: float, b: float) -> bool:
    return abs(a - b) <= max(SIZE_TOLERANCE_M2, SIZE_TOLERANCE_PCT * max(a, b))


def _same_price(a: float, b: float) -> bool:
    return abs(a - b) <= PRICE_TOLERANCE_PCT * max(a, b)


def _agree(a, b) -> bool:
    """Equal, or unknown on either side."""
    if a is None or b is None:
        return True
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return True


def _pin(row):
    """The portal's own map pin (lat, lng), or None — a geocoded point says
    only where the district is."""
    if row.get("coords_source") != "listing":
        return None
    lat, lng = row.get("lat"), row.get("lng")
    return (lat, lng) if lat is not None and lng is not None else None


def _metres(p, q) -> float:
    import math
    dy = (p[0] - q[0]) * 111_000
    dx = (p[1] - q[1]) * 111_000 * math.cos(math.radians((p[0] + q[0]) / 2))
    return math.hypot(dx, dy)


# A street and its house number: "Hálova 12", "Námestie SNP 3/A", "ul. 1. mája 7".
_STREET_RE = re.compile(r"((?:[^\W\d_][\w.]*\s+){0,3}?[^\W\d_][\w.]{2,})\s+\d+[a-z]?(?:/\d+[a-z]?)?(?!\w)")
_NOT_A_STREET = {"byt", "izba", "izbovy", "izbovy byt", "poschodie", "podlazie", "m2", "okres",
                 "bratislava", "kosice", "praha", "brno", "cast", "psc"}


def _street(row) -> str | None:
    """The street named in the listing's address, folded ("halova"); None
    when it names none."""
    addr = _fold(row.get("address_raw") or "")
    addr = re.sub(r"(?<!\w)(?:ul\.|ulica|ulice|nam\.)\s*", "", addr)
    for m in _STREET_RE.finditer(addr):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .")
        if name and name.split()[-1] not in _NOT_A_STREET and name not in _NOT_A_STREET:
            return name
    return None


def _photo(row) -> str:
    """The first photo's address without its size or cache parameters."""
    url = (row.get("primary_image_url") or "").strip()
    return url.split("?", 1)[0].lower()


def contradict(a: dict, b: dict) -> bool:
    """Something says these are two flats: a different room count, floor or
    floor area, pins far apart, or two streets."""
    if not (_agree(a.get("rooms"), b.get("rooms")) and _agree(a.get("floor"), b.get("floor"))):
        return True
    if not _same_size(a["size_m2"], b["size_m2"]):
        return True
    pa, pb = _pin(a), _pin(b)
    if pa and pb and _metres(pa, pb) > PIN_SAME_M:
        return True
    sa, sb = _street(a), _street(b)
    return bool(sa and sb and sa != sb)


def evidence(a: dict, b: dict) -> bool:
    """Something says these are one flat: pins close together, the same
    street, the same first photo, or — with none of these to go by — the
    same floor area to within EXACT_SIZE_M2."""
    pa, pb = _pin(a), _pin(b)
    if pa and pb and _metres(pa, pb) <= PIN_SAME_M:
        return True
    sa, sb = _street(a), _street(b)
    if sa and sb and sa == sb:
        return True
    fa, fb = _photo(a), _photo(b)
    if fa and fb and fa == fb:
        return True
    return abs(a["size_m2"] - b["size_m2"]) < EXACT_SIZE_M2


# Portals name a Bratislava flat either by city part ("Ružinov") or by
# administrative district ("Bratislava II"); both mean the same place here.
_BA_PART_TO_DISTRICT = {
    "staré mesto": "bratislava i",
    "ružinov": "bratislava ii", "vrakuňa": "bratislava ii", "podunajské": "bratislava ii",
    "nové mesto": "bratislava iii", "rača": "bratislava iii", "vajnory": "bratislava iii",
    "karlova ves": "bratislava iv", "dúbravka": "bratislava iv", "lamač": "bratislava iv",
    "devínska": "bratislava iv", "záhorská": "bratislava iv",
    "petržalka": "bratislava v", "rusovce": "bratislava v", "jarovce": "bratislava v",
    "čunovo": "bratislava v",
}


def _location_key(row: dict) -> str:
    """Where a listing is, for matching: its market, then its rent key (a
    Bratislava city part as its administrative district) or, with only the
    default key, its raw district. "" when it has no district."""
    import markets
    from engine.financial import match_rent_key
    district = (row.get("district") or "").strip()
    if not district:
        return ""
    market = markets.of_row(row)
    if market == "sk":
        key = match_rent_key(district)
        if key != "default":
            key = _BA_PART_TO_DISTRICT.get(key, key)
    else:
        key = match_rent_key(district, market=market)
        if key == "praha":
            # Prague's rent key is the city's; its districts are apart.
            m = re.search(r"praha\s*[-–]?\s*(\d{1,2})(?!\d)", _fold(district))
            key = f"praha {m.group(1)}" if m else "raw:" + district.lower()
    from engine.financial import rent_fallback_kind
    if key == "default" or (not key.startswith("raw:")
                            and rent_fallback_kind(key, market=market) == "kraj"):
        # A town with only its kraj's rent is its own place, not its kraj.
        key = "raw:" + district.lower()
    return f"{market}:{key}"


def is_same_flat(a: dict, b: dict) -> bool:
    if a["url"] == b["url"]:
        return False
    loc = _location_key(a)
    if not loc or loc != _location_key(b):
        return False
    return (_same_price(a["price_eur"], b["price_eur"])
            and not contradict(a, b) and evidence(a, b))


def _primary_rank(row: dict) -> int:
    """Verified LV first, then unchecked or unverified, LV-rejected last."""
    status = row.get("lv_status")
    return 0 if status == "PASS" else 2 if status == "REJECTED" else 1


def group_duplicates(rows: list[dict]) -> dict[str, str]:
    """{listing id: primary id} for every listing that has at least one copy.

    rows need id, url, district, size_m2, price_eur and optionally rooms,
    floor, scraped_at, lv_status. Rows without a price or size can't be
    compared and are left out. Grouping is transitive (union-find), so A~B and
    B~C put all three together even when A and C are just outside tolerance
    of each other.
    """
    rows = [r for r in rows if (r.get("price_eur") or 0) > 0 and (r.get("size_m2") or 0) > 0]
    parent = {r["id"]: r["id"] for r in rows}
    members = {r["id"]: [r] for r in rows}        # each root's group

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_loc: dict[str, list[dict]] = {}
    for r in rows:
        loc = _location_key(r)
        if loc:
            by_loc.setdefault(loc, []).append(r)

    for bucket in by_loc.values():
        bucket.sort(key=lambda r: r["size_m2"])
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if not _same_size(a["size_m2"], b["size_m2"]):
                    break                       # sorted by size: no more matches
                if is_same_flat(a, b):
                    ra, rb = find(a["id"]), find(b["id"])
                    # Never through a member that contradicts another.
                    if ra != rb and not any(contradict(x, y) for x in members[ra]
                                            for y in members[rb]):
                        parent[rb] = ra
                        members[ra] += members.pop(rb)

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(r)

    out: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        primary = min(members, key=lambda r: (_primary_rank(r), r["price_eur"],
                                              r.get("scraped_at") or "", r["id"]))
        for m in members:
            out[m["id"]] = primary["id"]
    return out


def one_per_flat(rows: list[dict]) -> list[dict]:
    """Keep one copy of each flat among dashboard rows that carry dup_group
    (database.mark_duplicates): the group's primary when it is among `rows`,
    else the copy group_duplicates would pick from the ones left. Rows with
    no group pass through, and the order is kept.

    Run it after the other filters: picking the primary first lost the whole
    flat whenever the primary alone failed a filter (another portal, a price
    over the cap) although a copy that passes was right there."""
    best: dict[str, tuple] = {}
    for r in rows:
        g = r.get("dup_group")
        if not g:
            continue
        key = (r.get("id") != g, _primary_rank(r), r.get("price_eur") or 0,
               r.get("scraped_at") or "", r.get("id") or "")
        if g not in best or key < best[g][0]:
            best[g] = (key, r.get("id"))
    kept = {v[1] for v in best.values()}
    return [r for r in rows if not r.get("dup_group") or r.get("id") in kept]

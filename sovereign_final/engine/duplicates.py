"""
engine/duplicates.py — the same flat listed on several portals.

An agency puts one flat on nehnutelnosti, topreality and bazos at once, and a
seller often reposts it on the same portal through a second agency. Each copy
is its own row, scored on its own, so one flat can fill three slots of the
shortlist. group_duplicates() finds the copies; database.mark_duplicates()
stores the grouping so the dashboard can show one row with "listed on 3
portals" and links to every copy.

Two listings are the same flat when all of these hold:
  - the district resolves to the same rent key (engine.financial.match_rent_key),
    with a Bratislava city part counted as its administrative district —
    or, when that key is only the "default" fallback, the raw district
    strings are equal;
  - the floor areas are within SIZE_TOLERANCE_M2 (or SIZE_TOLERANCE_PCT);
  - the asking prices are within PRICE_TOLERANCE_PCT (portals lag each other
    on price cuts, so exact equality would miss real copies);
  - the room counts agree whenever both listings state one;
  - the floors agree whenever both listings state one.
It is deliberately strict: two identical flats in one new building are the
one realistic false match, and dev projects are hidden by default anyway.

The group's primary listing — the one the dashboard shows — is the copy
whose title deed was verified (LV PASS), then the cheapest (a buyer wants the
lowest asking price on offer), then the one seen first. An LV-rejected copy
is never the primary; see database.mark_duplicates for what it does instead.
"""

from __future__ import annotations

SIZE_TOLERANCE_M2   = 1.0
SIZE_TOLERANCE_PCT  = 0.015
PRICE_TOLERANCE_PCT = 0.03


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
    from engine.financial import match_rent_key
    district = (row.get("district") or "").strip()
    if not district:
        return ""
    key = match_rent_key(district)
    if key == "default":
        return "raw:" + district.lower()
    return _BA_PART_TO_DISTRICT.get(key, key)


def is_same_flat(a: dict, b: dict) -> bool:
    if a["url"] == b["url"]:
        return False
    loc = _location_key(a)
    if not loc or loc != _location_key(b):
        return False
    return (_same_size(a["size_m2"], b["size_m2"])
            and _same_price(a["price_eur"], b["price_eur"])
            and _agree(a.get("rooms"), b.get("rooms"))
            and _agree(a.get("floor"), b.get("floor")))


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
                    if ra != rb:
                        parent[rb] = ra

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

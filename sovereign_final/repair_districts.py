"""
repair_districts.py — correct districts the location matchers sent to
Bratislava, then re-score every listing.

The text matcher in scraper/nehnutelnosti.py (all three scrapers use it)
checked Bratislava's city parts before towns, so "Nové Mesto nad Váhom" and
"Kysucké Nové Mesto" read as Bratislava's Nové Mesto, and Košice's Staré Mesto
as Bratislava's. The URL-slug matcher had no "nove-mesto-nad-vahom", and wrote
six towns without diacritics ("Komarno", "Nove Zamky", ...), which match no
RENT_PER_M2 key. The cashflow engine then priced those flats at Bratislava
rent, or at the €6.50/m² default.

The matchers are fixed, but rows already in the database keep the old value
until their detail page is read again. This re-runs the fixed matchers over
what each suspect row stores (URL slug, title, description) and replaces the
district only when the answer fixes that bug: a town outside Bratislava that
carries the city-part name the row was given, or the accented spelling of an
unaccented town. Anything else is left alone, and so is a row whose stored
text names no place.

Then every cashflow score is cleared and recomputed, the same as 💰 RESCORE
ALL, because engine/financial also stopped pricing "Staré Mesto, Košice" at
Bratislava's rate.

  python3 repair_districts.py [--dry-run]

--dry-run reports what it would change and writes nothing.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.financial import _names_town_outside_bratislava  # noqa: E402
from scraper.nehnutelnosti import _extract_location_from_text, _parse_slug  # noqa: E402

# Bratislava city parts the old matchers gave to other towns.
_GENERIC_PARTS = ("Nové Mesto", "Staré Mesto")
# Towns the old slug matcher wrote without diacritics.
_UNACCENTED = {"Komarno", "Nove Zamky", "Partizanske", "Lucenec", "Sala", "Vrable"}


def _parts(value) -> set:
    return {p.strip() for p in (value or "").split(",") if p.strip()}


def corrected_location(row: dict) -> str:
    """The location the fixed matchers give this row, when it corrects what the
    old ones wrote; "" when there is nothing to correct.

    The first source that names a place decides: the URL slug (nehnutelnosti
    only), then the title and description together, as the rendered page the
    text matcher originally read had them. A Bratislava answer, or one naming
    an unrelated town, leaves the row as it is.
    """
    district = row.get("district") or ""
    stored = _parts(district) | _parts(row.get("address_raw"))
    generic = [p for p in _GENERIC_PARTS if p in stored]
    unaccented = bool(stored & _UNACCENTED)
    if not generic and not unaccented:
        return ""

    slug = ""
    if row.get("source") == "nehnutelnosti":
        slug = _parse_slug(row.get("url") or "").get("district", "")
    text = "\n".join(t for t in (row.get("title"), row.get("description")) if t)

    for found in (slug, _extract_location_from_text(text)):
        if not found:
            continue
        if found == district:
            return ""
        if unaccented and found == slug:
            return found
        if (any(p in found for p in generic)
                and _names_town_outside_bratislava(found.lower())):
            return found
        return ""
    return ""


def _new_address(row: dict, location: str) -> str:
    """address_raw to store alongside a corrected district. It is replaced only
    when it was itself the matcher's output (the district, or "Nové Mesto,
    Bratislava" behind a district cut down to "Bratislava"); a real address
    stays."""
    address = row.get("address_raw") or ""
    if address == (row.get("district") or "") or address in {
        f"{p}, Bratislava" for p in _GENERIC_PARTS
    }:
        return location
    return address


def rederive_districts(dry_run: bool = False) -> list[dict]:
    """Correct every misrouted district. Returns the changes (made, or that
    would be made under dry_run)."""
    from database import get_conn
    markers = ["Mesto", *sorted(_UNACCENTED)]
    where = " OR ".join(
        f"{col} LIKE ?" for _ in markers for col in ("district", "address_raw")
    )
    params = [f"%{m}%" for m in markers for _ in ("district", "address_raw")]

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, source, url, title, description, district, address_raw "
            f"FROM listings WHERE {where}",
            params,
        ).fetchall()
        changes = []
        for r in rows:
            row = dict(zip(
                ("id", "source", "url", "title", "description", "district",
                 "address_raw"), r))
            location = corrected_location(row)
            if not location:
                continue
            changes.append({
                "id": row["id"], "source": row["source"],
                "title": row["title"] or row["url"],
                "old": row["district"] or "", "new": location,
                "address_raw": _new_address(row, location),
            })
        if not dry_run:
            for c in changes:
                conn.execute(
                    "UPDATE listings SET district=?, address_raw=? WHERE id=?",
                    (c["new"], c["address_raw"], c["id"]),
                )
            conn.commit()
    finally:
        conn.close()
    return changes


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv

    from database import init_db, clear_cashflow_scores
    from modules.cashflow_runner import run_scoring
    init_db()

    changes = rederive_districts(dry_run=dry_run)
    for c in changes:
        label = (c["title"] or "")[:44].replace("\n", " ")
        print(f"  [{c['source']}] {label}: {c['old']!r} → {c['new']!r}")
    verb = "would correct" if dry_run else "corrected"
    print(f"\n{verb} {len(changes)} districts")

    if dry_run:
        print("DRY RUN — nothing written, nothing re-scored.")
        return 0

    print("\n♻️  Clearing cashflow scores so the corrected rents take effect...")
    cleared = clear_cashflow_scores()
    scored = run_scoring()
    print(f"✅ {cleared} scores cleared, {scored} listings re-scored.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())

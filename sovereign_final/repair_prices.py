"""
repair_prices.py — re-read listings whose stored price looks like it came from
a different listing, using the current extraction.

Until recently the scrapers took the largest € figure on a detail page as the
sale price. Every nehnutelnosti page also renders a promoted-listings strip, so
that figure was often a neighbouring property's: €1,250,000 ended up on seven
unrelated flats, €1,399,000 on three of 200, 188 and 114 m². The extraction now
reads the listing's own price heading instead — but only for listings it reads
again, and a row with a price and a size already looks complete to
get_fresh_detail_urls(), so the wrong values sit there untouched.

This opens each suspect listing's page and settles it:

  new price found   → stored, replacing the wrong one (or confirming a right one)
  no price on page  → cleared, because the stored value came from the guessing
                      that has since been removed; the row goes back to PENDING
                      for the dev-project harvest or a later read to fill

  python3 repair_prices.py [max_listings] [--dry-run]

Default max_listings=100. --dry-run reports what it would change and writes
nothing. nehnutelnosti only — that is where the page-scanning bug was.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (  # noqa: E402
    get_shared_price_listings, set_listing_price,
)
from scraper.nehnutelnosti import (  # noqa: E402
    SEARCH_PAGE, _open_browser, _scrape_detail_page,
)

SOURCE = "nehnutelnosti"


def _parse_args(argv) -> tuple[int, bool]:
    dry_run = "--dry-run" in argv
    limit = 100
    for a in argv:
        if a.isdigit():
            limit = int(a)
            break
    return limit, dry_run


def repeated_across_sizes(proposals) -> set:
    """Ids whose proposed price would land on listings of more than one size.

    A read that returns the same price for differently-sized flats has read
    something other than those flats — the exact fault being repaired. Left
    unchecked, the first repair run replaced one shared price with another,
    writing €697,800 onto seven listings of 104 to 178 m², and gave different
    answers on two passes minutes apart because the carousel it was reading
    rotates. So a proposal that repeats is not written.
    """
    sizes_by_price: dict = {}
    for p in proposals:
        if not p["price"]:
            continue
        sizes_by_price.setdefault(p["price"], set()).add(
            round(float(p["size_m2"] or 0), 2)
        )
    repeated = {price for price, sizes in sizes_by_price.items() if len(sizes) > 1}
    return {p["id"] for p in proposals if p["price"] in repeated}


def _read_proposals(page, suspects) -> tuple[list, int]:
    """Read every suspect's page first, deciding nothing yet."""
    proposals, failed = [], 0
    for i, row in enumerate(suspects, 1):
        try:
            detail = _scrape_detail_page(page, row["url"])
        except Exception as e:
            print(f"  [{i}/{len(suspects)}] read error: {e}", flush=True)
            failed += 1
            continue
        proposals.append({
            "id": row["id"],
            "url": row["url"],
            "title": row["title"] or row["url"],
            "old": float(row["price_eur"] or 0),
            "size_m2": float(row["size_m2"] or 0),
            "price": float((detail or {}).get("price") or 0),
        })
        if i % 20 == 0 or i == len(suspects):
            print(f"  read {i}/{len(suspects)}", flush=True)
    return proposals, failed


def main() -> int:
    limit, dry_run = _parse_args(sys.argv[1:])

    suspects = get_shared_price_listings(SOURCE, limit=limit)
    if not suspects:
        print("No listing shares a price with a differently-sized listing. "
              "Nothing to repair.")
        return 0

    print(f"{len(suspects)} listings share a price with a differently-sized "
          f"listing (limit {limit})"
          f"{'  — DRY RUN, nothing will be written' if dry_run else ''}\n")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, capture = _open_browser(pw)
        page.remove_listener("response", capture)
        try:
            # Warm up Imperva on the index before hitting detail pages.
            try:
                page.goto(SEARCH_PAGE.format(page=1),
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
            proposals, failed = _read_proposals(page, suspects)
        finally:
            browser.close()

    rejected = repeated_across_sizes(proposals)
    corrected = cleared = confirmed = 0

    print()
    for p in proposals:
        per_m2 = f"{p['old'] / p['size_m2']:,.0f}" if p["size_m2"] else "?"
        label = p["title"][:44].replace("\n", " ")

        if p["price"] and p["id"] in rejected:
            cleared += 1
            verdict = (f"REJECTED €{p['price']:,.0f} — that price came back for "
                       f"differently-sized listings too; cleared instead")
            write = 0
        elif p["price"] and abs(p["price"] - p["old"]) < 1:
            confirmed += 1
            verdict = "confirmed"
            write = None
        elif p["price"]:
            corrected += 1
            verdict = f"corrected → €{p['price']:,.0f}"
            write = p["price"]
        else:
            cleared += 1
            verdict = "cleared (page states no single price)"
            write = 0

        if write is not None and not dry_run:
            set_listing_price(p["id"], write)
        if verdict != "confirmed":
            print(f"  €{p['old']:,.0f} ({per_m2} €/m², {p['size_m2']:g} m²)  "
                  f"{label}\n        → {verdict}", flush=True)

    print(f"\nDone. corrected {corrected}, cleared {cleared}, "
          f"confirmed {confirmed}, failed {failed}."
          + ("\n(dry run — nothing was written)" if dry_run else ""))
    if cleared and not dry_run:
        print("Cleared rows are PENDING with no detail_enriched_at stamp, so "
              "the next scrape reads them again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

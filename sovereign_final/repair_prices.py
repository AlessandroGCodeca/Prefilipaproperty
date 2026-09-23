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

    corrected = cleared = confirmed = failed = 0

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

            for i, row in enumerate(suspects, 1):
                old = float(row["price_eur"] or 0)
                size = float(row["size_m2"] or 0)
                label = (row["title"] or row["url"])[:44].replace("\n", " ")

                try:
                    detail = _scrape_detail_page(page, row["url"])
                except Exception as e:
                    print(f"  [{i}/{len(suspects)}] error: {e}", flush=True)
                    failed += 1
                    continue

                new = float((detail or {}).get("price") or 0)

                if new and abs(new - old) < 1:
                    confirmed += 1
                    verdict = "confirmed"
                elif new:
                    corrected += 1
                    verdict = f"corrected → €{new:,.0f}"
                    if not dry_run:
                        set_listing_price(row["id"], new)
                else:
                    cleared += 1
                    verdict = "cleared (page states no single price)"
                    if not dry_run:
                        set_listing_price(row["id"], 0)

                if verdict != "confirmed":
                    per_m2 = f"{old / size:,.0f}" if size else "?"
                    print(f"  [{i}/{len(suspects)}] €{old:,.0f} "
                          f"({per_m2} €/m², {size:g} m²)  {label}\n"
                          f"        → {verdict}", flush=True)
                elif i % 20 == 0:
                    print(f"  progress {i}/{len(suspects)}", flush=True)
        finally:
            browser.close()

    print(f"\nDone. corrected {corrected}, cleared {cleared}, "
          f"confirmed {confirmed}, failed {failed}."
          + ("\n(dry run — nothing was written)" if dry_run else ""))
    if cleared and not dry_run:
        print("Cleared rows are PENDING with no detail_enriched_at stamp, so "
              "the next scrape reads them again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

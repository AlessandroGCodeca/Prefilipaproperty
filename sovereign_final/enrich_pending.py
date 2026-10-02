"""
enrich_pending.py — re-read nehnutelnosti listings missing a price, a size or
a district, and retire the ones that turn out to be gone.

Goes through every active nehnutelnosti listing where price_eur=0, size_m2=0
or the district is blank, and runs the same detail-page read a fresh scrape
uses. The daily scrape can't reach most of these: get_fresh_detail_urls()
skips a row that already has a price and a size, however blank its district,
and a listing that has left the search results is never opened again at all.
This reads them through its own path.

  read found data       → upserted; a district filled in drops the cashflow
                          score worked out on the blank-district default rent,
                          so the next CASHFLOW SCORE run redoes it
  listing gone          → deactivated on sight: the page shows a grid of
                          similar listings where the listing was. Upserting it
                          would have re-activated it instead.

  python3 enrich_pending.py [max_listings] [--dry-run]

Default max_listings=200. Pass a larger number to do more. --dry-run reads
every page and reports what it would change, writing nothing — each gone
listing's URL is printed so the verdict can be checked in a browser first.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from database import get_conn, upsert_listing, deactivate_listings
from scraper.nehnutelnosti import (
    _scrape_detail_page, _apply_detail,
)


def _parse_args(argv) -> tuple[int, bool]:
    dry_run = "--dry-run" in argv
    limit = 200
    for a in argv:
        if a.isdigit():
            limit = int(a)
            break
    return limit, dry_run


def fetch_pending(limit: int = 200) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, source, url, url_hash, title, price_eur, size_m2,
               energy_class, address_raw, district, primary_image_url
        FROM listings
        WHERE source='nehnutelnosti' AND is_active=1
          AND (price_eur=0 OR size_m2=0 OR district IS NULL OR district='')
        ORDER BY scraped_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def settle(row: dict, detail: dict, now: str, dry_run: bool = False) -> set[str]:
    """Write one re-read back and return what it did: "gone", or any of
    "price", "size" and "district" that it filled in. With dry_run, work
    that out without writing anything."""
    if detail.get("gone"):
        print(f"  gone: {row['url']}", flush=True)
        if not dry_run:
            deactivate_listings([row["url"]])
        return {"gone"}
    if not detail:
        return set()

    listing = {
        "id": row["id"], "source": row["source"], "url": row["url"],
        "url_hash": row["url_hash"], "title": row["title"] or "",
        "description": "",
        "price_eur": row["price_eur"] or 0.0,
        "size_m2": row["size_m2"] or 0.0,
        "rooms": None, "floor": None, "year_built": None,
        "energy_class": row["energy_class"] or "UNKNOWN",
        "address_raw": row["address_raw"] or "",
        "district": row["district"] or "",
        "city": "",
        "primary_image_url": row["primary_image_url"] or "",
        "image_urls": row["primary_image_url"] or "",
        "classification": "PENDING",
        "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
    }
    _apply_detail(listing, detail)
    if not dry_run:
        upsert_listing(listing)

    filled = set()
    if not row["price_eur"] and listing["price_eur"]:
        filled.add("price")
    if not row["size_m2"] and listing["size_m2"]:
        filled.add("size")
    if not (row["district"] or "").strip() and listing["district"]:
        filled.add("district")
        print(f"  district → {listing['district']}: {row['url']}", flush=True)
    return filled


def main() -> None:
    limit, dry_run = _parse_args(sys.argv[1:])
    pending = fetch_pending(limit)
    print(f"Found {len(pending)} listings to enrich (LIMIT={limit})"
          f"{'  — DRY RUN, nothing will be written' if dry_run else ''}")
    if not pending:
        return

    counts = {"price": 0, "size": 0, "district": 0, "gone": 0}
    now = datetime.now(timezone.utc).isoformat()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            locale="sk-SK",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',  { get: () => [1,2,3,4,5] });
            window.chrome = { runtime: {}, loadTimes: ()=>({}), csi: ()=>({}) };
        """)
        page = ctx.new_page()

        # Warm up Imperva by visiting the listings index once
        try:
            page.goto("https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj?page=1",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

        for i, row in enumerate(pending, 1):
            try:
                detail = _scrape_detail_page(page, row["url"])
                for what in settle(row, detail, now, dry_run=dry_run):
                    counts[what] += 1
            except Exception as e:
                print(f"  [{i}/{len(pending)}] error: {e}", flush=True)

            if i % 20 == 0 or i == len(pending):
                print(f"  progress {i}/{len(pending)} "
                      f"(+price: {counts['price']}, +size: {counts['size']}, "
                      f"+district: {counts['district']}, gone: {counts['gone']})",
                      flush=True)

        browser.close()

    print(f"\nDone. Added price to {counts['price']}, size to {counts['size']}, "
          f"district to {counts['district']}; deactivated {counts['gone']} "
          f"gone listings."
          + ("\n(dry run — nothing was written)" if dry_run else ""))
    if counts["district"] and not dry_run:
        print("Rows that gained a district lost their cashflow score — run "
              "CASHFLOW SCORE to rescore them at their district's rent.")


if __name__ == "__main__":
    main()

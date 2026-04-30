"""
enrich_pending.py — backfill missing price/size on existing nehnutelnosti
listings (URL-only records left over from older scraper runs).

Goes through every active nehnutelnosti listing where price_eur=0 OR
size_m2=0 and attempts the same detail-page enrichment used during a
fresh scrape, then upserts the updated row.

  python3 enrich_pending.py [max_listings]

Default max_listings=200. Pass a larger number to do more.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from database import get_conn, upsert_listing
from scraper.nehnutelnosti import (
    _scrape_detail_page, _apply_detail, _district,
)

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def fetch_pending() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, source, url, url_hash, title, price_eur, size_m2,
               energy_class, address_raw, district, primary_image_url
        FROM listings
        WHERE source='nehnutelnosti' AND is_active=1
          AND (price_eur=0 OR size_m2=0)
        ORDER BY scraped_at DESC
        LIMIT ?
    """, (LIMIT,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main() -> None:
    pending = fetch_pending()
    print(f"Found {len(pending)} listings to enrich (LIMIT={LIMIT})")
    if not pending:
        return

    updated_price = 0
    updated_size = 0
    now = datetime.now(timezone.utc).isoformat()

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
            except Exception as e:
                print(f"  [{i}/{len(pending)}] error: {e}", flush=True)
                continue

            if not detail:
                continue

            had_price = row["price_eur"] > 0
            had_size = row["size_m2"] > 0

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

            if not had_price and listing["price_eur"] > 0:
                updated_price += 1
            if not had_size and listing["size_m2"] > 0:
                updated_size += 1

            try:
                upsert_listing(listing)
            except Exception as e:
                print(f"  [{i}] upsert error: {e}", flush=True)

            if i % 20 == 0 or i == len(pending):
                print(f"  progress {i}/{len(pending)} "
                      f"(+price: {updated_price}, +size: {updated_size})",
                      flush=True)

        browser.close()

    print(f"\nDone. Added price to {updated_price}, size to {updated_size}.")


if __name__ == "__main__":
    main()

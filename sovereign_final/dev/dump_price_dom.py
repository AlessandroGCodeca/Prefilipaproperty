"""
dev/dump_price_dom.py — one-off probe, not part of the pipeline.

The scrapers read the sale price by scanning the whole rendered page for €
figures, because JSON-LD often omits the price on PREMIUM listings. A detail
page also renders OTHER listings — recommendation carousels, the agency's own
portfolio — so that scan can return a neighbouring property's price. The
signature is one price repeated across listings of different sizes: €1,250,000
turned up on seven unrelated flats, €1,399,000 on three more.

pick_sale_price() drops candidates whose €/m² is absurd for the region, which
catches it on small flats and misses it on large ones. The real fix is to read
the price from the listing's own element instead of the page — which needs to
know what that element looks like.

This prints, for every € figure on a page, where in the DOM it sits: the tag,
its classes and id, and its ancestor chain. A selector that isolates the
listing's own price should be obvious from the output.

Run from sovereign_final/ with the venv active:

    python3 dev/dump_price_dom.py                  # picks a suspect from the DB
    python3 dev/dump_price_dom.py <listing-url>    # or probe one you name
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import _open_browser  # noqa: E402

# Same shape the scraper's own scan uses.
PRICE_RE = re.compile(r"(\d{1,3}(?:[\s\xa0  ]\d{3})+|\d{4,8})\s*€")


def _suspect_from_db() -> tuple[str, float, float]:
    """A listing whose price is shared with other listings of a different size
    — the pattern that says the price came off a neighbouring card."""
    from database import get_conn
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT url, price_eur, size_m2 FROM listings
            WHERE source='nehnutelnosti' AND price_eur > 0 AND size_m2 > 0
              AND price_eur IN (
                  SELECT price_eur FROM listings
                  WHERE source='nehnutelnosti' AND price_eur > 0 AND size_m2 > 0
                  GROUP BY price_eur HAVING COUNT(DISTINCT size_m2) > 1
              )
            ORDER BY price_eur DESC LIMIT 1
        """).fetchone()
    finally:
        conn.close()
    if not row:
        return "", 0.0, 0.0
    return row[0], row[1], row[2]


def _report_repeats() -> None:
    """How widespread the repeats are, before we look at any one page."""
    from database import get_conn
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT price_eur, COUNT(*) AS n, COUNT(DISTINCT size_m2) AS sizes
            FROM listings
            WHERE price_eur > 0 AND size_m2 > 0
            GROUP BY price_eur HAVING sizes > 1
            ORDER BY n DESC LIMIT 10
        """).fetchall()
    finally:
        conn.close()
    if not rows:
        print("No price is shared across listings of different sizes.")
        return
    print("── Prices shared across differently-sized listings " + "─" * 18)
    print(f"{'price':>12}  {'listings':>8}  {'distinct sizes':>14}")
    for price, n, sizes in rows:
        print(f"{price:>12,.0f}  {n:>8}  {sizes:>14}")
    print()


JS_DESCRIBE = """
els => els.map(e => {
  const chain = [];
  let p = e;
  for (let i = 0; i < 4 && p; i++) {
    chain.push(
      p.tagName.toLowerCase()
      + (p.id ? '#' + p.id : '')
      + (p.className && typeof p.className === 'string'
          ? '.' + p.className.trim().split(/\\s+/).slice(0, 3).join('.')
          : '')
    );
    p = p.parentElement;
  }
  return {
    text: (e.innerText || '').trim().slice(0, 60),
    chain: chain,
  };
})
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    url = sys.argv[1] if len(sys.argv) > 1 else ""
    price = size = 0.0
    if not url:
        _report_repeats()
        url, price, size = _suspect_from_db()
        if not url:
            print("No suspect listing in the database. Pass a URL instead:\n"
                  "   python3 dev/dump_price_dom.py <listing-url>")
            return 1
        print(f"Probing {url}\n  stored price €{price:,.0f} for {size} m² "
              f"(€{price / size:,.0f}/m²)\n")

    with sync_playwright() as pw:
        browser, page, capture = _open_browser(pw)
        page.remove_listener("response", capture)
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)

            # Every leaf element whose own text holds a € figure. Leaves only,
            # or every ancestor up to <body> matches and buries the signal.
            nodes = page.eval_on_selector_all(
                "*:not(:has(*))", JS_DESCRIBE
            )
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {str(e)[:200]}")
            browser.close()
            return 1
        browser.close()

    hits = []
    for n in nodes:
        for m in PRICE_RE.finditer(n["text"]):
            try:
                v = float(re.sub(r"[\s\xa0  ]", "", m.group(1)))
            except ValueError:
                continue
            hits.append((v, n["text"], n["chain"]))

    if not hits:
        print("No € figures found in leaf elements — the price may be split "
              "across child nodes. Send me the page and I'll widen the probe.")
        return 1

    print(f"── {len(hits)} € figures on the page " + "─" * 30)
    for v, text, chain in sorted(hits, key=lambda h: -h[0]):
        marker = "  ← STORED" if price and abs(v - price) < 1 else ""
        print(f"\n€{v:,.0f}{marker}")
        print(f"   text : {text!r}")
        print(f"   path : {' < '.join(chain)}")

    print("\nWhat to look for: the listing's own price and the carousel prices "
          "should sit under different ancestors. That difference is the "
          "selector the scraper should use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

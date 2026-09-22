"""
dev/dump_dev_project_api.py — one-off probe, not part of the pipeline.

Opening a listing's detail page makes nehnutelnosti fetch the other units in
the same development:

    /api/v2/dev-projects/detail/{id}/advertisements

Those responses carry real for-sale units the search page never lists, so
scraper/nehnutelnosti.py harvests them. The harvest only keeps items that
carry a real URL field, and a live run showed it keeping none of them — so the
URL must sit under a key _api_item_url() doesn't know about, or be absent.

This script captures one such response and prints its shape, so the parser can
be fixed against the real payload instead of a guess.

Run from sovereign_final/ with the venv active:

    python3 dev/dump_dev_project_api.py

It writes the full JSON to dev/dev_project_sample.json and prints a summary.
Pass a project id to probe a specific one (ids show up in the scraper's
"API hit" lines):

    python3 dev/dump_dev_project_api.py Ju9cw3H1PgW
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import BASE, SEARCH_PAGE, _open_browser  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "dev_project_sample.json")


def _summarise(payload) -> None:
    """Print enough structure to fix the parser, without dumping everything."""
    print("\n── Response shape " + "─" * 50)
    if isinstance(payload, dict):
        print(f"top-level keys: {sorted(payload.keys())}")
    elif isinstance(payload, list):
        print(f"top-level: list of {len(payload)}")

    from scraper.nehnutelnosti import _extract_items_from_json
    items = _extract_items_from_json(payload)
    print(f"items found by _extract_items_from_json: {len(items)}")
    if not items:
        print("  ⚠️  none — the list sits under a key that helper doesn't check")
        return

    first = items[0]
    if not isinstance(first, dict):
        print(f"  ⚠️  items are {type(first).__name__}, not dicts")
        return

    print(f"\nfirst item keys: {sorted(first.keys())}")

    # Which keys hold something URL-shaped? That's what the parser needs.
    print("\nURL-ish values:")
    found_url = False
    for k, v in first.items():
        if isinstance(v, str) and ("/" in v or v.startswith("http")):
            print(f"  {k} = {v[:100]}")
            found_url = True
    if not found_url:
        print("  (none — items carry no URL at all; we'd have to build one"
              " from an id, which means confirming that form resolves)")

    print("\nfirst item, in full:")
    print(json.dumps(first, ensure_ascii=False, indent=2)[:2000])


def main() -> int:
    from playwright.sync_api import sync_playwright

    want_id = sys.argv[1] if len(sys.argv) > 1 else ""
    captured: list[tuple[str, object]] = []

    with sync_playwright() as pw:
        browser, page, capture = _open_browser(pw)
        # _open_browser wires up the scraper's own filtered capture; this probe
        # needs the raw bodies, so listen separately.
        page.remove_listener("response", capture)

        def _on_response(response):
            if "/dev-projects/detail/" not in response.url:
                return
            if "advertisement" not in response.url:
                return
            try:
                captured.append((response.url, response.json()))
                print(f"  captured: {response.url}", flush=True)
            except Exception as e:
                print(f"  (unreadable: {e})", flush=True)

        page.on("response", _on_response)

        try:
            if want_id:
                url = f"{BASE}/api/v2/dev-projects/detail/{want_id}/advertisements"
                print(f"Fetching {url} directly...", flush=True)
                # Establish Imperva cookies on the real site first, otherwise
                # the WAF answers the API call with a challenge page.
                page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                body = page.inner_text("body")
                try:
                    captured.append((url, json.loads(body)))
                except Exception:
                    print(f"  ⚠️  not JSON — first 300 chars:\n{body[:300]}")
            else:
                print("Loading search page, then walking detail pages until a "
                      "dev-project call fires...", flush=True)
                page.goto(SEARCH_PAGE.format(page=1),
                          wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(3000)
                links = page.eval_on_selector_all(
                    "a[href*='/detail/']", "els => els.map(e => e.href)"
                )
                seen: set[str] = set()
                for href in links:
                    if href in seen:
                        continue
                    seen.add(href)
                    try:
                        page.goto(href, wait_until="domcontentloaded", timeout=25000)
                        page.wait_for_timeout(900)
                    except Exception:
                        continue
                    if captured:
                        break
                    if len(seen) >= 25:
                        print("  gave up after 25 detail pages", flush=True)
                        break
        finally:
            browser.close()

    if not captured:
        print("\n❌ No dev-project response captured. Re-run with an id from a "
              "scraper 'API hit' line, e.g.:\n"
              "   python3 dev/dump_dev_project_api.py Ju9cw3H1PgW")
        return 1

    url, payload = captured[0]
    print(f"\n✅ Captured {url}")
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"   full JSON written to {OUT_PATH}")
    _summarise(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

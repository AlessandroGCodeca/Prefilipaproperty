"""
modules/description_enrichment.py — wire parse_description into the pipeline.

Reads the free-text description each scraper stored on a listing, runs the
Claude-powered parse_description() helper (modules/llm_enrichment), and persists
the high-value structured features — parking, balcony, furnishing level,
condition — back onto the listing row.

Why it matters: has_parking and furnished feed engine.financial.get_rent_estimate,
which now applies a rent premium for them. A parsed description therefore raises
the estimated rent, which lifts the cashflow ratio / cap rate, which in turn
lifts the composite deal score — premiums the score previously couldn't see.

Degrades gracefully: when no ANTHROPIC_API_KEY is configured (llm_enrichment
disabled) this is a no-op returning 0, so the daily pipeline runs unchanged
without a key. desc_parsed is only set on a successful parse, so transient
failures are retried on the next run (bounded by `limit`).
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_unparsed_descriptions, update_description_features
from modules.llm_enrichment import is_enabled, parse_description


def _to_features(parsed: dict) -> dict:
    """Map a parse_description() result onto the DB column shape.

    Booleans become 0/1 so the rent-premium check stays a simple truthiness
    test. The floor/rooms sentinels from the schema aren't stored here — rooms
    is already captured during scraping and floor isn't used for rent yet.
    """
    return {
        "has_parking": 1 if parsed.get("parking") else 0,
        "has_balcony": 1 if parsed.get("balcony") else 0,
        "furnished":   parsed.get("furnished") or "unknown",
        "condition":   parsed.get("condition") or "unknown",
    }


def run_description_enrichment(limit: int = 200, progress_callback=None) -> int:
    """Parse descriptions for up to `limit` un-parsed active listings.

    Returns the number of descriptions successfully parsed and stored.
    """
    if not is_enabled():
        print("ℹ️  Description enrichment skipped — no ANTHROPIC_API_KEY set.")
        return 0

    pending = get_unparsed_descriptions(limit)
    if not pending:
        print("✅ No descriptions to enrich.")
        return 0

    print(f"📝 Parsing {len(pending)} descriptions via Claude...")
    parsed_n = 0
    for i, row in enumerate(pending, 1):
        if progress_callback:
            progress_callback(i, len(pending))

        result = parse_description(row["description"])
        if not result:
            # Leave desc_parsed=0 so a later run retries; `limit` caps the cost.
            continue
        try:
            update_description_features(row["id"], _to_features(result))
            parsed_n += 1
        except Exception as ex:
            print(f"  ⚠️ store error for {row['id']}: {ex}")

        if i % 20 == 0 or i == len(pending):
            print(f"  progress {i}/{len(pending)} (parsed: {parsed_n})", flush=True)

    print(f"\n✅ Description enrichment done. {parsed_n} parsed.\n")
    return parsed_n


if __name__ == "__main__":
    from database import init_db
    init_db()
    run_description_enrichment()

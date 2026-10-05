"""
modules/cashflow_runner.py — Sovereign Investor Dashboard
Runs the financial engine on all unscored PASS listings.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import (
    get_unscored_cashflow, upsert_cashflow, init_db, requeue_scores_without_benchmark,
    requeue_scores_with_stale_class,
)
from engine.financial import analyse, result_to_db_dict, deal_extras, base_rent_rate


def run_scoring(progress_callback=None) -> int:
    requeued = requeue_scores_without_benchmark()
    if requeued:
        print(f"♻️  {requeued} listings now have a regional median — re-scoring them.")
    stale = requeue_scores_with_stale_class()
    if stale:
        print(f"♻️  {stale} scores no longer match the current class rules — re-scoring them.")
    listings = get_unscored_cashflow()
    if not listings:
        print("✅ No new listings to score.")
        return 0

    # Live €/m² from prenájom comps (engine/rent_comps), read once per run.
    # Empty when no rentals have been scraped yet — the baseline then applies.
    from engine.rent_comps import load_live_rates
    rates = load_live_rates()
    if rates:
        print(f"🏘️  Using live rent comps for {len(rates)} districts.")

    print(f"💰 Scoring {len(listings)} listings...")
    scored = 0
    emojis = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪"}

    for i, row in enumerate(listings):
        if progress_callback:
            progress_callback(i + 1, len(listings))

        try:
            district = row.get("district") or ""
            result = analyse(
                price_eur  = row["price_eur"],
                size_m2    = row["size_m2"],
                district   = district,
                listing_id = row["id"],
                rooms      = row.get("rooms"),
                parking    = row.get("has_parking"),
                furnished  = row.get("furnished"),
                balcony    = row.get("has_balcony"),
                rent_rates = rates,
            )
            db_data = result_to_db_dict(result)
            db_data.update(deal_extras(result))
            db_data["rent_source"] = base_rent_rate(district, rates)[2]
            upsert_cashflow(db_data)
            scored += 1
            e = emojis.get(result.classification, "")
            print(f"  {e} {result.classification} | €{result.price_eur:,.0f} | "
                  f"s.r.o. surplus €{result.surplus_sro:+,.0f}/mo | {row.get('district','?')}")
        except Exception as ex:
            print(f"  ⚠️ Score error for {row['id']}: {ex}")

    print(f"\n✅ Cash-flow scoring done. {scored} scored.\n")
    return scored


if __name__ == "__main__":
    init_db()
    run_scoring()

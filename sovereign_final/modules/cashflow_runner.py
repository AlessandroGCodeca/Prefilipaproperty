"""
modules/cashflow_runner.py — Sovereign Investor Dashboard
Runs the financial engine on all unscored PASS listings.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_unscored_cashflow, upsert_cashflow, init_db
from engine.financial import analyse, result_to_db_dict


def run_scoring(progress_callback=None) -> int:
    listings = get_unscored_cashflow()
    if not listings:
        print("✅ No new listings to score.")
        return 0

    print(f"💰 Scoring {len(listings)} listings...")
    scored = 0
    emojis = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪"}

    for i, row in enumerate(listings):
        if progress_callback:
            progress_callback(i + 1, len(listings))

        try:
            result = analyse(
                price_eur  = row["price_eur"],
                size_m2    = row["size_m2"],
                district   = row.get("district") or "default",
                listing_id = row["id"],
            )
            db_data = result_to_db_dict(result)
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

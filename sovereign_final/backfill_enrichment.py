"""
backfill_enrichment.py — one-shot: run every LLM enricher across the existing DB,
then rescore so the new signals actually take effect on current listings.

Order matters. Address + description enrichment run first (they fill blank
districts and parse parking / furnished / balcony / condition), THEN the
cashflow scores are cleared and recomputed so the resolved districts and rent
premiums flow into every listing's score and deal grade.

  python3 backfill_enrichment.py [limit]

`limit` (default 1000) caps how many listings each enricher processes in one
pass — run again to continue. The enrichment steps need ANTHROPIC_API_KEY and
no-op without it; the rescore always runs so scores reflect the latest data and
engine assumptions.
"""

import sys, os

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, clear_cashflow_scores
from modules.address_enrichment import run_address_enrichment
from modules.description_enrichment import run_description_enrichment
from modules.cashflow_runner import run_scoring


def main(limit: int = 1000) -> dict:
    """Run the full backfill and return a summary of what changed."""
    init_db()
    print("=" * 60)
    print("BACKFILL ENRICHMENT — addresses, descriptions, then rescore")
    print("=" * 60)

    addresses    = run_address_enrichment(limit=limit)
    descriptions = run_description_enrichment(limit=limit)

    print("\n♻️  Clearing cashflow scores so the new signals take effect...")
    cleared = clear_cashflow_scores()
    scored  = run_scoring()

    summary = {
        "addresses": addresses,
        "descriptions": descriptions,
        "cleared": cleared,
        "scored": scored,
    }
    print("=" * 60)
    print(f"✅ Backfill done. {addresses} districts resolved, "
          f"{descriptions} descriptions parsed, "
          f"{cleared} scores cleared, {scored} rescored.")
    print("=" * 60)
    return summary


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    main(lim)

"""
modules/address_enrichment.py — wire normalize_address into the pipeline.

Some listings arrive with a messy or partial address_raw but a blank district
(JSON-LD without locality, premium listings, odd slug forms). A blank district
makes engine.financial.get_rent_estimate fall through to the €6.50/m² default
rate, which understates rent for anything in a real city — distorting the
cashflow and deal scores.

This runs the Claude-powered normalize_address() helper (modules/llm_enrichment)
on those listings and writes back a district the rent matcher can resolve.

Degrades gracefully: a no-op returning 0 when no ANTHROPIC_API_KEY is set.
addr_normalized is only set once normalize_address returns (so a definitive
"can't determine" isn't retried), while transient call failures (None) are left
to retry on the next run, bounded by `limit`.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import get_unnormalized_addresses, update_address
from modules.llm_enrichment import is_enabled, normalize_address


def _compose_district(norm: dict) -> str:
    """Build the district string the rent matcher resolves best.

    get_rent_estimate does fuzzy substring matching, so "Suburb, City" lets it
    match either the specific suburb rate or fall back to the city anchor. We
    join district (suburb) + city, de-duplicated and order-preserving, dropping
    blanks — e.g. {district:'Ružinov', city:'Bratislava'} -> 'Ružinov, Bratislava',
    {district:'', city:'Nitra'} -> 'Nitra', {district:'Nitra', city:'Nitra'} -> 'Nitra'.
    """
    seen: list[str] = []
    for part in (norm.get("district"), norm.get("city")):
        part = (part or "").strip()
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def run_address_enrichment(limit: int = 200, progress_callback=None) -> int:
    """Resolve blank districts for up to `limit` listings via normalize_address.

    Returns the number of listings for which a non-empty district was resolved.
    """
    if not is_enabled():
        print("ℹ️  Address normalization skipped — no ANTHROPIC_API_KEY set.")
        return 0

    pending = get_unnormalized_addresses(limit)
    if not pending:
        print("✅ No addresses to normalize.")
        return 0

    print(f"🗺️  Normalizing {len(pending)} addresses via Claude...")
    fixed = 0
    for i, row in enumerate(pending, 1):
        if progress_callback:
            progress_callback(i, len(pending))

        norm = normalize_address(row["address_raw"])
        if norm is None:
            # Transient failure — leave addr_normalized=0 to retry; `limit` caps cost.
            continue

        district = _compose_district(norm)
        try:
            update_address(row["id"], district, (norm.get("city") or "").strip())
            if district:
                fixed += 1
        except Exception as ex:
            print(f"  ⚠️ store error for {row['id']}: {ex}")

        if i % 20 == 0 or i == len(pending):
            print(f"  progress {i}/{len(pending)} (resolved: {fixed})", flush=True)

    print(f"\n✅ Address normalization done. {fixed} districts resolved.\n")
    return fixed


if __name__ == "__main__":
    from database import init_db
    init_db()
    run_address_enrichment()

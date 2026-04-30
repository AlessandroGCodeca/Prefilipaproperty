"""Quick DB inventory — what's actually scored vs gated, and why."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import get_conn

conn = get_conn()

print("\n=== Counts by source × data completeness ===\n")
rows = conn.execute("""
    SELECT
      source,
      COUNT(*)                                                  AS total,
      SUM(CASE WHEN price_eur > 0  THEN 1 ELSE 0 END)           AS has_price,
      SUM(CASE WHEN size_m2  > 0   THEN 1 ELSE 0 END)           AS has_size,
      SUM(CASE WHEN price_eur > 0 AND size_m2 > 0 THEN 1 ELSE 0 END) AS scoreable,
      SUM(CASE WHEN classification='PENDING' THEN 1 ELSE 0 END) AS pending
    FROM listings
    WHERE is_active=1
    GROUP BY source
""").fetchall()
print(f"{'source':<16} {'total':>6} {'price>0':>8} {'size>0':>7} {'both>0':>7} {'pending':>8}")
for r in rows:
    print(f"{r['source']:<16} {r['total']:>6} {r['has_price']:>8} {r['has_size']:>7} {r['scoreable']:>7} {r['pending']:>8}")

print("\n=== Already-scored count ===")
r = conn.execute("SELECT COUNT(*) AS c FROM cashflow_scores").fetchone()
print(f"  cashflow_scores rows: {r['c']}")

print("\n=== Unscored but eligible (gate passes) ===")
r = conn.execute("""
    SELECT COUNT(*) AS c FROM listings l
    LEFT JOIN cashflow_scores c ON l.id = c.listing_id
    WHERE l.lv_status != 'REJECTED' AND c.listing_id IS NULL
      AND l.price_eur > 0 AND l.size_m2 > 0 AND l.is_active=1
""").fetchone()
print(f"  eligible for next scoring batch: {r['c']}")

print("\n=== PENDING breakdown — why listings aren't scored ===")
r2 = conn.execute("""
    SELECT
      SUM(CASE WHEN price_eur = 0 AND size_m2 = 0 THEN 1 ELSE 0 END) AS missing_both,
      SUM(CASE WHEN price_eur = 0 AND size_m2 > 0 THEN 1 ELSE 0 END) AS missing_price,
      SUM(CASE WHEN price_eur > 0 AND size_m2 = 0 THEN 1 ELSE 0 END) AS missing_size,
      SUM(CASE WHEN lv_status = 'REJECTED'         THEN 1 ELSE 0 END) AS lv_rejected
    FROM listings
    WHERE classification = 'PENDING' AND is_active = 1
""").fetchone()
print(f"  missing price+size : {r2['missing_both']}")
print(f"  missing price only : {r2['missing_price']}")
print(f"  missing size only  : {r2['missing_size']}")
print(f"  LV rejected        : {r2['lv_rejected']}")

print("\n=== Classification distribution ===")
rows = conn.execute("""
    SELECT classification, COUNT(*) AS n
    FROM listings WHERE is_active=1
    GROUP BY classification ORDER BY n DESC
""").fetchall()
for r in rows:
    print(f"  {r['classification']:<10} {r['n']:>5}")

print("\n=== Rent estimate coverage (district matching) ===")
rows = conn.execute("""
    SELECT district, COUNT(*) AS n
    FROM listings
    WHERE is_active=1 AND price_eur > 0 AND size_m2 > 0
    GROUP BY district ORDER BY n DESC LIMIT 20
""").fetchall()
print(f"  {'district':<35} {'count':>6}")
for r in rows:
    print(f"  {(r['district'] or '(blank)'):<35} {r['n']:>6}")

print("\n=== Sample listings by classification ===")
for cls in ("GREEN", "YELLOW", "WHITE", "PENDING"):
    rows = conn.execute("""
        SELECT price_eur, size_m2, district, source, substr(title,1,55) AS title
        FROM listings WHERE classification=? AND is_active=1
        ORDER BY price_eur DESC LIMIT 3
    """, (cls,)).fetchall()
    if rows:
        print(f"\n  {cls}:")
        for r in rows:
            print(f"    [{r['source']:<12}] €{r['price_eur']:>8.0f}  {r['size_m2']:>5.1f}m²  "
                  f"{(r['district'] or '?'):<25}  {r['title']}")

conn.close()

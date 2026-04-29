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

print("\n=== Sample nehnutelnosti listings (5 random) ===")
rows = conn.execute("""
    SELECT id, price_eur, size_m2, district, classification, substr(title,1,60) AS title
    FROM listings WHERE source='nehnutelnosti' AND is_active=1
    ORDER BY scraped_at DESC LIMIT 8
""").fetchall()
for r in rows:
    print(f"  €{r['price_eur']:>8.0f}  {r['size_m2']:>5.1f}m²  {r['classification']:<8}  {r['district']!r:<25}  {r['title']}")

conn.close()

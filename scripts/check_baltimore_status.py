#!/usr/bin/env python3
"""Quick Baltimore City (24510) data-quality snapshot from Postgres."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "core"))

from parking_core.pilot import load_pilot_config  # noqa: E402

_env = ROOT / "deploy" / ".env"
if _env.is_file():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

COUNTY = "24510"
engine = create_engine(os.environ["DATABASE_URL"])
floor = float(load_pilot_config(ROOT / "config" / "pilot.yaml").scoring.qualified_min_score)

SQL = """
select
  count(*) as total,
  count(*) filter (where distance_to_nearest_demand_m is null) as no_demand_m,
  count(*) filter (where distance_to_nearest_demand_m <= 450) as within_demand_buffer,
  count(*) filter (where poi_commercial_count_400m is null) as no_poi,
  count(*) filter (where poi_commercial_count_400m >= 8) as strong_poi
from parcels where county_fips = :cf;

select count(*) as with_entitlement
from parcels p
where p.county_fips = :cf
  and exists (
    select 1 from parcel_scores s
    where s.parcel_id = p.id and s.score_profile = 'entitlement'
  );

select count(*) as qualified_55
from parcels p
join lateral (
  select total_score from parcel_scores s
  where s.parcel_id = p.id and s.score_profile = 'entitlement'
  order by s.created_at desc limit 1
) sc on true
where p.county_fips = :cf and sc.total_score >= 55;

select count(*) as qualified_floor
from parcels p
join lateral (
  select total_score from parcel_scores s
  where s.parcel_id = p.id and s.score_profile = 'entitlement'
  order by s.created_at desc limit 1
) sc on true
where p.county_fips = :cf and sc.total_score >= :floor;

select min(distance_to_nearest_demand_m) as min_d,
       percentile_cont(0.5) within group (order by distance_to_nearest_demand_m) as median_d
from parcels where county_fips = :cf and distance_to_nearest_demand_m is not null;
"""

with engine.connect() as conn:
    r1 = conn.execute(text(SQL.split(";")[0]), {"cf": COUNTY}).mappings().one()
    r2 = conn.execute(text(SQL.split(";")[1]), {"cf": COUNTY}).scalar()
    r3 = conn.execute(text(SQL.split(";")[2]), {"cf": COUNTY}).scalar()
    r4 = conn.execute(text(SQL.split(";")[3]), {"cf": COUNTY, "floor": floor}).scalar()
    r5 = conn.execute(text(SQL.split(";")[4]), {"cf": COUNTY}).mappings().one()


def pct(count: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{100 * count / total:.2f}%"

print("Baltimore City (24510)")
print("  parcels:", r1["total"])
print("  missing demand distance:", r1["no_demand_m"])
print("  within 450m demand POI:", r1["within_demand_buffer"])
print("  missing OSM POI count:", r1["no_poi"])
print("  strong POI (8+):", r1["strong_poi"])
print("  with entitlement score:", r2)
print(
    "  qualified at old floor (entitlement >= 55): "
    f"{r3} ({pct(int(r3 or 0), int(r1['total'] or 0))})"
)
print(
    f"  qualified at current floor (entitlement >= {floor:g}): "
    f"{r4} ({pct(int(r4 or 0), int(r1['total'] or 0))})"
)
print("  demand distance min / median m:", r5["min_d"], round(float(r5["median_d"] or 0), 1))

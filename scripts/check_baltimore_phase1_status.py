#!/usr/bin/env python3
"""Baltimore City Phase-1 funnel coverage snapshot.

Phase 1 here means the parcel anchor exists in Postgres and has an
``identification`` (Cartographer / prescreen) score. Full Atlas/Beacon,
owner outreach, and vendor skip-trace are later funnel stages.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
COUNTY = "24510"
SOURCE_LAYER = "https://egis.baltimorecity.gov/egis/rest/services/Parcel_Information/Parcel/FeatureServer/0"


def _load_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = ROOT / "deploy" / ".env"
    if env.is_file():
        for raw in env.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                return val.strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL is not set")


def _source_count() -> int | None:
    params = urllib.parse.urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"})
    req = urllib.request.Request(
        f"{SOURCE_LAYER}/query?{params}",
        headers={"User-Agent": "parking-baltimore-phase1-status/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    count = payload.get("count")
    return int(count) if count is not None else None


def _pct(numerator: int, denominator: int | None) -> float | None:
    if not denominator:
        return None
    return round((numerator / denominator) * 100, 2)


def build_status() -> dict[str, Any]:
    engine = create_engine(_load_database_url())
    source = _source_count()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                with latest_ident as (
                  select distinct on (s.parcel_id)
                    s.parcel_id,
                    s.total_score,
                    s.created_at
                  from parcel_scores s
                  join parcels p on p.id = s.parcel_id
                  where p.county_fips = :cf
                    and s.score_profile = 'identification'
                  order by s.parcel_id, s.created_at desc
                )
                select
                  count(p.*)::int as parcel_total,
                  count(distinct p.apn)::int as distinct_apns,
                  (count(p.*) - count(distinct p.apn))::int as duplicate_apn_rows,
                  count(p.*) filter (where nullif(trim(p.apn), '') is null)::int as missing_apn,
                  count(p.*) filter (where p.footprint is null)::int as missing_footprint,
                  count(li.parcel_id)::int as identification_score_count,
                  count(p.*) filter (where li.parcel_id is null)::int as missing_identification_score,
                  count(li.parcel_id) filter (where li.total_score >= 45)::int as prescreen_qualified_45,
                  max(li.created_at)::text as latest_identification_score_at
                from parcels p
                left join latest_ident li on li.parcel_id = p.id
                where p.county_fips = :cf
                """,
            ),
            {"cf": COUNTY},
        ).mappings().one()

    parcel_total = int(row["parcel_total"] or 0)
    missing_ident = int(row["missing_identification_score"] or 0)
    source_gap = max((source or 0) - parcel_total, 0) if source is not None else None
    return {
        "county_fips": COUNTY,
        "source_parcel_count": source,
        "parcel_total": parcel_total,
        "source_gap": source_gap,
        "source_coverage_pct": _pct(parcel_total, source),
        "distinct_apns": int(row["distinct_apns"] or 0),
        "duplicate_apn_rows": int(row["duplicate_apn_rows"] or 0),
        "missing_apn": int(row["missing_apn"] or 0),
        "missing_footprint": int(row["missing_footprint"] or 0),
        "identification_score_count": int(row["identification_score_count"] or 0),
        "missing_identification_score": missing_ident,
        "identification_coverage_pct": _pct(parcel_total - missing_ident, parcel_total),
        "prescreen_qualified_45": int(row["prescreen_qualified_45"] or 0),
        "latest_identification_score_at": row["latest_identification_score_at"],
        "phase1_complete_for_source": source is not None and source_gap == 0 and missing_ident == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()
    status = build_status()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return
    print("Baltimore City Phase 1 (parcel anchor + identification prescreen)")
    print(f"  source parcels: {status['source_parcel_count']}")
    print(f"  parcels in DB: {status['parcel_total']}")
    print(f"  source gap: {status['source_gap']}")
    print(f"  source coverage: {status['source_coverage_pct']}%")
    print(f"  with identification score: {status['identification_score_count']}")
    print(f"  missing identification score: {status['missing_identification_score']}")
    print(f"  identification coverage: {status['identification_coverage_pct']}%")
    print(f"  prescreen qualified (>=45): {status['prescreen_qualified_45']}")
    print(f"  latest identification score at: {status['latest_identification_score_at']}")
    print(f"  phase1 complete for source: {status['phase1_complete_for_source']}")


if __name__ == "__main__":
    main()

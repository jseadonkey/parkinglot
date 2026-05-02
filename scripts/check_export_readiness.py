#!/usr/bin/env python3
"""Print gap counts for stakeholder CSV columns and owner outreach brief (Phase A–C — before export).

Uses the same ``DATABASE_URL`` and Python env as ``export_scored_parcels_csv.py``.

  DATABASE_URL=postgresql+psycopg://... python3 scripts/check_export_readiness.py
  python3 scripts/check_export_readiness.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from parcel_export_common import ensure_api_path, normalize_database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV export readiness gap counts")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "error: DATABASE_URL is not set (same requirement as export_scored_parcels_csv.py).",
            file=sys.stderr,
        )
        return 2

    ensure_api_path()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.export_readiness import export_readiness_summary

    url = normalize_database_url(os.environ["DATABASE_URL"].strip())
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        data = export_readiness_summary(db)
    finally:
        db.close()

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    total = data["parcel_row_total"]
    print(f"Parcel rows in DB: {total}")
    print()
    for key in (
        "parcels_missing_footprint",
        "parcels_missing_zoning_code",
        "parcels_missing_lot_sqft",
        "parcels_missing_distance_to_nearest_demand_m",
        "parcels_missing_score_identification",
        "parcels_missing_score_entitlement",
        "parcels_missing_score_strategic",
        "parcels_missing_entitlement_or_strategic",
        "parcels_missing_owner_outreach_brief",
    ):
        row = data[key]
        print(f"  {key}: {row['count']} ({row['pct']}% of parcels)")
    print()
    print("Suggested actions:")
    for line in data.get("recommended_next_steps", []):
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

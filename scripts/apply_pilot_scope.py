#!/usr/bin/env python3
"""Recompute ``parcels.pilot_in_scope`` for King/Kent geographic pilot scope.

Run after changing ``config/pilot*.yaml`` ``region.in_scope`` or boundary GeoJSON files,
and once after deploying migration ``20260531_0004``.

  cd /opt/workspaces/parkinglot
  export DATABASE_URL=postgresql+psycopg://...
  .venv/bin/python scripts/apply_pilot_scope.py
  .venv/bin/python scripts/apply_pilot_scope.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply King/Kent pilot_in_scope flags to all parcels.")
    parser.add_argument("--json", action="store_true", help="Print summary JSON only")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels (debug)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL", "").strip():
        print("error: DATABASE_URL is required", file=sys.stderr)
        return 2

    sys.path.insert(0, str(_REPO / "services" / "api"))
    sys.path.insert(0, str(_REPO / "packages" / "core"))

    from parcel_export_common import ensure_api_path, normalize_database_url

    ensure_api_path()

    from geoalchemy2.shape import to_shape
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Parcel
    from app.pilot_scope_filter import classify_parcel_scope, load_primary_pilot

    pilot = load_primary_pilot()
    url = normalize_database_url(os.environ["DATABASE_URL"].strip())
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()

    in_scope = 0
    out_scope = 0
    no_footprint = 0
    try:
        stmt = select(Parcel).where(Parcel.footprint.isnot(None)).order_by(Parcel.created_at)
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = db.scalars(stmt).all()
        for row in rows:
            if row.footprint is None:
                no_footprint += 1
                continue
            scoped = classify_parcel_scope(row, pilot)
            row.pilot_in_scope = scoped
            db.add(row)
            if scoped:
                in_scope += 1
            else:
                out_scope += 1
        db.commit()

        total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
        in_db = int(db.scalar(select(func.count()).select_from(Parcel).where(Parcel.pilot_in_scope.is_(True))) or 0)
        out_db = int(db.scalar(select(func.count()).select_from(Parcel).where(Parcel.pilot_in_scope.is_(False))) or 0)
    finally:
        db.close()

    summary = {
        "pilot_region": pilot.region.name,
        "processed_with_footprint": in_scope + out_scope,
        "marked_in_scope": in_scope,
        "marked_out_of_scope": out_scope,
        "parcels_total": total,
        "parcels_in_scope_db": in_db,
        "parcels_out_of_scope_db": out_db,
        "county_fips": pilot.region.county_fips,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Pilot: {summary['pilot_region']}")
        print(f"Processed {summary['processed_with_footprint']} parcels with footprints")
        print(f"  in scope:  {summary['marked_in_scope']}")
        print(f"  out scope: {summary['marked_out_of_scope']}")
        print(f"DB totals: {summary['parcels_in_scope_db']} in / {summary['parcels_out_of_scope_db']} out / {summary['parcels_total']} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

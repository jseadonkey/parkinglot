#!/usr/bin/env python3
"""Merge King County taxpayer rows into parcels.raw_properties.owner_record.

  python3 scripts/backfill_owner_records.py
  python3 scripts/backfill_owner_records.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
DEFAULT_JSON = REPO / "data/pilot/top10_owner_records.json"
SOURCE = "king_county_assessor_gis"


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill raw_properties.owner_record on parcels.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = p.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("error: set DATABASE_URL", file=sys.stderr)
        return 2
    if not args.json.is_file():
        print(f"error: not found: {args.json}", file=sys.stderr)
        return 2

    rows = json.loads(args.json.read_text())
    engine = create_engine(db_url)
    enriched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    updated = 0

    with engine.connect() as conn:
        for row in rows:
            apn = str(row["apn"]).strip()
            pin = apn.split("-")[-1]
            owner_record = {
                "taxpayer_name": row.get("taxpayer_name"),
                "taxpayer_attn": row.get("taxpayer_attn") or None,
                "mailing_address": row.get("mailing_address"),
                "situs_address": row.get("situs_address"),
                "addr_full": row.get("addr_full"),
                "situs_city": row.get("situs_city"),
                "situs_zip": row.get("situs_zip"),
                "kctp_addr": row.get("kctp_addr"),
                "kctp_cityst": row.get("kctp_cityst"),
                "kctp_zip": row.get("kctp_zip"),
                "alias1": row.get("alias1"),
                "alias2": row.get("alias2"),
                "appraised_land": row.get("appraised_land"),
                "appraised_improvements": row.get("appraised_improvements"),
                "property_type": row.get("property_type"),
                "erealproperty_url": (
                    f"https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={pin}"
                ),
                "data_source": SOURCE,
                "enriched_at": enriched_at,
            }
            payload = json.dumps(owner_record)
            name = str(row.get("taxpayer_name") or "").strip()
            if args.dry_run:
                n = conn.execute(
                    text("SELECT COUNT(*) FROM parcels WHERE apn = :apn"),
                    {"apn": apn},
                ).scalar()
                print(f"dry-run {apn}: would update {n} row(s) -> {name}")
                updated += int(n or 0)
                continue

            res = conn.execute(
                text(
                    """
                    UPDATE parcels
                    SET raw_properties = COALESCE(raw_properties, '{}'::jsonb)
                        || jsonb_build_object('owner_record', CAST(:rec AS jsonb))
                    WHERE apn = :apn
                    """
                ),
                {"apn": apn, "rec": payload},
            )
            if res.rowcount and name:
                conn.execute(
                    text(
                        """
                        UPDATE owner_candidates
                        SET display_name = :name,
                            kind = 'taxpayer',
                            confidence = 0.85,
                            source = :source,
                            raw = CAST(:rec AS jsonb)
                        WHERE parcel_id IN (SELECT id FROM parcels WHERE apn = :apn)
                          AND display_name = 'Unknown owner'
                        """
                    ),
                    {"apn": apn, "name": name, "source": SOURCE, "rec": payload},
                )
            updated += res.rowcount
        if not args.dry_run:
            conn.commit()

    mode = "dry-run" if args.dry_run else "applied"
    print(f"{mode}: {updated} parcel(s) with owner_record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Recompute parcels.zoning_allows_surface_parking from rules YAML + raw_properties jurisdiction.

  DATABASE_URL=postgresql+psycopg://… python3 scripts/backfill_zoning_surface_parking.py
  python3 scripts/backfill_zoning_surface_parking.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "ingestion"))

from parking_ingestion.zoning_rules import (  # noqa: E402
    effective_zoning_rules_path,
    load_zoning_rules,
    resolve_surface_parking,
)


def _jurisdiction_from_raw(raw: dict | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    j = raw.get("ZONING_JURISDICTION") or raw.get("zoning_jurisdiction")
    return str(j).strip().lower() if j else None


def main() -> int:
    p = argparse.ArgumentParser(description="Backfill zoning_allows_surface_parking on parcels.")
    p.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = p.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("error: set DATABASE_URL", file=sys.stderr)
        return 2

    rules_path = effective_zoning_rules_path(REPO / "data/zoning/wa/kent_king_surface_parking_rules.yaml")
    rules = load_zoning_rules(rules_path)
    engine = create_engine(db_url)

    updates: list[tuple[bool, str]] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, zoning_code, zoning_allows_surface_parking, raw_properties FROM parcels")
        ).fetchall()
        for pid, zone, stored, raw in rows:
            juris = _jurisdiction_from_raw(raw)
            expected = resolve_surface_parking(zone, juris, None, rules)
            if bool(stored) != bool(expected):
                updates.append((bool(expected), str(pid)))

        if not args.dry_run and updates:
            for expected, pid in updates:
                conn.execute(
                    text(
                        "UPDATE parcels SET zoning_allows_surface_parking = :val WHERE id = :id"
                    ),
                    {"val": expected, "id": pid},
                )
            conn.commit()

    to_true = sum(1 for v, _ in updates if v)
    to_false = len(updates) - to_true
    mode = "dry-run" if args.dry_run else "applied"
    print(f"{mode}: {len(updates)} parcel(s) updated ({to_true} → true, {to_false} → false)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

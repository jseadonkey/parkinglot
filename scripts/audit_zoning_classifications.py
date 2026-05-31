#!/usr/bin/env python3
"""Audit parcel zoning codes vs kent_king_surface_parking_rules.yaml.

Prints counts by zone, jurisdiction, allows_surface_parking flag, and unknown codes.

  python3 scripts/audit_zoning_classifications.py
  DATABASE_URL=postgresql+psycopg://… python3 scripts/audit_zoning_classifications.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "ingestion"))

from parking_ingestion.zoning_rules import (  # noqa: E402
    effective_zoning_rules_path,
    load_zoning_rules,
    lookup_zone_entry,
    resolve_surface_parking,
)


def _jurisdiction_from_raw(raw: dict | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    j = raw.get("ZONING_JURISDICTION") or raw.get("zoning_jurisdiction")
    return str(j).strip().lower() if j else None


def main() -> int:
    p = argparse.ArgumentParser(description="Audit zoning classification vs rules YAML.")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = p.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("error: set DATABASE_URL", file=sys.stderr)
        return 2

    rules_path = effective_zoning_rules_path(REPO / "data/zoning/wa/kent_king_surface_parking_rules.yaml")
    rules = load_zoning_rules(rules_path)
    jurisdictions = rules.get("jurisdictions") or {}

    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, zoning_code, zoning_allows_surface_parking, raw_properties
                FROM parcels
                """
            )
        ).fetchall()

    by_zone: Counter[tuple[str, str, bool, bool]] = Counter()
    unknown: Counter[tuple[str, str]] = Counter()
    mismatch = 0
    would_allow = 0

    for _pid, zone, stored, raw in rows:
        juris = _jurisdiction_from_raw(raw) or "unknown"
        z = (zone or "").strip() or "(empty)"
        block = jurisdictions.get(juris) if isinstance(jurisdictions, dict) else None
        zones = (block or {}).get("zones") if isinstance(block, dict) else {}
        entry = lookup_zone_entry(zones if isinstance(zones, dict) else {}, z if z != "(empty)" else None)
        in_rules = entry is not None
        if z != "(empty)" and not in_rules:
            unknown[(juris, z)] += 1
        expected = resolve_surface_parking(
            z if z != "(empty)" else None,
            juris if juris != "unknown" else None,
            None,
            rules,
        )
        if expected:
            would_allow += 1
        if bool(stored) != bool(expected):
            mismatch += 1
        by_zone[(juris, z, bool(stored), bool(expected))] += 1

    if args.json:
        payload = {
            "rules_path": str(rules_path) if rules_path else None,
            "parcel_count": len(rows),
            "stored_allows_true": sum(1 for r in rows if r[2]),
            "expected_allows_true": would_allow,
            "mismatch_count": mismatch,
            "unknown_zone_counts": {f"{j}|{z}": c for (j, z), c in unknown.most_common()},
            "by_zone": [
                {"jurisdiction": j, "zone": z, "stored": s, "expected": e, "count": c}
                for (j, z, s, e), c in sorted(by_zone.items(), key=lambda x: -x[1])
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Rules: {rules_path}")
    print(f"Parcels: {len(rows)}")
    print(f"Stored allows=true: {sum(1 for r in rows if r[2])}")
    print(f"Expected allows=true (from rules): {would_allow}")
    print(f"Rows where stored != expected: {mismatch}")
    if unknown:
        print("\nUnknown zone codes (default_when_unknown=false):")
        for (j, z), c in unknown.most_common():
            print(f"  {j:20} {z:16} {c}")
    print("\nBy jurisdiction / zone (stored vs expected):")
    for (j, z, s, e), c in sorted(by_zone.items(), key=lambda x: (-x[1], x[0][0], x[0][1])):
        flag = "" if s == e else "  <-- MISMATCH"
        print(f"  {j:20} {z:16} stored={str(s):5} expected={str(e):5} n={c}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

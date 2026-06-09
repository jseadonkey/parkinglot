#!/usr/bin/env python3
"""Report address-source status from jurisdiction files and optional live DB gaps."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "data" / "jurisdictions" / "wa" / "jurisdiction_registry.csv"


def _read_registry(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _db_wa_gaps() -> list[dict[str, int | str]] | None:
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.candidate_address import wa_candidate_address_gaps_by_county

        engine = create_engine(db_url)
        with Session(engine) as db:
            return wa_candidate_address_gaps_by_county(db, limit=39)
    except Exception as exc:
        print(f"DB gaps unavailable: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Address coverage report (registry + optional DB)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.registry.is_file():
        print(f"Missing {args.registry}", file=sys.stderr)
        return 1

    rows = _read_registry(args.registry)
    by_status: dict[str, int] = {}
    wa_rows = [r for r in rows if (r.get("state_fips") or "").strip() == "53"]
    for row in wa_rows:
        st = (row.get("address_source_status") or "unknown").strip()
        by_status[st] = by_status.get(st, 0) + 1

    report = {
        "registry_path": str(args.registry),
        "wa_jurisdiction_rows": len(wa_rows),
        "address_source_status_counts": by_status,
        "not_started_or_blocked": [
            {
                "jurisdiction_id": r.get("jurisdiction_id"),
                "jurisdiction_name": r.get("jurisdiction_name"),
                "address_source_status": r.get("address_source_status"),
                "address_source_name": r.get("address_source_name"),
            }
            for r in wa_rows
            if (r.get("address_source_status") or "") in ("not_started", "blocked", "source_found")
        ],
        "live_db_wa_candidate_gaps_by_county": _db_wa_gaps(),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"WA jurisdiction rows: {len(wa_rows)}")
        print("Address source status:")
        for st, n in sorted(by_status.items()):
            print(f"  {st}: {n}")
        gaps = report.get("live_db_wa_candidate_gaps_by_county")
        if gaps:
            print("Live candidate address gaps by county (top):")
            for row in gaps[:10]:
                print(f"  {row['county_fips']}: {row['candidate_gap']}")
        elif not os.environ.get("DATABASE_URL"):
            print("(Set DATABASE_URL for live candidate gap counts)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

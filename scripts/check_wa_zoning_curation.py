#!/usr/bin/env python3
"""Report Washington zoning-preference curation progress.

This is intentionally a status gate, not an ordinance scraper. It makes the
remaining city/county zoning curation work machine-visible so future resource
runs can keep going until every Washington jurisdiction has ordinance-backed
zone preference entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_paths() -> None:
    for pkg in ("packages/core", "services/ingestion"):
        p = _REPO_ROOT / pkg
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _is_curated_rules_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    zones = block.get("zones")
    if not isinstance(zones, dict) or not zones:
        return False
    # Empty dict entries are still placeholders. A boolean or a dict with at
    # least one decision field counts as an intentional curation entry.
    for entry in zones.values():
        if isinstance(entry, bool):
            return True
        if isinstance(entry, dict) and any(
            key in entry
            for key in (
                "allows_surface_parking",
                "principal_use_symbol",
                "note",
                "source_url",
                "ordinance_ref",
            )
        ):
            return True
    return False


def _jurisdiction_sort_key(row: dict[str, Any], county_priority: list[str]) -> tuple[int, str, str]:
    county = str(row.get("county_fips") or "")
    try:
        county_rank = county_priority.index(county)
    except ValueError:
        county_rank = len(county_priority)
    return (county_rank, county, str(row.get("jurisdiction_key") or ""))


def main() -> int:
    _ensure_repo_paths()

    from parking_core.geography_registry import load_geography_registry
    from parking_ingestion.zoning_rules import load_effective_zoning_rules
    parser = argparse.ArgumentParser(description="Report WA zoning curation completeness.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=_REPO_ROOT / "config" / "geography_registry.yaml",
        help="Geography registry YAML",
    )
    parser.add_argument(
        "--rollout-config",
        type=Path,
        default=_REPO_ROOT / "config" / "wa_statewide_rollout.yaml",
        help="WA county rollout priority YAML",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Number of uncurated priority jurisdictions to print in text mode",
    )
    parser.add_argument(
        "--fail-if-incomplete",
        action="store_true",
        help="Exit non-zero until every WA jurisdiction has curated zone entries",
    )
    args = parser.parse_args()

    registry = load_geography_registry(args.registry)
    rules = load_effective_zoning_rules()
    jurisdictions = rules.get("jurisdictions") if isinstance(rules.get("jurisdictions"), dict) else {}
    rollout_raw = yaml.safe_load(args.rollout_config.read_text(encoding="utf-8"))
    rollout = rollout_raw if isinstance(rollout_raw, dict) else {}
    county_priority = [str(fips) for fips in rollout.get("county_fips_priority") or []]

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for geo in registry.geographies:
        if geo.state_fips != "53" or not geo.jurisdiction_key:
            continue
        key = (geo.jurisdiction_key, geo.county_fips, geo.boundary_path)
        if key in seen:
            continue
        seen.add(key)
        block = jurisdictions.get(geo.jurisdiction_key)
        curated = _is_curated_rules_block(block)
        zones = block.get("zones") if isinstance(block, dict) else {}
        rows.append(
            {
                "geography_key": geo.key,
                "name": geo.name,
                "type": geo.type,
                "county_fips": geo.county_fips,
                "jurisdiction_key": geo.jurisdiction_key,
                "boundary_path": geo.boundary_path,
                "has_rules_block": isinstance(block, dict),
                "curated": curated,
                "zone_entry_count": len(zones) if isinstance(zones, dict) else 0,
            }
        )

    rows.sort(key=lambda row: _jurisdiction_sort_key(row, county_priority))
    curated_rows = [row for row in rows if row["curated"]]
    uncurated_rows = [row for row in rows if not row["curated"]]

    by_county: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "curated": 0, "uncurated": 0})
    for row in rows:
        county = str(row.get("county_fips") or "unknown")
        by_county[county]["total"] += 1
        by_county[county]["curated"] += 1 if row["curated"] else 0
        by_county[county]["uncurated"] += 0 if row["curated"] else 1

    summary = {
        "registry": str(args.registry.resolve()),
        "rollout_config": str(args.rollout_config.resolve()),
        "wa_jurisdiction_count": len(rows),
        "curated_count": len(curated_rows),
        "uncurated_count": len(uncurated_rows),
        "complete": len(uncurated_rows) == 0,
        "county_count": len(by_county),
        "counties": dict(sorted(by_county.items())),
        "curated_jurisdictions": curated_rows,
        "uncurated_jurisdictions": uncurated_rows,
        "next_priority_jurisdictions": uncurated_rows[: max(args.limit, 0)],
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("Washington zoning curation status")
        print(f"Registry: {summary['registry']}")
        print(f"WA jurisdictions: {summary['wa_jurisdiction_count']}")
        print(f"Curated: {summary['curated_count']}")
        print(f"Uncurated: {summary['uncurated_count']}")
        print(f"Complete: {summary['complete']}")
        if uncurated_rows:
            print("\nNext priority jurisdictions:")
            for row in summary["next_priority_jurisdictions"]:
                print(
                    "  "
                    f"{row['county_fips']} {row['jurisdiction_key']} "
                    f"({row['type']}, {row['name']})"
                )
            if len(uncurated_rows) > args.limit:
                print(f"  ... {len(uncurated_rows) - args.limit} more")

    return 1 if args.fail_if_incomplete and uncurated_rows else 0


if __name__ == "__main__":
    raise SystemExit(main())

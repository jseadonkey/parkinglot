#!/usr/bin/env python3
"""Validate geography-agent registry coverage against the pilot county list."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_paths() -> None:
    for pkg in ("packages/core", "services/ingestion"):
        p = _REPO_ROOT / pkg
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def main() -> int:
    _ensure_repo_paths()

    from parking_core.geography_registry import load_geography_registry, validate_geography_registry
    from parking_core.pilot import load_pilot_config
    from parking_ingestion.zoning_rules import load_effective_zoning_rules

    parser = argparse.ArgumentParser(description="Validate geography registry coverage.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=_REPO_ROOT / "config" / "geography_registry.yaml",
        help="Geography registry YAML",
    )
    parser.add_argument(
        "--pilot-config",
        type=Path,
        default=_REPO_ROOT / "config" / "pilot.yaml",
        help="Pilot YAML with county_fips list",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    registry = load_geography_registry(args.registry)
    pilot = load_pilot_config(args.pilot_config)
    rules = load_effective_zoning_rules()
    issues = validate_geography_registry(registry, pilot_county_fips=pilot.region.county_fips, zoning_rules=rules)
    counts = Counter(issue.severity for issue in issues)

    summary = {
        "registry": str(args.registry.resolve()),
        "pilot_config": str(args.pilot_config.resolve()),
        "source_count": len(registry.sources),
        "geography_count": len(registry.geographies),
        "city_inventory_source_count": len(registry.city_inventory_sources),
        "pilot_county_count": len(pilot.region.county_fips),
        "issue_counts": dict(counts),
        "issues": [issue.model_dump() for issue in issues],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Registry: {summary['registry']}")
        print(f"Sources: {summary['source_count']}")
        print(f"Geography agents: {summary['geography_count']}")
        print(f"City inventory sources: {summary['city_inventory_source_count']}")
        print(f"Pilot counties covered: {summary['pilot_county_count']}")
        print(f"Issues: {summary['issue_counts'] or '{}'}")
        for issue in issues:
            geo = f" [{issue.geography_key}]" if issue.geography_key else ""
            print(f"  {issue.severity.upper()} {issue.code}{geo}: {issue.message}")

    return 1 if counts.get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

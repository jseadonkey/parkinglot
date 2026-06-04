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
    from parking_core.city_inventory import load_city_inventory_manifest
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
    wa_city_summary = None
    for source in registry.city_inventory_sources:
        if source.state_fips != "53" or not source.manifest_path:
            continue
        manifest_path = Path(source.manifest_path)
        if not manifest_path.is_absolute():
            manifest_path = _REPO_ROOT / manifest_path
        manifest = load_city_inventory_manifest(manifest_path)
        city_agents = [
            geo
            for geo in registry.geographies
            if geo.type == "city" and geo.state_fips == "53" and geo.boundary_path
        ]
        city_agent_keys = {
            (geo.jurisdiction_key, geo.boundary_path, geo.county_fips)
            for geo in city_agents
            if geo.jurisdiction_key and geo.county_fips
        }
        missing_places: list[str] = []
        missing_slices: list[str] = []
        for entry in manifest.entries:
            if not any(
                geo.jurisdiction_key == entry.jurisdiction_key and geo.boundary_path == entry.boundary_path
                for geo in city_agents
            ):
                missing_places.append(entry.geoid)
            for county in entry.county_fips:
                if (entry.jurisdiction_key, entry.boundary_path, county) not in city_agent_keys:
                    missing_slices.append(f"{entry.geoid}:{county}")
        if missing_places or missing_slices:
            counts["error"] += 1
        wa_city_summary = {
            "manifest": str(manifest_path.resolve()),
            "manifest_place_count": manifest.place_count,
            "manifest_county_slice_count": manifest.county_slice_count,
            "loaded_city_agent_count": len(city_agents),
            "missing_place_geoids": missing_places,
            "missing_county_slices": missing_slices,
            "lsadc_counts": manifest.lsadc_counts,
        }

    summary = {
        "registry": str(args.registry.resolve()),
        "pilot_config": str(args.pilot_config.resolve()),
        "source_count": len(registry.sources),
        "geography_count": len(registry.geographies),
        "city_inventory_source_count": len(registry.city_inventory_sources),
        "pilot_county_count": len(pilot.region.county_fips),
        "issue_counts": dict(counts),
        "issues": [issue.model_dump() for issue in issues],
        "wa_city_manifest": wa_city_summary,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Registry: {summary['registry']}")
        print(f"Sources: {summary['source_count']}")
        print(f"Geography agents: {summary['geography_count']}")
        print(f"City inventory sources: {summary['city_inventory_source_count']}")
        print(f"Pilot counties covered: {summary['pilot_county_count']}")
        if wa_city_summary:
            print(
                "WA city manifest: "
                f"{wa_city_summary['manifest_place_count']} places / "
                f"{wa_city_summary['manifest_county_slice_count']} county slices / "
                f"{wa_city_summary['loaded_city_agent_count']} loaded city agents"
            )
            if wa_city_summary["missing_place_geoids"] or wa_city_summary["missing_county_slices"]:
                print("  ERROR missing WA city manifest coverage")
        print(f"Issues: {summary['issue_counts'] or '{}'}")
        for issue in issues:
            geo = f" [{issue.geography_key}]" if issue.geography_key else ""
            print(f"  {issue.severity.upper()} {issue.code}{geo}: {issue.message}")

    return 1 if counts.get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

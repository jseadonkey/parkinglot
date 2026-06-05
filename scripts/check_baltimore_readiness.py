#!/usr/bin/env python3
"""Repo-level Baltimore readiness check for geography rollout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_paths() -> None:
    for pkg in ("packages/core", "services/ingestion"):
        p = _REPO_ROOT / pkg
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _exists(rel_path: str) -> bool:
    return (_REPO_ROOT / rel_path).is_file()


def main() -> int:
    _ensure_repo_paths()

    from parking_core.geography_registry import load_geography_registry
    from parking_ingestion.zoning_rules import load_effective_zoning_rules

    parser = argparse.ArgumentParser(description="Check Baltimore geography rollout readiness from repo assets.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    registry = load_geography_registry(_REPO_ROOT / "config/geography_registry.yaml")
    rules = load_effective_zoning_rules()
    jurisdictions = rules.get("jurisdictions") or {}
    city_rules = jurisdictions.get("baltimore_city") or {}
    county_rules = jurisdictions.get("baltimore_county_unincorporated") or {}

    city_checks = {
        "registry_agent": registry.geography_for_jurisdiction("baltimore_city") is not None,
        "curated_rules": bool(city_rules.get("zones")),
        "zoning_doc": _exists("docs/zoning-sources-baltimore.md"),
        "parcel_sample": _exists("data/baltimore/baltimore_city_parcels.geojson"),
        "zoning_district_sample": _exists("data/baltimore/baltimore_city_zoning_districts.geojson"),
        "overlay_sample": _exists("data/baltimore/baltimore_city_zoning_overlay.geojson"),
        "overlay_builder": _exists("scripts/build_baltimore_zoning_overlay.py"),
        "tier_report": _exists("scripts/summarize_baltimore_zoning_tiers.py"),
    }
    county_checks = {
        "registry_agent": registry.geography_for_jurisdiction("baltimore_county_unincorporated") is not None,
        "rules_skeleton": isinstance(county_rules, dict),
        "curated_rules": bool(county_rules.get("zones")) if isinstance(county_rules, dict) else False,
        "zoning_doc": _exists("docs/zoning-sources-baltimore-county.md"),
        "parcel_sample": _exists("data/baltimore/baltimore_county_parcels.geojson"),
        "zoning_district_sample": _exists("data/baltimore/baltimore_county_zoning_districts.geojson"),
        "overlay_sample": _exists("data/baltimore/baltimore_county_zoning_overlay.geojson"),
    }

    city_ready = all(city_checks.values())
    county_ready = all(county_checks.values())
    county_block = {
        "county_fips": "24005",
        "status": "ready" if county_ready else "scaffolded_not_ready",
        "checks": county_checks,
    }
    if county_ready:
        county_block["notes"] = [
            "County source docs, local overlay sample, and conservative reviewed-zone rules are present.",
            "Rules do not grant permitted-by-right zoning credit until counsel confirms specific zones.",
        ]
    else:
        county_block["next_steps"] = [
            "Select county zoning layer/source and document it.",
            "Curate data/zoning/md/baltimore_county_surface_parking_rules.yaml.",
            "Build county zoning overlay assets and enable ops rollout.",
        ]

    summary = {
        "baltimore_city": {
            "county_fips": "24510",
            "status": "ready" if city_ready else "needs_attention",
            "checks": city_checks,
        },
        "baltimore_county": county_block,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for label, block in summary.items():
            print(f"{label} ({block['county_fips']}): {block['status']}")
            for check, ok in block["checks"].items():
                print(f"  {'OK' if ok else 'NO'} {check}")
            if block.get("next_steps"):
                print("  next:")
                for step in block["next_steps"]:
                    print(f"    - {step}")
            if block.get("notes"):
                print("  notes:")
                for note in block["notes"]:
                    print(f"    - {note}")
    return 0 if city_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

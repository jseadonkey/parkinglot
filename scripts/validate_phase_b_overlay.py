#!/usr/bin/env python3
"""Dry-run validation for Phase B zoning overlay GeoJSON.

Uses the same ``iter_parcels_from_geojson_dict`` path as
``merge_parcel_attributes_geojson`` so counts match what the worker will iterate.

Usage:
  DATABASE_URL not required.
  python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson
  python3 scripts/validate_phase_b_overlay.py --json /path/to/overlay.geojson

Optional:
  ZONING_RULES_PATH — same as API/worker (see data/zoning/wa/README.md)
  PHASE_B_PILOT_CONFIG — defaults to config/pilot.yaml (region county filter)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_repo_paths() -> None:
    api_pkg = _REPO_ROOT / "services" / "api"
    if str(api_pkg) not in sys.path:
        sys.path.insert(0, str(api_pkg))
    for pkg in ("packages/core", "services/ingestion", "services/scoring"):
        p = _REPO_ROOT / pkg
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def main() -> int:
    _ensure_repo_paths()

    _default_rules = [
        _REPO_ROOT / "data/zoning/wa/kent_king_surface_parking_rules.yaml",
        _REPO_ROOT / "data/zoning/wa/wa_county_surface_parking_rules.yaml",
    ]
    _existing_rules = [str(path) for path in _default_rules if path.is_file()]
    if _existing_rules:
        os.environ.setdefault("ZONING_RULES_PATH", ",".join(_existing_rules))

    from parking_core.pilot import load_pilot_config
    from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path

    parser = argparse.ArgumentParser(description="Validate Phase B overlay GeoJSON before merge.")
    parser.add_argument("path", type=Path, help="Path to GeoJSON file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary only",
    )
    parser.add_argument(
        "--pilot-config",
        type=Path,
        default=None,
        help="Pilot YAML for region filter (default: config/pilot.yaml or PHASE_B_PILOT_CONFIG)",
    )
    args = parser.parse_args()

    pilot_path = args.pilot_config or Path(
        os.environ.get("PHASE_B_PILOT_CONFIG", str(_REPO_ROOT / "config" / "pilot.yaml"))
    )
    if not args.path.is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2

    data = load_geojson_path(args.path)
    pilot = load_pilot_config(pilot_path)
    allowed_counties = set(pilot.region.county_fips or [])

    total_iter = 0
    with_apn_county = 0
    skipped_region = 0
    missing_apn = 0
    missing_county = 0
    zoning_codes: Counter[str] = Counter()
    jurisdictions: Counter[str] = Counter()

    for attrs, _geom in iter_parcels_from_geojson_dict(data):
        total_iter += 1
        county = str(attrs.get("county_fips") or "").strip()
        apn = str(attrs.get("apn") or "").strip()
        if not apn:
            missing_apn += 1
        if not county:
            missing_county += 1
        if allowed_counties and county and county not in allowed_counties:
            skipped_region += 1
        if apn and county:
            with_apn_county += 1
        zc = attrs.get("zoning_code")
        if zc is not None and str(zc).strip():
            zoning_codes[str(zc).strip()[:80]] += 1
        jur = attrs.get("zoning_jurisdiction") or attrs.get("ZONING_JURISDICTION")
        if jur is not None and str(jur).strip():
            jurisdictions[str(jur).strip()[:64]] += 1

    summary = {
        "path": str(args.path.resolve()),
        "pilot_config": str(pilot_path.resolve()),
        "pilot_region_counties": sorted(allowed_counties),
        "features_iterated": total_iter,
        "features_with_apn_and_county": with_apn_county,
        "missing_apn": missing_apn,
        "missing_county_fips": missing_county,
        "skipped_wrong_region": skipped_region,
        "distinct_zoning_codes_seen": len(zoning_codes),
        "top_zoning_codes": dict(zoning_codes.most_common(15)),
        "top_zoning_jurisdictions": dict(jurisdictions.most_common(10)),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"Overlay: {summary['path']}")
    print(f"Pilot region counties ({pilot_path.name}): {summary['pilot_region_counties'] or '(none — no filter)'}")
    print(f"Features iterated (polygon features passed loader): {total_iter}")
    print(f"Rows with both apn + county_fips: {with_apn_county}")
    print(f"Missing apn (merge skips): {missing_apn}")
    print(f"Missing county_fips (merge skips): {missing_county}")
    print(f"Skipped wrong region vs pilot: {skipped_region}")
    print(f"Distinct zoning_code values: {len(zoning_codes)}")
    if zoning_codes:
        print("Top zoning codes:")
        for code, n in zoning_codes.most_common(10):
            print(f"  {n:5d}  {code}")
    if jurisdictions:
        print("Top zoning jurisdictions:")
        for j, n in jurisdictions.most_common(5):
            print(f"  {n:5d}  {j}")

    if total_iter == 0:
        print("\nwarning: no parcel rows yielded — check GeoJSON type and polygon features.", file=sys.stderr)
        return 1
    if missing_apn or missing_county:
        print(
            "\nwarning: rows missing apn/county will not update DB (same as merge task).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

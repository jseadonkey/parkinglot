#!/usr/bin/env python3
"""Validate zoning-governance coverage for pilot counties and priority markets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOVERNANCE = REPO_ROOT / "data" / "zoning" / "governance.yaml"
DEFAULT_PILOT = REPO_ROOT / "config" / "pilot.yaml"
DEFAULT_GEO_MARKETS = REPO_ROOT / "config" / "geo_markets.yaml"

OK_STATUSES = {"curated", "in_review", "not_started", "paused"}


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return raw


def _pilot_counties(path: Path) -> list[str]:
    raw = _load_yaml(path)
    region = raw.get("region") if isinstance(raw.get("region"), dict) else {}
    return [str(x).strip() for x in region.get("county_fips") or [] if str(x).strip()]


def _priority_counties(path: Path) -> set[str]:
    raw = _load_yaml(path)
    primary = raw.get("primary_market") if isinstance(raw.get("primary_market"), dict) else {}
    return {str(x).strip() for x in primary.get("priority_county_fips") or [] if str(x).strip()}


def _coverage_for_county(coverage: dict[str, Any], county_fips: str) -> tuple[str | None, dict[str, Any] | None]:
    if county_fips in coverage and isinstance(coverage[county_fips], dict):
        return county_fips, coverage[county_fips]
    state_key = county_fips[:2]
    if state_key in coverage and isinstance(coverage[state_key], dict):
        return state_key, coverage[state_key]
    return None, None


def _rules_for_jurisdiction(jurisdiction_key: str, rules_file: Path) -> dict[str, Any] | None:
    if not rules_file.is_file():
        return None
    raw = _load_yaml(rules_file)
    jurisdictions = raw.get("jurisdictions") if isinstance(raw.get("jurisdictions"), dict) else {}
    block = jurisdictions.get(jurisdiction_key)
    return block if isinstance(block, dict) else None


def validate(
    *,
    governance_path: Path = DEFAULT_GOVERNANCE,
    pilot_path: Path = DEFAULT_PILOT,
    geo_markets_path: Path = DEFAULT_GEO_MARKETS,
) -> dict[str, Any]:
    gov = _load_yaml(governance_path)
    coverage = gov.get("county_coverage") if isinstance(gov.get("county_coverage"), dict) else {}
    jurisdictions = gov.get("jurisdictions") if isinstance(gov.get("jurisdictions"), dict) else {}
    policy = gov.get("policy") if isinstance(gov.get("policy"), dict) else {}
    counties = _pilot_counties(pilot_path)
    priority = _priority_counties(geo_markets_path)

    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    if policy.get("unknown_default_must_be_false") is not True:
        errors.append("policy.unknown_default_must_be_false must be true")

    for county in counties:
        coverage_key, entry = _coverage_for_county(coverage, county)
        if entry is None:
            errors.append(f"county {county} has no zoning governance coverage entry")
            rows.append({"county_fips": county, "status": "missing", "priority": county in priority})
            continue

        status = str(entry.get("status") or "").strip()
        if status not in OK_STATUSES:
            errors.append(f"county {county} has invalid zoning governance status {status!r}")
        jkeys = [str(x).strip() for x in entry.get("jurisdiction_keys") or [] if str(x).strip()]
        priority_county = county in priority
        if priority_county and status != "curated":
            errors.append(f"priority county {county} must be curated before trusted scoring; got {status!r}")
        if status == "curated" and not jkeys:
            errors.append(f"curated county {county} must list jurisdiction_keys")

        rows.append(
            {
                "county_fips": county,
                "coverage_key": coverage_key,
                "status": status,
                "priority": priority_county,
                "jurisdiction_keys": jkeys,
                "note": entry.get("note"),
            }
        )

    for jkey, meta in jurisdictions.items():
        if not isinstance(meta, dict):
            errors.append(f"jurisdiction {jkey} metadata must be a mapping")
            continue
        status = str(meta.get("status") or "").strip()
        if status not in OK_STATUSES:
            errors.append(f"jurisdiction {jkey} has invalid status {status!r}")
            continue
        rules_rel = str(meta.get("rules_file") or "").strip()
        if not rules_rel:
            errors.append(f"jurisdiction {jkey} missing rules_file")
            continue
        rules_file = (REPO_ROOT / rules_rel).resolve()
        block = _rules_for_jurisdiction(str(jkey), rules_file)
        zones = block.get("zones") if isinstance(block, dict) and isinstance(block.get("zones"), dict) else {}
        if status == "curated":
            if block is None:
                errors.append(f"curated jurisdiction {jkey} missing rules block in {rules_rel}")
                continue
            if not zones:
                errors.append(f"curated jurisdiction {jkey} must have non-empty zone mappings")
            if not meta.get("source_doc"):
                errors.append(f"curated jurisdiction {jkey} missing source_doc")
            if not meta.get("last_reviewed"):
                errors.append(f"curated jurisdiction {jkey} missing last_reviewed")
            rules_raw = _load_yaml(rules_file)
            if rules_raw.get("default_when_unknown") is not False:
                errors.append(f"{rules_rel} must keep default_when_unknown=false")
        elif zones:
            warnings.append(f"jurisdiction {jkey} has {len(zones)} zones but status is {status!r}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "pilot_county_count": len(counties),
        "priority_county_fips": sorted(priority),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate zoning governance coverage.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE)
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--geo-markets", type=Path, default=DEFAULT_GEO_MARKETS)
    args = parser.parse_args()

    result = validate(
        governance_path=args.governance,
        pilot_path=args.pilot,
        geo_markets_path=args.geo_markets,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Zoning governance: {'OK' if result['ok'] else 'FAILED'}")
        print(f"Pilot counties: {result['pilot_county_count']}")
        print(f"Priority counties: {', '.join(result['priority_county_fips']) or '(none)'}")
        for row in result["rows"]:
            priority = " priority" if row.get("priority") else ""
            print(
                f"  {row['county_fips']}: {row.get('status')} via {row.get('coverage_key')}"
                f"{priority} jurisdictions={','.join(row.get('jurisdiction_keys') or []) or '-'}"
            )
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        for error in result["errors"]:
            print(f"error: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

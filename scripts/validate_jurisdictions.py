#!/usr/bin/env python3
"""Validate WA jurisdiction registry and source catalog (address + zoning tracking)."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "data" / "jurisdictions" / "wa" / "jurisdiction_registry.csv"
DEFAULT_CATALOG = REPO_ROOT / "data" / "jurisdictions" / "wa" / "source_catalog.csv"
DEFAULT_MAPS = REPO_ROOT / "data" / "jurisdictions" / "wa" / "address_field_maps.yaml"

REGISTRY_REQUIRED = {
    "state_fips",
    "county_fips",
    "county_name",
    "jurisdiction_type",
    "jurisdiction_id",
    "jurisdiction_name",
    "zoning_authority_status",
    "address_source_status",
    "last_checked_at",
}
CATALOG_REQUIRED = {
    "source_id",
    "source_type",
    "jurisdiction_id",
    "county_fips",
    "source_name",
    "address_source_status",
    "last_checked_at",
}
OK_ZONING_STATUS = {
    "not_started",
    "source_found",
    "layer_downloaded",
    "joined",
    "rules_drafted",
    "qa_passed",
    "blocked",
    "not_applicable",
    "in_review",
    "curated",
    "paused",
}
OK_ADDRESS_STATUS = {
    "not_started",
    "source_found",
    "ingested",
    "qa_passed",
    "blocked",
    "not_available",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def validate_registry(path: Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"missing registry: {path}"], warnings, []

    rows = _read_csv(path)
    if not rows:
        return ["registry is empty"], warnings, []

    seen_ids: set[str] = set()
    for i, row in enumerate(rows, start=2):
        missing = REGISTRY_REQUIRED - set(row.keys())
        if missing:
            errors.append(f"registry line {i}: missing columns {sorted(missing)}")
            continue
        jid = (row.get("jurisdiction_id") or "").strip()
        if not jid:
            errors.append(f"registry line {i}: empty jurisdiction_id")
            continue
        if jid in seen_ids:
            errors.append(f"registry line {i}: duplicate jurisdiction_id {jid}")
        seen_ids.add(jid)
        zst = (row.get("zoning_authority_status") or "").strip()
        ast = (row.get("address_source_status") or "").strip()
        if zst and zst not in OK_ZONING_STATUS:
            errors.append(f"registry line {i}: invalid zoning_authority_status {zst!r}")
        if ast and ast not in OK_ADDRESS_STATUS:
            errors.append(f"registry line {i}: invalid address_source_status {ast!r}")
        if row.get("state_fips") == "53" and not str(row.get("county_fips", "")).startswith("53"):
            warnings.append(f"registry line {i}: WA row with non-WA county_fips {row.get('county_fips')}")

    return errors, warnings, rows


def validate_catalog(path: Path, registry_ids: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"missing source catalog: {path}"], warnings

    rows = _read_csv(path)
    seen: set[str] = set()
    for i, row in enumerate(rows, start=2):
        missing = CATALOG_REQUIRED - set(row.keys())
        if missing:
            errors.append(f"catalog line {i}: missing columns {sorted(missing)}")
            continue
        sid = (row.get("source_id") or "").strip()
        if sid in seen:
            errors.append(f"catalog line {i}: duplicate source_id {sid}")
        seen.add(sid)
        jid = (row.get("jurisdiction_id") or "").strip()
        if jid and jid not in registry_ids:
            warnings.append(f"catalog line {i}: jurisdiction_id {jid} not in registry")
        ast = (row.get("address_source_status") or "").strip()
        if ast and ast not in OK_ADDRESS_STATUS:
            errors.append(f"catalog line {i}: invalid address_source_status {ast!r}")
    return errors, warnings


def validate_maps(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return [f"missing address field maps: {path}"], warnings
    text = path.read_text(encoding="utf-8")
    if "default_wa_watech:" not in text:
        errors.append("address_field_maps.yaml missing default_wa_watech")
    if "counties:" not in text:
        warnings.append("address_field_maps.yaml has no counties section")
    if '"53033"' not in text and "53033" not in text:
        warnings.append("address_field_maps.yaml has no King County (53033) entry")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate jurisdiction registry and address catalog")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--maps", type=Path, default=DEFAULT_MAPS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reg_errors, reg_warnings, reg_rows = validate_registry(args.registry)
    registry_ids = {(r.get("jurisdiction_id") or "").strip() for r in reg_rows}
    cat_errors, cat_warnings = validate_catalog(args.catalog, registry_ids)
    map_errors, map_warnings = validate_maps(args.maps)

    errors = reg_errors + cat_errors + map_errors
    warnings = reg_warnings + cat_warnings + map_warnings
    out = {
        "ok": not errors,
        "registry_rows": len(reg_rows),
        "errors": errors,
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Registry rows: {len(reg_rows)}")
        for w in warnings:
            print(f"WARNING: {w}")
        for e in errors:
            print(f"ERROR: {e}")
        print("OK" if not errors else f"FAILED ({len(errors)} error(s))")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

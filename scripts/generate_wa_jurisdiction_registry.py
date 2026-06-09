#!/usr/bin/env python3
"""Generate/refresh WA jurisdiction registry rows (all counties + seeded cities)."""

from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PILOT_SCOPE = REPO / "services" / "api" / "app" / "pilot_scope.py"
REGISTRY = REPO / "data" / "jurisdictions" / "wa" / "jurisdiction_registry.csv"
CITIES_SEED = REPO / "data" / "jurisdictions" / "wa" / "wa_cities_seed.yaml"
CATALOG = REPO / "data" / "jurisdictions" / "wa" / "source_catalog.csv"

FIELDS = [
    "state_fips",
    "county_fips",
    "county_name",
    "jurisdiction_type",
    "jurisdiction_id",
    "jurisdiction_name",
    "parent_county_fips",
    "zoning_authority_status",
    "address_source_status",
    "address_source_name",
    "value_source_status",
    "last_checked_at",
    "notes",
]


def _wa_county_names() -> dict[str, str]:
    tree = ast.parse(PILOT_SCOPE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "WA_COUNTY_NAMES" and node.value is not None:
                value = ast.literal_eval(node.value)
                return dict(value) if isinstance(value, dict) else {}
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "WA_COUNTY_NAMES":
                    value = ast.literal_eval(node.value)
                    return dict(value) if isinstance(value, dict) else {}
    return {}


def _load_cities() -> dict[str, list[dict[str, str]]]:
    raw = yaml.safe_load(CITIES_SEED.read_text(encoding="utf-8"))
    block = raw.get("cities_by_county_fips") if isinstance(raw, dict) else {}
    return block if isinstance(block, dict) else {}


def _slug_county(fips: str, name: str) -> str:
    base = name.lower().replace(" ", "_").replace("-", "_")
    return f"{base}_county"


def build_rows() -> list[dict[str, str]]:
    today = datetime.now(timezone.utc).date().isoformat()
    counties = _wa_county_names()
    cities = _load_cities()
    rows: list[dict[str, str]] = []

    # Baltimore reference row (priority MD)
    rows.append(
        {
            "state_fips": "24",
            "county_fips": "24510",
            "county_name": "Baltimore City",
            "jurisdiction_type": "city",
            "jurisdiction_id": "baltimore_city",
            "jurisdiction_name": "Baltimore City",
            "parent_county_fips": "24510",
            "zoning_authority_status": "joined",
            "address_source_status": "qa_passed",
            "address_source_name": "baltimore_realproperty",
            "value_source_status": "ingested",
            "last_checked_at": today,
            "notes": "Priority MD; address-health wave_0",
        }
    )

    for fips in sorted(counties):
        name = counties[fips]
        county_id = _slug_county(fips, name)
        addr_status = "ingested" if fips == "53033" else "not_started"
        addr_source = "watech_statewide" if fips.startswith("53") else ""
        rows.append(
            {
                "state_fips": "53",
                "county_fips": fips,
                "county_name": name,
                "jurisdiction_type": "countywide",
                "jurisdiction_id": county_id,
                "jurisdiction_name": f"{name} County",
                "parent_county_fips": fips,
                "zoning_authority_status": "not_started",
                "address_source_status": addr_status,
                "address_source_name": addr_source,
                "value_source_status": "not_started",
                "last_checked_at": today,
                "notes": "Auto-generated countywide row; cities expand via wa_cities_seed.yaml",
            }
        )
        rows.append(
            {
                "state_fips": "53",
                "county_fips": fips,
                "county_name": name,
                "jurisdiction_type": "county_unincorporated",
                "jurisdiction_id": f"{county_id.replace('_county', '')}_unincorporated",
                "jurisdiction_name": f"{name} County unincorporated",
                "parent_county_fips": fips,
                "zoning_authority_status": "not_started",
                "address_source_status": "not_started",
                "address_source_name": "",
                "value_source_status": "not_started",
                "last_checked_at": today,
                "notes": "Unincorporated zoning/address authority",
            }
        )
        for city in cities.get(fips, []):
            cid = str(city.get("id") or "").strip()
            cname = str(city.get("name") or "").strip()
            if not cid or not cname:
                continue
            rows.append(
                {
                    "state_fips": "53",
                    "county_fips": fips,
                    "county_name": name,
                    "jurisdiction_type": "city",
                    "jurisdiction_id": cid,
                    "jurisdiction_name": cname,
                    "parent_county_fips": fips,
                    "zoning_authority_status": "not_started",
                    "address_source_status": "not_started",
                    "address_source_name": "",
                    "value_source_status": "not_started",
                    "last_checked_at": today,
                    "notes": "City address source TBD — add to source_catalog when GIS found",
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate WA jurisdiction registry CSV")
    parser.add_argument("--out", type=Path, default=REGISTRY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = build_rows()
    if args.dry_run:
        print(f"Would write {len(rows)} rows to {args.out}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

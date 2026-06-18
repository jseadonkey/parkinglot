#!/usr/bin/env python3
"""Build Phase B overlay GeoJSON: Benton WaTech parcels × Tri-Cities zoning layers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ingest = ROOT / "services" / "ingestion"
if _ingest.is_dir():
    sys.path.insert(0, str(_ingest))

from parking_ingestion.benton_zoning_overlay import build_benton_zoning_overlay_geojson  # noqa: E402
from parking_ingestion.watech_parcels import fetch_county_geojson  # noqa: E402

BENTON_COUNTY_FIPS = "53005"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Benton County zoning overlay GeoJSON")
    parser.add_argument(
        "--parcels",
        type=Path,
        default=None,
        help="Parcel GeoJSON (WaTech export). When omitted, fetch live from WaTech.",
    )
    parser.add_argument(
        "--kennewick-table",
        type=Path,
        default=Path("data/benton/kennewick_parcel_zoning_by_tax_id.json"),
        help="Kennewick CountyTaxID → Zoning JSON from fetch_benton_zoning_layers.py",
    )
    parser.add_argument(
        "--pasco-zoning",
        type=Path,
        default=Path("data/benton/pasco_zoning_districts.geojson"),
    )
    parser.add_argument(
        "--benton-zoning",
        type=Path,
        default=Path("data/benton/benton_county_zoning_districts.geojson"),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/benton/benton_county_zoning_overlay.geojson"),
    )
    parser.add_argument(
        "--max-parcels",
        type=int,
        default=None,
        help="Optional cap when fetching parcels live from WaTech",
    )
    args = parser.parse_args()

    if args.parcels and args.parcels.is_file():
        parcels_fc = json.loads(args.parcels.read_text(encoding="utf-8"))
    else:
        print("Fetching Benton parcels from WaTech…", file=sys.stderr)
        parcels_fc = fetch_county_geojson(BENTON_COUNTY_FIPS, max_features=args.max_parcels)

    if not args.kennewick_table.is_file():
        print(f"error: Kennewick table not found: {args.kennewick_table}", file=sys.stderr)
        return 2
    kennewick = json.loads(args.kennewick_table.read_text(encoding="utf-8"))

    pasco_fc = None
    if args.pasco_zoning.is_file():
        pasco_fc = json.loads(args.pasco_zoning.read_text(encoding="utf-8"))
    benton_fc = None
    if args.benton_zoning.is_file():
        benton_fc = json.loads(args.benton_zoning.read_text(encoding="utf-8"))

    overlay = build_benton_zoning_overlay_geojson(
        parcels_fc,
        kennewick_zoning_by_tax_id=kennewick,
        pasco_zoning_fc=pasco_fc,
        benton_county_zoning_fc=benton_fc,
    )
    n = len(overlay.get("features", []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(overlay), encoding="utf-8")
    print(f"Wrote {n} overlay features to {args.output}")
    if n == 0:
        print("warning: no overlay features — check parcel APN keys and zoning caches", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

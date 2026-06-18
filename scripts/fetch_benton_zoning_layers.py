#!/usr/bin/env python3
"""Download Benton County / Tri-Cities zoning GIS layers for Phase B overlay work."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ingest = ROOT / "services" / "ingestion"
if _ingest.is_dir():
    sys.path.insert(0, str(_ingest))

from parking_ingestion.benton_zoning import (  # noqa: E402
    fetch_kennewick_zoning_by_tax_id,
    fetch_zoning_geojson,
    BENTON_COUNTY_ZONING_LAYER,
    PASCO_ZONING_LAYER,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Benton / Tri-Cities zoning GIS layers")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/benton"),
        help="Directory for cached GIS exports",
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=None,
        help="Optional cap per polygon layer (Kennewick table always full unless capped separately)",
    )
    parser.add_argument(
        "--kennewick-max",
        type=int,
        default=None,
        help="Optional cap for Kennewick parcel-zoning attribute table",
    )
    args = parser.parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    kennewick = fetch_kennewick_zoning_by_tax_id(max_features=args.kennewick_max)
    kennewick_path = out_dir / "kennewick_parcel_zoning_by_tax_id.json"
    kennewick_path.write_text(json.dumps(kennewick, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(kennewick)} Kennewick tax-id rows to {kennewick_path}")

    exit_code = 0
    for label, layer_url, filename in (
        ("Pasco zoning", PASCO_ZONING_LAYER, "pasco_zoning_districts.geojson"),
        ("Benton County zoning", BENTON_COUNTY_ZONING_LAYER, "benton_county_zoning_districts.geojson"),
    ):
        out_path = out_dir / filename
        try:
            fc = fetch_zoning_geojson(
                layer_url=layer_url,
                label=label,
                max_features=args.max_features,
            )
            out_path.write_text(json.dumps(fc), encoding="utf-8")
            print(f"Wrote {len(fc.get('features', []))} {label} polygons to {out_path}")
        except Exception as exc:
            print(f"warning: {label} fetch failed: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

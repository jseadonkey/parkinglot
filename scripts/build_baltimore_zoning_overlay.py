#!/usr/bin/env python3
"""Build Phase B overlay GeoJSON: Baltimore City parcels × CityView zoning districts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ingest = ROOT / "services" / "ingestion"
if _ingest.is_dir():
    sys.path.insert(0, str(_ingest))

from parking_ingestion.baltimore_zoning_overlay import build_zoning_overlay_geojson  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Spatial join Baltimore parcels to zoning districts")
    parser.add_argument(
        "--parcels",
        type=Path,
        default=Path("data/baltimore/baltimore_city_parcels.geojson"),
        help="Parcel GeoJSON (EGIS export)",
    )
    parser.add_argument(
        "--zoning",
        type=Path,
        default=Path("data/baltimore/baltimore_city_zoning_districts.geojson"),
        help="Zoning district GeoJSON (CityView export)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/baltimore/baltimore_city_zoning_overlay.geojson"),
    )
    parser.add_argument(
        "--zoning-field",
        default="Zoning",
        help="Property name on zoning features (CityView default: Zoning)",
    )
    args = parser.parse_args()

    if not args.parcels.is_file():
        print(f"error: parcels not found: {args.parcels}", file=sys.stderr)
        raise SystemExit(2)
    if not args.zoning.is_file():
        print(f"error: zoning not found: {args.zoning}", file=sys.stderr)
        raise SystemExit(2)

    parcels_fc = json.loads(args.parcels.read_text(encoding="utf-8"))
    zoning_fc = json.loads(args.zoning.read_text(encoding="utf-8"))
    overlay = build_zoning_overlay_geojson(
        parcels_fc,
        zoning_fc,
        zoning_field=args.zoning_field,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(overlay), encoding="utf-8")
    n = len(overlay.get("features", []))
    print(f"Wrote {n} overlay features to {args.output}")
    if n == 0:
        print("warning: no features — check parcel APN fields and zoning coverage", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

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

DEFAULTS = {
    "city": {
        "parcels": Path("data/baltimore/baltimore_city_parcels.geojson"),
        "zoning": Path("data/baltimore/baltimore_city_zoning_districts.geojson"),
        "output": Path("data/baltimore/baltimore_city_zoning_overlay.geojson"),
        "county_fips": "24510",
        "zoning_field": "Zoning",
        "jurisdiction": "baltimore_city",
    },
    "county": {
        "parcels": Path("data/baltimore/baltimore_county_parcels.geojson"),
        "zoning": Path("data/baltimore/baltimore_county_zoning_districts.geojson"),
        "output": Path("data/baltimore/baltimore_county_zoning_overlay.geojson"),
        "county_fips": "24005",
        "zoning_field": "ZONE_DIST",
        "jurisdiction": "baltimore_county_unincorporated",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Spatial join Baltimore parcels to zoning districts")
    parser.add_argument(
        "--county",
        choices=("city", "county"),
        default="city",
        help="Use Baltimore City or Baltimore County path/field defaults",
    )
    parser.add_argument(
        "--parcels",
        type=Path,
        default=None,
        help="Parcel GeoJSON (EGIS export)",
    )
    parser.add_argument(
        "--zoning",
        type=Path,
        default=None,
        help="Zoning district GeoJSON (CityView export)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--zoning-field",
        default=None,
        help="Property name on zoning features (CityView default: Zoning)",
    )
    parser.add_argument("--county-fips", default=None)
    parser.add_argument("--zoning-jurisdiction", default=None)
    args = parser.parse_args()

    defaults = DEFAULTS[args.county]
    parcels = args.parcels or defaults["parcels"]
    zoning = args.zoning or defaults["zoning"]
    output = args.output or defaults["output"]
    zoning_field = args.zoning_field or str(defaults["zoning_field"])
    county_fips = args.county_fips or str(defaults["county_fips"])
    jurisdiction = args.zoning_jurisdiction or str(defaults["jurisdiction"])

    if not parcels.is_file():
        print(f"error: parcels not found: {parcels}", file=sys.stderr)
        raise SystemExit(2)
    if not zoning.is_file():
        print(f"error: zoning not found: {zoning}", file=sys.stderr)
        raise SystemExit(2)

    parcels_fc = json.loads(parcels.read_text(encoding="utf-8"))
    zoning_fc = json.loads(zoning.read_text(encoding="utf-8"))
    overlay = build_zoning_overlay_geojson(
        parcels_fc,
        zoning_fc,
        county_fips=county_fips,
        zoning_field=zoning_field,
        zoning_jurisdiction=jurisdiction,
    )
    n = len(overlay.get("features", []))
    payload = json.dumps(overlay)
    if str(output) == "-":
        sys.stdout.write(payload)
        print(f"Wrote {n} overlay features to stdout", file=sys.stderr)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"Wrote {n} overlay features to {output}")
    if n == 0:
        print("warning: no features — check parcel APN fields and zoning coverage", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

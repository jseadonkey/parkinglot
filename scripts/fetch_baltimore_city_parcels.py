#!/usr/bin/env python3
"""Download Baltimore City parcel GeoJSON from EGIS (for local ingest or scp to Droplet)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "ingestion"))

from parking_ingestion.baltimore_parcels import fetch_baltimore_city_geojson  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Baltimore City parcels from EGIS ArcGIS")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/baltimore_city_parcels.geojson"),
        help="Output GeoJSON path",
    )
    parser.add_argument("--max-features", type=int, default=None, help="Cap feature count")
    args = parser.parse_args()

    collection = fetch_baltimore_city_geojson(max_features=args.max_features)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection), encoding="utf-8")
    n = len(collection.get("features", []))
    print(f"Wrote {n} features to {args.output}")


if __name__ == "__main__":
    main()

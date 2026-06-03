#!/usr/bin/env python3
"""Download Baltimore City parcel GeoJSON from EGIS (for local ingest or scp to Droplet)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_fetcher():
    """Load fetcher without importing parking_ingestion.__init__ (avoids shapely on bare host)."""
    import importlib.util

    mod_path = ROOT / "services/ingestion/parking_ingestion/baltimore_parcels.py"
    spec = importlib.util.spec_from_file_location("baltimore_parcels", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.fetch_baltimore_city_geojson


fetch_baltimore_city_geojson = _load_fetcher()


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

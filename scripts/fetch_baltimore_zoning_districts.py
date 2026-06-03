#!/usr/bin/env python3
"""Download Baltimore City zoning district polygons from CityView/Zoning_New (for overlay joins)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BALTIMORE_ZONING_LAYER = (
    "https://geodata.baltimorecity.gov/egis/rest/services/CityView/Zoning_New/MapServer/0"
)


def fetch_zoning_geojson(
    *,
    page_size: int = 1000,
    max_features: int | None = None,
    sleep_sec: float = 0.2,
    layer_url: str = BALTIMORE_ZONING_LAYER,
) -> dict:
    features: list[dict] = []
    offset = 0
    total_cap = max_features if max_features is not None else 10**12

    while len(features) < total_cap:
        batch_limit = min(page_size, total_cap - len(features))
        params: dict[str, str | int] = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
        qs = urllib.parse.urlencode(params)
        url = f"{layer_url.rstrip('/')}/query?{qs}"
        print(f"Fetch offset={offset} limit={batch_limit}", file=sys.stderr)

        req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Baltimore zoning query failed: {e}") from e

        data = json.loads(raw)
        batch = data.get("features") or []
        if not batch:
            break
        features.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)

    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Baltimore City zoning districts GeoJSON")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/baltimore/baltimore_city_zoning_districts.geojson"),
    )
    parser.add_argument("--max-features", type=int, default=None)
    args = parser.parse_args()

    collection = fetch_zoning_geojson(max_features=args.max_features)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection), encoding="utf-8")
    n = len(collection.get("features", []))
    print(f"Wrote {n} zoning features to {args.output}")
    if n and collection["features"]:
        props = collection["features"][0].get("properties") or {}
        print("Sample property keys:", sorted(props.keys())[:20], file=sys.stderr)


if __name__ == "__main__":
    main()

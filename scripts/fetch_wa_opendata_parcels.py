#!/usr/bin/env python3
"""Download WaTech public parcel GeoJSON for one WA county (writes a file).

From repo root (after ``pip install -e ./services/ingestion``):

  python scripts/fetch_wa_opendata_parcels.py --county-fips 53033 --out /tmp/king.geojson --max-features 2000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "services" / "ingestion"))

from parking_ingestion.watech_parcels import fetch_county_geojson  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch WaTech statewide parcels for one county.")
    p.add_argument("--county-fips", required=True, help="5-digit WA county FIPS, e.g. 53033")
    p.add_argument("--out", required=True, type=Path, help="Output GeoJSON path")
    p.add_argument("--max-features", type=int, default=5000)
    args = p.parse_args()

    data = fetch_county_geojson(args.county_fips, max_features=args.max_features)
    n = len(data.get("features", []))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data), encoding="utf-8")
    print(f"Wrote {n} features to {args.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Print property keys from the first feature of an ArcGIS Feature Layer or local GeoJSON.

Use this to pick ``--kent-zone-field`` / ``--king-zone-field`` for
``scripts/build_king_kent_zoning_overlay.py``.

  python3 scripts/inspect_zoning_layer.py 'https://…/FeatureServer/0'
  python3 scripts/inspect_zoning_layer.py /path/to/zoning.geojson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _fetch_first_feature_geojson(layer_base_url: str) -> dict | None:
    base = layer_base_url.rstrip("/")
    if not base.lower().endswith("/query"):
        base = f"{base}/query"
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "resultRecordCount": "1",
        "resultOffset": "0",
    }
    url = f"{base}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "parkinglot-zoning-inspect/1.0"})
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.reason}") from e
    except URLError as e:
        raise RuntimeError(str(e)) from e

    chunk = json.loads(raw)
    feats = chunk.get("features") or []
    return feats[0] if feats else None


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect zoning GeoJSON / Esri layer fields.")
    p.add_argument("source", help="FeatureServer …/0 URL or path to .geojson")
    p.add_argument("--json", action="store_true", help="Print raw properties JSON only")
    args = p.parse_args()
    src = args.source.strip()

    if src.lower().startswith(("http://", "https://")):
        try:
            feat = _fetch_first_feature_geojson(src)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if feat is None:
            print("error: no features returned (check URL and layer permissions).", file=sys.stderr)
            return 2
        props = feat.get("properties") or {}
    else:
        path = Path(src)
        if not path.is_file():
            print(f"error: not found: {path}", file=sys.stderr)
            return 2
        data = json.loads(path.read_text())
        feats = data.get("features") or []
        if not feats:
            print("error: no features in file.", file=sys.stderr)
            return 2
        props = feats[0].get("properties") or {}

    if args.json:
        print(json.dumps(props, indent=2))
        return 0

    keys = sorted(props.keys())
    print(f"Property keys ({len(keys)}):", flush=True)
    for k in keys:
        v = props[k]
        preview = repr(v)
        if len(preview) > 72:
            preview = preview[:69] + "..."
        print(f"  {k}: {preview}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

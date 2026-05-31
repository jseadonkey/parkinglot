#!/usr/bin/env python3
"""Build Phase B merge-ready GeoJSON: zoning from published GIS layers + parcel footprints from Postgres.

Automates the spatial join described in docs/zoning-sources-kent.md (no desktop GIS).
Supply Esri Feature Layer base URLs (``…/FeatureServer/0``) or local GeoJSON files. Comply
with each provider’s terms (King County has redistribution restrictions — see their catalog).

Examples:

  export DATABASE_URL=postgresql+psycopg://...
  export KENT_ZONING='https://…/FeatureServer/0'
  export KING_ZONING='https://…/FeatureServer/0'

  python3 scripts/build_king_kent_zoning_overlay.py \\
    -o data/zoning/wa/king_kent_zoning_overlay.geojson \\
    --kent-zone-field ZONE_ABBR --king-zone-field CURRZONE

  python3 scripts/validate_phase_b_overlay.py data/zoning/wa/king_kent_zoning_overlay.geojson
  PHASE_B_OVERLAY_PATH=/app/data/zoning/wa/king_kent_zoning_overlay.geojson ./scripts/execute-phase-b.sh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from parcel_export_common import ensure_api_path, normalize_database_url

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fetch_esri_query_pages(layer_base_url: str, *, page_size: int = 2000) -> dict[str, Any]:
    """Fetch all features from an ArcGIS Feature Layer query endpoint (paged GeoJSON)."""
    base = layer_base_url.rstrip("/")
    if not base.lower().endswith("/query"):
        base = f"{base}/query"

    all_features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "resultRecordCount": str(page_size),
            "resultOffset": str(offset),
        }
        url = f"{base}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "parkinglot-overlay-builder/1.0"})
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} fetching {base}: {e.reason}") from e
        except URLError as e:
            raise RuntimeError(f"network error fetching {base}: {e}") from e

        chunk = json.loads(raw)
        feats = chunk.get("features") or []
        if not feats:
            break
        all_features.extend(feats)
        if len(feats) < page_size:
            break
        offset += page_size

    return {"type": "FeatureCollection", "features": all_features}


def _load_geojson_path(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_zoning_source(src: str) -> dict[str, Any]:
    s = src.strip()
    if s.lower().startswith(("http://", "https://")):
        return _fetch_esri_query_pages(s)
    p = Path(s)
    if not p.is_file():
        raise FileNotFoundError(f"zoning source not found: {p}")
    return _load_geojson_path(p)


def _geom_props_pairs(fc: dict[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    from shapely.geometry import shape

    geoms = []
    props: list[dict[str, Any]] = []
    features = fc.get("features") if fc.get("type") == "FeatureCollection" else []
    for feat in features:
        g = feat.get("geometry")
        if not g:
            continue
        geoms.append(shape(g))
        props.append(dict(feat.get("properties") or {}))
    return geoms, props


def _zone_value(props: dict[str, Any], field: str) -> str | None:
    if field not in props or props[field] is None:
        return None
    s = str(props[field]).strip()
    return s if s else None


def _pick_zoning_for_point(
    pt,
    tree,
    geoms: list,
    prop_rows: list[dict[str, Any]],
    zone_field: str,
) -> str | None:
    from shapely import prepared

    cand = list(tree.query(pt, predicate="within"))
    if not cand:
        cand = list(tree.query(pt, predicate="intersects"))
    if not cand:
        return None

    best: tuple[float, str | None] | None = None
    for i in cand:
        g = geoms[i]
        if not g.contains(pt) and not g.intersects(pt):
            continue
        pr = prepared.prep(g)
        if not pr.contains(pt) and not pr.intersects(pt):
            continue
        z = _zone_value(prop_rows[i], zone_field)
        if z is None:
            continue
        try:
            area = float(g.area)
        except Exception:
            area = 0.0
        if best is None or area < best[0]:
            best = (area, z)
    return best[1] if best else None


def _load_kent_boundary(path: Path):
    from shapely.geometry import shape
    from shapely.ops import unary_union

    data = _load_geojson_path(path)
    feats = data.get("features") or []
    polys = []
    for f in feats:
        name = str((f.get("properties") or {}).get("name") or "").lower()
        if "kent" in name and "city" in name:
            polys.append(shape(f["geometry"]))
    if not polys:
        for f in feats:
            polys.append(shape(f["geometry"]))
    return unary_union(polys)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build King/Kent zoning overlay GeoJSON from GIS + DB.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output GeoJSON path")
    parser.add_argument(
        "--boundary-geojson",
        type=Path,
        default=_REPO_ROOT / "data/boundaries/wa/kent_city_census_places.geojson",
        help="Kent city polygon(s) for jurisdiction split",
    )
    parser.add_argument("--county-fips", default="53033", help="Parcel county filter (default King)")
    parser.add_argument("--limit", type=int, default=None, help="Max parcels (debug)")
    parser.add_argument("--kent-zone-field", default=os.environ.get("KENT_ZONE_FIELD", "ZONE_ABBR"))
    parser.add_argument("--king-zone-field", default=os.environ.get("KING_ZONE_FIELD", "CURRZONE"))
    parser.add_argument(
        "--kent-zoning",
        default=os.environ.get("KENT_ZONING", "").strip(),
        help="Kent zoning: FeatureServer layer URL or GeoJSON path (env KENT_ZONING)",
    )
    parser.add_argument(
        "--king-zoning",
        default=os.environ.get("KING_ZONING", "").strip(),
        help="King unincorporated zoning: URL or GeoJSON path (env KING_ZONING)",
    )
    args = parser.parse_args()

    if not args.kent_zoning:
        print("error: set --kent-zoning or KENT_ZONING", file=sys.stderr)
        return 2
    if not args.king_zoning:
        print("error: set --king-zoning or KING_ZONING", file=sys.stderr)
        return 2
    if not os.environ.get("DATABASE_URL", "").strip():
        print("error: DATABASE_URL is required.", file=sys.stderr)
        return 2

    ensure_api_path()

    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping
    from shapely.strtree import STRtree
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Parcel

    print("Loading Kent city boundary…", flush=True)
    kent_boundary = _load_kent_boundary(args.boundary_geojson)

    print("Loading zoning layers…", flush=True)
    try:
        kent_fc = _load_zoning_source(args.kent_zoning)
        king_fc = _load_zoning_source(args.king_zoning)
    except (OSError, RuntimeError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    k_geoms, k_props = _geom_props_pairs(kent_fc)
    king_geoms, king_props = _geom_props_pairs(king_fc)
    if not k_geoms:
        print("error: Kent zoning source has no polygon features.", file=sys.stderr)
        return 2
    if not king_geoms:
        print("error: King zoning source has no polygon features.", file=sys.stderr)
        return 2

    k_tree = STRtree(k_geoms)
    king_tree = STRtree(king_geoms)

    url = normalize_database_url(os.environ["DATABASE_URL"].strip())
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()

    stmt = select(Parcel).where(Parcel.county_fips == args.county_fips, Parcel.footprint.isnot(None))
    if args.limit:
        stmt = stmt.limit(args.limit)

    out_features: list[dict[str, Any]] = []
    try:
        rows = db.scalars(stmt).all()
        print(f"Joining zoning for {len(rows)} parcels…", flush=True)
        for row in rows:
            fp = row.footprint
            if fp is None:
                continue
            geom = to_shape(fp)
            c = geom.centroid
            inside_kent = kent_boundary.contains(c)
            juris = "kent_city" if inside_kent else "king_unincorporated"
            if inside_kent:
                zone = _pick_zoning_for_point(c, k_tree, k_geoms, k_props, args.kent_zone_field)
            else:
                zone = _pick_zoning_for_point(c, king_tree, king_geoms, king_props, args.king_zone_field)

            props: dict[str, Any] = {
                "APN": row.apn,
                "COUNTY_FIPS": row.county_fips,
                "ZONING_JURISDICTION": juris,
            }
            if zone:
                props["ZONING"] = zone
            out_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": props,
                }
            )
    finally:
        db.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fc_out = {"type": "FeatureCollection", "features": out_features}
    args.output.write_text(json.dumps(fc_out, indent=2))
    print(f"Wrote {len(out_features)} features to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

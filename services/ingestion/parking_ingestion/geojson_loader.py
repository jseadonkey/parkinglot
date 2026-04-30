from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


def _prop(props: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in props and props[k] is not None:
            return props[k]
    return default


def iter_parcels_from_geojson_dict(
    data: dict[str, Any],
) -> Iterator[tuple[dict[str, Any], BaseGeometry]]:
    """Yield (attributes dict, shapely geometry) for each polygon feature."""
    ftype = data.get("type")
    if ftype == "FeatureCollection":
        features = data.get("features", [])
    elif ftype == "Feature":
        features = [data]
    else:
        msg = f"Unsupported GeoJSON type: {ftype}"
        raise ValueError(msg)

    for feat in features:
        geom = shape(feat["geometry"])
        props = feat.get("properties") or {}
        apn = str(_prop(props, "APN", "apn", default=""))
        county = str(_prop(props, "COUNTY_FIPS", "county_fips", default=""))
        attrs = {
            "apn": apn,
            "county_fips": county,
            "lot_sqft": _prop(props, "LOT_SQFT", "lot_sqft"),
            "zoning_code": _prop(props, "ZONING", "zoning_code"),
            "zoning_allows_surface_parking": bool(
                _prop(props, "ZONING_ALLOWS_SURFACE_PARKING", "zoning_allows_surface_parking", default=False)
            ),
            "is_corner_lot": bool(_prop(props, "IS_CORNER", "is_corner", default=False)),
            "distance_to_nearest_demand_m": _prop(props, "DIST_DEMAND_M", "distance_to_nearest_demand_m"),
            "raw_properties": props,
        }
        yield attrs, geom


def load_geojson_path(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())

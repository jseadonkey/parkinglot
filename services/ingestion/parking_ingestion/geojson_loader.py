from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from parking_ingestion.zoning_rules import (
    effective_zoning_rules_path,
    load_zoning_rules,
    resolve_surface_parking,
)


def _prop(props: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in props and props[k] is not None:
            return props[k]
    return default


def _explicit_surface_parking(props: dict[str, Any]) -> bool | None:
    """Tri-state: key absent → None (infer from rules); key present → bool."""
    for k in ("ZONING_ALLOWS_SURFACE_PARKING", "zoning_allows_surface_parking"):
        if k in props:
            return bool(props[k])
    return None


def _lot_sqft_from_props(props: dict[str, Any]) -> float | None:
    """Square feet from common assessor / GIS column names (incl. WA county exports)."""
    direct = _prop(
        props,
        "LOT_SQFT",
        "lot_sqft",
        "LAND_SQFT",
        "land_sqft",
        "LOT_SIZE_SQFT",
        "Shape_Area",
        "SHAPE_AREA",
        default=None,
    )
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    acres = _prop(props, "CALC_ACRES", "calc_acres", "ACRES", "acres", "LOT_ACRES", "lot_acres", default=None)
    if acres is not None:
        try:
            return float(acres) * 43560.0
        except (TypeError, ValueError):
            return None
    return None


def iter_parcels_from_geojson_dict(
    data: dict[str, Any],
    *,
    rules_path: Path | None = None,
) -> Iterator[tuple[dict[str, Any], BaseGeometry]]:
    """Yield (attributes dict, shapely geometry) for each polygon feature.

    ``rules_path``: optional path to ``kent_king_surface_parking_rules.yaml``. When ``None``,
    resolves via ``effective_zoning_rules_path`` (env ``ZONING_RULES_PATH``, then
    ``/app/data/zoning/wa/...``, then ``cwd/data/zoning/wa/...``).
    """
    eff_rules_path = effective_zoning_rules_path(rules_path)
    rules = load_zoning_rules(eff_rules_path)

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
        apn = str(
            _prop(
                props,
                "APN",
                "apn",
                "PIN",
                "pin",
                "PARCEL_ID",
                "parcel_id",
                "PARCEL_ID_NR",
                "PARCEL_NBR",
                "parcel_nbr",
                "PARCEL_NUM",
                "parcel_num",
                "ORIG_PARCEL_ID",
                "orig_parcel_id",
                "TaxParcelID",
                "TAXPARCELID",
                default="",
            )
        ).strip()
        county = str(_prop(props, "COUNTY_FIPS", "county_fips", "COUNTYFP", "COUNTY_FIP", default="")).strip()
        zoning_code = _prop(props, "ZONING", "zoning_code", "ZONE", "zone", "ZONING_CLASS", "ZONING_CODE")
        juris = _prop(props, "ZONING_JURISDICTION", "zoning_jurisdiction")
        juris_s = str(juris).strip() if juris is not None else None

        explicit_sp = _explicit_surface_parking(props)
        zoning_ok = resolve_surface_parking(
            str(zoning_code) if zoning_code is not None else None,
            juris_s,
            explicit_sp,
            rules,
        )

        attrs = {
            "apn": apn,
            "county_fips": county,
            "lot_sqft": _lot_sqft_from_props(props),
            "zoning_code": zoning_code,
            "zoning_allows_surface_parking": zoning_ok,
            "is_corner_lot": bool(_prop(props, "IS_CORNER", "is_corner", default=False)),
            "distance_to_nearest_demand_m": _prop(props, "DIST_DEMAND_M", "distance_to_nearest_demand_m"),
            "raw_properties": props,
        }
        yield attrs, geom


def load_geojson_path(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())

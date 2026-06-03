"""Spatial join Baltimore City parcels to CityView zoning districts (Phase B overlay)."""

from __future__ import annotations

import logging
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from parking_ingestion.baltimore_parcels import BALTIMORE_CITY_COUNTY_FIPS, parcel_apn_from_props

logger = logging.getLogger(__name__)

DEFAULT_ZONING_FIELD = "Zoning"


def _parcel_apn(props: dict[str, Any], *, county_fips: str = BALTIMORE_CITY_COUNTY_FIPS) -> str:
    return parcel_apn_from_props(props, county_fips=county_fips)


def _zoning_code_from_props(props: dict[str, Any], zoning_field: str) -> str | None:
    for key in (zoning_field, "Zoning", "ZONING", "zoning_code", "DISTRICT"):
        val = props.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _best_zoning_index(
    parcel_geom: BaseGeometry,
    candidate_indices: list[int],
    zoning_geoms: list[BaseGeometry],
) -> int | None:
    """Pick zoning polygon: prefer contains(centroid), else largest intersection area."""
    if not candidate_indices:
        return None
    if len(candidate_indices) == 1:
        return candidate_indices[0]

    pt = parcel_geom.representative_point()
    for idx in candidate_indices:
        if zoning_geoms[idx].contains(pt):
            return idx

    best_idx: int | None = None
    best_area = 0.0
    for idx in candidate_indices:
        try:
            inter = parcel_geom.intersection(zoning_geoms[idx])
            area = float(inter.area) if not inter.is_empty else 0.0
        except Exception:
            area = 0.0
        if area > best_area:
            best_area = area
            best_idx = idx
    return best_idx


def build_zoning_overlay_geojson(
    parcels_fc: dict[str, Any],
    zoning_fc: dict[str, Any],
    *,
    county_fips: str = BALTIMORE_CITY_COUNTY_FIPS,
    zoning_field: str = DEFAULT_ZONING_FIELD,
    zoning_jurisdiction: str = "baltimore_city",
) -> dict[str, Any]:
    """Join parcel polygons to zoning districts; output overlay FeatureCollection for merge."""
    parcel_features = parcels_fc.get("features") or []
    zoning_features = zoning_fc.get("features") or []
    if not parcel_features:
        return {"type": "FeatureCollection", "features": []}
    if not zoning_features:
        raise ValueError("zoning FeatureCollection has no features")

    zoning_geoms: list[BaseGeometry] = []
    zoning_codes: list[str | None] = []
    for zf in zoning_features:
        zprops = zf.get("properties") or {}
        zoning_geoms.append(shape(zf["geometry"]))
        zoning_codes.append(_zoning_code_from_props(zprops, zoning_field))

    tree = STRtree(zoning_geoms)
    out_features: list[dict[str, Any]] = []
    matched = 0
    no_zoning_code = 0
    unmatched = 0

    for pf in parcel_features:
        props = dict(pf.get("properties") or {})
        apn = _parcel_apn(props, county_fips=county_fips)
        if not apn:
            continue
        if not str(props.get("COUNTY_FIPS", "")).strip():
            props["COUNTY_FIPS"] = county_fips

        p_geom = shape(pf["geometry"])
        if p_geom.is_empty:
            continue

        pt = p_geom.representative_point()
        try:
            hit_indices = list(tree.query(pt, predicate="intersects"))
        except TypeError:
            hit_indices = [i for i, zg in enumerate(zoning_geoms) if zg.intersects(pt)]

        z_idx = _best_zoning_index(p_geom, hit_indices, zoning_geoms)
        if z_idx is None:
            unmatched += 1
            continue

        z_code = zoning_codes[z_idx]
        if not z_code:
            no_zoning_code += 1
            continue

        matched += 1
        props["APN"] = apn
        props["COUNTY_FIPS"] = county_fips
        props["ZONING"] = z_code
        props["ZONING_JURISDICTION"] = zoning_jurisdiction

        out_features.append(
            {
                "type": "Feature",
                "geometry": pf["geometry"],
                "properties": props,
            }
        )

    logger.info(
        "baltimore zoning overlay: parcels_in=%s matched=%s unmatched=%s no_zoning_code=%s out=%s",
        len(parcel_features),
        matched,
        unmatched,
        no_zoning_code,
        len(out_features),
    )
    return {"type": "FeatureCollection", "features": out_features}

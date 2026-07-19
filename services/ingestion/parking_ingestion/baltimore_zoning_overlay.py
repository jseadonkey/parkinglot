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


def _feature_geometry(feat: dict[str, Any]) -> BaseGeometry | None:
    """Return shapely geometry for a GeoJSON feature, or None if missing/invalid."""
    geom = feat.get("geometry")
    if not geom or not isinstance(geom, dict):
        return None
    try:
        g = shape(geom)
    except Exception:
        return None
    return None if g.is_empty else g


def _filter_features_with_geometry(
    features: list[dict[str, Any]],
    *,
    label: str,
) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    skipped = 0
    for feat in features:
        if _feature_geometry(feat) is None:
            skipped += 1
            continue
        kept.append(feat)
    if skipped:
        logger.warning("%s: skipped %s features with missing/invalid geometry", label, skipped)
    return kept, skipped


def _parcel_apn(props: dict[str, Any], *, county_fips: str = BALTIMORE_CITY_COUNTY_FIPS) -> str:
    apn = parcel_apn_from_props(props, county_fips=county_fips)
    if apn:
        return apn
    for key in ("PARCEL_ID_NR", "ORIG_PARCEL_ID", "PIN", "TAXPIN"):
        val = str(props.get(key) or "").strip()
        if val:
            return val
    return ""


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
    jurisdiction_field: str | None = None,
    jurisdiction_normalizer: Any | None = None,
    extra_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Join parcel polygons to zoning districts; output overlay FeatureCollection for merge.

    ``jurisdiction_field`` (optional): read ``ZONING_JURISDICTION`` per-zoning-feature
    (e.g. WAZA ``Jurisdiction``) instead of the fixed ``zoning_jurisdiction`` string;
    ``jurisdiction_normalizer`` maps the raw name to a stable key. ``extra_fields``
    copies additional zoning-feature attributes onto the matched parcel.
    """
    parcel_features = parcels_fc.get("features") or []
    zoning_features = zoning_fc.get("features") or []
    if not parcel_features:
        return {"type": "FeatureCollection", "features": []}
    if not zoning_features:
        raise ValueError("zoning FeatureCollection has no features")

    parcel_features, skipped_parcels = _filter_features_with_geometry(
        list(parcel_features),
        label="parcel",
    )
    zoning_features, skipped_zoning = _filter_features_with_geometry(
        list(zoning_features),
        label="zoning",
    )
    if not parcel_features:
        return {"type": "FeatureCollection", "features": []}
    if not zoning_features:
        raise ValueError("zoning FeatureCollection has no valid features")

    extra_fields = list(extra_fields or [])
    zoning_geoms: list[BaseGeometry] = []
    zoning_codes: list[str | None] = []
    zoning_jurisdictions: list[str] = []
    zoning_extras: list[dict[str, Any]] = []
    for zf in zoning_features:
        zprops = zf.get("properties") or {}
        z_geom = _feature_geometry(zf)
        if z_geom is None:
            continue
        zoning_geoms.append(z_geom)
        zoning_codes.append(_zoning_code_from_props(zprops, zoning_field))
        juris = zoning_jurisdiction
        if jurisdiction_field:
            raw_j = zprops.get(jurisdiction_field)
            if raw_j is not None and str(raw_j).strip():
                juris = (
                    jurisdiction_normalizer(str(raw_j).strip())
                    if jurisdiction_normalizer is not None
                    else str(raw_j).strip()
                )
        zoning_jurisdictions.append(juris or zoning_jurisdiction)
        zoning_extras.append(
            {f: zprops.get(f) for f in extra_fields if zprops.get(f) is not None}
        )

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

        p_geom = _feature_geometry(pf)
        if p_geom is None:
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
        props["ZONING_JURISDICTION"] = zoning_jurisdictions[z_idx]
        for k, v in zoning_extras[z_idx].items():
            props.setdefault(k, v)

        out_features.append(
            {
                "type": "Feature",
                "geometry": pf["geometry"],
                "properties": props,
            }
        )

    logger.info(
        "baltimore zoning overlay: parcels_in=%s skipped_parcels=%s skipped_zoning=%s "
        "matched=%s unmatched=%s no_zoning_code=%s out=%s",
        len(parcels_fc.get("features") or []),
        skipped_parcels,
        skipped_zoning,
        matched,
        unmatched,
        no_zoning_code,
        len(out_features),
    )
    return {"type": "FeatureCollection", "features": out_features}

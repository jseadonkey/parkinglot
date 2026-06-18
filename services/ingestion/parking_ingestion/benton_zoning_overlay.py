"""Build Phase B overlay GeoJSON for Benton County parcels × Tri-Cities zoning sources."""

from __future__ import annotations

import logging
from typing import Any

from parking_ingestion.baltimore_zoning_overlay import build_zoning_overlay_geojson
from parking_ingestion.benton_zoning import (
    BENTON_COUNTY_FIPS,
    normalize_benton_county_tax_id,
    situs_city_from_props,
)

logger = logging.getLogger(__name__)


def _parcel_apn(props: dict[str, Any]) -> str:
    for key in ("PARCEL_ID_NR", "APN", "apn", "ORIG_PARCEL_ID"):
        val = str(props.get(key) or "").strip()
        if val:
            return val
    return ""


def _overlay_feature(
    *,
    apn: str,
    zoning_code: str,
    jurisdiction: str,
    match_method: str,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "APN": apn,
            "COUNTY_FIPS": BENTON_COUNTY_FIPS,
            "ZONING": zoning_code,
            "ZONING_JURISDICTION": jurisdiction,
            "ZONING_MATCH_METHOD": match_method,
        },
    }


def apply_kennewick_attribute_join(
    parcels_fc: dict[str, Any],
    *,
    kennewick_zoning_by_tax_id: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (overlay_features, unmatched_parcel_features)."""
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for feat in parcels_fc.get("features") or []:
        props = feat.get("properties") or {}
        apn = _parcel_apn(props)
        tax_id = normalize_benton_county_tax_id(apn)
        zoning = kennewick_zoning_by_tax_id.get(tax_id)
        if zoning:
            matched.append(
                _overlay_feature(
                    apn=apn,
                    zoning_code=zoning,
                    jurisdiction="kennewick_city",
                    match_method="kennewick_county_tax_id",
                    geometry=feat.get("geometry"),
                )
            )
        else:
            unmatched.append(feat)
    return matched, unmatched


def build_benton_zoning_overlay_geojson(
    parcels_fc: dict[str, Any],
    *,
    kennewick_zoning_by_tax_id: dict[str, str],
    pasco_zoning_fc: dict[str, Any] | None = None,
    benton_county_zoning_fc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join Benton WaTech parcels to Kennewick attribute table + spatial zoning layers."""
    kennewick_features, unmatched = apply_kennewick_attribute_join(
        parcels_fc,
        kennewick_zoning_by_tax_id=kennewick_zoning_by_tax_id,
    )
    features: list[dict[str, Any]] = list(kennewick_features)
    logger.info(
        "Kennewick attribute join matched %s parcels; %s remain for spatial joins",
        len(kennewick_features),
        len(unmatched),
    )

    if not unmatched:
        return {"type": "FeatureCollection", "features": features}

    pasco_candidates = []
    richland_candidates = []
    county_candidates = []
    for feat in unmatched:
        city = situs_city_from_props(feat.get("properties") or {})
        if city == "PASCO":
            pasco_candidates.append(feat)
        elif city in {"RICHLAND", "WEST RICHLAND"}:
            richland_candidates.append(feat)
        else:
            county_candidates.append(feat)

    spatial_batches: list[tuple[list[dict[str, Any]], dict[str, Any], str, str, str]] = []
    if pasco_zoning_fc and pasco_candidates:
        spatial_batches.append(
            (pasco_candidates, pasco_zoning_fc, "Zone", "pasco_city", "pasco_spatial"),
        )
    # Richland parcel-zoning REST currently rejects queries; route through county layer for now.
    if benton_county_zoning_fc:
        for batch in (richland_candidates, county_candidates):
            if batch:
                spatial_batches.append(
                    (batch, benton_county_zoning_fc, "LandUseTyp", "benton_unincorporated", "benton_county_spatial"),
                )

    seen_apns: set[str] = {str(f["properties"]["APN"]) for f in features if f.get("properties", {}).get("APN")}
    for batch, zoning_fc, zoning_field, jurisdiction, method in spatial_batches:
        partial_fc = {"type": "FeatureCollection", "features": batch}
        joined = build_zoning_overlay_geojson(
            partial_fc,
            zoning_fc,
            county_fips=BENTON_COUNTY_FIPS,
            zoning_field=zoning_field,
            zoning_jurisdiction=jurisdiction,
        )
        for feat in joined.get("features") or []:
            props = dict(feat.get("properties") or {})
            apn = str(props.get("APN") or props.get("apn") or "").strip()
            if not apn or apn in seen_apns:
                continue
            props["ZONING_MATCH_METHOD"] = method
            props.setdefault("ZONING_JURISDICTION", jurisdiction)
            props.setdefault("COUNTY_FIPS", BENTON_COUNTY_FIPS)
            features.append(
                {
                    "type": "Feature",
                    "geometry": feat.get("geometry"),
                    "properties": props,
                }
            )
            seen_apns.add(apn)

    return {"type": "FeatureCollection", "features": features}

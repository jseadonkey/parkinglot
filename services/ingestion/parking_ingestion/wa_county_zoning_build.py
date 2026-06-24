"""Build WA county zoning overlay GeoJSON inside Celery workers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BENTON_COUNTY_FIPS = "53005"

DEFAULT_ARCGIS_ZONING_SOURCES: dict[str, list[dict[str, str]]] = {
    "53033": [
        {
            "source_id": "king_unincorporated_zoning",
            "label": "King County unincorporated zoning",
            "layer_url": "https://gismaps.kingcounty.gov/ArcGIS/rest/services/Districts/DistrictsReport/MapServer/22",
            "zoning_field": "CURRZONE",
            "zoning_jurisdiction": "king_unincorporated",
            "out_fields": "CURRZONE",
        },
    ],
    "53053": [
        {
            "source_id": "pierce_county_zoning",
            "label": "Pierce County zoning",
            "layer_url": "https://services2.arcgis.com/1UvBaQ5y1ubjUPmd/ArcGIS/rest/services/Zoning/FeatureServer/0",
            "zoning_field": "ZONING",
            "zoning_jurisdiction": "pierce_county",
            "out_fields": "ZONING,JURISDICT,ZON_CUR_NA,ZON_TYP",
        },
    ],
    "53061": [
        {
            "source_id": "snohomish_county_zoning",
            "label": "Snohomish County zoning",
            "layer_url": "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/CouncilExv1A_Zoning/FeatureServer/0",
            "zoning_field": "ABBREV",
            "zoning_jurisdiction": "snohomish_county",
            "out_fields": "ABBREV,LABEL,AREA_TYPE",
        },
    ],
    "53035": [
        {
            "source_id": "kitsap_county_zoning",
            "label": "Kitsap County zoning",
            "layer_url": "https://gis.parametrix.com/arcgis/rest/services/KitsapSR16PR_Zoning_Web/MapServer/0",
            "zoning_field": "ZONEBREV",
            "zoning_jurisdiction": "kitsap_county",
            "out_fields": "ZONEBREV,ZONE_DESCR,ZONING_DEN,GMA_JURISD",
        },
    ],
    "53067": [
        {
            "source_id": "thurston_county_zoning",
            "label": "Thurston County zoning",
            "layer_url": "https://tconline.co.thurston.wa.us/server/rest/services/ThurstonExt/Thurston_Zoning/FeatureServer/1",
            "zoning_field": "ZoneCode",
            "zoning_jurisdiction": "thurston_county",
            "out_fields": "ZoneCode,Name,Jurisdiction,PlanningAreaName",
        },
    ],
}


def build_county_zoning_overlay_geojson(
    county_fips: str,
    *,
    cache_dir: Path | None = None,
    zoning_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch GIS + WaTech parcels and return overlay FeatureCollection."""
    cf = str(county_fips or "").strip()
    sources = zoning_sources if zoning_sources is not None else DEFAULT_ARCGIS_ZONING_SOURCES.get(cf)
    if cf == BENTON_COUNTY_FIPS and not sources:
        return _build_benton_overlay(cache_dir=cache_dir)
    if sources:
        return _build_arcgis_spatial_overlay(cf, sources=sources, cache_dir=cache_dir)
    msg = f"no Phase B overlay builder registered for county {cf}"
    raise ValueError(msg)


def write_county_zoning_overlay(
    county_fips: str,
    overlay_path: Path,
    *,
    cache_dir: Path | None = None,
    zoning_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build overlay and persist to ``overlay_path`` (creates parent dirs)."""
    overlay = build_county_zoning_overlay_geojson(
        county_fips,
        cache_dir=cache_dir,
        zoning_sources=zoning_sources,
    )
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    feature_count = len(overlay.get("features") or [])
    logger.info(
        "wrote county %s zoning overlay %s features -> %s",
        county_fips,
        feature_count,
        overlay_path,
    )
    return {"overlay_path": str(overlay_path), "feature_count": feature_count}


def _source_cache_name(source: dict[str, Any]) -> str:
    raw = str(source.get("source_id") or source.get("label") or "zoning").strip().lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_")
    return f"{safe or 'zoning'}_districts.geojson"


def _parcel_apn(props: dict[str, Any]) -> str:
    for key in ("APN", "apn", "PARCEL_ID_NR", "ORIG_PARCEL_ID", "PIN", "TAXPIN"):
        val = str(props.get(key) or "").strip()
        if val:
            return val
    return ""


def _build_arcgis_spatial_overlay(
    county_fips: str,
    *,
    sources: list[dict[str, Any]],
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    from parking_ingestion.baltimore_zoning_overlay import build_zoning_overlay_geojson
    from parking_ingestion.benton_zoning import fetch_zoning_geojson
    from parking_ingestion.watech_parcels import fetch_county_geojson

    cache = cache_dir or Path(f"/app/data/wa/{county_fips}")
    cache.mkdir(parents=True, exist_ok=True)

    parcels_fc = fetch_county_geojson(county_fips)
    remaining = list(parcels_fc.get("features") or [])
    features: list[dict[str, Any]] = []
    seen_apns: set[str] = set()

    for source in sources:
        layer_url = str(source.get("layer_url") or "").strip()
        zoning_field = str(source.get("zoning_field") or "").strip()
        jurisdiction = str(source.get("zoning_jurisdiction") or "").strip()
        label = str(source.get("label") or source.get("source_id") or layer_url).strip()
        if not layer_url or not zoning_field or not jurisdiction:
            raise ValueError(f"incomplete zoning source for county {county_fips}: {source!r}")

        source_path = cache / _source_cache_name(source)
        if source_path.is_file():
            zoning_fc = json.loads(source_path.read_text(encoding="utf-8"))
        else:
            zoning_fc = fetch_zoning_geojson(
                layer_url=layer_url,
                label=label,
                where=str(source.get("where") or "1=1"),
                out_fields=str(source.get("out_fields") or "*"),
            )
            source_path.write_text(json.dumps(zoning_fc), encoding="utf-8")

        partial_fc = {"type": "FeatureCollection", "features": remaining}
        joined = build_zoning_overlay_geojson(
            partial_fc,
            zoning_fc,
            county_fips=county_fips,
            zoning_field=zoning_field,
            zoning_jurisdiction=jurisdiction,
        )

        matched_now: set[str] = set()
        for feat in joined.get("features") or []:
            props = dict(feat.get("properties") or {})
            apn = _parcel_apn(props)
            if not apn or apn in seen_apns:
                continue
            props["APN"] = apn
            props["COUNTY_FIPS"] = county_fips
            props.setdefault("ZONING_JURISDICTION", jurisdiction)
            props["ZONING_MATCH_METHOD"] = f"{source.get('source_id') or jurisdiction}_spatial"
            features.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})
            seen_apns.add(apn)
            matched_now.add(apn)

        if matched_now:
            remaining = [
                feat
                for feat in remaining
                if _parcel_apn(feat.get("properties") or {}) not in matched_now
            ]
        logger.info(
            "WA county %s source %s matched %s parcels; %s remain",
            county_fips,
            label,
            len(matched_now),
            len(remaining),
        )
        if not remaining:
            break

    return {"type": "FeatureCollection", "features": features}


def _build_benton_overlay(*, cache_dir: Path | None = None) -> dict[str, Any]:
    from parking_ingestion.benton_zoning import (
        BENTON_COUNTY_ZONING_LAYER,
        PASCO_ZONING_LAYER,
        fetch_kennewick_zoning_by_tax_id,
        fetch_zoning_geojson,
    )
    from parking_ingestion.benton_zoning_overlay import build_benton_zoning_overlay_geojson
    from parking_ingestion.watech_parcels import fetch_county_geojson

    cache = cache_dir or Path("/app/data/benton")
    cache.mkdir(parents=True, exist_ok=True)

    kennewick_path = cache / "kennewick_parcel_zoning_by_tax_id.json"
    if kennewick_path.is_file():
        kennewick = json.loads(kennewick_path.read_text(encoding="utf-8"))
    else:
        kennewick = fetch_kennewick_zoning_by_tax_id()
        kennewick_path.write_text(json.dumps(kennewick, indent=2, sort_keys=True), encoding="utf-8")

    pasco_fc = None
    pasco_path = cache / "pasco_zoning_districts.geojson"
    if pasco_path.is_file():
        pasco_fc = json.loads(pasco_path.read_text(encoding="utf-8"))
    else:
        try:
            pasco_fc = fetch_zoning_geojson(layer_url=PASCO_ZONING_LAYER, label="Pasco zoning")
            pasco_path.write_text(json.dumps(pasco_fc), encoding="utf-8")
        except Exception:
            logger.warning("Pasco zoning fetch failed — continuing with Kennewick + county layers only")

    benton_path = cache / "benton_county_zoning_districts.geojson"
    if benton_path.is_file():
        benton_fc = json.loads(benton_path.read_text(encoding="utf-8"))
    else:
        benton_fc = fetch_zoning_geojson(
            layer_url=BENTON_COUNTY_ZONING_LAYER,
            label="Benton County zoning",
        )
        benton_path.write_text(json.dumps(benton_fc), encoding="utf-8")

    parcels_fc = fetch_county_geojson(BENTON_COUNTY_FIPS)
    return build_benton_zoning_overlay_geojson(
        parcels_fc,
        kennewick_zoning_by_tax_id=kennewick,
        pasco_zoning_fc=pasco_fc,
        benton_county_zoning_fc=benton_fc,
    )

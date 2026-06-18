"""Build WA county zoning overlay GeoJSON inside Celery workers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BENTON_COUNTY_FIPS = "53005"


def build_county_zoning_overlay_geojson(
    county_fips: str,
    *,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch GIS + WaTech parcels and return overlay FeatureCollection."""
    cf = str(county_fips or "").strip()
    if cf == BENTON_COUNTY_FIPS:
        return _build_benton_overlay(cache_dir=cache_dir)
    msg = f"no Phase B overlay builder registered for county {cf}"
    raise ValueError(msg)


def write_county_zoning_overlay(
    county_fips: str,
    overlay_path: Path,
    *,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Build overlay and persist to ``overlay_path`` (creates parent dirs)."""
    overlay = build_county_zoning_overlay_geojson(county_fips, cache_dir=cache_dir)
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

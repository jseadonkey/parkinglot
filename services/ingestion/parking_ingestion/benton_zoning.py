"""Benton County (53005) Tri-Cities zoning GIS fetch helpers."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

BENTON_COUNTY_FIPS = "53005"

KENNEWICK_PARCEL_ZONING_LAYER = (
    "https://maps.ci.kennewick.wa.us/server/rest/services/Public/AllGISLayers/FeatureServer/59"
)
PASCO_ZONING_LAYER = (
    "https://gis.pasco-wa.gov/gs/rest/services/Citybase_Published_Layers/Zoning/FeatureServer/0"
)
BENTON_COUNTY_ZONING_LAYER = "https://maps.co.benton.wa.us/server/rest/services/Zoning/MapServer/0"
RICHLAND_ZONING_PARCELS_LAYER = (
    "https://gisweb24.ci.richland.wa.us/arcgis24web/rest/services/Richland/Zoning/MapServer/0"
)


def normalize_benton_county_tax_id(apn: str | None) -> str:
    """Normalize WaTech ``PARCEL_ID_NR`` to Benton assessor tax id (Kennewick GIS key).

    WaTech uses ``005-104893100000004``; Kennewick ``CountyTaxID`` uses ``104893100000004``.
    """
    raw = str(apn or "").strip()
    if not raw:
        return ""
    if raw.upper().startswith("005-"):
        raw = raw[4:]
    return raw.replace("-", "").strip()


def _arcgis_query_rows(
    *,
    layer_url: str,
    label: str,
    out_fields: tuple[str, ...],
    where: str = "1=1",
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    return_geometry: bool = False,
    out_sr: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    total_cap = max_features if max_features is not None else 10**12
    while len(rows) < total_cap:
        batch_limit = min(page_size, total_cap - len(rows))
        params: dict[str, str | int] = {
            "where": where,
            "outFields": ",".join(out_fields),
            "returnGeometry": "true" if return_geometry else "false",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
        if return_geometry and out_sr is not None:
            params["outSR"] = out_sr
        qs = urllib.parse.urlencode(params)
        url = f"{layer_url.rstrip('/')}/query?{qs}"
        logger.info("%s fetch offset=%s limit=%s", label, offset, batch_limit)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logger.exception("%s HTTP error", label)
            raise RuntimeError(f"{label} query failed: {e}") from e

        data = json.loads(raw)
        if data.get("error"):
            raise RuntimeError(f"{label} query failed: {data['error']}")
        batch = [feat.get("attributes") or {} for feat in data.get("features") or []]
        if return_geometry:
            batch = data.get("features") or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)
    return rows


def fetch_kennewick_zoning_by_tax_id(
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
) -> dict[str, str]:
    """Return ``CountyTaxID`` → zoning code for City of Kennewick parcel-zoning layer."""
    rows = _arcgis_query_rows(
        layer_url=KENNEWICK_PARCEL_ZONING_LAYER,
        label="Kennewick parcel zoning",
        out_fields=("CountyTaxID", "Zoning"),
        page_size=page_size,
        max_features=max_features,
        sleep_sec=sleep_sec,
    )
    out: dict[str, str] = {}
    for row in rows:
        tax_id = str(row.get("CountyTaxID") or "").strip()
        zoning = str(row.get("Zoning") or "").strip()
        if tax_id and zoning:
            out[tax_id] = zoning
    return out


def fetch_arcgis_geojson_pages(
    *,
    layer_url: str,
    label: str,
    where: str = "1=1",
    out_fields: str = "*",
    page_size: int = 1000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    out_sr: int = 4326,
):
    """Yield GeoJSON FeatureCollection pages from an ArcGIS layer."""
    fetched = 0
    offset = 0
    total_cap = max_features if max_features is not None else 10**12
    while fetched < total_cap:
        batch_limit = min(page_size, total_cap - fetched)
        params: dict[str, str | int] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": out_sr,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
        qs = urllib.parse.urlencode(params)
        url = f"{layer_url.rstrip('/')}/query?{qs}"
        logger.info("%s geojson offset=%s limit=%s", label, offset, batch_limit)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logger.exception("%s HTTP error", label)
            raise RuntimeError(f"{label} geojson query failed: {e}") from e

        data = json.loads(raw)
        if data.get("error"):
            raise RuntimeError(f"{label} geojson query failed: {data['error']}")
        features = data.get("features") or []
        if not features:
            break
        yield {"type": "FeatureCollection", "features": features}
        fetched += len(features)
        if len(features) < batch_limit:
            break
        offset += len(features)
        time.sleep(sleep_sec)


def fetch_zoning_geojson(
    *,
    layer_url: str,
    label: str,
    where: str = "1=1",
    out_fields: str = "*",
    page_size: int = 1000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for page in fetch_arcgis_geojson_pages(
        layer_url=layer_url,
        label=label,
        where=where,
        out_fields=out_fields,
        page_size=page_size,
        max_features=max_features,
        sleep_sec=sleep_sec,
    ):
        features.extend(page.get("features") or [])
    return {"type": "FeatureCollection", "features": features}


def situs_city_from_props(props: dict[str, Any]) -> str:
    city = str(props.get("SITUS_CITY_NM") or props.get("situs_city") or "").strip().upper()
    if city:
        return city
    situs = str(props.get("SITUS_ADDRESS") or props.get("situs_address") or "").upper()
    for token in ("KENNEWICK", "RICHLAND", "PASCO", "WEST RICHLAND"):
        if token in situs:
            return token
    return ""

"""Fetch Baltimore City and Baltimore County parcel polygons from Maryland ArcGIS."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

BALTIMORE_CITY_PARCELS_LAYER = (
    "https://egis.baltimorecity.gov/egis/rest/services/Parcel_Information/Parcel/FeatureServer/0"
)
BALTIMORE_COUNTY_PARCELS_LAYER = (
    "https://bcgisdata.baltimorecountymd.gov/arcgis/rest/services/Property/Property/MapServer/1"
)

BALTIMORE_CITY_COUNTY_FIPS = "24510"
BALTIMORE_COUNTY_COUNTY_FIPS = "24005"


def _fetch_arcgis_parcels_geojson(
    *,
    layer_url: str,
    county_fips: str,
    apn_prefix: str,
    label: str,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    pin_fields: tuple[str, ...] = ("PARCELNUM", "BLOCKLOT", "TAXPIN"),
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    offset = 0
    total_cap = max_features if max_features is not None else 10**12

    while len(features) < total_cap:
        batch_limit = min(page_size, total_cap - len(features))
        params: dict[str, str | int] = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
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
        batch = data.get("features") or []
        if not batch:
            break

        for feat in batch:
            props = feat.setdefault("properties", {})
            if not str(props.get("COUNTY_FIPS", "")).strip():
                props["COUNTY_FIPS"] = county_fips
            if not str(props.get("APN", "")).strip():
                pin = ""
                for field in pin_fields:
                    pin = str(props.get(field) or "").strip()
                    if pin:
                        break
                if pin:
                    props["APN"] = f"{apn_prefix}{pin}"

        features.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)

    return {"type": "FeatureCollection", "features": features}


def fetch_baltimore_city_geojson(
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    layer_url: str = BALTIMORE_CITY_PARCELS_LAYER,
) -> dict[str, Any]:
    """Download Baltimore City parcels; normalize APN and COUNTY_FIPS on each feature."""
    return _fetch_arcgis_parcels_geojson(
        layer_url=layer_url,
        county_fips=BALTIMORE_CITY_COUNTY_FIPS,
        apn_prefix="MD-BALT-CITY-",
        label="Baltimore City",
        page_size=page_size,
        max_features=max_features,
        sleep_sec=sleep_sec,
        pin_fields=("PARCELNUM", "BLOCKLOT", "TAXPIN"),
    )


def fetch_baltimore_county_geojson(
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    layer_url: str = BALTIMORE_COUNTY_PARCELS_LAYER,
) -> dict[str, Any]:
    """Download Baltimore County tax parcels; normalize APN and COUNTY_FIPS."""
    return _fetch_arcgis_parcels_geojson(
        layer_url=layer_url,
        county_fips=BALTIMORE_COUNTY_COUNTY_FIPS,
        apn_prefix="MD-BALT-CO-",
        label="Baltimore County",
        page_size=page_size,
        max_features=max_features,
        sleep_sec=sleep_sec,
        pin_fields=("TAXPIN", "PARCEL_ASSET_ID", "OBJECTID"),
    )

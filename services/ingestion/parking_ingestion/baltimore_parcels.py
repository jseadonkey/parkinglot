"""Fetch Baltimore City parcel polygons from EGIS ArcGIS (Maryland)."""

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

BALTIMORE_CITY_COUNTY_FIPS = "24510"


def fetch_baltimore_city_geojson(
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    layer_url: str = BALTIMORE_CITY_PARCELS_LAYER,
) -> dict[str, Any]:
    """Download Baltimore City parcels; normalize APN and COUNTY_FIPS on each feature."""
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
        logger.info("Baltimore City fetch offset=%s limit=%s", offset, batch_limit)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logger.exception("Baltimore City HTTP error")
            raise RuntimeError(f"Baltimore City query failed: {e}") from e

        data = json.loads(raw)
        batch = data.get("features") or []
        if not batch:
            break

        for feat in batch:
            props = feat.setdefault("properties", {})
            if not str(props.get("COUNTY_FIPS", "")).strip():
                props["COUNTY_FIPS"] = BALTIMORE_CITY_COUNTY_FIPS
            if not str(props.get("APN", "")).strip():
                pin = str(
                    props.get("PARCELNUM")
                    or props.get("BLOCKLOT")
                    or props.get("TAXPIN")
                    or ""
                ).strip()
                if pin:
                    props["APN"] = f"MD-BALT-CITY-{pin}"

        features.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)

    return {"type": "FeatureCollection", "features": features}

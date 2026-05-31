"""Fetch parcel polygons from the Washington State Parcels Project (WaTech / ArcGIS Hub).

Public REST layer — verify OCIO / WaTech terms for production-scale use.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

WATECH_STATEWIDE_PARCELS_LAYER = (
    "https://services.arcgis.com/jsIt88o09Q0r1j8h/arcgis/rest/services/Previous_Parcels/FeatureServer/0"
)


def county_fips_to_watech_fips_nr(county_fips_5: str) -> str:
    """WaTech ``FIPS_NR`` uses the 3-digit county code within Washington (e.g. ``033`` → King)."""
    cf = county_fips_5.strip()
    if len(cf) != 5 or not cf.isdigit():
        msg = f"expected 5-digit county FIPS, got {county_fips_5!r}"
        raise ValueError(msg)
    if not cf.startswith("53"):
        msg = f"expected Washington state FIPS 53xxx, got {county_fips_5!r}"
        raise ValueError(msg)
    return cf[2:]


def watech_fips_nr_to_county_fips(fips_nr: str) -> str:
    tail = fips_nr.strip().zfill(3)
    return "53" + tail[-3:]


def fetch_county_geojson(
    county_fips_5: str,
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    layer_url: str = WATECH_STATEWIDE_PARCELS_LAYER,
) -> dict[str, Any]:
    """Download parcels for one WA county; return a GeoJSON FeatureCollection."""
    fips_nr = county_fips_to_watech_fips_nr(county_fips_5)
    where = f"FIPS_NR='{fips_nr}'"

    features: list[dict[str, Any]] = []
    offset = 0
    total_cap = max_features if max_features is not None else 10**12

    while len(features) < total_cap:
        batch_limit = min(page_size, total_cap - len(features))
        params: dict[str, str | int] = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
        qs = urllib.parse.urlencode(params)
        url = f"{layer_url.rstrip('/')}/query?{qs}"
        logger.info("WaTech fetch offset=%s limit=%s county=%s", offset, batch_limit, county_fips_5)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logger.exception("WaTech HTTP error for county %s", county_fips_5)
            raise RuntimeError(f"WaTech query failed: {e}") from e

        data = json.loads(raw)
        batch = data.get("features") or []
        if not batch:
            break

        for feat in batch:
            props = feat.setdefault("properties", {})
            if not str(props.get("COUNTY_FIPS", "")).strip():
                fnr = str(props.get("FIPS_NR", fips_nr)).strip()
                props["COUNTY_FIPS"] = watech_fips_nr_to_county_fips(fnr)

        features.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)

    return {"type": "FeatureCollection", "features": features}


def iterate_county_features(
    county_fips_5: str,
    *,
    page_size: int = 2000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
    layer_url: str = WATECH_STATEWIDE_PARCELS_LAYER,
):
    """Yield GeoJSON features for one WA county page by page (memory-friendly)."""
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    fips_nr = county_fips_to_watech_fips_nr(county_fips_5)
    where = f"FIPS_NR='{fips_nr}'"
    offset = 0
    total_cap = max_features if max_features is not None else 10**12
    yielded = 0

    while yielded < total_cap:
        batch_limit = min(page_size, total_cap - yielded)
        params: dict[str, str | int] = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
        }
        qs = urllib.parse.urlencode(params)
        url = f"{layer_url.rstrip('/')}/query?{qs}"
        logger.info("WaTech fetch offset=%s limit=%s county=%s", offset, batch_limit, county_fips_5)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logger.exception("WaTech HTTP error for county %s", county_fips_5)
            raise RuntimeError(f"WaTech query failed: {e}") from e

        data = json.loads(raw)
        batch = data.get("features") or []
        if not batch:
            break

        for feat in batch:
            props = feat.setdefault("properties", {})
            if not str(props.get("COUNTY_FIPS", "")).strip():
                fnr = str(props.get("FIPS_NR", fips_nr)).strip()
                props["COUNTY_FIPS"] = watech_fips_nr_to_county_fips(fnr)
            yield feat
            yielded += 1
            if yielded >= total_cap:
                return

        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)

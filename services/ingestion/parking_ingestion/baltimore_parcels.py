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
BALTIMORE_CITY_REALPROPERTY_LAYER = (
    "https://geodata.baltimorecity.gov/egis/rest/services/CityView/Realproperty_OB/FeatureServer/0"
)
BALTIMORE_COUNTY_PARCELS_LAYER = (
    "https://bcgisdata.baltimorecountymd.gov/arcgis/rest/services/Property/Property/MapServer/1"
)

BALTIMORE_CITY_COUNTY_FIPS = "24510"
BALTIMORE_COUNTY_COUNTY_FIPS = "24005"

BALTIMORE_CITY_REALPROPERTY_FIELDS: tuple[str, ...] = (
    "OBJECTID",
    "PIN",
    "PINRELATE",
    "BLOCKLOT",
    "FULLADDR",
    "MAILTOADD",
    "VACIND",
    "OWNER_1",
    "OWNER_2",
    "OWNER_3",
    "OWNER_ABBR",
    "USEGROUP",
    "SDATCODE",
    "DHCDUSE1",
    "DHCDUSE2",
    "DHCDUSE3",
    "DHCDUSE4",
    "DWELUNIT",
    "LOT_SIZE",
    "NO_IMPRV",
    "ZONECODE",
    "SDATLINK",
)


def parcel_apn_from_props(props: dict[str, Any], *, county_fips: str) -> str:
    """Stable APN for Baltimore layers — must match ingest and overlay merge keys."""
    existing = str(props.get("APN") or props.get("apn") or "").strip()
    if county_fips == BALTIMORE_CITY_COUNTY_FIPS:
        prefix = "MD-BALT-CITY-"
        pin_fields: tuple[str, ...] = ("PIN", "BLOCKLOT", "PARCELNUM", "TAXPIN")
    elif county_fips == BALTIMORE_COUNTY_COUNTY_FIPS:
        prefix = "MD-BALT-CO-"
        pin_fields = ("TAXPIN", "PARCEL_ASSET_ID", "OBJECTID")
    else:
        return existing
    if existing.startswith(prefix) and len(existing) > len(prefix):
        return existing
    for field in pin_fields:
        pin = str(props.get(field) or "").strip()
        if pin:
            return f"{prefix}{pin}"
    return existing


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _join_key(value: Any) -> str:
    return _clean_str(value).upper()


def _copy_if_present(props: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    if _clean_str(props.get(key)):
        return
    props[key] = value


def _realproperty_keys(row: dict[str, Any]) -> set[str]:
    return {_join_key(row.get(k)) for k in ("PIN", "PINRELATE", "BLOCKLOT") if _join_key(row.get(k))}


def _parcel_realproperty_keys(props: dict[str, Any]) -> set[str]:
    return {_join_key(props.get(k)) for k in ("PIN", "BLOCKLOT", "PARCELNUM") if _join_key(props.get(k))}


def _realproperty_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in _realproperty_keys(row):
            index.setdefault(key, []).append(row)
    return index


def _best_realproperty_match(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def rank(row: dict[str, Any]) -> tuple[int, int, int]:
        has_addr = 1 if _clean_str(row.get("FULLADDR")) else 0
        not_vacant = 1 if _join_key(row.get("VACIND")) != "Y" else 0
        has_mail = 1 if _clean_str(row.get("MAILTOADD")) else 0
        return has_addr, not_vacant, has_mail

    return max(rows, key=rank)


def _apply_realproperty_row(props: dict[str, Any], row: dict[str, Any]) -> None:
    for key in BALTIMORE_CITY_REALPROPERTY_FIELDS:
        if key == "OBJECTID":
            _copy_if_present(props, "REALPROPERTY_OBJECTID", row.get(key))
        else:
            _copy_if_present(props, key, row.get(key))

    fulladdr = _clean_str(row.get("FULLADDR"))
    if fulladdr:
        # Existing outreach extraction already understands these generic aliases.
        _copy_if_present(props, "PROPERTY_ADDRESS", fulladdr)
        _copy_if_present(props, "SITUS_ADDRESS", fulladdr)
        _copy_if_present(props, "ADDR_FULL", fulladdr)

    mailto = _clean_str(row.get("MAILTOADD"))
    if mailto:
        _copy_if_present(props, "MAILING_ADDRESS", mailto)
        _copy_if_present(props, "MAIL_ADDR", mailto)

    owner_parts = [_clean_str(row.get(k)) for k in ("OWNER_1", "OWNER_2", "OWNER_3")]
    owner_name = " ".join(part for part in owner_parts if part)
    if owner_name:
        _copy_if_present(props, "OWNER_NAME", owner_name)


def _merge_realproperty_attributes(
    features: list[dict[str, Any]],
    realproperty_rows: list[dict[str, Any]],
) -> int:
    index = _realproperty_index(realproperty_rows)
    merged = 0
    for feat in features:
        props = feat.setdefault("properties", {})
        candidates_by_id: dict[Any, dict[str, Any]] = {}
        for key in _parcel_realproperty_keys(props):
            for row in index.get(key, []):
                candidates_by_id[row.get("OBJECTID", id(row))] = row
        match = _best_realproperty_match(list(candidates_by_id.values()))
        if match is None:
            continue
        _apply_realproperty_row(props, match)
        props["BALTIMORE_REALPROPERTY_MATCHED"] = True
        merged += 1
    return merged


def _fetch_arcgis_json_rows(
    *,
    layer_url: str,
    label: str,
    out_fields: tuple[str, ...],
    where: str = "1=1",
    page_size: int = 1000,
    max_features: int | None = None,
    sleep_sec: float = 0.15,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    total_cap = max_features if max_features is not None else 10**12
    while len(rows) < total_cap:
        batch_limit = min(page_size, total_cap - len(rows))
        params: dict[str, str | int] = {
            "where": where,
            "outFields": ",".join(out_fields),
            "returnGeometry": "false",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": batch_limit,
            "orderByFields": "OBJECTID",
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
        if data.get("error"):
            raise RuntimeError(f"{label} query failed: {data['error']}")
        batch = [feat.get("attributes") or {} for feat in data.get("features") or []]
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_limit:
            break
        offset += len(batch)
        time.sleep(sleep_sec)
    return rows


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _realproperty_where_for_keys(keys: list[str]) -> str:
    quoted = ", ".join(_sql_string(k) for k in keys)
    return f"PIN IN ({quoted}) OR PINRELATE IN ({quoted}) OR BLOCKLOT IN ({quoted})"


def _fetch_realproperty_rows_for_parcels(
    *,
    features: list[dict[str, Any]],
    layer_url: str,
    page_size: int = 1000,
    sleep_sec: float = 0.15,
    keys_per_query: int = 50,
) -> list[dict[str, Any]]:
    keys = sorted({key for feat in features for key in _parcel_realproperty_keys(feat.get("properties") or {})})
    rows: list[dict[str, Any]] = []
    for i in range(0, len(keys), keys_per_query):
        chunk = keys[i : i + keys_per_query]
        if not chunk:
            continue
        rows.extend(
            _fetch_arcgis_json_rows(
                layer_url=layer_url,
                label="Baltimore City Realproperty",
                out_fields=BALTIMORE_CITY_REALPROPERTY_FIELDS,
                where=_realproperty_where_for_keys(chunk),
                page_size=page_size,
                sleep_sec=sleep_sec,
            )
        )
    return rows


def _enrich_baltimore_city_realproperty(
    collection: dict[str, Any],
    *,
    layer_url: str = BALTIMORE_CITY_REALPROPERTY_LAYER,
    page_size: int = 1000,
    max_features: int | None = None,
    parcel_sample_mode: bool = False,
    sleep_sec: float = 0.15,
) -> int:
    features = collection.get("features") or []
    if not features:
        return 0
    if parcel_sample_mode:
        rows = _fetch_realproperty_rows_for_parcels(
            features=features,
            layer_url=layer_url,
            page_size=page_size,
            sleep_sec=sleep_sec,
        )
    else:
        rows = _fetch_arcgis_json_rows(
            layer_url=layer_url,
            label="Baltimore City Realproperty",
            out_fields=BALTIMORE_CITY_REALPROPERTY_FIELDS,
            page_size=page_size,
            max_features=max_features,
            sleep_sec=sleep_sec,
        )
    merged = _merge_realproperty_attributes(features, rows)
    logger.info("Baltimore City Realproperty matched %s/%s parcel features", merged, len(features))
    return merged


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
            pin = ""
            for field in pin_fields:
                pin = str(props.get(field) or "").strip()
                if pin:
                    break
            normalized = parcel_apn_from_props(props, county_fips=county_fips)
            if normalized:
                props["APN"] = normalized

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
    enrich_realproperty: bool = True,
    realproperty_layer_url: str = BALTIMORE_CITY_REALPROPERTY_LAYER,
    realproperty_page_size: int = 1000,
    realproperty_max_features: int | None = None,
) -> dict[str, Any]:
    """Download Baltimore City parcels; normalize APN and enrich addresses from Realproperty."""
    collection = _fetch_arcgis_parcels_geojson(
        layer_url=layer_url,
        county_fips=BALTIMORE_CITY_COUNTY_FIPS,
        apn_prefix="MD-BALT-CITY-",
        label="Baltimore City",
        page_size=page_size,
        max_features=max_features,
        sleep_sec=sleep_sec,
        pin_fields=("PIN", "BLOCKLOT", "PARCELNUM", "TAXPIN"),
    )
    if enrich_realproperty:
        _enrich_baltimore_city_realproperty(
            collection,
            layer_url=realproperty_layer_url,
            page_size=realproperty_page_size,
            max_features=realproperty_max_features,
            parcel_sample_mode=max_features is not None and realproperty_max_features is None,
            sleep_sec=sleep_sec,
        )
    return collection


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

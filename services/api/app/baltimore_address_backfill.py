"""Measured Baltimore City property-address backfill batches."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.models import Parcel
from parking_ingestion.baltimore_parcels import (
    BALTIMORE_CITY_COUNTY_FIPS,
    _merge_realproperty_attributes,
)

REALPROPERTY_LAYER_URL = "https://geodata.baltimorecity.gov/egis/rest/services/CityView/Realproperty_OB/FeatureServer/0"
REALPROPERTY_FIELDS = (
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

ADDRESS_KEYS = (
    "PROPERTY_ADDRESS",
    "property_address",
    "SITUS_ADDRESS",
    "situs_address",
    "ADDR_FULL",
    "addr_full",
    "FULLADDR",
)


def _missing_address_sql() -> str:
    present = " OR ".join(f"(raw_properties ? '{key}')" for key in ADDRESS_KEYS)
    return f"(raw_properties is null or not ({present}))"


def _pin_from_apn(apn: str) -> str | None:
    prefix = "MD-BALT-CITY-"
    if apn.startswith(prefix) and len(apn) > len(prefix):
        return apn[len(prefix) :]
    return None


def _props_for_lookup(parcel: Parcel) -> dict[str, Any]:
    props = dict(parcel.raw_properties or {})
    if not str(props.get("APN") or "").strip():
        props["APN"] = parcel.apn
    pin = _pin_from_apn(parcel.apn)
    if pin and not str(props.get("PIN") or "").strip():
        props["PIN"] = pin
    return props


def _clean_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _lookup_keys(props: dict[str, Any]) -> set[str]:
    return {_clean_key(props.get(key)) for key in ("PIN", "BLOCKLOT", "PARCELNUM") if _clean_key(props.get(key))}


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _where_for_keys(keys: list[str]) -> str:
    quoted = ", ".join(_sql_string(key) for key in keys)
    return f"PIN IN ({quoted}) OR PINRELATE IN ({quoted}) OR BLOCKLOT IN ({quoted})"


def _fetch_realproperty_rows(features: list[dict[str, Any]], *, keys_per_query: int = 10) -> list[dict[str, Any]]:
    keys = sorted({key for feature in features for key in _lookup_keys(feature.get("properties") or {})})
    rows: list[dict[str, Any]] = []
    for i in range(0, len(keys), keys_per_query):
        chunk = keys[i : i + keys_per_query]
        if not chunk:
            continue
        params = {
            "where": _where_for_keys(chunk),
            "outFields": ",".join(REALPROPERTY_FIELDS),
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": "1000",
        }
        url = f"{REALPROPERTY_LAYER_URL}/query?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "parking-acquisition-agents/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError(f"Baltimore Realproperty query failed: {data['error']}")
        rows.extend([feature.get("attributes") or {} for feature in data.get("features") or []])
    return rows


def _has_address(props: dict[str, Any]) -> bool:
    return any(str(props.get(key) or "").strip() for key in ADDRESS_KEYS)


def backfill_baltimore_property_addresses(
    db: Session,
    *,
    limit: int = 500,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill a bounded batch of Baltimore property addresses from Realproperty_OB.

    This is intentionally batch-limited so operators can measure elapsed time and DB
    impact before scaling up.
    """
    started = monotonic()
    cap = min(max(int(limit), 1), 5000)
    stmt = (
        select(Parcel)
        .where(Parcel.county_fips == BALTIMORE_CITY_COUNTY_FIPS)
        .where(text(_missing_address_sql()))
        .order_by(Parcel.created_at.asc(), Parcel.id.asc())
        .limit(cap)
    )
    parcels = list(db.scalars(stmt))
    features = [
        {
            "type": "Feature",
            "geometry": None,
            "properties": _props_for_lookup(parcel),
        }
        for parcel in parcels
    ]
    real_rows: list[dict[str, Any]] = []
    if features:
        real_rows = _fetch_realproperty_rows(features)
    matched = _merge_realproperty_attributes(features, real_rows)

    updated = 0
    with_address = 0
    sample_ids: list[str] = []
    for parcel, feature in zip(parcels, features, strict=False):
        props = feature.get("properties") or {}
        if _has_address(props):
            with_address += 1
        if props.get("BALTIMORE_REALPROPERTY_MATCHED") and _has_address(props):
            sample_ids.append(str(parcel.id))
            if not dry_run:
                merged = dict(parcel.raw_properties or {})
                merged.update({k: v for k, v in props.items() if v is not None})
                parcel.raw_properties = merged
                db.add(parcel)
                updated += 1

    if not dry_run and updated:
        db.commit()
        write_audit(
            db,
            actor="system",
            action="baltimore_address_backfill_batch",
            entity_type="parcel",
            entity_id=None,
            meta={
                "limit": cap,
                "selected": len(parcels),
                "matched": matched,
                "updated": updated,
                "sample_parcel_ids": sample_ids[:25],
            },
        )
    elif dry_run:
        db.rollback()

    elapsed = round(monotonic() - started, 3)
    return {
        "county_fips": BALTIMORE_CITY_COUNTY_FIPS,
        "limit": cap,
        "dry_run": dry_run,
        "selected": len(parcels),
        "realproperty_rows_fetched": len(real_rows),
        "matched": matched,
        "with_address": with_address,
        "updated": updated,
        "elapsed_sec": elapsed,
        "measured_at": datetime.now(UTC).isoformat(),
        "sample_parcel_ids": sample_ids[:25],
        "note": "Pilot batch only; inspect DB CPU/runtime before scaling.",
    }

"""Measured Baltimore City property-address backfill batches."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.models import Parcel
from parking_ingestion.baltimore_parcels import (
    BALTIMORE_CITY_COUNTY_FIPS,
    _fetch_realproperty_rows_for_parcels,
    _merge_realproperty_attributes,
)

REALPROPERTY_LAYER_URL = "https://geodata.baltimorecity.gov/egis/rest/services/CityView/Realproperty_OB/FeatureServer/0"

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
        real_rows = _fetch_realproperty_rows_for_parcels(
            features=features,
            layer_url=REALPROPERTY_LAYER_URL,
            sleep_sec=0.05,
        )
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

"""Measured Baltimore City property-address backfill batches."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.models import Parcel, ParcelScore
from app.pipeline_funnel import (
    entitlement_qualified_floor,
    identification_prescreen_floor,
    strategic_qualified_floor,
)
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.zoning_entitlement import effective_zoning_code
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
ADDRESS_BACKFILL_STATUS_KEY = "BALTIMORE_ADDRESS_BACKFILL_STATUS"
ADDRESS_BACKFILL_ATTEMPTED_AT_KEY = "BALTIMORE_ADDRESS_BACKFILL_ATTEMPTED_AT"
ADDRESS_BACKFILL_LOOKUP_KEYS = "BALTIMORE_ADDRESS_BACKFILL_LOOKUP_KEYS"
ADDRESS_BACKFILL_SOURCE_KEY = "BALTIMORE_ADDRESS_BACKFILL_SOURCE"
ADDRESS_BACKFILL_SOURCE = "Baltimore Realproperty_OB"
ADDRESS_BACKFILL_ADDRESS_FOUND = "address_found"
ADDRESS_BACKFILL_MATCHED_WITHOUT_ADDRESS = "matched_without_address"
ADDRESS_BACKFILL_NO_MATCH = "no_match"
ADDRESS_BACKFILL_TERMINAL_STATUSES = (
    ADDRESS_BACKFILL_MATCHED_WITHOUT_ADDRESS,
    ADDRESS_BACKFILL_NO_MATCH,
)


def _missing_address_sql() -> str:
    present = " OR ".join(f"(raw_properties ? '{key}')" for key in ADDRESS_KEYS)
    terminal_statuses = ", ".join(_sql_string(status) for status in ADDRESS_BACKFILL_TERMINAL_STATUSES)
    not_terminal = f"coalesce(raw_properties->>'{ADDRESS_BACKFILL_STATUS_KEY}', '') not in ({terminal_statuses})"
    return f"(raw_properties is null or not ({present})) and {not_terminal}"


def _vacant_or_suitable_sql() -> str:
    # Uses fields that may already exist from earlier Realproperty/parcel ingest attempts.
    use_blob = """
        upper(concat_ws(
            ' ',
            raw_properties->>'USEGROUP',
            raw_properties->>'SDATCODE',
            raw_properties->>'DHCDUSE1',
            raw_properties->>'DHCDUSE2',
            raw_properties->>'DHCDUSE3',
            raw_properties->>'DHCDUSE4'
        ))
    """
    return f"""
    (
        upper(coalesce(raw_properties->>'VACIND', '')) = 'Y'
        or upper(coalesce(raw_properties->>'NO_IMPRV', '')) in ('Y', 'YES', 'TRUE', '1')
        or {use_blob} similar to '%(VACANT|UNIMPROVED|PARKING|GARAGE|LOT|AUTO)%'
    )
    """


def _latest_score(profile: str):
    return (
        select(ParcelScore.total_score)
        .where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == profile,
        )
        .order_by(ParcelScore.created_at.desc())
        .limit(1)
        .correlate(Parcel)
        .scalar_subquery()
    )


def _target_address_backfill_filters():
    """Select only Baltimore parcels where a street address is worth backfilling."""
    latest_identification_score = _latest_score(IDENTIFICATION)
    latest_entitlement_score = _latest_score(ENTITLEMENT)
    latest_strategic_score = _latest_score(STRATEGIC)
    targetable = or_(
        latest_identification_score >= identification_prescreen_floor(),
        latest_entitlement_score >= entitlement_qualified_floor(),
        latest_strategic_score >= strategic_qualified_floor(),
        Parcel.zoning_allows_surface_parking.is_(True),
        text(_vacant_or_suitable_sql()),
    )
    return (
        Parcel.county_fips == BALTIMORE_CITY_COUNTY_FIPS,
        text(_missing_address_sql()),
        targetable,
    )


def _target_address_backfill_stmt(limit: int):
    """Select only Baltimore parcels where a street address is worth backfilling."""
    latest_identification_score = _latest_score(IDENTIFICATION)
    latest_entitlement_score = _latest_score(ENTITLEMENT)
    return (
        select(Parcel)
        .where(*_target_address_backfill_filters())
        .order_by(
            desc(latest_entitlement_score).nulls_last(),
            desc(latest_identification_score).nulls_last(),
            Parcel.created_at.asc(),
            Parcel.id.asc(),
        )
        .limit(limit)
    )


def count_target_baltimore_address_backfill_parcels(db: Session) -> int:
    """Return actionable Baltimore candidate rows still eligible for address lookup."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(*_target_address_backfill_filters())
        )
        or 0
    )


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


def _mark_attempted(props: dict[str, Any], *, status: str, measured_at: str) -> None:
    props[ADDRESS_BACKFILL_STATUS_KEY] = status
    props[ADDRESS_BACKFILL_ATTEMPTED_AT_KEY] = measured_at
    props[ADDRESS_BACKFILL_SOURCE_KEY] = ADDRESS_BACKFILL_SOURCE
    props[ADDRESS_BACKFILL_LOOKUP_KEYS] = sorted(_lookup_keys(props))


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
    stmt = _target_address_backfill_stmt(cap)
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

    measured_at = datetime.now(UTC).isoformat()
    updated = 0
    marked_attempted = 0
    matched_without_address = 0
    no_match = 0
    with_address = 0
    sample_ids: list[str] = []
    for parcel, feature in zip(parcels, features, strict=False):
        props = feature.get("properties") or {}
        if _has_address(props):
            with_address += 1
        matched_parcel = bool(props.get("BALTIMORE_REALPROPERTY_MATCHED"))
        has_address = _has_address(props)
        if matched_parcel and has_address:
            sample_ids.append(str(parcel.id))
            status = ADDRESS_BACKFILL_ADDRESS_FOUND
            updated += 1
        elif matched_parcel:
            status = ADDRESS_BACKFILL_MATCHED_WITHOUT_ADDRESS
            matched_without_address += 1
            marked_attempted += 1
        else:
            status = ADDRESS_BACKFILL_NO_MATCH
            no_match += 1
            marked_attempted += 1

        if not dry_run:
            merged = dict(parcel.raw_properties or {})
            merged.update({k: v for k, v in props.items() if v is not None})
            _mark_attempted(merged, status=status, measured_at=measured_at)
            parcel.raw_properties = merged
            parcel.zoning_code = effective_zoning_code(getattr(parcel, "zoning_code", None), merged)
            db.add(parcel)

    if not dry_run and parcels:
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
                "marked_attempted": marked_attempted,
                "matched_without_address": matched_without_address,
                "no_match": no_match,
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
        "marked_attempted": marked_attempted,
        "matched_without_address": matched_without_address,
        "no_match": no_match,
        "elapsed_sec": elapsed,
        "measured_at": measured_at,
        "sample_parcel_ids": sample_ids[:25],
        "note": (
            "Targeted batch only: high-scoring, surface-parking-zoned, or vacant/suitable-looking parcels; "
            "inspect DB CPU/runtime before scaling."
        ),
    }

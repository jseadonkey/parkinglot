"""WA candidate-only situs backfill via centroid reverse geocode (Nominatim)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.candidate_address import target_address_backfill_filters
from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import IDENTIFICATION
from parking_enrichment.batchdata_skip_trace_client import property_address_for_skip_trace

FALLBACK_SOURCE = "nominatim_centroid_fallback"
STATUS_KEY = "WA_ADDRESS_BACKFILL_STATUS"
ATTEMPTED_AT_KEY = "WA_ADDRESS_BACKFILL_ATTEMPTED_AT"


def _latest_identification_score():
    return (
        select(ParcelScore.total_score)
        .where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == IDENTIFICATION,
        )
        .order_by(ParcelScore.created_at.desc())
        .limit(1)
        .correlate(Parcel)
        .scalar_subquery()
    )


def _candidate_stmt(county_fips: str | None, limit: int):
    if county_fips:
        filters = list(target_address_backfill_filters(county_fips=county_fips))
    else:
        filters = list(target_address_backfill_filters(wa_only=True))
    # Highest-scored gaps first so the operator list fills before long-tail parcels.
    return (
        select(Parcel)
        .where(*filters)
        .order_by(_latest_identification_score().desc().nulls_last(), Parcel.id.asc())
        .limit(limit)
    )


def backfill_wa_centroid_addresses(
    db: Session,
    *,
    limit: int = 100,
    county_fips: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fill VISIT_ADDRESS / PROPERTY_ADDRESS for qualified WA parcels missing situs."""
    rows = list(db.scalars(_candidate_stmt(county_fips, limit)))
    found = 0
    no_match = 0
    skipped_no_anchor = 0

    for parcel in rows:
        props = dict(parcel.raw_properties or {})
        lat_lon = None
        if parcel.footprint is not None:
            try:
                pt = to_shape(parcel.footprint).centroid
                lat_lon = (float(pt.y), float(pt.x))
            except Exception:
                lat_lon = None

        resolved = property_address_for_skip_trace(
            props,
            centroid_lat_lon=lat_lon,
            allow_centroid_geocode=True,
        )
        props[ATTEMPTED_AT_KEY] = datetime.now(UTC).isoformat()
        if not resolved:
            props[STATUS_KEY] = "no_geocode_match"
            if not props.get("SITUS_CITY") and not props.get("SITUS_CITY_NM"):
                skipped_no_anchor += 1
            no_match += 1
            if not dry_run:
                parcel.raw_properties = props
            continue

        street = resolved.get("street") or ""
        city = resolved.get("city") or ""
        state = resolved.get("state") or "WA"
        zip_code = resolved.get("zip") or ""
        full = ", ".join(p for p in (street, city, f"{state} {zip_code}".strip()) if p)
        # Overwrite blank/ZIP-only placeholders; setdefault would leave "" in place.
        if not str(props.get("VISIT_ADDRESS") or "").strip():
            props["VISIT_ADDRESS"] = full
        if not str(props.get("MAP_ADDRESS") or "").strip():
            props["MAP_ADDRESS"] = full
        if not str(props.get("PROPERTY_ADDRESS") or "").strip():
            props["PROPERTY_ADDRESS"] = street or full
        if not str(props.get("SITUS_ADDRESS") or "").strip():
            props["SITUS_ADDRESS"] = street or full
        if not str(props.get("SITUS_CITY") or props.get("SITUS_CITY_NM") or "").strip():
            props["SITUS_CITY"] = city
        if not str(props.get("SITUS_ZIP") or "").strip():
            props["SITUS_ZIP"] = zip_code
        props[STATUS_KEY] = "fallback_address_found"
        props["ADDRESS_BACKFILL_SOURCE"] = FALLBACK_SOURCE
        found += 1
        if not dry_run:
            parcel.raw_properties = props

    if dry_run:
        db.rollback()
    else:
        db.commit()
        write_audit(
            db,
            actor="system",
            action="wa_centroid_address_backfill",
            entity_type="county",
            entity_id=county_fips or "53",
            meta={
                "limit": limit,
                "selected": len(rows),
                "found": found,
                "no_match": no_match,
                "skipped_no_anchor": skipped_no_anchor,
            },
        )
        db.commit()

    return {
        "county_fips": county_fips,
        "selected": len(rows),
        "found": found,
        "no_match": no_match,
        "skipped_no_city_zip_anchor": skipped_no_anchor,
        "dry_run": dry_run,
    }

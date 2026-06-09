"""Shared candidate-only street address gap detection (Baltimore + Washington)."""

from __future__ import annotations

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.pipeline_funnel import (
    entitlement_qualified_floor,
    identification_prescreen_floor,
    strategic_qualified_floor,
)
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from parking_ingestion.address_normalize import ADDRESS_KEYS, has_usable_situs

BALTIMORE_CITY_FIPS = "24510"
WA_COUNTY_PREFIX = "53"

FALLBACK_ADDRESS_KEYS = (
    "VISIT_ADDRESS",
    "visit_address",
    "MAP_ADDRESS",
    "map_address",
)


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


def _missing_address_sql() -> str:
    present = " OR ".join(f"(raw_properties ? '{key}')" for key in (*ADDRESS_KEYS, *FALLBACK_ADDRESS_KEYS))
    return f"(raw_properties is null or not ({present}))"


def _target_candidate_score_filters():
    latest_identification_score = _latest_score(IDENTIFICATION)
    latest_entitlement_score = _latest_score(ENTITLEMENT)
    latest_strategic_score = _latest_score(STRATEGIC)
    return or_(
        latest_identification_score >= identification_prescreen_floor(),
        latest_entitlement_score >= entitlement_qualified_floor(),
        latest_strategic_score >= strategic_qualified_floor(),
        Parcel.zoning_allows_surface_parking.is_(True),
    )


def target_address_backfill_filters(*, county_fips: str | None = None, wa_only: bool = False):
    filters = [
        text(_missing_address_sql()),
        _target_candidate_score_filters(),
    ]
    if county_fips:
        filters.insert(0, Parcel.county_fips == county_fips)
    elif wa_only:
        filters.insert(0, Parcel.county_fips.like(f"{WA_COUNTY_PREFIX}%"))
    return tuple(filters)


def _wa_candidate_pool_filters():
    filters = [_target_candidate_score_filters(), Parcel.county_fips.like(f"{WA_COUNTY_PREFIX}%")]
    return tuple(filters)


def count_wa_candidate_pool_parcels(db: Session) -> int:
    """WA deal candidates (score/zoning gate) regardless of address presence."""
    return int(
        db.scalar(select(func.count()).select_from(Parcel).where(*_wa_candidate_pool_filters())) or 0
    )


def count_candidate_pool_parcels(
    db: Session,
    *,
    county_fips: str | None = None,
    wa_only: bool = False,
) -> int:
    """Deal candidates (score/zoning gate) regardless of address presence."""
    filters = [_target_candidate_score_filters()]
    if county_fips:
        filters.insert(0, Parcel.county_fips == county_fips)
    elif wa_only:
        filters.insert(0, Parcel.county_fips.like(f"{WA_COUNTY_PREFIX}%"))
    return int(db.scalar(select(func.count()).select_from(Parcel).where(*filters)) or 0)


def count_target_candidate_address_backfill_parcels(
    db: Session,
    *,
    county_fips: str | None = None,
    wa_only: bool = False,
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(*target_address_backfill_filters(county_fips=county_fips, wa_only=wa_only))
        )
        or 0
    )


def wa_candidate_address_gaps_by_county(db: Session, limit: int = 20) -> list[dict[str, int | str]]:
    """Top WA counties by candidate address gap (for coverage reports)."""
    rows = db.execute(
        select(Parcel.county_fips, func.count())
        .where(*target_address_backfill_filters(wa_only=True))
        .group_by(Parcel.county_fips)
        .order_by(desc(func.count()))
        .limit(limit)
    )
    return [{"county_fips": str(fips), "candidate_gap": int(cnt)} for fips, cnt in rows]


def parcel_has_usable_address(raw_properties: dict | None) -> bool:
    return has_usable_situs(raw_properties or {})

"""Candidate selection for OSM POI-density enrichment."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.db.models import Parcel, ParcelScore
from app.pipeline_funnel import entitlement_qualified_floor, strategic_qualified_floor
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC

POI_DENSITY_CANDIDATE_MODE = "qualified_entitlement_and_strategic"


def _latest_score(profile: str) -> Any:
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


def poi_density_candidate_condition(
    *,
    entitlement_floor: float | None = None,
    strategic_floor: float | None = None,
) -> ColumnElement[bool]:
    """True for parcels qualified enough to justify POI-density enrichment."""
    ent_floor = entitlement_qualified_floor() if entitlement_floor is None else entitlement_floor
    strat_floor = strategic_qualified_floor() if strategic_floor is None else strategic_floor
    return and_(
        _latest_score(ENTITLEMENT) >= ent_floor,
        _latest_score(STRATEGIC) >= strat_floor,
    )


def poi_density_candidate_ordering() -> list[Any]:
    """Prioritize the strongest deal candidates before spending Overpass calls."""
    latest_strategic_score = _latest_score(STRATEGIC)
    latest_entitlement_score = _latest_score(ENTITLEMENT)
    latest_identification_score = _latest_score(IDENTIFICATION)
    return [
        desc(latest_strategic_score).nulls_last(),
        desc(latest_entitlement_score).nulls_last(),
        desc(latest_identification_score).nulls_last(),
        Parcel.distance_to_nearest_demand_m.asc().nulls_last(),
        Parcel.created_at.asc(),
        Parcel.id.asc(),
    ]


def _candidate_filters(
    *,
    county_fips: str | None = None,
    missing_only: bool = False,
    require_footprint: bool = False,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [poi_density_candidate_condition()]
    cf = (county_fips or "").strip()
    if cf:
        filters.append(Parcel.county_fips == cf)
    if missing_only:
        filters.append(Parcel.poi_commercial_count_400m.is_(None))
    if require_footprint:
        filters.append(Parcel.footprint.isnot(None))
    return filters


def count_poi_density_candidates(
    db: Session,
    *,
    county_fips: str | None = None,
    missing_only: bool = False,
    require_footprint: bool = False,
) -> int:
    """Count qualified parcels in the POI-density candidate pool."""
    return int(
        db.scalar(
            select(func.count()).select_from(Parcel).where(
                *_candidate_filters(
                    county_fips=county_fips,
                    missing_only=missing_only,
                    require_footprint=require_footprint,
                ),
            ),
        )
        or 0,
    )


def select_poi_density_candidates(
    *,
    limit: int,
    county_fips: str | None = None,
    only_missing: bool = True,
    exclude_ids: Iterable[uuid.UUID] | None = None,
):
    """Build the parcel query used by POI-density refresh batches."""
    stmt = select(Parcel).where(
        *_candidate_filters(
            county_fips=county_fips,
            missing_only=only_missing,
            require_footprint=True,
        ),
    )
    excluded = list(exclude_ids or [])
    if excluded:
        stmt = stmt.where(Parcel.id.notin_(excluded))
    return stmt.order_by(*poi_density_candidate_ordering()).limit(limit)

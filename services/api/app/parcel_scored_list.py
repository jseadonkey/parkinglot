"""Parcels with latest Atlas / Beacon / Cartographer scores for operator list views."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import desc, nulls_last, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC

ParcelSortProfile = Literal["entitlement", "strategic", "identification"]


@dataclass(frozen=True)
class ParcelScoredRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    zoning_code: str | None
    lot_sqft: float | None
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    created_at: datetime


def _latest_score_subq(parcel_id_col: Any, profile: str) -> Any:
    return (
        select(ParcelScore.total_score)
        .where(ParcelScore.parcel_id == parcel_id_col)
        .where(ParcelScore.score_profile == profile)
        .order_by(desc(ParcelScore.created_at))
        .limit(1)
        .correlate(Parcel)
        .scalar_subquery()
    )


def query_parcels_scored_list(
    db: Session,
    *,
    limit: int,
    sort: ParcelSortProfile = ENTITLEMENT,
) -> list[ParcelScoredRowData]:
    """All parcels with latest score per profile, ordered by ``sort`` (null scores last)."""
    cap = min(max(limit, 1), 2000)
    ent_sub = _latest_score_subq(Parcel.id, ENTITLEMENT)
    str_sub = _latest_score_subq(Parcel.id, STRATEGIC)
    id_sub = _latest_score_subq(Parcel.id, IDENTIFICATION)

    sort_col = ent_sub
    if sort == STRATEGIC:
        sort_col = str_sub
    elif sort == IDENTIFICATION:
        sort_col = id_sub

    stmt = (
        select(
            Parcel.id,
            Parcel.apn,
            Parcel.county_fips,
            Parcel.zoning_code,
            Parcel.lot_sqft,
            Parcel.created_at,
            ent_sub.label("ent_score"),
            str_sub.label("str_score"),
            id_sub.label("id_score"),
        )
        .order_by(nulls_last(desc(sort_col)), desc(Parcel.created_at))
        .limit(cap)
    )
    out: list[ParcelScoredRowData] = []
    for r in db.execute(stmt).all():
        pid, apn, cfips, zoning, sqft, created, ent_f, str_f, id_f = r
        out.append(
            ParcelScoredRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                zoning_code=zoning,
                lot_sqft=float(sqft) if sqft is not None else None,
                entitlement_score=float(ent_f) if ent_f is not None else None,
                strategic_score=float(str_f) if str_f is not None else None,
                identification_score=float(id_f) if id_f is not None else None,
                created_at=created,
            ),
        )
    return out

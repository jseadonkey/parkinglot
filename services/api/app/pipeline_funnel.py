"""Funnel gates between identification prescreen and full ``run_pipeline`` scoring."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.config import get_settings
from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from parking_core.pilot import load_pilot_config


def identification_prescreen_floor() -> float:
    settings = get_settings()
    pilot_i = load_pilot_config(settings.pilot_identification_config_path)
    return float(pilot_i.scoring.qualified_min_score)


def identification_prescreen_qualified(floor: float | None = None) -> ColumnElement[bool]:
    """True when the parcel's latest identification score ≥ prescreen floor."""
    f = floor if floor is not None else identification_prescreen_floor()
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == IDENTIFICATION)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    return exists(
        select(1)
        .select_from(ParcelScore)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == IDENTIFICATION,
            ParcelScore.total_score >= f,
        )
    )


def has_identification_score() -> ColumnElement[bool]:
    return exists(
        select(1).where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == IDENTIFICATION,
        )
    )


def has_entitlement_score() -> ColumnElement[bool]:
    return exists(
        select(1).where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == ENTITLEMENT,
        )
    )


def has_strategic_score() -> ColumnElement[bool]:
    return exists(
        select(1).where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == STRATEGIC,
        )
    )


def entitlement_qualified_floor() -> float:
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    return float(pilot.scoring.qualified_min_score)


def strategic_qualified_floor() -> float:
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_strategic_config_path)
    return float(pilot.scoring.qualified_min_score)


def _latest_profile_score_at_least(profile: str, floor: float) -> ColumnElement[bool]:
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    return exists(
        select(1)
        .select_from(ParcelScore)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == profile,
            ParcelScore.total_score >= floor,
        )
    )


def needs_pipeline_scoring() -> ColumnElement[bool]:
    """True when Atlas has not run, or Atlas passed and Beacon has not run yet."""
    floor_ent = entitlement_qualified_floor()
    return or_(
        not_(has_entitlement_score()),
        and_(
            _latest_profile_score_at_least(ENTITLEMENT, floor_ent),
            not_(has_strategic_score()),
        ),
    )


def missing_pipeline_pair() -> ColumnElement[bool]:
    return or_(not_(has_entitlement_score()), not_(has_strategic_score()))


def pipeline_funnel_backlog(floor: float | None = None) -> ColumnElement[bool]:
    """Prescreen-qualified parcels that still need Atlas and/or Beacon scoring."""
    return and_(identification_prescreen_qualified(floor), needs_pipeline_scoring())


def ruled_out_at_atlas() -> ColumnElement[bool]:
    """Atlas scored below floor — Beacon and enrichment should not run."""
    floor_ent = entitlement_qualified_floor()
    return and_(
        identification_prescreen_qualified(),
        has_entitlement_score(),
        not_(_latest_profile_score_at_least(ENTITLEMENT, floor_ent)),
    )


def ruled_out_by_prescreen(floor: float | None = None) -> ColumnElement[bool]:
    """Has identification score but below prescreen floor; no full pipeline yet."""
    f = floor if floor is not None else identification_prescreen_floor()
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == IDENTIFICATION)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    below_floor = exists(
        select(1)
        .select_from(ParcelScore)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(
            ParcelScore.parcel_id == Parcel.id,
            ParcelScore.score_profile == IDENTIFICATION,
            ParcelScore.total_score < f,
        )
    )
    return and_(missing_pipeline_pair(), below_floor)


def count_where(db: Session, condition: ColumnElement[bool]) -> int:
    return int(db.scalar(select(func.count()).select_from(Parcel).where(condition)) or 0)


def parcel_prescreen_qualified(db: Session, parcel_id: object, *, floor: float | None = None) -> bool:
    """Return whether ``parcel_id`` has latest identification score ≥ prescreen floor."""
    f = floor if floor is not None else identification_prescreen_floor()
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == IDENTIFICATION)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    ok = db.scalar(
        select(func.count())
        .select_from(ParcelScore)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(
            ParcelScore.parcel_id == parcel_id,
            ParcelScore.score_profile == IDENTIFICATION,
            ParcelScore.total_score >= f,
        )
    )
    return int(ok or 0) > 0


def filter_prescreen_qualified_ids(db: Session, parcel_ids: list[str]) -> list[str]:
    """Keep only parcel ids that pass the identification prescreen floor."""
    if not parcel_ids:
        return []
    floor = identification_prescreen_floor()
    uuids = [uuid.UUID(pid) for pid in parcel_ids]
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == IDENTIFICATION)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    rows = db.scalars(
        select(ParcelScore.parcel_id)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(
            ParcelScore.parcel_id.in_(uuids),
            ParcelScore.score_profile == IDENTIFICATION,
            ParcelScore.total_score >= floor,
        )
        .order_by(ParcelScore.total_score.desc())
    ).all()
    return [str(pid) for pid in rows]

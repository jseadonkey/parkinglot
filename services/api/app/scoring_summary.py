"""Fast aggregate counts for GET /internal/stats/scoring-summary (operator funnel)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Parcel, ParcelScore
from app.pipeline_funnel import (
    count_where,
    identification_prescreen_floor,
    identification_prescreen_qualified,
    pipeline_funnel_backlog,
    ruled_out_by_prescreen,
)
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from parking_core.pilot import load_pilot_config


def _latest_scores_subquery(profile: str):
    """One row per parcel: latest total_score for the given profile."""
    agg = (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    return (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            ParcelScore.total_score.label("total_score"),
        )
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.parcel_id,
                ParcelScore.created_at == agg.c.mx,
                ParcelScore.score_profile == profile,
            ),
        )
        .subquery(f"latest_{profile.replace('-', '_')}")
    )


def _count_subquery_rows(db: Session, subq) -> int:
    return int(db.scalar(select(func.count()).select_from(subq)) or 0)


def _count_subquery_qualified(db: Session, subq, floor: float) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(subq).where(subq.c.total_score >= floor),
        )
        or 0,
    )


def _count_paired_latest_ent_strategic(db: Session) -> int:
    ent = _latest_scores_subquery(ENTITLEMENT)
    st = _latest_scores_subquery(STRATEGIC)
    return int(
        db.scalar(
            select(func.count())
            .select_from(ent)
            .join(st, ent.c.parcel_id == st.c.parcel_id),
        )
        or 0,
    )


def scoring_summary_stats(db: Session) -> dict[str, Any]:
    """Return ScoringSummaryResponse fields using SQL counts only (no full-row load)."""
    settings = get_settings()
    pilot_e = load_pilot_config(settings.pilot_config_path)
    pilot_s = load_pilot_config(settings.pilot_strategic_config_path)
    pilot_i = load_pilot_config(settings.pilot_identification_config_path)
    floor_e = float(pilot_e.scoring.qualified_min_score)
    floor_s = float(pilot_s.scoring.qualified_min_score)
    floor_i = float(pilot_i.scoring.qualified_min_score)

    sub_ent = _latest_scores_subquery(ENTITLEMENT)
    sub_str = _latest_scores_subquery(STRATEGIC)
    sub_id = _latest_scores_subquery(IDENTIFICATION)

    total_parcels = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
    floor_i = identification_prescreen_floor()
    prescreen_qualified = count_where(db, identification_prescreen_qualified(floor_i))
    ruled_out_prescreen = count_where(db, ruled_out_by_prescreen(floor_i))
    pipeline_backlog = count_where(db, pipeline_funnel_backlog(floor_i))

    return {
        "total_parcels": total_parcels,
        "parcels_prescreen_qualified": prescreen_qualified,
        "prescreen_floor": floor_i,
        "parcels_ruled_out_by_prescreen": ruled_out_prescreen,
        "parcels_pipeline_funnel_backlog": pipeline_backlog,
        "parcels_with_latest_entitlement_score": _count_subquery_rows(db, sub_ent),
        "parcels_with_latest_strategic_score": _count_subquery_rows(db, sub_str),
        "parcels_with_latest_identification_score": _count_subquery_rows(db, sub_id),
        "parcels_with_both_profiles_scored": _count_paired_latest_ent_strategic(db),
        "qualified_count_entitlement": _count_subquery_qualified(db, sub_ent, floor_e),
        "qualified_count_strategic": _count_subquery_qualified(db, sub_str, floor_s),
        "qualified_count_identification": _count_subquery_qualified(db, sub_id, floor_i),
        "qualified_min_score": {
            "entitlement": floor_e,
            "strategic": floor_s,
            "identification": floor_i,
        },
        "pilot_region": pilot_e.region.name,
    }

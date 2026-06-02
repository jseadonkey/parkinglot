from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore, WorkflowRun
from app.db.schema_compat import parcel_load_only, parcel_to_read
from app.db.session import get_db
from app.parcel_deal_context import build_parcel_deal_context
from app.pipeline_funnel import identification_prescreen_floor, parcel_prescreen_qualified
from app.schemas import (
    ParcelDealContextResponse,
    ParcelPipelineTaskResponse,
    ParcelRead,
    ParcelScoreRead,
    WorkflowRunRead,
)
from app.scoring_profiles import ENTITLEMENT, ScoreProfile
from app.tasks import run_pipeline
from parking_core.pilot import load_pilot_config

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("", response_model=list[ParcelRead])
def list_parcels(
    limit: int = 50,
    min_score: float | None = None,
    qualified_only: bool = False,
    db: Session = Depends(get_db),
) -> list[ParcelRead]:
    """List parcels. Use ``qualified_only=true`` (latest score ≥ pilot ``qualified_min_score``) or ``min_score=``."""
    lim = min(limit, 200)
    floor = min_score
    if qualified_only and floor is None:
        from app.config import get_settings

        pilot = load_pilot_config(get_settings().pilot_config_path)
        floor = float(pilot.scoring.qualified_min_score)
    if floor is not None:
        latest_total = (
            select(ParcelScore.total_score)
            .where(ParcelScore.parcel_id == Parcel.id)
            .where(ParcelScore.score_profile == ENTITLEMENT)
            .order_by(desc(ParcelScore.created_at))
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(Parcel)
            .options(parcel_load_only(db))
            .where(latest_total >= floor)
            .order_by(Parcel.created_at.desc())
            .limit(lim)
        )
    else:
        stmt = select(Parcel).options(parcel_load_only(db)).order_by(Parcel.created_at.desc()).limit(lim)
    rows = list(db.scalars(stmt))
    return [parcel_to_read(db, r) for r in rows]


@router.get("/{parcel_id}", response_model=ParcelRead)
def get_parcel(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> ParcelRead:
    row = db.scalars(select(Parcel).options(parcel_load_only(db)).where(Parcel.id == parcel_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    return parcel_to_read(db, row)


@router.get("/{parcel_id}/workflow-runs", response_model=list[WorkflowRunRead])
def list_workflow_runs_for_parcel(
    parcel_id: uuid.UUID,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[WorkflowRun]:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    cap = min(max(limit, 1), 200)
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.parcel_id == parcel_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(cap)
    )
    return list(db.scalars(stmt))


@router.get("/{parcel_id}/deal-context", response_model=ParcelDealContextResponse)
def get_parcel_deal_context(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ParcelDealContextResponse:
    """Nearby qualified parcels, parking rate comps, and illustrative gross revenue."""
    raw = build_parcel_deal_context(db, parcel_id)
    if not raw.get("found"):
        raise HTTPException(status_code=404, detail="parcel not found")
    return ParcelDealContextResponse(**raw)


@router.get("/{parcel_id}/score", response_model=ParcelScoreRead)
def get_latest_score(
    parcel_id: uuid.UUID,
    profile: ScoreProfile = ENTITLEMENT,
    db: Session = Depends(get_db),
) -> ParcelScore:
    stmt = (
        select(ParcelScore)
        .where(ParcelScore.parcel_id == parcel_id)
        .where(ParcelScore.score_profile == profile)
        .order_by(ParcelScore.created_at.desc())
        .limit(1)
    )
    row = db.scalars(stmt).first()
    if row is None:
        raise HTTPException(status_code=404, detail="score not found")
    return row


@router.post("/{parcel_id}/pipeline/run", response_model=ParcelPipelineTaskResponse)
def run_pipeline_for_parcel(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ParcelPipelineTaskResponse:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    floor = identification_prescreen_floor()
    if not parcel_prescreen_qualified(db, parcel_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"parcel below identification prescreen floor ({floor:.0f}); "
                "full pipeline (owner enrichment, memo, contract) is not run for ruled-out lots"
            ),
        )
    async_result = run_pipeline.delay(str(parcel_id))
    return ParcelPipelineTaskResponse(task_id=async_result.id, parcel_id=str(parcel_id))

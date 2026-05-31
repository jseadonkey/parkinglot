from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, nulls_last, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore, WorkflowRun
from app.db.session import get_db
from app.parcel_detail import build_parcel_detail
from app.pilot_scope_filter import parcel_in_scope_clause
from app.schemas import (
    ParcelDetailRead,
    ParcelListRead,
    ParcelPipelineTaskResponse,
    ParcelRead,
    ParcelScoreRead,
    WorkflowRunRead,
)
from app.outreach_board import _latest_score_subq
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC, ScoreProfile
from app.tasks import run_pipeline
from parking_core.pilot import load_pilot_config

router = APIRouter(prefix="/parcels", tags=["parcels"])


def _parcel_list_read(
    parcel: Parcel,
    *,
    id_score: float | None,
    ent_score: float | None,
    str_score: float | None,
) -> ParcelListRead:
    base = ParcelRead.model_validate(parcel)
    return ParcelListRead(
        **base.model_dump(),
        latest_identification_score=float(id_score) if id_score is not None else None,
        latest_entitlement_score=float(ent_score) if ent_score is not None else None,
        latest_strategic_score=float(str_score) if str_score is not None else None,
    )


@router.get("", response_model=list[ParcelListRead])
def list_parcels(
    limit: int = 50,
    min_score: float | None = None,
    qualified_only: bool = False,
    sort: Literal["created_at", "score"] = Query(
        default="created_at",
        description="Order results by ingest time or latest entitlement score (highest first).",
    ),
    db: Session = Depends(get_db),
) -> list[ParcelListRead]:
    """List parcels. Use ``qualified_only=true`` (latest score ≥ pilot ``qualified_min_score``) or ``min_score=``."""
    lim = min(limit, 200)
    floor = min_score
    if qualified_only and floor is None:
        from app.config import get_settings

        pilot = load_pilot_config(get_settings().pilot_config_path)
        floor = float(pilot.scoring.qualified_min_score)

    id_sub = _latest_score_subq(Parcel.id, IDENTIFICATION)
    ent_sub = _latest_score_subq(Parcel.id, ENTITLEMENT)
    str_sub = _latest_score_subq(Parcel.id, STRATEGIC)
    order_by = (
        [nulls_last(ent_sub.desc()), Parcel.created_at.desc()]
        if sort == "score"
        else [Parcel.created_at.desc()]
    )

    if floor is not None:
        stmt = (
            select(
                Parcel,
                id_sub.label("id_score"),
                ent_sub.label("ent_score"),
                str_sub.label("str_score"),
            )
            .where(parcel_in_scope_clause(), ent_sub >= floor)
            .order_by(*order_by)
            .limit(lim)
        )
    else:
        stmt = (
            select(
                Parcel,
                id_sub.label("id_score"),
                ent_sub.label("ent_score"),
                str_sub.label("str_score"),
            )
            .where(parcel_in_scope_clause())
            .order_by(*order_by)
            .limit(lim)
        )

    rows = db.execute(stmt).all()
    return [
        _parcel_list_read(p, id_score=i, ent_score=e, str_score=s)
        for p, i, e, s in rows
    ]


@router.get("/{parcel_id}", response_model=ParcelRead)
def get_parcel(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> Parcel:
    row = db.get(Parcel, parcel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    return row


@router.get("/{parcel_id}/detail", response_model=ParcelDetailRead)
def get_parcel_detail(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> ParcelDetailRead:
    """All known data for one parcel — scores, owners, memos, approvals, enrichment."""
    raw = build_parcel_detail(db, parcel_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    return ParcelDetailRead.model_validate(raw)


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
    async_result = run_pipeline.delay(str(parcel_id))
    return ParcelPipelineTaskResponse(task_id=async_result.id, parcel_id=str(parcel_id))

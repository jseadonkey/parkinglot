from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore, WorkflowRun
from app.db.session import get_db
from app.schemas import ParcelRead, ParcelScoreRead, WorkflowRunRead
from app.tasks import run_pipeline

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("", response_model=list[ParcelRead])
def list_parcels(limit: int = 50, db: Session = Depends(get_db)) -> list[Parcel]:
    stmt = select(Parcel).order_by(Parcel.created_at.desc()).limit(min(limit, 200))
    return list(db.scalars(stmt))


@router.get("/{parcel_id}", response_model=ParcelRead)
def get_parcel(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> Parcel:
    row = db.get(Parcel, parcel_id)
    if row is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    return row


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
def get_latest_score(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> ParcelScore:
    stmt = (
        select(ParcelScore)
        .where(ParcelScore.parcel_id == parcel_id)
        .order_by(ParcelScore.created_at.desc())
        .limit(1)
    )
    row = db.scalars(stmt).first()
    if row is None:
        raise HTTPException(status_code=404, detail="score not found")
    return row


@router.post("/{parcel_id}/pipeline/run")
def run_pipeline_for_parcel(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    async_result = run_pipeline.delay(str(parcel_id))
    return {"task_id": async_result.id, "parcel_id": str(parcel_id)}

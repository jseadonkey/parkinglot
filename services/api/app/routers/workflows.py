from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import WorkflowRun
from app.db.session import get_db
from app.schemas import WorkflowRunRead

router = APIRouter(prefix="/workflow-runs", tags=["workflows"])


@router.get("", response_model=list[WorkflowRunRead])
def list_workflow_runs(
    parcel_id: uuid.UUID | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[WorkflowRun]:
    cap = min(max(limit, 1), 200)
    stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(cap)
    if parcel_id is not None:
        stmt = stmt.where(WorkflowRun.parcel_id == parcel_id)
    return list(db.scalars(stmt))


@router.get("/{run_id}", response_model=WorkflowRunRead)
def get_workflow_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> WorkflowRun:
    row = db.get(WorkflowRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    return row

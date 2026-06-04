"""Latest workflow run per parcel for operator deal-progress view."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, WorkflowRun
from app.outreach_board import _derive_pipeline_stage, _pending_approval_counts
from parking_workflows.state import WorkflowStatus


@dataclass(frozen=True)
class DealProgressRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    workflow_run_id: uuid.UUID
    workflow_status: str
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime
    pending_approval_count: int
    pipeline_stage: str


@dataclass(frozen=True)
class DealProgressSummary:
    total_parcels: int
    by_status: dict[str, int]
    by_step: dict[str, int]


def query_deal_progress_board(
    db: Session,
    *,
    limit: int,
    county_fips: str | None = None,
    state_fips: str | None = None,
) -> tuple[DealProgressSummary, list[DealProgressRowData]]:
    """One row per parcel — latest workflow run only (not every historical run)."""
    cap = min(max(limit, 1), 2000)
    cf = (county_fips or "").strip()
    st = (state_fips or "").strip()

    latest_sub = (
        select(
            WorkflowRun.parcel_id.label("parcel_id"),
            func.max(WorkflowRun.updated_at).label("max_updated"),
        )
        .group_by(WorkflowRun.parcel_id)
        .subquery("latest_wr")
    )

    stmt = (
        select(WorkflowRun, Parcel)
        .join(
            latest_sub,
            and_(
                WorkflowRun.parcel_id == latest_sub.c.parcel_id,
                WorkflowRun.updated_at == latest_sub.c.max_updated,
            ),
        )
        .join(Parcel, Parcel.id == WorkflowRun.parcel_id)
    )
    if cf:
        stmt = stmt.where(Parcel.county_fips == cf)
    elif st:
        stmt = stmt.where(Parcel.county_fips.startswith(st))
    stmt = stmt.order_by(desc(WorkflowRun.updated_at)).limit(cap)

    pairs = list(db.execute(stmt).all())
    if not pairs:
        empty = DealProgressSummary(total_parcels=0, by_status={}, by_step={})
        return empty, []

    parcel_ids = [wr.parcel_id for wr, _ in pairs]
    pending_map = _pending_approval_counts(db, parcel_ids)

    by_status: dict[str, int] = {}
    by_step: dict[str, int] = {}
    rows: list[DealProgressRowData] = []

    for wr, parcel in pairs:
        stage = _derive_pipeline_stage(wr)
        by_status[stage] = by_status.get(stage, 0) + 1
        if wr.status in (WorkflowStatus.running.value, WorkflowStatus.pending.value) and wr.current_step:
            by_step[wr.current_step] = by_step.get(wr.current_step, 0) + 1
        rows.append(
            DealProgressRowData(
                parcel_id=wr.parcel_id,
                apn=parcel.apn,
                county_fips=parcel.county_fips,
                workflow_run_id=wr.id,
                workflow_status=wr.status,
                workflow_step=wr.current_step,
                workflow_error=wr.error,
                workflow_updated_at=wr.updated_at,
                pending_approval_count=pending_map.get(str(wr.parcel_id), 0),
                pipeline_stage=stage,
            ),
        )

    summary = DealProgressSummary(
        total_parcels=len(rows),
        by_status=dict(sorted(by_status.items())),
        by_step=dict(sorted(by_step.items())),
    )
    return summary, rows

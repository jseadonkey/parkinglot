"""Aggregated rows for operator outreach-pipeline view (qualified parcels + workflow + briefs)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest, Parcel, ParcelScore, WorkflowRun
from app.pilot_scope_filter import parcel_in_scope_clause
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from parking_workflows.state import WorkflowStatus


@dataclass(frozen=True)
class OutreachPipelineRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    workflow_run_id: uuid.UUID | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    has_outreach_brief: bool
    pending_approval_count: int
    pipeline_stage: str
    owner_research_tier: str | None


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


def _derive_pipeline_stage(wr: WorkflowRun | None) -> str:
    """Single label for UI filters (parallel to ``workflow_runs.status``)."""
    if wr is None:
        return "no_run"
    st = wr.status
    if st == WorkflowStatus.failed.value:
        return "failed"
    if st == WorkflowStatus.blocked.value:
        return "blocked"
    if st == WorkflowStatus.completed.value:
        return "completed"
    if st == WorkflowStatus.pending.value or st == WorkflowStatus.running.value:
        return "running"
    return "other"


def query_outreach_pipeline_board(
    db: Session,
    *,
    qualified_min_entitlement: float,
    qualified_min_strategic: float,
    limit: int,
) -> list[OutreachPipelineRowData]:
    """Parcels whose latest entitlement **and** strategic scores meet pilot floors."""
    cap = min(max(limit, 1), 2000)
    ent_sub = _latest_score_subq(Parcel.id, ENTITLEMENT)
    str_sub = _latest_score_subq(Parcel.id, STRATEGIC)
    id_sub = _latest_score_subq(Parcel.id, IDENTIFICATION)

    stmt = (
        select(
            Parcel.id,
            Parcel.apn,
            Parcel.county_fips,
            Parcel.owner_outreach_brief,
            ent_sub.label("ent_score"),
            str_sub.label("str_score"),
            id_sub.label("id_score"),
        )
        .where(
            parcel_in_scope_clause(),
            ent_sub >= qualified_min_entitlement,
            str_sub >= qualified_min_strategic,
        )
        .order_by(desc(ent_sub), desc(str_sub), desc(Parcel.created_at))
        .limit(cap)
    )
    qrows = list(db.execute(stmt).all())
    if not qrows:
        return []

    parcel_ids = [r[0] for r in qrows]

    wr_all = list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.parcel_id.in_(parcel_ids))
            .order_by(WorkflowRun.parcel_id, desc(WorkflowRun.created_at)),
        ).all(),
    )
    latest_wr: dict[uuid.UUID, WorkflowRun] = {}
    for w in wr_all:
        if w.parcel_id not in latest_wr:
            latest_wr[w.parcel_id] = w

    pid_strings = [str(pid) for pid in parcel_ids]
    pending_map: dict[str, int] = {}
    if pid_strings:
        pid_expr = ApprovalRequest.payload["parcel_id"].as_string()
        rows_pa = db.execute(
            select(pid_expr, func.count())
            .where(ApprovalRequest.status == "pending")
            .where(pid_expr.in_(pid_strings))
            .group_by(pid_expr),
        ).all()
        pending_map = {str(a): int(b) for a, b in rows_pa}

    out: list[OutreachPipelineRowData] = []
    for r in qrows:
        pid, apn, cfips, brief_json, ent_f, str_f, id_f = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        wr = latest_wr.get(pid)
        has_brief = bool(brief_json)
        tier = None
        if isinstance(brief_json, dict):
            raw_tier = brief_json.get("owner_research_tier")
            if isinstance(raw_tier, str):
                tier = raw_tier
        stage = _derive_pipeline_stage(wr)
        pcount = pending_map.get(str(pid), 0)
        out.append(
            OutreachPipelineRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                entitlement_score=float(ent_f) if ent_f is not None else None,
                strategic_score=float(str_f) if str_f is not None else None,
                identification_score=float(id_f) if id_f is not None else None,
                workflow_run_id=wr.id if wr else None,
                workflow_status=wr.status if wr else None,
                workflow_step=wr.current_step if wr else None,
                workflow_error=wr.error if wr else None,
                workflow_updated_at=wr.updated_at if wr else None,
                has_outreach_brief=has_brief,
                pending_approval_count=pcount,
                pipeline_stage=stage,
                owner_research_tier=tier,
            ),
        )
    return out

"""Aggregated rows for operator outreach-pipeline view (qualified parcels + workflow + briefs)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, desc, inspect, literal, select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest, Parcel, ParcelScore, WorkflowRun
from app.geo_markets import priority_county_fips
from app.outreach_decisions import OWNER_CONTACT_PENDING
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION
from parking_workflows.state import WorkflowStatus


@dataclass(frozen=True)
class OutreachPipelineRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    entitlement_score: float | None
    identification_score: float | None
    workflow_run_id: uuid.UUID | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    has_outreach_brief: bool
    owner_contact_decision: str
    pending_approval_count: int
    pipeline_stage: str


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


def _parcels_have_outreach_brief_column(db: Session) -> bool:
    try:
        cols = inspect(db.get_bind()).get_columns("parcels")
    except Exception:
        return False
    return any(c.get("name") == "owner_outreach_brief" for c in cols)


def _parcels_have_owner_contact_decision_column(db: Session) -> bool:
    try:
        cols = inspect(db.get_bind()).get_columns("parcels")
    except Exception:
        return False
    return any(c.get("name") == "owner_contact_decision" for c in cols)


def _pending_approval_counts(db: Session, parcel_ids: list[uuid.UUID]) -> dict[str, int]:
    """Count pending approvals per parcel from JSON payload (no JSONB ->> SQL)."""
    if not parcel_ids:
        return {}
    want = {str(pid) for pid in parcel_ids}
    counts = {pid: 0 for pid in want}
    pending = db.scalars(select(ApprovalRequest).where(ApprovalRequest.status == "pending")).all()
    for row in pending:
        payload = row.payload if isinstance(row.payload, dict) else {}
        raw = payload.get("parcel_id")
        if raw is None:
            continue
        key = str(raw)
        if key in want:
            counts[key] = counts.get(key, 0) + 1
    return counts


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
    limit: int,
    county_fips: str | None = None,
    state_fips: str | None = None,
) -> list[OutreachPipelineRowData]:
    """Parcels whose latest **entitlement** score meets the pilot floor, with latest workflow + counts."""
    cap = min(max(limit, 1), 2000)
    cf = (county_fips or "").strip()
    st = (state_fips or "").strip()
    pri = priority_county_fips()
    ent_sub = _latest_score_subq(Parcel.id, ENTITLEMENT)
    id_sub = _latest_score_subq(Parcel.id, IDENTIFICATION)
    has_brief_col = _parcels_have_outreach_brief_column(db)
    brief_col = Parcel.owner_outreach_brief if has_brief_col else literal(None).label("owner_outreach_brief")
    has_decision_col = _parcels_have_owner_contact_decision_column(db)
    decision_col = (
        Parcel.owner_contact_decision
        if has_decision_col
        else literal(OWNER_CONTACT_PENDING).label("owner_contact_decision")
    )

    stmt = select(
        Parcel.id,
        Parcel.apn,
        Parcel.county_fips,
        brief_col,
        decision_col,
        ent_sub.label("ent_score"),
        id_sub.label("id_score"),
    ).where(ent_sub >= qualified_min_entitlement)
    if cf:
        stmt = stmt.where(Parcel.county_fips == cf)
    elif st:
        stmt = stmt.where(Parcel.county_fips.startswith(st))
    order_cols = [desc(ent_sub), desc(Parcel.created_at)]
    if pri:
        geo_first = case((Parcel.county_fips.in_(pri), 0), else_=1)
        order_cols = [geo_first, *order_cols]
    stmt = stmt.order_by(*order_cols).limit(cap)
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

    pending_map = _pending_approval_counts(db, parcel_ids)

    out: list[OutreachPipelineRowData] = []
    for r in qrows:
        pid, apn, cfips, brief_json, decision, ent_f, id_f = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        wr = latest_wr.get(pid)
        has_brief = bool(brief_json) if has_brief_col else False
        stage = _derive_pipeline_stage(wr)
        pcount = pending_map.get(str(pid), 0)
        out.append(
            OutreachPipelineRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                entitlement_score=float(ent_f) if ent_f is not None else None,
                identification_score=float(id_f) if id_f is not None else None,
                workflow_run_id=wr.id if wr else None,
                workflow_status=wr.status if wr else None,
                workflow_step=wr.current_step if wr else None,
                workflow_error=wr.error if wr else None,
                workflow_updated_at=wr.updated_at if wr else None,
                has_outreach_brief=has_brief,
                owner_contact_decision=decision or OWNER_CONTACT_PENDING,
                pending_approval_count=pcount,
                pipeline_stage=stage,
            ),
        )
    return out

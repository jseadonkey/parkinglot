"""Operator deal-progress board — one row per parcel with human-friendly deal stage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest, Parcel, ParcelScore, WorkflowRun
from app.outreach_board import _latest_score_subq
from app.pilot_scope_filter import parcel_in_scope_clause
from app.pipeline_gates import parcel_qualifies_for_human_gate
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from parking_workflows.state import WorkflowStatus

DEAL_STAGES: tuple[str, ...] = (
    "in_queue",
    "scoring",
    "needs_review",
    "approved_ready",
    "screened_out",
    "failed",
    "no_run",
)

_STAGE_SORT: dict[str, int] = {s: i for i, s in enumerate(DEAL_STAGES)}


@dataclass(frozen=True)
class DealProgressRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    deal_stage: str
    deal_stage_label: str
    workflow_run_id: uuid.UUID | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    owner_research_tier: str | None
    pending_approval_count: int
    has_approved_memo: bool
    has_approved_contract: bool


DEAL_STAGE_LABELS: dict[str, str] = {
    "in_queue": "In queue",
    "scoring": "Scoring / enriching",
    "needs_review": "Qualified — needs your review",
    "approved_ready": "Approved — ready for outreach",
    "screened_out": "Screened out (below score floor)",
    "failed": "Failed — needs fix",
    "no_run": "No pipeline run yet",
}


def derive_deal_stage(
    *,
    workflow: WorkflowRun | None,
    entitlement_score: float | None,
    strategic_score: float | None,
    min_entitlement: float,
    min_strategic: float,
    pending_approval_count: int,
    has_approved_memo: bool,
    has_approved_contract: bool,
) -> str:
    if workflow is None:
        return "no_run"
    st = workflow.status
    if st == WorkflowStatus.failed.value:
        return "failed"
    if st == WorkflowStatus.pending.value:
        return "in_queue"
    if st == WorkflowStatus.running.value:
        return "scoring"

    dual = False
    if entitlement_score is not None and strategic_score is not None:
        dual = parcel_qualifies_for_human_gate(
            entitlement_score,
            strategic_score,
            min_entitlement=min_entitlement,
            min_strategic=min_strategic,
        )

    if dual:
        if pending_approval_count > 0:
            return "needs_review"
        if has_approved_memo and has_approved_contract:
            return "approved_ready"
        if st == WorkflowStatus.blocked.value and pending_approval_count == 0:
            return "approved_ready"
        return "needs_review"

    if st == WorkflowStatus.completed.value:
        return "screened_out"
    if st == WorkflowStatus.blocked.value:
        return "approved_ready" if pending_approval_count == 0 else "needs_review"
    return "screened_out"


def _approval_maps(
    db: Session,
    parcel_ids: list[uuid.UUID],
) -> tuple[dict[str, int], dict[str, bool], dict[str, bool]]:
    pending: dict[str, int] = {}
    memo_ok: dict[str, bool] = {}
    contract_ok: dict[str, bool] = {}
    if not parcel_ids:
        return pending, memo_ok, contract_ok
    pid_strings = [str(p) for p in parcel_ids]
    pid_expr = ApprovalRequest.payload["parcel_id"].as_string()
    rows = db.execute(
        select(
            pid_expr,
            ApprovalRequest.type,
            ApprovalRequest.status,
        ).where(pid_expr.in_(pid_strings)),
    ).all()
    for pid, atype, status in rows:
        key = str(pid)
        if status == "pending":
            pending[key] = pending.get(key, 0) + 1
        if atype == "deal_memo_publish" and status == "approved":
            memo_ok[key] = True
        if atype == "contract_send" and status == "approved":
            contract_ok[key] = True
    return pending, memo_ok, contract_ok


def query_deal_progress_board(
    db: Session,
    *,
    qualified_min_entitlement: float,
    qualified_min_strategic: float,
    limit: int,
    stage: str | None = None,
) -> tuple[dict[str, int], list[DealProgressRowData]]:
    """Latest workflow run per in-scope parcel → operator deal stage."""
    cap = min(max(limit, 1), 2000)
    stage_filter = (stage or "").strip().lower()
    if stage_filter and stage_filter not in DEAL_STAGES:
        stage_filter = ""

    wr_all = list(
        db.scalars(
            select(WorkflowRun)
            .join(Parcel, WorkflowRun.parcel_id == Parcel.id)
            .where(parcel_in_scope_clause())
            .order_by(WorkflowRun.parcel_id, desc(WorkflowRun.created_at)),
        ).all(),
    )
    latest_wr: dict[uuid.UUID, WorkflowRun] = {}
    for w in wr_all:
        if w.parcel_id not in latest_wr:
            latest_wr[w.parcel_id] = w

    parcel_ids = list(latest_wr.keys())
    if not parcel_ids:
        return {s: 0 for s in DEAL_STAGES}, []

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
        .where(Parcel.id.in_(parcel_ids))
        .order_by(desc(Parcel.created_at))
    )
    parcel_rows = list(db.execute(stmt).all())
    pending_map, memo_map, contract_map = _approval_maps(db, parcel_ids)

    all_rows: list[DealProgressRowData] = []
    stage_counts: dict[str, int] = {s: 0 for s in DEAL_STAGES}

    for r in parcel_rows:
        pid, apn, cfips, brief_json, ent_f, str_f, id_f = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        wr = latest_wr.get(pid)
        pid_s = str(pid)
        pending = pending_map.get(pid_s, 0)
        has_memo = memo_map.get(pid_s, False)
        has_contract = contract_map.get(pid_s, False)
        ent = float(ent_f) if ent_f is not None else None
        stg = float(str_f) if str_f is not None else None
        deal_stage = derive_deal_stage(
            workflow=wr,
            entitlement_score=ent,
            strategic_score=stg,
            min_entitlement=qualified_min_entitlement,
            min_strategic=qualified_min_strategic,
            pending_approval_count=pending,
            has_approved_memo=has_memo,
            has_approved_contract=has_contract,
        )
        stage_counts[deal_stage] = stage_counts.get(deal_stage, 0) + 1

        tier = None
        if isinstance(brief_json, dict):
            raw_tier = brief_json.get("owner_research_tier")
            if isinstance(raw_tier, str):
                tier = raw_tier

        all_rows.append(
            DealProgressRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                entitlement_score=ent,
                strategic_score=stg,
                identification_score=float(id_f) if id_f is not None else None,
                deal_stage=deal_stage,
                deal_stage_label=DEAL_STAGE_LABELS.get(deal_stage, deal_stage),
                workflow_run_id=wr.id if wr else None,
                workflow_status=wr.status if wr else None,
                workflow_step=wr.current_step if wr else None,
                workflow_error=wr.error if wr else None,
                workflow_updated_at=wr.updated_at if wr else None,
                owner_research_tier=tier,
                pending_approval_count=pending,
                has_approved_memo=has_memo,
                has_approved_contract=has_contract,
            ),
        )

    all_rows.sort(
        key=lambda row: (
            _STAGE_SORT.get(row.deal_stage, 99),
            -(row.workflow_updated_at.timestamp() if row.workflow_updated_at else 0),
        ),
    )

    if stage_filter:
        filtered = [row for row in all_rows if row.deal_stage == stage_filter]
    else:
        filtered = all_rows

    return stage_counts, filtered[:cap]

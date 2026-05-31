"""Deal progress stage derivation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.deal_progress_board import derive_deal_stage
from app.db.models import WorkflowRun
from parking_workflows.state import WorkflowStatus, WorkflowStep


def _wr(status: str, step: str = "enrich") -> WorkflowRun:
    return WorkflowRun(
        id=uuid.uuid4(),
        parcel_id=uuid.uuid4(),
        status=status,
        current_step=step,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_screened_out_when_completed_below_floor() -> None:
    stage = derive_deal_stage(
        workflow=_wr(WorkflowStatus.completed.value),
        entitlement_score=40.0,
        strategic_score=30.0,
        min_entitlement=55.0,
        min_strategic=52.0,
        pending_approval_count=0,
        has_approved_memo=False,
        has_approved_contract=False,
    )
    assert stage == "screened_out"


def test_needs_review_when_dual_qualified_with_pending() -> None:
    stage = derive_deal_stage(
        workflow=_wr(WorkflowStatus.blocked.value, WorkflowStep.awaiting_human.value),
        entitlement_score=60.0,
        strategic_score=55.0,
        min_entitlement=55.0,
        min_strategic=52.0,
        pending_approval_count=2,
        has_approved_memo=False,
        has_approved_contract=False,
    )
    assert stage == "needs_review"


def test_approved_ready_when_dual_qualified_approvals_done() -> None:
    stage = derive_deal_stage(
        workflow=_wr(WorkflowStatus.blocked.value, WorkflowStep.awaiting_human.value),
        entitlement_score=60.0,
        strategic_score=55.0,
        min_entitlement=55.0,
        min_strategic=52.0,
        pending_approval_count=0,
        has_approved_memo=True,
        has_approved_contract=True,
    )
    assert stage == "approved_ready"


def test_failed_status() -> None:
    stage = derive_deal_stage(
        workflow=_wr(WorkflowStatus.failed.value),
        entitlement_score=None,
        strategic_score=None,
        min_entitlement=55.0,
        min_strategic=52.0,
        pending_approval_count=0,
        has_approved_memo=False,
        has_approved_contract=False,
    )
    assert stage == "failed"

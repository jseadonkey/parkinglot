from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.models import ApprovalRequest
from app.db.session import get_db
from app.schemas import ApprovalDecision, ApprovalRead

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRead])
def list_approvals(status: str | None = None, db: Session = Depends(get_db)) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest)
    if status is not None:
        stmt = stmt.where(ApprovalRequest.status == status)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(200)
    return list(db.scalars(stmt))


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
def approve_request(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    db: Session = Depends(get_db),
) -> ApprovalRequest:
    row = db.get(ApprovalRequest, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="approval is not pending")
    row.status = "approved"
    row.approved_by = body.approved_by
    row.approved_at = datetime.now(tz=UTC)
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor=body.approved_by,
        action="approval_granted",
        entity_type="approval_request",
        entity_id=str(row.id),
        meta={"type": row.type, "note": body.note},
    )
    return row


@router.post("/{approval_id}/reject", response_model=ApprovalRead)
def reject_request(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    db: Session = Depends(get_db),
) -> ApprovalRequest:
    row = db.get(ApprovalRequest, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="approval is not pending")
    row.status = "rejected"
    row.approved_by = body.approved_by
    row.approved_at = datetime.now(tz=UTC)
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor=body.approved_by,
        action="approval_rejected",
        entity_type="approval_request",
        entity_id=str(row.id),
        meta={"type": row.type, "note": body.note},
    )
    return row

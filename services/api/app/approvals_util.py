from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.models import ApprovalRequest


def _pending_for_parcel(
    db: Session,
    *,
    approval_type: str,
    parcel_id: str,
    payload_match: dict[str, str] | None = None,
) -> ApprovalRequest | None:
    rows = db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.type == approval_type,
            ApprovalRequest.status == "pending",
        )
        .order_by(ApprovalRequest.created_at.desc())
    ).all()
    for row in rows:
        payload = row.payload or {}
        if str(payload.get("parcel_id")) != parcel_id:
            continue
        if payload_match is not None:
            if not all(str(payload.get(k)) == v for k, v in payload_match.items()):
                continue
        return row
    return None


def pending_approval_for(
    db: Session,
    *,
    approval_type: str,
    parcel_id: str,
    payload_match: dict[str, str] | None = None,
) -> ApprovalRequest | None:
    return _pending_for_parcel(
        db,
        approval_type=approval_type,
        parcel_id=parcel_id,
        payload_match=payload_match,
    )


def queue_approval(
    db: Session,
    *,
    approval_type: str,
    payload: dict,
    auto_approve_types: frozenset[str] | None = None,
    actor: str = "system",
    payload_match: dict[str, str] | None = None,
) -> ApprovalRequest | None:
    """Create a pending approval, or skip if one already exists for this parcel+type.

    When ``approval_type`` is in ``auto_approve_types``, the row is stored as approved
    immediately (pilot convenience for internal deal memos only).

    ``payload_match`` requires extra payload keys to match (e.g. outreach channel).
    """
    parcel_id = str(payload.get("parcel_id") or "")
    if not parcel_id:
        raise ValueError("approval payload must include parcel_id")

    existing = _pending_for_parcel(
        db,
        approval_type=approval_type,
        parcel_id=parcel_id,
        payload_match=payload_match,
    )
    if existing is not None:
        return None

    now = datetime.now(tz=UTC)
    auto = auto_approve_types is not None and approval_type in auto_approve_types
    row = ApprovalRequest(
        id=uuid.uuid4(),
        type=approval_type,
        status="approved" if auto else "pending",
        payload=payload,
        approved_by=actor if auto else None,
        approved_at=now if auto else None,
    )
    db.add(row)
    if auto:
        write_audit(
            db,
            actor=actor,
            action="approval_granted",
            entity_type="approval_request",
            entity_id=str(row.id),
            meta={"type": approval_type, "note": "auto-approved (pilot config)"},
        )
    return row

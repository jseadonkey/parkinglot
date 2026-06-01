from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.approvals_util import pending_approval_for, queue_approval
from app.audit import write_audit
from app.db.models import Parcel, ParcelContactPoint
from app.db.schema_compat import table_exists
from app.db.session import get_db
from app.outreach_contacts import (
    find_contact_point,
    load_outreach_attempts,
    load_persisted_contact_points,
    merge_brief_with_persisted_contacts,
    normalize_contact_value,
    record_outreach_attempt,
)
from app.outreach_templates import PARCEL_DRAFT_CHANNELS, build_parcel_outreach_drafts
from app.schemas import (
    ApprovalRead,
    OutreachApprovalRequest,
    OutreachAttemptCreate,
    OutreachAttemptRead,
    OwnerContactPointCreate,
    OwnerContactPointRead,
    ParcelOutreachDraftRead,
    ParcelOutreachRead,
)
from parking_core.models import ApprovalType, ContactKind, OwnerOutreachBrief

router = APIRouter(prefix="/parcels", tags=["outreach"])

_VALID_DRAFT_CHANNELS = frozenset(ch for ch, _ in PARCEL_DRAFT_CHANNELS)


def _require_templates_table(db: Session) -> None:
    if not table_exists(db, "outreach_templates"):
        raise HTTPException(
            status_code=503,
            detail="outreach_templates table missing — restart the API container so migrations can run",
        )


def _require_brief(parcel: Parcel) -> OwnerOutreachBrief:
    if not parcel.owner_outreach_brief:
        raise HTTPException(status_code=404, detail="outreach brief not found; run pipeline first")
    return OwnerOutreachBrief.model_validate(parcel.owner_outreach_brief)


@router.get("/{parcel_id}/outreach", response_model=ParcelOutreachRead)
def get_parcel_outreach(parcel_id: uuid.UUID, db: Session = Depends(get_db)) -> ParcelOutreachRead:
    parcel = db.get(Parcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    brief = _require_brief(parcel)
    persisted = load_persisted_contact_points(db, parcel_id)
    merged = merge_brief_with_persisted_contacts(brief, persisted)
    attempts = load_outreach_attempts(db, parcel_id)
    return ParcelOutreachRead(
        brief=merged.model_dump(mode="json"),
        contact_points=[OwnerContactPointRead.model_validate(row) for row in persisted],
        attempts=[OutreachAttemptRead.model_validate(row) for row in attempts],
    )


@router.get("/{parcel_id}/outreach/drafts", response_model=list[ParcelOutreachDraftRead])
def get_parcel_outreach_drafts(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[ParcelOutreachDraftRead]:
    _require_templates_table(db)
    parcel = db.get(Parcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    brief = _require_brief(parcel)
    persisted = load_persisted_contact_points(db, parcel_id)
    merged = merge_brief_with_persisted_contacts(brief, persisted)
    raw = build_parcel_outreach_drafts(db, parcel=parcel, brief=merged)
    return [ParcelOutreachDraftRead.model_validate(d) for d in raw]


@router.post(
    "/{parcel_id}/outreach/drafts/{channel}/request-approval",
    response_model=ApprovalRead,
)
def request_outreach_draft_approval(
    parcel_id: uuid.UUID,
    channel: str,
    body: OutreachApprovalRequest,
    db: Session = Depends(get_db),
) -> ApprovalRead:
    _require_templates_table(db)
    if channel not in _VALID_DRAFT_CHANNELS:
        raise HTTPException(status_code=400, detail=f"invalid channel: {channel}")

    parcel = db.get(Parcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    brief = _require_brief(parcel)
    persisted = load_persisted_contact_points(db, parcel_id)
    merged = merge_brief_with_persisted_contacts(brief, persisted)
    drafts = build_parcel_outreach_drafts(db, parcel=parcel, brief=merged)
    draft = next((d for d in drafts if d["channel"] == channel), None)
    if draft is None:
        raise HTTPException(status_code=404, detail="template not found for channel")
    if not draft.get("has_recipient"):
        raise HTTPException(
            status_code=400,
            detail=f"no recipient on file for {channel} — add contact info before requesting approval",
        )

    payload = {
        "parcel_id": str(parcel_id),
        "apn": parcel.apn,
        "county_fips": parcel.county_fips,
        "channel": channel,
        "template_slug": draft["template_slug"],
        "subject": draft.get("subject"),
        "body": draft["body"],
        "to_name": draft.get("to_name"),
        "to_email": draft.get("to_email"),
        "to_phone": draft.get("to_phone"),
        "to_mailing_address": draft.get("to_mailing_address"),
        "from_name": draft["from_name"],
        "from_company": draft.get("from_company"),
        "from_email": draft.get("from_email"),
        "from_phone": draft.get("from_phone"),
        "requested_by": body.requested_by,
    }

    existing = pending_approval_for(
        db,
        approval_type=ApprovalType.outbound_message.value,
        parcel_id=str(parcel_id),
        payload_match={"channel": channel},
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"pending outbound_message approval already exists for this parcel and channel ({existing.id})",
        )

    row = queue_approval(
        db,
        approval_type=ApprovalType.outbound_message.value,
        payload=payload,
        payload_match={"channel": channel},
    )
    if row is None:
        raise HTTPException(status_code=500, detail="failed to queue approval")
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor=body.requested_by,
        action="outreach_approval_requested",
        entity_type="approval_request",
        entity_id=str(row.id),
        meta={"parcel_id": str(parcel_id), "channel": channel, "apn": parcel.apn},
    )
    return ApprovalRead.model_validate(row)


@router.get("/{parcel_id}/outreach/attempts", response_model=list[OutreachAttemptRead])
def list_outreach_attempts(
    parcel_id: uuid.UUID,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[OutreachAttemptRead]:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    rows = load_outreach_attempts(db, parcel_id, limit=limit)
    return [OutreachAttemptRead.model_validate(row) for row in rows]


@router.post("/{parcel_id}/outreach/attempts", response_model=OutreachAttemptRead)
def create_outreach_attempt(
    parcel_id: uuid.UUID,
    body: OutreachAttemptCreate,
    db: Session = Depends(get_db),
) -> OutreachAttemptRead:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    try:
        target_kind = ContactKind(body.target_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid target_kind: {body.target_kind}") from exc
    contact_point_id = body.contact_point_id
    if contact_point_id is not None:
        row = db.get(ParcelContactPoint, contact_point_id)
        if row is None or row.parcel_id != parcel_id:
            raise HTTPException(status_code=400, detail="contact_point_id not found for parcel")
    attempt = record_outreach_attempt(
        db,
        parcel_id=parcel_id,
        channel=body.channel,
        target_kind=target_kind,
        target_value=body.target_value,
        attempted_by=body.attempted_by,
        result=body.result,
        result_detail=body.result_detail,
        contact_point_id=contact_point_id,
        approval_request_id=body.approval_request_id,
    )
    db.commit()
    db.refresh(attempt)
    write_audit(
        db,
        actor=body.attempted_by,
        action="outreach_attempt_recorded",
        entity_type="outreach_attempt",
        entity_id=str(attempt.id),
        meta={
            "parcel_id": str(parcel_id),
            "channel": body.channel,
            "target_kind": target_kind.value,
            "target_value": body.target_value,
            "result": body.result,
        },
    )
    return OutreachAttemptRead.model_validate(attempt)


@router.post("/{parcel_id}/outreach/contacts", response_model=OwnerContactPointRead)
def add_contact_point(
    parcel_id: uuid.UUID,
    body: OwnerContactPointCreate,
    db: Session = Depends(get_db),
) -> OwnerContactPointRead:
    if db.get(Parcel, parcel_id) is None:
        raise HTTPException(status_code=404, detail="parcel not found")
    try:
        kind = ContactKind(body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid kind: {body.kind}") from exc
    norm = normalize_contact_value(kind, body.value)
    existing = find_contact_point(db, parcel_id=parcel_id, kind=kind, value=body.value)
    if existing is not None:
        raise HTTPException(status_code=409, detail="contact already exists for parcel")
    row = ParcelContactPoint(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        kind=kind.value,
        value=body.value.strip(),
        normalized_value=norm,
        source=body.source,
        label=body.label,
        confidence=float(body.confidence),
        updated_at=datetime.now(tz=UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return OwnerContactPointRead.model_validate(row)

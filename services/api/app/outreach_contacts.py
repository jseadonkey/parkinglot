from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import OutreachAttemptRow, ParcelContactPoint
from parking_core.models import ContactKind, OwnerContactPoint, OwnerOutreachBrief

_AUTO_REFRESH_SOURCES = frozenset({"assessor_roll", "vendor", "sos"})


def normalize_contact_value(kind: ContactKind | str, value: str) -> str:
    k = kind.value if isinstance(kind, ContactKind) else str(kind)
    text = value.strip()
    if k == ContactKind.email.value:
        return text.casefold()
    if k == ContactKind.phone.value:
        digits = re.sub(r"\D", "", text)
        return digits[-10:] if len(digits) >= 10 else digits
    return re.sub(r"\s+", " ", text).casefold()


def sync_contact_points_from_brief(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    brief: OwnerOutreachBrief,
) -> list[ParcelContactPoint]:
    """Replace auto-sourced contacts from the brief; preserve manually added contacts."""
    db.execute(
        delete(ParcelContactPoint).where(
            ParcelContactPoint.parcel_id == parcel_id,
            ParcelContactPoint.source.in_(_AUTO_REFRESH_SOURCES),
        )
    )
    rows: list[ParcelContactPoint] = []
    for point in brief.contact_points:
        row = ParcelContactPoint(
            id=uuid.uuid4(),
            parcel_id=parcel_id,
            kind=point.kind.value,
            value=point.value.strip(),
            normalized_value=normalize_contact_value(point.kind, point.value),
            source=point.source,
            label=point.label,
            confidence=float(point.confidence),
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def load_persisted_contact_points(db: Session, parcel_id: uuid.UUID) -> list[ParcelContactPoint]:
    from app.db.schema_compat import table_exists

    if not table_exists(db, "parcel_contact_points"):
        return []
    stmt = (
        select(ParcelContactPoint)
        .where(ParcelContactPoint.parcel_id == parcel_id)
        .order_by(ParcelContactPoint.kind, ParcelContactPoint.created_at)
    )
    return list(db.scalars(stmt))


def load_outreach_attempts(db: Session, parcel_id: uuid.UUID, *, limit: int = 200) -> list[OutreachAttemptRow]:
    from app.db.schema_compat import table_exists

    if not table_exists(db, "outreach_attempts"):
        return []
    cap = min(max(limit, 1), 500)
    stmt = (
        select(OutreachAttemptRow)
        .where(OutreachAttemptRow.parcel_id == parcel_id)
        .order_by(desc(OutreachAttemptRow.attempted_at))
        .limit(cap)
    )
    return list(db.scalars(stmt))


def find_contact_point(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    kind: ContactKind,
    value: str,
) -> ParcelContactPoint | None:
    norm = normalize_contact_value(kind, value)
    stmt = (
        select(ParcelContactPoint)
        .where(
            ParcelContactPoint.parcel_id == parcel_id,
            ParcelContactPoint.kind == kind.value,
            ParcelContactPoint.normalized_value == norm,
        )
        .limit(1)
    )
    return db.scalars(stmt).first()


def contact_point_to_model(row: ParcelContactPoint) -> OwnerContactPoint:
    return OwnerContactPoint(
        id=str(row.id),
        kind=ContactKind(row.kind),
        value=row.value,
        source=row.source,
        label=row.label,
        confidence=float(row.confidence),
    )


def merge_brief_with_persisted_contacts(
    brief: OwnerOutreachBrief,
    persisted: list[ParcelContactPoint],
) -> OwnerOutreachBrief:
    if not persisted:
        return brief
    merged = brief.model_copy(
        update={
            "contact_points": [contact_point_to_model(row) for row in persisted],
            "mailing_address_guess": next(
                (row.value for row in persisted if row.kind == ContactKind.mailing_address.value),
                brief.mailing_address_guess,
            ),
            "situs_address_guess": next(
                (row.value for row in persisted if row.kind == ContactKind.situs_address.value),
                brief.situs_address_guess,
            ),
            "phone_guess": next(
                (row.value for row in persisted if row.kind == ContactKind.phone.value),
                brief.phone_guess,
            ),
            "email_guess": next(
                (row.value for row in persisted if row.kind == ContactKind.email.value),
                brief.email_guess,
            ),
        }
    )
    return merged


def record_outreach_attempt(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    channel: str,
    target_kind: ContactKind,
    target_value: str,
    attempted_by: str,
    result: str = "attempted",
    result_detail: str | None = None,
    contact_point_id: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    attempted_at: datetime | None = None,
    meta: dict | None = None,
) -> OutreachAttemptRow:
    contact_id = contact_point_id
    if contact_id is None:
        match = find_contact_point(db, parcel_id=parcel_id, kind=target_kind, value=target_value)
        if match is not None:
            contact_id = match.id
    row = OutreachAttemptRow(
        id=uuid.uuid4(),
        parcel_id=parcel_id,
        contact_point_id=contact_id,
        channel=channel,
        target_kind=target_kind.value,
        target_value=target_value.strip(),
        result=result,
        result_detail=result_detail,
        attempted_by=attempted_by,
        attempted_at=attempted_at or datetime.now(tz=UTC),
        approval_request_id=approval_request_id,
        meta=meta,
    )
    db.add(row)
    db.flush()
    return row

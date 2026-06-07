from __future__ import annotations

from fastapi import HTTPException

OWNER_CONTACT_PENDING = "pending"
OWNER_CONTACT_APPROVED = "approved"
OWNER_CONTACT_REJECTED = "rejected"
OWNER_CONTACT_DECISIONS = frozenset(
    {
        OWNER_CONTACT_PENDING,
        OWNER_CONTACT_APPROVED,
        OWNER_CONTACT_REJECTED,
    },
)


def owner_contact_decision(parcel: object) -> str:
    raw = getattr(parcel, "owner_contact_decision", None)
    if raw in OWNER_CONTACT_DECISIONS:
        return raw
    return OWNER_CONTACT_PENDING


def owner_contact_approved(parcel: object) -> bool:
    return owner_contact_decision(parcel) == OWNER_CONTACT_APPROVED


def require_owner_contact_approved(parcel: object) -> None:
    decision = owner_contact_decision(parcel)
    if decision == OWNER_CONTACT_APPROVED:
        return
    if decision == OWNER_CONTACT_REJECTED:
        detail = "owner contact was rejected by human review; message drafts are blocked"
    else:
        detail = "human review must approve owner contact before message drafts are generated"
    raise HTTPException(status_code=403, detail=detail)

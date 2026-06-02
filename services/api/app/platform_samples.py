"""Sample deal outputs for partner platform page (PII redacted)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import ContractDraft, DealMemo, Parcel
from app.db.schema_compat import parcel_load_only
from app.outreach_templates import build_parcel_outreach_drafts
from app.partner_redact import excerpt_markdown, redact_partner_text
from app.storage import get_text_object
from parking_core.models import OwnerOutreachBrief


def _brief_from_parcel(parcel: Parcel) -> OwnerOutreachBrief | None:
    raw = parcel.owner_outreach_brief
    if not raw:
        return None
    try:
        return OwnerOutreachBrief.model_validate(raw)
    except Exception:
        return None


def _sample_memo(db: Session) -> dict[str, Any] | None:
    memo = db.scalars(select(DealMemo).order_by(desc(DealMemo.created_at)).limit(1)).first()
    if memo is None:
        return None
    parcel = db.get(Parcel, memo.parcel_id)
    apn = parcel.apn if parcel else "—"
    body = excerpt_markdown(redact_partner_text(memo.body_md))
    return {
        "kind": "deal_memo",
        "title": memo.title,
        "excerpt": body,
        "parcel_apn": apn,
        "redacted": True,
    }


def _sample_contract(db: Session) -> dict[str, Any] | None:
    draft = db.scalars(select(ContractDraft).order_by(desc(ContractDraft.created_at)).limit(1)).first()
    if draft is None:
        return None
    parcel = db.get(Parcel, draft.parcel_id)
    if parcel is None:
        return None
    body = ""
    try:
        body = get_text_object(draft.s3_key)
    except Exception:
        from app.contract_render import render_ground_lease_draft

        owner = "Property Owner"
        brief = _brief_from_parcel(parcel)
        if brief and brief.recorded_owner_one_liner:
            owner = brief.recorded_owner_one_liner.split("—")[0].strip()[:80]
        body = render_ground_lease_draft(
            apn=parcel.apn,
            county_fips=parcel.county_fips,
            owner_name=owner,
            lot_sqft=parcel.lot_sqft,
        )
    body = excerpt_markdown(redact_partner_text(body), max_chars=2000)
    return {
        "kind": "contract_draft",
        "title": f"Ground lease draft — {parcel.apn}",
        "excerpt": body,
        "parcel_apn": parcel.apn,
        "redacted": True,
    }


def _sample_outreach(db: Session) -> dict[str, Any] | None:
    parcel = db.scalars(
        select(Parcel)
        .options(parcel_load_only(db))
        .where(Parcel.owner_outreach_brief.isnot(None))
        .order_by(desc(Parcel.created_at))
        .limit(1),
    ).first()
    if parcel is None:
        return None
    brief = _brief_from_parcel(parcel)
    if brief is None:
        return None
    try:
        drafts = build_parcel_outreach_drafts(db, parcel=parcel, brief=brief)
    except Exception:
        return None
    email = next((d for d in drafts if d.get("channel") == "email"), drafts[0] if drafts else None)
    if email is None:
        return None
    subject = redact_partner_text(str(email.get("subject") or "Outreach email"))
    body = excerpt_markdown(redact_partner_text(str(email.get("body") or "")), max_chars=1200)
    return {
        "kind": "outreach_email",
        "title": f"Email outreach — {parcel.apn}",
        "excerpt": f"**Subject:** {subject}\n\n{body}",
        "parcel_apn": parcel.apn,
        "redacted": True,
    }


def build_platform_sample_deliverables(db: Session) -> list[dict[str, Any]]:
    """Up to three redacted excerpts from real pipeline output."""
    out: list[dict[str, Any]] = []
    for builder in (_sample_memo, _sample_contract, _sample_outreach):
        sample = builder(db)
        if sample is not None:
            out.append(sample)
    return out

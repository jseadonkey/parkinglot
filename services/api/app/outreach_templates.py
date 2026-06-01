from __future__ import annotations

from typing import Any

from jinja2 import BaseLoader, Environment, Undefined
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import OutreachTemplate, Parcel
from parking_core.models import OUTREACH_TEMPLATE_PLACEHOLDERS, OutreachTemplateSlug, OwnerOutreachBrief
from parking_core.pilot import load_pilot_config

# Display order for parcel outreach drafts (channel → stored template slug).
PARCEL_DRAFT_CHANNELS: list[tuple[str, OutreachTemplateSlug]] = [
    ("email", OutreachTemplateSlug.email_outreach),
    ("sms", OutreachTemplateSlug.sms_outreach),
    ("phone", OutreachTemplateSlug.phone_call_script),
    ("certified_mail", OutreachTemplateSlug.certified_mail_letter),
]


class _SilentUndefined(Undefined):
    def __str__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False


def _jinja_env() -> Environment:
    return Environment(
        loader=BaseLoader(),
        undefined=_SilentUndefined,
        autoescape=False,
    )


def sender_defaults() -> dict[str, str]:
    s = get_settings()
    return {
        "sender_name": (s.outreach_sender_name or "Your Name").strip(),
        "sender_company": (s.outreach_sender_company or "Your Company").strip(),
        "sender_email": (s.outreach_sender_email or "contact@example.com").strip(),
        "sender_phone": (s.outreach_sender_phone or "(555) 555-0100").strip(),
    }


def sample_render_context() -> dict[str, Any]:
    pilot = load_pilot_config(get_settings().pilot_config_path)
    return {
        "owner_name": "Jane Doe / Example Holdings LLC",
        "mailing_address": "100 Main St, Seattle, WA 98101",
        "situs_address": "102 Main St, Seattle, WA 98101",
        "apn": "123456-7890",
        "county_fips": "53033",
        "lot_sqft": 12500,
        "region_name": pilot.region.name,
        **sender_defaults(),
    }


def parcel_render_context(parcel: Parcel, brief: OwnerOutreachBrief) -> dict[str, Any]:
    pilot = load_pilot_config(get_settings().pilot_config_path)
    return {
        "owner_name": brief.recorded_owner_one_liner or "",
        "mailing_address": brief.mailing_address_guess or "",
        "situs_address": brief.situs_address_guess or "",
        "apn": parcel.apn,
        "county_fips": parcel.county_fips,
        "lot_sqft": parcel.lot_sqft or "",
        "region_name": pilot.region.name,
        **sender_defaults(),
    }


def list_templates(db: Session) -> list[OutreachTemplate]:
    stmt = select(OutreachTemplate).order_by(OutreachTemplate.slug)
    return list(db.scalars(stmt))


def get_template(db: Session, slug: str) -> OutreachTemplate | None:
    return db.get(OutreachTemplate, slug)


def render_template_text(
    template_body: str,
    *,
    subject: str | None = None,
    context: dict[str, Any] | None = None,
    use_sample_fill: bool = True,
) -> tuple[str, str | None]:
    """Render Jinja2 body (and optional subject). Raises TemplateSyntaxError on bad syntax."""
    if use_sample_fill:
        ctx = {**sample_render_context(), **(context or {})}
    else:
        ctx = {**sender_defaults(), **(context or {})}
    env = _jinja_env()
    rendered_body = env.from_string(template_body).render(**ctx)
    rendered_subject = env.from_string(subject).render(**ctx) if subject else None
    return rendered_body, rendered_subject


def render_stored_template(
    row: OutreachTemplate,
    *,
    context: dict[str, Any] | None = None,
    use_sample_fill: bool = True,
) -> tuple[str, str | None]:
    return render_template_text(row.body, subject=row.subject, context=context, use_sample_fill=use_sample_fill)


def build_parcel_outreach_drafts(
    db: Session,
    *,
    parcel: Parcel,
    brief: OwnerOutreachBrief,
) -> list[dict[str, Any]]:
    """Render admin templates for a parcel using owner contact data from the brief."""
    ctx = parcel_render_context(parcel, brief)
    senders = sender_defaults()
    to_name = brief.recorded_owner_one_liner
    to_email = brief.email_guess
    to_phone = brief.phone_guess
    to_mail = brief.mailing_address_guess

    drafts: list[dict[str, Any]] = []
    for channel, slug in PARCEL_DRAFT_CHANNELS:
        row = get_template(db, slug.value)
        if row is None:
            continue
        body, subject = render_stored_template(row, context=ctx, use_sample_fill=False)
        has_recipient = {
            "email": bool(to_email),
            "sms": bool(to_phone),
            "phone": bool(to_phone),
            "certified_mail": bool(to_mail),
        }.get(channel, False)
        drafts.append(
            {
                "channel": channel,
                "template_slug": slug.value,
                "to_name": to_name,
                "to_email": to_email if channel == "email" else None,
                "to_phone": to_phone if channel in {"sms", "phone"} else None,
                "to_mailing_address": to_mail if channel == "certified_mail" else None,
                "from_name": senders["sender_name"],
                "from_company": senders["sender_company"],
                "from_email": senders["sender_email"],
                "from_phone": senders["sender_phone"],
                "subject": subject,
                "body": body,
                "has_recipient": has_recipient,
            }
        )
    return drafts


def validate_slug(slug: str) -> OutreachTemplateSlug:
    try:
        return OutreachTemplateSlug(slug)
    except ValueError as exc:
        msg = f"unknown template slug: {slug}"
        raise ValueError(msg) from exc


def placeholder_help() -> list[str]:
    return list(OUTREACH_TEMPLATE_PLACEHOLDERS)

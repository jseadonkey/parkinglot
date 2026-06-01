from __future__ import annotations

from typing import Any

from jinja2 import BaseLoader, Environment, Undefined
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import OutreachTemplate
from parking_core.models import OUTREACH_TEMPLATE_PLACEHOLDERS, OutreachTemplateSlug
from parking_core.pilot import load_pilot_config


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
) -> tuple[str, str | None]:
    """Render Jinja2 body (and optional subject). Raises TemplateSyntaxError on bad syntax."""
    ctx = {**sample_render_context(), **(context or {})}
    env = _jinja_env()
    rendered_body = env.from_string(template_body).render(**ctx)
    rendered_subject = env.from_string(subject).render(**ctx) if subject else None
    return rendered_body, rendered_subject


def render_stored_template(
    row: OutreachTemplate,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    return render_template_text(row.body, subject=row.subject, context=context)


def validate_slug(slug: str) -> OutreachTemplateSlug:
    try:
        return OutreachTemplateSlug(slug)
    except ValueError as exc:
        msg = f"unknown template slug: {slug}"
        raise ValueError(msg) from exc


def placeholder_help() -> list[str]:
    return list(OUTREACH_TEMPLATE_PLACEHOLDERS)

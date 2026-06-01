from __future__ import annotations

from app.outreach_templates import render_template_text, sample_render_context, validate_slug
from parking_core.models import OutreachTemplateSlug


def test_validate_slug_includes_sms() -> None:
    assert validate_slug("sms_outreach") == OutreachTemplateSlug.sms_outreach


def test_render_template_fills_owner_and_address() -> None:
    body = "Dear {{ owner_name }},\n\nMail to {{ mailing_address }}.\nAPN {{ apn }}"
    rendered, _ = render_template_text(body)
    assert "Jane Doe" in rendered or "Example" in rendered
    assert "98101" in rendered
    assert "123456" in rendered


def test_render_template_subject_line() -> None:
    subject = "Interest — APN {{ apn }}"
    _, rendered_subject = render_template_text("Body", subject=subject, context=sample_render_context())
    assert rendered_subject is not None
    assert "123456" in rendered_subject


def test_render_template_or_fallback() -> None:
    body = "Site: {{ situs_address or mailing_address }}"
    rendered, _ = render_template_text(body, context={"situs_address": "", "mailing_address": "PO Box 1"})
    assert "PO Box 1" in rendered

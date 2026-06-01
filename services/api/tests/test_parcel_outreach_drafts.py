from __future__ import annotations

from datetime import UTC, datetime

from app.outreach_templates import parcel_render_context, render_template_text
from parking_core.models import OwnerOutreachBrief


def _sample_brief() -> OwnerOutreachBrief:
    return OwnerOutreachBrief(
        county_fips="53033",
        apn="123456-7890",
        recorded_owner_one_liner="Jane Doe",
        contact_points=[],
        mailing_address_guess="100 Main St, Seattle, WA 98101",
        situs_address_guess="102 Main St, Seattle, WA 98101",
        phone_guess="206-555-0100",
        email_guess="owner@example.com",
        steps=[],
        data_gaps=[],
        compliance_notes=[],
        computed_at=datetime.now(tz=UTC),
    )


class _FakeParcel:
    apn = "123456-7890"
    county_fips = "53033"
    lot_sqft = 12500.0


def test_parcel_render_context_uses_brief_not_sample() -> None:
    brief = _sample_brief()
    ctx = parcel_render_context(_FakeParcel(), brief)
    assert ctx["owner_name"] == "Jane Doe"
    assert ctx["apn"] == "123456-7890"
    assert "Example Holdings" not in ctx["owner_name"]


def test_render_template_without_sample_fill_uses_empty_fallbacks() -> None:
    brief = _sample_brief()
    brief.mailing_address_guess = None
    ctx = parcel_render_context(_FakeParcel(), brief)
    body = "Mail: {{ mailing_address or 'MISSING' }}"
    rendered, _ = render_template_text(body, context=ctx, use_sample_fill=False)
    assert "98101" not in rendered
    assert "MISSING" in rendered


def test_render_template_with_sample_fill_keeps_preview_defaults() -> None:
    body = "Owner: {{ owner_name }}"
    rendered, _ = render_template_text(body)
    assert "Jane Doe" in rendered or "Example" in rendered

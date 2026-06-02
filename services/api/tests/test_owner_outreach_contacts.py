from __future__ import annotations

from parking_core.models import ContactKind, OwnerKind, VendorLookupSummary
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row


def test_build_brief_collects_multiple_phones_and_emails() -> None:
    props = {
        "OWNER_NAME": "Example LLC",
        "PHONE": "206-555-0100",
        "PHONE_2": "206-555-0199",
        "EMAIL": "owner@example.com",
        "EMAIL_2": "billing@example.com",
        "MAIL_ADDR": "100 Main St, Seattle, WA 98101",
        "MAIL_ADDR_2": "PO Box 99, Seattle, WA 98104",
    }
    owners = enrich_from_parcel_row(props)
    brief = build_owner_outreach_brief(
        county_fips="53033",
        apn="123",
        raw_properties=props,
        owners=owners,
    )
    assert brief.schema_version == "2"
    assert len([p for p in brief.contact_points if p.kind == ContactKind.phone]) == 2
    assert len([p for p in brief.contact_points if p.kind == ContactKind.email]) == 2
    assert len([p for p in brief.contact_points if p.kind == ContactKind.mailing_address]) == 2
    assert any("log each attempt separately" in gap.lower() for gap in brief.data_gaps)
    assert owners[0].kind == OwnerKind.entity


def test_build_brief_dedupes_same_email_case_insensitive() -> None:
    props = {
        "OWNER_NAME": "Jane Doe",
        "EMAILS": ["Owner@Example.com", "owner@example.com", "other@example.com"],
    }
    brief = build_owner_outreach_brief(
        county_fips="53033",
        apn="456",
        raw_properties=props,
        owners=enrich_from_parcel_row(props),
    )
    emails = [p.value for p in brief.contact_points if p.kind == ContactKind.email]
    assert emails == ["Owner@Example.com", "other@example.com"]


def test_build_brief_sets_research_tier_from_vendor_lookup() -> None:
    props = {"OWNER_NAME": "Example LLC"}
    owners = enrich_from_parcel_row(props)
    hit = build_owner_outreach_brief(
        county_fips="53033",
        apn="789",
        raw_properties=props,
        owners=owners,
        vendor_lookup=VendorLookupSummary(provider="acme", outcome="hit", contacts=[]),
    )
    skipped = build_owner_outreach_brief(
        county_fips="53033",
        apn="790",
        raw_properties=props,
        owners=owners,
        vendor_lookup=VendorLookupSummary(provider="acme", outcome="skipped_tier", notes="below floor"),
    )
    assert hit.owner_research_tier == "enriched"
    assert skipped.owner_research_tier == "basic"

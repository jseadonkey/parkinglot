from __future__ import annotations

from datetime import UTC, datetime

from parking_core.models import OwnerOutreachBrief


def test_brief_accepts_vendor_skipped_tier() -> None:
    brief = OwnerOutreachBrief.model_validate(
        {
            "schema_version": "2",
            "county_fips": "53033",
            "apn": "123",
            "recorded_owner_one_liner": "Example LLC",
            "owner_research_tier": "basic",
            "vendor_lookup": {
                "provider": "webhook",
                "outcome": "skipped_tier",
                "notes": "Parcel below dual score floor for vendor lookup.",
                "contacts": [],
            },
            "computed_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    assert brief.vendor_lookup is not None
    assert brief.vendor_lookup.outcome == "skipped_tier"
    assert brief.owner_research_tier == "basic"

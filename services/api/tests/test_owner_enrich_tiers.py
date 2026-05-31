from app.owner_enrich_tiers import (
    parcel_meets_owner_lookup_tier,
    resolve_owner_research_tier,
)
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row


def test_parcel_meets_owner_lookup_tier_dual_floor() -> None:
    assert parcel_meets_owner_lookup_tier(55.0, 52.0, min_entitlement=55.0, min_strategic=52.0)
    assert not parcel_meets_owner_lookup_tier(54.9, 52.0, min_entitlement=55.0, min_strategic=52.0)
    assert not parcel_meets_owner_lookup_tier(55.0, 51.9, min_entitlement=55.0, min_strategic=52.0)


def test_resolve_owner_research_tier() -> None:
    assert resolve_owner_research_tier(dual_qualified=False, vendor_attempted=False) == "basic"
    assert resolve_owner_research_tier(dual_qualified=True, vendor_attempted=False) == "standard"
    assert resolve_owner_research_tier(dual_qualified=True, vendor_attempted=True) == "deep"


def test_basic_brief_skips_sos_and_vendor_steps() -> None:
    props = {
        "APN": "WA-KING-SAMPLE-001",
        "COUNTY_FIPS": "53033",
        "OWNER_NAME": "Puget Sound Example Holdings LLC",
    }
    owners = enrich_from_parcel_row(props)
    brief = build_owner_outreach_brief(
        county_fips="53033",
        apn="WA-KING-SAMPLE-001",
        raw_properties=props,
        owners=owners,
        owner_research_tier="basic",
    )
    assert brief.owner_research_tier == "basic"
    channels = [s.channel.value for s in brief.steps]
    assert "secretary_of_state" not in channels
    assert "vendor_research" not in channels
    assert any("basic" in g.lower() for g in brief.data_gaps)

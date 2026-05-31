"""Tests for owner name classification and owner record view assembly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import OwnerCandidateRow, Parcel
from app.owner_record_view import build_owner_record_view
from parking_enrichment.owner_classification import classify_owner_display_name, is_entity_name
from parking_core.models import OwnerKind


def test_classify_entity_names() -> None:
    assert classify_owner_display_name("ILLUFA LLC") == OwnerKind.entity
    assert classify_owner_display_name("FLYNN & BACHENBERG TRUST ER") == OwnerKind.entity
    assert classify_owner_display_name("DESMET LARRY") == OwnerKind.individual
    assert is_entity_name("MADISON PLAZA LLC") is True


def test_owner_record_view_entity_with_mailing() -> None:
    parcel = Parcel(
        id=uuid.uuid4(),
        apn="033-2951900025",
        county_fips="53033",
        raw_properties={
            "owner_record": {
                "taxpayer_name": "ILLUFA LLC",
                "mailing_address": "PO BOX 50583 BELLEVUE WA 98015",
                "data_source": "king_county_assessor_gis",
            }
        },
        owner_outreach_brief={
            "owner_research_tier": "standard",
            "registry_lookup": {
                "outcome": "manual_url_only",
                "search_results_url": "https://ccfs.sos.wa.gov/#/BusinessSearch?SearchCriteria=ILLUFA",
            },
        },
        created_at=datetime.now(tz=UTC),
    )
    owners = [
        OwnerCandidateRow(
            id=uuid.uuid4(),
            parcel_id=parcel.id,
            display_name="ILLUFA LLC",
            kind="entity",
            confidence=0.85,
            source="king_county_assessor",
        )
    ]
    view = build_owner_record_view(parcel, owners)
    assert view["is_entity"] is True
    assert view["enrichment_status"] == "entity_mailing_only"
    assert view["sos_search_url"] is not None
    assert "ccfs.sos.wa.gov" in view["sos_search_url"]
    assert any("SOS" in s for s in view["next_steps"])
    assert any("registered agent" in g.lower() for g in view["enrichment_gaps"])


def test_owner_record_view_multiple_candidates() -> None:
    parcel = Parcel(
        id=uuid.uuid4(),
        apn="033-2922059132",
        county_fips="53033",
        raw_properties={
            "owner_record": {
                "taxpayer_name": "SINGH MALKIAT+HARJEET",
                "mailing_address": "25913 116TH AVE SW KENT WA 98030",
                "situs_address": "25913 116TH AVE SE, Kent, WA 98030",
                "kctp_addr": "25913 116TH AVE SW",
                "kctp_cityst": "KENT WA",
                "kctp_zip": "98030",
                "data_source": "king_county_assessor_gis",
            }
        },
        owner_outreach_brief={},
        created_at=datetime.now(tz=UTC),
    )
    view = build_owner_record_view(parcel, [])
    names = [c["value"] for c in view["name_candidates"]]
    assert "SINGH MALKIAT+HARJEET" in names
    assert any("MALKIAT" in n for n in names)
    assert len(view["mailing_address_candidates"]) >= 1
    assert len(view["situs_address_candidates"]) >= 1
    assert view["mailing_address"] != view["situs_address"]

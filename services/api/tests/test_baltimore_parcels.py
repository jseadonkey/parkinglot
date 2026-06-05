from __future__ import annotations

from parking_core.models import ContactKind
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_ingestion.baltimore_parcels import _merge_realproperty_attributes


def test_merge_realproperty_attributes_adds_address_aliases() -> None:
    features = [
        {
            "type": "Feature",
            "properties": {
                "PIN": "1786024",
                "BLOCKLOT": "1786 024",
                "APN": "MD-BALT-CITY-1786024",
            },
            "geometry": None,
        }
    ]
    rows = [
        {
            "OBJECTID": 10,
            "PIN": "1786024",
            "PINRELATE": "1786024",
            "BLOCKLOT": "1786 024",
            "FULLADDR": "123 W BALTIMORE ST",
            "MAILTOADD": "PO BOX 100, BALTIMORE, MD 21201",
            "VACIND": None,
            "OWNER_1": "Example Parking",
            "OWNER_2": "LLC",
        }
    ]

    assert _merge_realproperty_attributes(features, rows) == 1

    props = features[0]["properties"]
    assert props["BALTIMORE_REALPROPERTY_MATCHED"] is True
    assert props["FULLADDR"] == "123 W BALTIMORE ST"
    assert props["PROPERTY_ADDRESS"] == "123 W BALTIMORE ST"
    assert props["SITUS_ADDRESS"] == "123 W BALTIMORE ST"
    assert props["MAILING_ADDRESS"] == "PO BOX 100, BALTIMORE, MD 21201"
    assert props["OWNER_NAME"] == "Example Parking LLC"


def test_baltimore_realproperty_aliases_feed_existing_outreach_contacts() -> None:
    props = {
        "PIN": "1786024",
        "BLOCKLOT": "1786 024",
        "APN": "MD-BALT-CITY-1786024",
    }
    rows = [
        {
            "OBJECTID": 10,
            "PIN": "1786024",
            "PINRELATE": "1786024",
            "BLOCKLOT": "1786 024",
            "FULLADDR": "123 W BALTIMORE ST",
            "MAILTOADD": "PO BOX 100, BALTIMORE, MD 21201",
            "OWNER_1": "Example Parking LLC",
        }
    ]
    _merge_realproperty_attributes([{"properties": props}], rows)

    brief = build_owner_outreach_brief(
        county_fips="24510",
        apn="MD-BALT-CITY-1786024",
        raw_properties=props,
        owners=enrich_from_parcel_row(props),
    )

    situs = [p.value for p in brief.contact_points if p.kind == ContactKind.situs_address]
    mailing = [p.value for p in brief.contact_points if p.kind == ContactKind.mailing_address]
    assert situs == ["123 W BALTIMORE ST"]
    assert mailing == ["PO BOX 100, BALTIMORE, MD 21201"]
    assert not any("No situs / property address" in gap for gap in brief.data_gaps)

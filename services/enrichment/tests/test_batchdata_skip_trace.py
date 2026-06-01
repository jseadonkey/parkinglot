"""Tests for BatchData skip-trace client (mocked HTTP)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from parking_enrichment.batchdata_skip_trace_client import (
    fetch_batchdata_skip_trace,
    property_address_for_skip_trace,
)


def test_property_address_from_owner_record_structured() -> None:
    raw = {
        "owner_record": {
            "addr_full": "909 W HARRISON ST",
            "situs_city": "Kent",
            "situs_zip": "98032",
        }
    }
    addr = property_address_for_skip_trace(raw)
    assert addr == {"street": "909 W HARRISON ST", "city": "Kent", "state": "WA", "zip": "98032"}


def test_property_address_parses_freeform_situs() -> None:
    raw = {"owner_record": {"situs_address": "903 W HARRISON ST, Kent, WA 98032"}}
    addr = property_address_for_skip_trace(raw)
    assert addr is not None
    assert addr["street"] == "903 W HARRISON ST"
    assert addr["city"] == "Kent"


def test_fetch_batchdata_skip_trace_maps_phones_and_emails() -> None:
    response_body = {
        "status": {"code": 200, "text": "OK"},
        "result": {
            "data": [
                {
                    "persons": [
                        {
                            "propertyOwner": True,
                            "name": {"full": "Jane Owner"},
                            "phones": [
                                {"rank": 1, "number": "2065550100", "type": "Mobile", "dnc": False},
                            ],
                            "emails": [{"rank": 1, "email": "jane@example.com"}],
                            "deceased": False,
                        }
                    ]
                }
            ]
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_body).encode()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    raw = {"owner_record": {"addr_full": "1 Main St", "situs_city": "Kent", "situs_zip": "98032"}}
    with patch("urllib.request.urlopen", return_value=mock_resp):
        summary = fetch_batchdata_skip_trace(
            enabled=True,
            api_key="test-key",
            parcel_id="p1",
            county_fips="53033",
            apn="033-1",
            raw_properties=raw,
        )

    assert summary.provider == "batchdata"
    assert summary.outcome == "hit"
    assert len(summary.contacts) == 2
    assert summary.contacts[0].channel == "phone"
    assert summary.contacts[1].value == "jane@example.com"


def test_should_skip_when_roll_has_phone_and_email() -> None:
    from parking_enrichment.batchdata_skip_trace_client import should_skip_skip_trace

    raw = {"OWNER_PHONE": "2065550100", "OWNER_EMAIL": "a@b.co"}
    assert should_skip_skip_trace(raw) is not None
    assert should_skip_skip_trace({"OWNER_PHONE": "2065550100"}) is None


def test_fetch_skipped_without_api_key() -> None:
    summary = fetch_batchdata_skip_trace(
        enabled=True,
        api_key="",
        parcel_id="p1",
        county_fips="53033",
        apn="033-1",
        raw_properties={"owner_record": {"addr_full": "1 Main", "situs_city": "Kent", "situs_zip": "98032"}},
    )
    assert summary.outcome == "skipped_no_url"

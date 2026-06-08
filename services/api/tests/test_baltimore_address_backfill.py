from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.baltimore_address_backfill import (
    ADDRESS_BACKFILL_MATCHED_WITHOUT_ADDRESS,
    ADDRESS_BACKFILL_NO_MATCH,
    ADDRESS_BACKFILL_STATUS_KEY,
    _target_address_backfill_stmt,
    backfill_baltimore_property_addresses,
)


def test_backfill_baltimore_property_addresses_updates_raw_properties() -> None:
    parcel = SimpleNamespace(
        id=uuid.uuid4(),
        apn="MD-BALT-CITY-1786024",
        raw_properties={"PIN": "1786024", "BLOCKLOT": "1786 024"},
    )
    db = MagicMock()
    db.scalars.return_value = [parcel]
    rows = [
        {
            "OBJECTID": 1,
            "PIN": "1786024",
            "PINRELATE": "1786024",
            "BLOCKLOT": "1786 024",
            "FULLADDR": "2328 FLEET ST",
            "MAILTOADD": "PO BOX 1, BALTIMORE, MD",
            "ZONECODE": "C-5DC",
        }
    ]

    with (
        patch("app.baltimore_address_backfill._fetch_realproperty_rows", return_value=rows),
        patch("app.baltimore_address_backfill.write_audit") as audit,
    ):
        out = backfill_baltimore_property_addresses(db, limit=1)

    assert out["selected"] == 1
    assert out["matched"] == 1
    assert out["updated"] == 1
    assert "Targeted batch only" in out["note"]
    assert parcel.raw_properties["PROPERTY_ADDRESS"] == "2328 FLEET ST"
    assert parcel.raw_properties["SITUS_ADDRESS"] == "2328 FLEET ST"
    assert parcel.raw_properties["ZONECODE"] == "C-5DC"
    assert parcel.raw_properties[ADDRESS_BACKFILL_STATUS_KEY] == "address_found"
    assert parcel.zoning_code == "C-5DC"
    db.commit.assert_called_once()
    audit.assert_called_once()


def test_backfill_baltimore_property_addresses_dry_run_rolls_back() -> None:
    parcel = SimpleNamespace(id=uuid.uuid4(), apn="MD-BALT-CITY-1786024", raw_properties={"PIN": "1786024"})
    db = MagicMock()
    db.scalars.return_value = [parcel]

    with patch("app.baltimore_address_backfill._fetch_realproperty_rows", return_value=[]):
        out = backfill_baltimore_property_addresses(db, limit=1, dry_run=True)

    assert out["dry_run"] is True
    assert out["updated"] == 0
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_backfill_baltimore_property_addresses_marks_unfillable_attempts() -> None:
    matched_without_address = SimpleNamespace(
        id=uuid.uuid4(),
        apn="MD-BALT-CITY-1786024",
        raw_properties={"PIN": "1786024", "BLOCKLOT": "1786 024"},
    )
    no_match = SimpleNamespace(
        id=uuid.uuid4(),
        apn="MD-BALT-CITY-1786025",
        raw_properties={"PIN": "1786025", "BLOCKLOT": "1786 025"},
    )
    db = MagicMock()
    db.scalars.return_value = [matched_without_address, no_match]
    rows = [
        {
            "OBJECTID": 1,
            "PIN": "1786024",
            "PINRELATE": "1786024",
            "BLOCKLOT": "1786 024",
            "FULLADDR": "",
            "MAILTOADD": "PO BOX 1, BALTIMORE, MD",
            "ZONECODE": "C-5DC",
        }
    ]

    with (
        patch("app.baltimore_address_backfill._fetch_realproperty_rows", return_value=rows),
        patch("app.baltimore_address_backfill.write_audit"),
    ):
        out = backfill_baltimore_property_addresses(db, limit=2)

    assert out["selected"] == 2
    assert out["matched"] == 1
    assert out["updated"] == 0
    assert out["marked_attempted"] == 2
    assert out["matched_without_address"] == 1
    assert out["no_match"] == 1
    assert (
        matched_without_address.raw_properties[ADDRESS_BACKFILL_STATUS_KEY]
        == ADDRESS_BACKFILL_MATCHED_WITHOUT_ADDRESS
    )
    assert no_match.raw_properties[ADDRESS_BACKFILL_STATUS_KEY] == ADDRESS_BACKFILL_NO_MATCH
    db.commit.assert_called_once()
    assert db.add.call_count == 2


def test_baltimore_address_backfill_stmt_targets_worthwhile_parcels() -> None:
    stmt = _target_address_backfill_stmt(25)
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )

    assert "parcels.county_fips = '24510'" in compiled
    assert "score_profile = 'identification'" in compiled
    assert "score_profile = 'entitlement'" in compiled
    assert "score_profile = 'strategic'" in compiled
    assert "parcels.zoning_allows_surface_parking IS true" in compiled
    assert "VACANT|UNIMPROVED|PARKING|GARAGE|LOT|AUTO" in compiled
    assert "BALTIMORE_ADDRESS_BACKFILL_STATUS" in compiled
    assert "matched_without_address" in compiled
    assert "no_match" in compiled
    assert "LIMIT 25" in compiled

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.baltimore_address_backfill import backfill_baltimore_property_addresses


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
        }
    ]

    with (
        patch("app.baltimore_address_backfill._fetch_realproperty_rows_for_parcels", return_value=rows),
        patch("app.baltimore_address_backfill.write_audit") as audit,
    ):
        out = backfill_baltimore_property_addresses(db, limit=1)

    assert out["selected"] == 1
    assert out["matched"] == 1
    assert out["updated"] == 1
    assert parcel.raw_properties["PROPERTY_ADDRESS"] == "2328 FLEET ST"
    assert parcel.raw_properties["SITUS_ADDRESS"] == "2328 FLEET ST"
    db.commit.assert_called_once()
    audit.assert_called_once()


def test_backfill_baltimore_property_addresses_dry_run_rolls_back() -> None:
    parcel = SimpleNamespace(id=uuid.uuid4(), apn="MD-BALT-CITY-1786024", raw_properties={"PIN": "1786024"})
    db = MagicMock()
    db.scalars.return_value = [parcel]

    with patch("app.baltimore_address_backfill._fetch_realproperty_rows_for_parcels", return_value=[]):
        out = backfill_baltimore_property_addresses(db, limit=1, dry_run=True)

    assert out["dry_run"] is True
    assert out["updated"] == 0
    db.rollback.assert_called_once()
    db.commit.assert_not_called()

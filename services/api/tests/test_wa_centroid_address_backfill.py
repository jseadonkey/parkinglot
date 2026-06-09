import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.wa_centroid_address_backfill import backfill_wa_centroid_addresses


def test_centroid_backfill_dry_run_no_rows() -> None:
    db = MagicMock()
    db.scalars.return_value = []
    out = backfill_wa_centroid_addresses(db, limit=5, county_fips="53099", dry_run=True)
    assert out["selected"] == 0
    assert out["dry_run"] is True


def test_centroid_backfill_fills_visit_address() -> None:
    parcel = SimpleNamespace(
        id=uuid.uuid4(),
        county_fips="53033",
        footprint=None,
        raw_properties={"SITUS_CITY_NM": "KENT", "SITUS_ZIP_NR": "98032"},
    )
    db = MagicMock()
    db.scalars.return_value = [parcel]
    with (
        patch(
            "app.wa_centroid_address_backfill.property_address_for_skip_trace",
            return_value={"street": "100 Main St", "city": "KENT", "state": "WA", "zip": "98032"},
        ),
        patch("app.wa_centroid_address_backfill.write_audit"),
    ):
        out = backfill_wa_centroid_addresses(db, limit=10, county_fips="53033", dry_run=False)
    assert out["found"] == 1
    assert parcel.raw_properties.get("VISIT_ADDRESS")
    assert parcel.raw_properties.get("PROPERTY_ADDRESS") == "100 Main St"

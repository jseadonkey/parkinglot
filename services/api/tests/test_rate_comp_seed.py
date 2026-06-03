from unittest.mock import MagicMock

from app.db.models import ParkingRateComp
from app.rate_comp_seed import (
    BALTIMORE_PARKING_RATE_COMPS,
    KING_COUNTY_PARKING_RATE_COMPS,
    seed_baltimore_parking_rate_comps,
    seed_king_county_parking_rate_comps,
)


def _mock_db(existing: list[ParkingRateComp] | None = None) -> MagicMock:
    db = MagicMock()
    db.scalars.return_value.all.return_value = existing or []
    return db


def test_seed_king_county_inserts_all_when_empty():
    db = _mock_db()
    result = seed_king_county_parking_rate_comps(db)
    assert result["inserted"] == len(KING_COUNTY_PARKING_RATE_COMPS)
    assert result["skipped"] == 0
    assert db.add.call_count == len(KING_COUNTY_PARKING_RATE_COMPS)
    db.commit.assert_called_once()


def test_seed_king_county_skips_existing_names():
    existing = ParkingRateComp(
        name=KING_COUNTY_PARKING_RATE_COMPS[0].name,
        hourly_mid_usd=1.0,
        location=None,
        active=True,
    )
    db = _mock_db([existing])
    result = seed_king_county_parking_rate_comps(db)
    assert result["skipped"] == 1
    assert result["inserted"] == len(KING_COUNTY_PARKING_RATE_COMPS) - 1


def test_seed_king_county_replace_updates_existing():
    existing = ParkingRateComp(
        name=KING_COUNTY_PARKING_RATE_COMPS[0].name,
        hourly_mid_usd=1.0,
        location=None,
        active=True,
    )
    db = _mock_db([existing])
    result = seed_king_county_parking_rate_comps(db, replace_existing=True)
    assert result["updated"] == 1
    assert result["inserted"] == len(KING_COUNTY_PARKING_RATE_COMPS) - 1
    assert existing.hourly_mid_usd == KING_COUNTY_PARKING_RATE_COMPS[0].hourly_mid_usd


def test_seed_baltimore_inserts_all_when_empty():
    db = _mock_db()
    result = seed_baltimore_parking_rate_comps(db)
    assert result["inserted"] == len(BALTIMORE_PARKING_RATE_COMPS)
    assert db.add.call_count == len(BALTIMORE_PARKING_RATE_COMPS)

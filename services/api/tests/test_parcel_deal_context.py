from __future__ import annotations

from app.parcel_deal_context import estimate_parking_revenue
from parking_core.pilot import ParkingRateCompObservation


def test_estimate_parking_revenue_basic() -> None:
    comps = [
        ParkingRateCompObservation(name="A", lat=47.6, lon=-122.3, hourly_mid_usd=10.0),
        ParkingRateCompObservation(name="B", lat=47.61, lon=-122.31, hourly_mid_usd=14.0),
    ]
    out = estimate_parking_revenue(lot_sqft=10_000, comps=comps)
    assert out["available"] is True
    assert out["stalls_estimated"] == 50
    assert out["hourly_rate_median_usd"] == 12.0
    assert out["monthly_gross_usd"] > 0


def test_estimate_parking_revenue_missing_inputs() -> None:
    assert estimate_parking_revenue(lot_sqft=None, comps=[]).get("available") is False

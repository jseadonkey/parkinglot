from __future__ import annotations

from app.parcel_deal_context import estimate_parking_revenue
from parking_core.pilot import ParkingRateCompObservation


def test_estimate_parking_revenue_basic() -> None:
    comps = [
        ParkingRateCompObservation(name="Surface lot A", lat=47.6, lon=-122.3, hourly_mid_usd=10.0, distance_m=200.0),
        ParkingRateCompObservation(name="Surface lot B", lat=47.61, lon=-122.31, hourly_mid_usd=14.0, distance_m=350.0),
    ]
    out = estimate_parking_revenue(
        lot_sqft=10_000,
        comps=comps,
        lat=47.605,
        lon=-122.305,
        is_corner_lot=False,
    )
    assert out["available"] is True
    assert out["stalls_low"] <= out["stalls_estimated"] <= out["stalls_high"]
    assert out["hourly_rate_weighted_usd"] is not None
    assert out["monthly_gross_usd"] > 0


def test_estimate_parking_revenue_missing_inputs() -> None:
    assert estimate_parking_revenue(lot_sqft=None, comps=[]).get("available") is False

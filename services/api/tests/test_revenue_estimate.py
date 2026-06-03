from __future__ import annotations

from parking_core.demand_signals import demand_occupancy_factor
from parking_core.pilot import ParkingRateCompObservation
from parking_core.revenue_estimate import (
    classify_parking_facility,
    effective_hourly_for_surface,
    enrich_rate_comps,
    estimate_parking_revenue,
    estimate_surface_stalls,
)


def test_estimate_surface_stalls_corner_and_size() -> None:
    small = estimate_surface_stalls(6_000, is_corner_lot=False)
    corner = estimate_surface_stalls(6_000, is_corner_lot=True)
    large = estimate_surface_stalls(40_000, is_corner_lot=False)
    assert corner["stalls_mid"] >= small["stalls_mid"]
    assert large["stalls_mid"] > small["stalls_mid"]
    assert small["stalls_low"] <= small["stalls_mid"] <= small["stalls_high"]


def test_classify_parking_facility() -> None:
    assert classify_parking_facility("Capitol Hill surface lot") == "surface"
    assert classify_parking_facility("Downtown garage") == "garage"
    assert classify_parking_facility("Harbor Park") == "unknown"


def test_weighted_rate_prefers_nearby_surface_comp() -> None:
    comps = [
        ParkingRateCompObservation(
            name="Near surface lot",
            lat=39.29,
            lon=-76.61,
            hourly_mid_usd=8.0,
            distance_m=120.0,
        ),
        ParkingRateCompObservation(
            name="Far garage",
            lat=39.31,
            lon=-76.63,
            hourly_mid_usd=20.0,
            distance_m=1800.0,
        ),
    ]
    out = estimate_parking_revenue(
        lot_sqft=20_000,
        comps=comps,
        lat=39.2904,
        lon=-76.6122,
        is_corner_lot=True,
    )
    assert out["available"] is True
    assert out["hourly_rate_weighted_usd"] < out["hourly_rate_median_usd"]
    assert out["hourly_rate_weighted_usd"] < 14.0
    assert out["stalls_estimated"] > 20
    assert out["monthly_gross_low_usd"] <= out["monthly_gross_usd"] <= out["monthly_gross_high_usd"]


def test_garage_comp_discounted_for_surface() -> None:
    garage = effective_hourly_for_surface(10.0, "garage")
    surface = effective_hourly_for_surface(10.0, "surface")
    assert garage < surface


def test_enrich_rate_comps_includes_distance_and_similarity() -> None:
    comps = [
        ParkingRateCompObservation(name="Garage A", lat=39.29, lon=-76.61, hourly_mid_usd=12.0),
    ]
    rows = enrich_rate_comps(comps, lat=39.2904, lon=-76.6122)
    assert rows[0]["facility_type"] == "garage"
    assert rows[0]["distance_m"] >= 0
    assert rows[0]["similarity"] == 0.55


def test_single_distant_comp_discounts_revenue() -> None:
    comps = [
        ParkingRateCompObservation(
            name="Distant lot",
            lat=39.31,
            lon=-76.63,
            hourly_mid_usd=11.0,
            distance_m=2000.0,
        ),
    ]
    out = estimate_parking_revenue(
        lot_sqft=30_133,
        comps=comps,
        lat=39.2904,
        lon=-76.6122,
        is_corner_lot=False,
    )
    assert out["available"] is True
    raw = float(out["monthly_gross_raw_usd"])
    adj = float(out["monthly_gross_usd"])
    assert out["market_confidence_tier"] in ("very_low", "low")
    assert float(out["market_confidence"]) <= 0.45
    assert adj < raw * 0.55
    assert out["comp_count"] == 1


def test_estimate_parking_revenue_missing_inputs() -> None:
    assert estimate_parking_revenue(lot_sqft=None, comps=[]).get("available") is False
    assert estimate_parking_revenue(lot_sqft=10_000, comps=[]).get("available") is False


def test_fallback_rate_when_no_comps() -> None:
    out = estimate_parking_revenue(
        lot_sqft=12_000,
        comps=[],
        lat=47.6,
        lon=-122.3,
        fallback_hourly_usd=9.5,
        fallback_source="King County indicative",
        fallback_confidence_factor=0.55,
    )
    assert out["available"] is True
    assert out["rate_source"] == "fallback"
    assert out["market_confidence_tier"] == "fallback"
    assert out["comp_count"] == 0
    assert float(out["hourly_rate_weighted_usd"]) == 9.5
    assert float(out["monthly_gross_usd"]) < float(out["monthly_gross_raw_usd"])


def test_demand_proximity_raises_occupancy_near_generator() -> None:
    near = estimate_parking_revenue(
        lot_sqft=10_000,
        comps=[],
        lat=39.29,
        lon=-76.61,
        fallback_hourly_usd=10.0,
        fallback_source="test",
        distance_to_nearest_demand_m=150.0,
        demand_buffer_m=400.0,
    )
    far = estimate_parking_revenue(
        lot_sqft=10_000,
        comps=[],
        lat=39.29,
        lon=-76.61,
        fallback_hourly_usd=10.0,
        fallback_source="test",
        distance_to_nearest_demand_m=5000.0,
        demand_buffer_m=400.0,
    )
    assert near["available"] and far["available"]
    assert float(near["occupancy_effective"]) > float(far["occupancy_effective"])
    assert float(near["monthly_gross_usd"]) > float(far["monthly_gross_usd"])


def test_poi_density_raises_revenue_with_fallback_rate() -> None:
    sparse = estimate_parking_revenue(
        lot_sqft=10_000,
        comps=[],
        fallback_hourly_usd=10.0,
        fallback_source="test",
        distance_to_nearest_demand_m=5000.0,
        poi_commercial_count=0,
    )
    dense = estimate_parking_revenue(
        lot_sqft=10_000,
        comps=[],
        fallback_hourly_usd=10.0,
        fallback_source="test",
        distance_to_nearest_demand_m=5000.0,
        poi_commercial_count=25,
    )
    assert float(dense["monthly_gross_usd"]) > float(sparse["monthly_gross_usd"])
    assert float(dense["poi_density_occupancy_factor"]) > float(sparse["poi_density_occupancy_factor"])


def test_demand_occupancy_factor() -> None:
    peak, _ = demand_occupancy_factor(50.0, buffer_m=400.0)
    far, _ = demand_occupancy_factor(3000.0, buffer_m=400.0)
    assert peak > far
    assert demand_occupancy_factor(None)[0] == 0.35


def test_weak_comps_blend_with_fallback() -> None:
    comps = [
        ParkingRateCompObservation(
            name="Distant lot",
            lat=39.31,
            lon=-76.63,
            hourly_mid_usd=14.0,
            distance_m=2200.0,
        ),
    ]
    out = estimate_parking_revenue(
        lot_sqft=15_000,
        comps=comps,
        lat=39.2904,
        lon=-76.6122,
        fallback_hourly_usd=9.0,
        fallback_source="Baltimore indicative",
    )
    assert out["available"] is True
    assert out["rate_source"] == "comps_and_fallback"
    assert float(out["hourly_rate_weighted_usd"]) < 14.0

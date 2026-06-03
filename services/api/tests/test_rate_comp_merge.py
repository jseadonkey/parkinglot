from __future__ import annotations

from parking_core.pilot import (
    ComplianceConfig,
    DataSourcesConfig,
    DealConfig,
    ParkingRateCompObservation,
    PilotConfig,
    RegionConfig,
    ScoringConfig,
    ScoringWeights,
)
from parking_core.rate_comps import merge_rate_comp_sequences, parking_market_component


def _pilot_with_parking_weight() -> PilotConfig:
    return PilotConfig(
        region=RegionConfig(name="t", state_fips="53"),
        deal=DealConfig(primary_structure="ground_lease"),
        compliance=ComplianceConfig(),
        scoring=ScoringConfig(
            weights=ScoringWeights(near_paid_parking_comps=15),
            parking_rate_comp_min_for_full_credit=2,
        ),
        data_sources=DataSourcesConfig(),
    )


def test_merge_rate_comp_sequences_dedupes_same_lat_lon_name() -> None:
    a = ParkingRateCompObservation(name="Lot A", lat=47.6062, lon=-122.3321, hourly_mid_usd=10.0)
    b = ParkingRateCompObservation(name="Lot A", lat=47.6062, lon=-122.3321, hourly_mid_usd=99.0)
    out = merge_rate_comp_sequences([a], [b])
    assert len(out) == 1
    assert out[0].hourly_mid_usd == 10.0


def test_merge_rate_comp_sequences_keeps_distinct_comps() -> None:
    db = ParkingRateCompObservation(
        name="DB comp",
        lat=47.61,
        lon=-122.33,
        hourly_mid_usd=12.0,
        origin="database",
    )
    pilot = ParkingRateCompObservation(name="Pilot comp", lat=47.62, lon=-122.34, hourly_mid_usd=14.0)
    out = merge_rate_comp_sequences([db], [pilot])
    assert len(out) == 2


def test_parking_market_component_zero_without_comps() -> None:
    pilot = _pilot_with_parking_weight()
    pts, notes = parking_market_component([], pilot)
    assert pts == 0.0
    assert notes


def test_parking_market_component_partial_with_one_comp() -> None:
    pilot = _pilot_with_parking_weight()
    comp = ParkingRateCompObservation(name="Garage", lat=47.6, lon=-122.3, hourly_mid_usd=12.0, distance_m=200.0)
    pts, _ = parking_market_component([comp], pilot)
    assert pts == 7.5


def test_parking_market_component_one_distant_comp_heavily_discounted() -> None:
    pilot = _pilot_with_parking_weight()
    comp = ParkingRateCompObservation(
        name="Far lot",
        lat=47.62,
        lon=-122.34,
        hourly_mid_usd=12.0,
        distance_m=2200.0,
    )
    pts, notes = parking_market_component([comp], pilot)
    assert pts < 4.0
    assert any("distance" in n.lower() for n in notes)


def test_parking_market_component_full_with_two_comps() -> None:
    pilot = _pilot_with_parking_weight()
    comps = [
        ParkingRateCompObservation(name="A", lat=47.61, lon=-122.33, hourly_mid_usd=10.0),
        ParkingRateCompObservation(name="B", lat=47.62, lon=-122.34, hourly_mid_usd=14.0),
    ]
    pts, notes = parking_market_component(comps, pilot)
    assert pts == 15.0
    assert "2 nearby paid parking comps" in notes[0]

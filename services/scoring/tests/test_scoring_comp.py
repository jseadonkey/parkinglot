"""Scoring engine — parking comp market signal."""

from __future__ import annotations

from pathlib import Path

from parking_core.models import ParcelFeature
from parking_core.pilot import ParkingCompMarketConfig, PilotConfig, ScoringConfig, ScoringWeights, load_pilot_config
from parking_scoring.engine import score_parcel

REPO = Path(__file__).resolve().parents[3]


def _feature(**overrides) -> ParcelFeature:
    base = dict(
        apn="TEST-001",
        county_fips="53033",
        lot_sqft=10000.0,
        zoning_code="C-1",
        zoning_allows_surface_parking=True,
        is_corner_lot=False,
        distance_to_nearest_demand_m=5000.0,
        distance_to_nearest_comp_parking_m=300.0,
        nearest_comp_rate_usd_per_day=18.0,
        nearest_comp_name="Kent Station garage",
    )
    base.update(overrides)
    return ParcelFeature(**base)


def _comp_pilot(**weight_overrides) -> PilotConfig:
    pilot = load_pilot_config(REPO / "config" / "pilot_strategic.yaml")
    w = pilot.scoring.weights.model_dump()
    w.update(weight_overrides)
    pilot.scoring = ScoringConfig(
        min_lot_sqft=pilot.scoring.min_lot_sqft,
        weights=ScoringWeights(**w),
        demand_generator_buffer_m=pilot.scoring.demand_generator_buffer_m,
        demand_generators=pilot.scoring.demand_generators,
        parking_comp_market=ParkingCompMarketConfig(
            enabled=True,
            buffer_m=800,
            min_rate_usd_per_day=6.0,
            premium_rate_usd_per_day=15.0,
        ),
        qualified_min_score=pilot.scoring.qualified_min_score,
    )
    return pilot


def test_comp_within_buffer_scores_full_demand_weight() -> None:
    pilot = _comp_pilot()
    result = score_parcel(_feature(), pilot)
    assert result.breakdown.demand_proximity_component == 40.0
    assert result.pilot_snapshot.get("demand_signal_source") == "comp"
    assert any("Kent Station garage" in n for n in result.breakdown.notes)


def test_comp_outside_buffer_scores_zero() -> None:
    pilot = _comp_pilot()
    result = score_parcel(_feature(distance_to_nearest_comp_parking_m=900.0), pilot)
    assert result.breakdown.demand_proximity_component == 0.0


def test_comp_below_min_rate_scores_zero() -> None:
    pilot = _comp_pilot()
    result = score_parcel(
        _feature(nearest_comp_rate_usd_per_day=3.0, distance_to_nearest_comp_parking_m=100.0),
        pilot,
    )
    assert result.breakdown.demand_proximity_component == 0.0


def test_poi_fallback_when_comp_missing() -> None:
    pilot = _comp_pilot(near_parking_comp_m=40, near_demand_generator_m=40)
    result = score_parcel(
        _feature(
            distance_to_nearest_comp_parking_m=None,
            nearest_comp_rate_usd_per_day=None,
            nearest_comp_name=None,
            distance_to_nearest_demand_m=200.0,
        ),
        pilot,
    )
    assert result.breakdown.demand_proximity_component == 40.0
    assert result.pilot_snapshot.get("demand_signal_source") == "poi"

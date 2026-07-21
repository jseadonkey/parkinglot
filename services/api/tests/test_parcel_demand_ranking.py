"""Demand-aware ordering for the paved vacant operator shortlist."""

from __future__ import annotations

from pathlib import Path

from app.parcel_scored_list import demand_sort_rank
from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_scoring.engine import score_parcel

REPO_ROOT = Path(__file__).resolve().parents[3]


def _feature(distance_m: float | None, poi: int | None = None) -> ParcelFeature:
    return ParcelFeature(
        apn="demand-test",
        county_fips="53033",
        lot_sqft=12_000,
        zoning_allows_surface_parking=True,
        is_corner_lot=False,
        distance_to_nearest_demand_m=distance_m,
        poi_commercial_count_400m=poi,
        raw_properties={"VALUE_BLDG": "0", "VALUE_LAND": "200000"},
    )


def test_nearby_demand_ranks_before_remote_rural_parcel() -> None:
    assert demand_sort_rank(350, None) < demand_sort_rank(290_000, None)


def test_commercial_poi_density_can_supply_local_demand_signal() -> None:
    assert demand_sort_rank(50_000, 8) < demand_sort_rank(5_000, 0)


def test_missing_demand_ranks_after_known_remote_distance() -> None:
    assert demand_sort_rank(50_000, None) < demand_sort_rank(None, None)


def test_distance_orders_parcels_within_same_demand_band() -> None:
    assert demand_sort_rank(150, 0) < demand_sort_rank(450, 0)


def test_downtown_poi_density_beats_small_town_proximity() -> None:
    """A dense downtown lot outranks a rural lot hugging its town's lone generator."""
    assert demand_sort_rank(73, 131) < demand_sort_rank(11, None)


def test_dense_poi_outranks_distance_only_proximity() -> None:
    """Band 0 requires commercial density — distance alone is not enough."""
    assert demand_sort_rank(5_000, 40) < demand_sort_rank(50, None)


def test_graduated_demand_decay_in_scorer() -> None:
    """Full credit inside buffer, partial just outside, zero when remote."""
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    weight = float(pilot.scoring.weights.near_demand_generator_m)
    buffer_m = float(pilot.scoring.demand_generator_buffer_m)

    inside = score_parcel(_feature(buffer_m * 0.5), pilot).breakdown.demand_proximity_component
    near_miss = score_parcel(_feature(buffer_m * 1.5), pilot).breakdown.demand_proximity_component
    remote = score_parcel(_feature(290_000), pilot).breakdown.demand_proximity_component

    assert inside == weight
    assert 0 < near_miss < weight
    assert remote == 0.0


def test_nearby_parcel_outscores_remote_twin() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    near = score_parcel(_feature(200), pilot).total_score
    far = score_parcel(_feature(290_000), pilot).total_score
    assert near > far

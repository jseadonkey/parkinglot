"""Demand-aware ordering for the paved vacant operator shortlist."""

from __future__ import annotations

from app.parcel_scored_list import demand_sort_rank


def test_nearby_demand_ranks_before_remote_rural_parcel() -> None:
    assert demand_sort_rank(350, None) < demand_sort_rank(290_000, None)


def test_commercial_poi_density_can_supply_local_demand_signal() -> None:
    assert demand_sort_rank(50_000, 8) < demand_sort_rank(5_000, 0)


def test_missing_demand_ranks_after_known_remote_distance() -> None:
    assert demand_sort_rank(50_000, None) < demand_sort_rank(None, None)


def test_distance_orders_parcels_within_same_demand_band() -> None:
    assert demand_sort_rank(150, 0) < demand_sort_rank(450, 0)

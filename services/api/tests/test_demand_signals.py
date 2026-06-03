from __future__ import annotations

from parking_core.demand_signals import (
    combined_demand_occupancy_factor,
    demand_occupancy_factor,
    poi_density_occupancy_factor,
)


def test_poi_density_saturates_with_count() -> None:
    low, _ = poi_density_occupancy_factor(0)
    mid, _ = poi_density_occupancy_factor(8)
    high, _ = poi_density_occupancy_factor(40)
    assert low < mid < high


def test_combined_uses_both_signals() -> None:
    combined, notes, detail = combined_demand_occupancy_factor(
        distance_to_nearest_demand_m=100.0,
        poi_commercial_count=20,
        demand_buffer_m=400.0,
    )
    gen_f, _ = demand_occupancy_factor(100.0, buffer_m=400.0)
    poi_f, _ = poi_density_occupancy_factor(20)
    assert combined >= min(gen_f, poi_f)
    assert detail["poi_commercial_count"] == 20
    assert any("Combined demand signal" in n for n in notes)

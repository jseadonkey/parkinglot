from __future__ import annotations

from parking_core.demand_signals import (
    combined_demand_occupancy_factor,
    demand_occupancy_factor,
    intensity_occupancy_factor,
    poi_density_occupancy_factor,
)


def test_poi_density_saturates_with_count() -> None:
    low, _ = poi_density_occupancy_factor(0)
    mid, _ = poi_density_occupancy_factor(8)
    high, _ = poi_density_occupancy_factor(40)
    assert low < mid < high


def test_intensity_beats_raw_poi_count_for_heavy_anchors() -> None:
    """A hospital nearby should outrank many small shops on occupancy."""
    heavy, notes = intensity_occupancy_factor(18.0, heavy_anchors=1)
    strip, _ = intensity_occupancy_factor(8.0, heavy_anchors=0)
    assert heavy > strip
    assert any("heavy" in n.lower() or "anchor" in n.lower() for n in notes)


def test_combined_prefers_intensity_over_raw_poi_count() -> None:
    with_intensity, notes, detail = combined_demand_occupancy_factor(
        distance_to_nearest_demand_m=120.0,
        poi_commercial_count=4,
        poi_demand_intensity=40.0,
        poi_heavy_anchor_count=2,
        demand_buffer_m=400.0,
    )
    poi_only, _, _ = combined_demand_occupancy_factor(
        distance_to_nearest_demand_m=120.0,
        poi_commercial_count=4,
        demand_buffer_m=400.0,
    )
    assert with_intensity > poi_only
    assert detail["intensity_occupancy_factor"] is not None
    assert detail["poi_demand_intensity"] == 40.0
    assert detail["poi_heavy_anchor_count"] == 2
    assert any("intensity" in n.lower() for n in notes)


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

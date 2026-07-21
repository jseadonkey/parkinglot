"""Demand-aware ordering for the paved vacant operator shortlist."""

from __future__ import annotations

from pathlib import Path

from app.parcel_scored_list import demand_sort_rank
from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_scoring.engine import (
    MARKET_GATE_SCORE_CAP,
    score_parcel,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _feature(
    distance_m: float | None,
    poi: int | None = None,
    *,
    intensity: float | None = None,
    heavy: int | None = None,
) -> ParcelFeature:
    return ParcelFeature(
        apn="demand-test",
        county_fips="53033",
        lot_sqft=12_000,
        zoning_allows_surface_parking=True,
        is_corner_lot=False,
        distance_to_nearest_demand_m=distance_m,
        poi_commercial_count_400m=poi,
        poi_demand_intensity=intensity,
        poi_heavy_anchor_count=heavy,
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


def test_weighted_intensity_outranks_raw_poi_count() -> None:
    """A hospital-heavy site (high intensity) beats many tiny shops."""
    assert demand_sort_rank(800, 4, intensity=40.0, heavy_anchors=2) < demand_sort_rank(
        200, 20, intensity=12.0, heavy_anchors=0
    )


def test_heavy_anchor_earns_top_band() -> None:
    assert demand_sort_rank(900, 1, intensity=12.0, heavy_anchors=1) < demand_sort_rank(
        100, 5, intensity=8.0, heavy_anchors=0
    )


def test_graduated_demand_decay_in_scorer() -> None:
    """Full credit inside buffer, partial just outside, zero when remote."""
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    weight = float(pilot.scoring.weights.near_demand_generator_m)
    buffer_m = float(pilot.scoring.demand_generator_buffer_m)

    inside = score_parcel(_feature(buffer_m * 0.5), pilot).breakdown.demand_proximity_component
    near_miss = score_parcel(_feature(buffer_m * 1.5), pilot).breakdown.demand_proximity_component
    remote = score_parcel(_feature(290_000), pilot).total_score

    assert inside == weight
    assert 0 < near_miss < weight
    # Remote with no intensity/POI data still scores other components; demand is 0.
    assert score_parcel(_feature(290_000), pilot).breakdown.demand_proximity_component == 0.0
    assert remote > 0


def test_nearby_parcel_outscores_remote_twin() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    near = score_parcel(_feature(200), pilot).total_score
    far = score_parcel(_feature(290_000), pilot).total_score
    assert near > far


def test_market_gate_zeros_demand_without_comps_or_anchors() -> None:
    """Low intensity + no heavy anchors + no comps → no opportunity (hard cut)."""
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    # Small-town strip: a few shops, no heavy draw, no paid comps.
    result = score_parcel(_feature(50, poi=4, intensity=8.0, heavy=0), pilot)
    assert result.breakdown.demand_proximity_component == 0.0
    assert result.total_score <= MARKET_GATE_SCORE_CAP
    assert result.pilot_snapshot.get("market_gate_failed") is True
    assert any("street parking" in n.lower() or "no opportunity" in n.lower() for n in result.breakdown.notes)


def test_heavy_anchor_passes_market_gate() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    result = score_parcel(_feature(600, poi=3, intensity=14.0, heavy=1), pilot)
    assert result.breakdown.demand_proximity_component > 0
    assert result.pilot_snapshot.get("market_gate_failed") is False


def test_dense_core_intensity_passes_market_gate() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    result = score_parcel(_feature(400, poi=40, intensity=55.0, heavy=0), pilot)
    assert result.breakdown.demand_proximity_component > 0
    assert result.pilot_snapshot.get("market_gate_failed") is False


def test_intensity_scales_demand_credit_by_magnitude() -> None:
    """One large draw (high intensity) earns more credit than a few small shops."""
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    hospital = score_parcel(_feature(700, intensity=40.0, heavy=1), pilot)
    strip = score_parcel(_feature(200, intensity=8.0, heavy=0), pilot)
    assert hospital.breakdown.demand_proximity_component > strip.breakdown.demand_proximity_component

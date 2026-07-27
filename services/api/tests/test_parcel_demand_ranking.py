"""Demand-aware ordering for the paved vacant operator shortlist."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.parcel_scored_list import ParcelScoredRowData, demand_sort_rank, prefer_paved_sort_key
from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_scoring.engine import (
    MARKET_GATE_SCORE_CAP,
    score_parcel,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _row(
    *,
    combined: float,
    surface: str = "mixed",
    demand_m: float | None = 50_000,
    poi: int | None = 0,
    intensity: float | None = 0.0,
    gov: bool = False,
) -> ParcelScoredRowData:
    return ParcelScoredRowData(
        parcel_id=uuid4(),
        apn="T",
        county_fips="53009",
        situs_address=None,
        mailing_address=None,
        zoning_code=None,
        lot_sqft=10_000,
        zoning_principal_use_symbol=None,
        zoning_entitlement_tier=None,
        entitlement_score=combined,
        strategic_score=None,
        identification_score=combined,
        combined_score=combined,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        surface_kind=surface,
        surface_paved_fraction=0.9 if surface == "paved" else 0.4,
        distance_to_nearest_demand_m=demand_m,
        poi_commercial_count_400m=poi,
        poi_demand_intensity=intensity,
        government_owned=gov,
    )


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


def test_prefer_paved_sort_keeps_higher_combined_ahead_of_nearer_demand() -> None:
    """Sort by Combined must win over demand proximity (the Parcels page bug)."""
    high_remote = _row(combined=74.3, surface="paved", demand_m=80_000, poi=0, intensity=0.0)
    low_near = _row(combined=64.3, surface="mixed", demand_m=200, poi=8, intensity=20.0)
    ordered = sorted([low_near, high_remote], key=lambda r: prefer_paved_sort_key(r, sort="combined"))
    assert ordered[0].combined_score == 74.3
    assert ordered[1].combined_score == 64.3


def test_prefer_paved_sort_uses_surface_then_demand_as_tiebreakers() -> None:
    paved = _row(combined=64.3, surface="paved", demand_m=5_000, poi=1)
    # Keep paved_fraction below the mostly-paved threshold so surface ranks differ.
    unknown_near = _row(combined=64.3, surface="unknown", demand_m=100, poi=10, intensity=30.0)
    ordered = sorted([unknown_near, paved], key=lambda r: prefer_paved_sort_key(r, sort="combined"))
    assert ordered[0].surface_kind == "paved"
    assert ordered[1].surface_kind == "unknown"


def test_prefer_paved_sort_sinks_government_owned() -> None:
    private = _row(combined=60.0, surface="paved")
    gov = _row(combined=90.0, surface="paved", gov=True)
    ordered = sorted([gov, private], key=lambda r: prefer_paved_sort_key(r, sort="combined"))
    assert ordered[0].government_owned is False
    assert ordered[1].government_owned is True


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

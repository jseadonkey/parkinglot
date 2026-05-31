from __future__ import annotations

from parking_core.models import ParcelFeature, ScoreBreakdown, ScoreResult
from parking_core.pilot import PilotConfig


def _comp_daily_rate(feature: ParcelFeature) -> float | None:
    if feature.nearest_comp_rate_usd_per_day is not None:
        return float(feature.nearest_comp_rate_usd_per_day)
    return None


def _market_demand_points(
    feature: ParcelFeature,
    pilot: PilotConfig,
) -> tuple[float, list[str], str]:
    """Comp parking (preferred) or POI demand generators (fallback). Returns (points, notes, source)."""
    w = pilot.scoring.weights
    comp_cfg = pilot.scoring.parking_comp_market
    comp_weight = float(w.near_parking_comp_m or 0)
    poi_weight = float(w.near_demand_generator_m or 0)

    if comp_cfg.enabled and comp_weight > 0 and feature.distance_to_nearest_comp_parking_m is not None:
        dist = float(feature.distance_to_nearest_comp_parking_m)
        rate = _comp_daily_rate(feature)
        min_rate = float(comp_cfg.min_rate_usd_per_day)
        buffer_m = int(comp_cfg.buffer_m)
        premium = float(comp_cfg.premium_rate_usd_per_day)
        name = feature.nearest_comp_name or "nearest comp"

        if rate is None or rate < min_rate:
            return (
                0.0,
                [f"Nearest parking comp below min rate (${min_rate}/day screening floor)."],
                "comp",
            )
        if dist > buffer_m:
            return (
                0.0,
                [f"Outside parking comp buffer ({buffer_m} m); nearest '{name}' at {dist:.0f} m, ${rate}/day."],
                "comp",
            )
        pts = comp_weight
        if rate >= premium:
            note = (
                f"Within {buffer_m} m of comp '{name}' at ${rate:.0f}/day (premium ≥ ${premium:.0f}/day)."
            )
        else:
            note = f"Within {buffer_m} m of comp '{name}' at ${rate:.0f}/day."
        return pts, [note], "comp"

    dist = feature.distance_to_nearest_demand_m
    if poi_weight <= 0:
        if comp_cfg.enabled and comp_weight <= 0:
            return 0.0, ["Parking comp market scoring disabled (zero weight)."], "none"
        return 0.0, ["No parking comp data; POI demand weight is zero."], "none"
    if dist is None:
        return 0.0, ["No demand distance (comp or POI); market proximity scored as zero."], "poi"
    if dist <= pilot.scoring.demand_generator_buffer_m:
        return (
            poi_weight,
            [f"POI demand fallback: within {pilot.scoring.demand_generator_buffer_m} m of generator."],
            "poi",
        )
    return (
        0.0,
        ["POI demand fallback: outside demand-generator buffer."],
        "poi",
    )


def score_parcel(feature: ParcelFeature, pilot: PilotConfig) -> ScoreResult:
    """Deterministic score from parcel features and pilot weights (0–100 scale)."""
    w = pilot.scoring.weights
    notes: list[str] = []

    zoning_pts = float(w.zoning_permitted_surface_parking if feature.zoning_allows_surface_parking else 0)
    if not feature.zoning_allows_surface_parking:
        notes.append("Zoning does not explicitly allow surface parking in ingest flags.")

    lot = feature.lot_sqft or 0.0
    if lot < pilot.scoring.min_lot_sqft:
        lot_pts = 0.0
        notes.append(f"Lot {lot} sqft under pilot minimum {pilot.scoring.min_lot_sqft}.")
    else:
        lot_pts = float(w.lot_size)

    corner_pts = float(w.corner_lot if feature.is_corner_lot else 0)

    demand_pts, demand_notes, demand_source = _market_demand_points(feature, pilot)
    notes.extend(demand_notes)

    total = min(100.0, zoning_pts + lot_pts + corner_pts + demand_pts)
    breakdown = ScoreBreakdown(
        zoning_component=zoning_pts,
        lot_size_component=lot_pts,
        corner_component=corner_pts,
        demand_proximity_component=demand_pts,
        notes=notes,
    )
    snapshot = {
        "min_lot_sqft": pilot.scoring.min_lot_sqft,
        "weights": pilot.scoring.weights.model_dump(),
        "buffer_m": pilot.scoring.demand_generator_buffer_m,
        "demand_signal_source": demand_source,
        "parking_comp_market": pilot.scoring.parking_comp_market.model_dump(),
    }
    return ScoreResult(total_score=total, breakdown=breakdown, pilot_snapshot=snapshot)

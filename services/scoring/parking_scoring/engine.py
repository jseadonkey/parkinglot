from __future__ import annotations

from parking_core.models import ParcelFeature, ScoreBreakdown, ScoreResult
from parking_core.pilot import ParkingRateCompObservation, PilotConfig


def _rate_comp_key(comp: ParkingRateCompObservation) -> tuple[str, float, float]:
    return (comp.name, round(comp.lat, 5), round(comp.lon, 5))


def _merge_rate_comp_sequences(
    primary: list[ParkingRateCompObservation],
    secondary: list[ParkingRateCompObservation],
) -> list[ParkingRateCompObservation]:
    """Merge comp lists; ``primary`` wins on duplicate (name, lat, lon)."""
    out = list(primary)
    seen = {_rate_comp_key(c) for c in primary}
    for comp in secondary:
        key = _rate_comp_key(comp)
        if key in seen:
            continue
        seen.add(key)
        out.append(comp)
    return out


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

    dist = feature.distance_to_nearest_demand_m
    if dist is None:
        demand_pts = 0.0
        notes.append("No demand generator distance; scoring demand proximity as zero.")
    elif dist <= pilot.scoring.demand_generator_buffer_m:
        demand_pts = float(w.near_demand_generator_m)
    else:
        demand_pts = 0.0
        notes.append("Parcel outside configured demand-generator buffer.")

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
    }
    return ScoreResult(total_score=total, breakdown=breakdown, pilot_snapshot=snapshot)

from __future__ import annotations

from parking_core.models import ParcelFeature, ScoreBreakdown, ScoreResult
from parking_core.pilot import ParkingRateCompObservation, PilotConfig
from parking_core.rate_comps import parking_market_component


def score_parcel(
    feature: ParcelFeature,
    pilot: PilotConfig,
    *,
    nearby_rate_comps: list[ParkingRateCompObservation] | None = None,
) -> ScoreResult:
    """Deterministic score from parcel features, pilot weights, and optional nearby rate comps."""
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

    comps = nearby_rate_comps or []
    parking_pts, parking_notes = parking_market_component(comps, pilot)
    notes.extend(parking_notes)

    total = min(100.0, zoning_pts + lot_pts + corner_pts + demand_pts + parking_pts)
    breakdown = ScoreBreakdown(
        zoning_component=zoning_pts,
        lot_size_component=lot_pts,
        corner_component=corner_pts,
        demand_proximity_component=demand_pts,
        parking_market_component=parking_pts,
        notes=notes,
    )
    snapshot: dict = {
        "min_lot_sqft": pilot.scoring.min_lot_sqft,
        "weights": pilot.scoring.weights.model_dump(),
        "buffer_m": pilot.scoring.demand_generator_buffer_m,
    }
    if comps:
        max_used = int(getattr(pilot.scoring, "parking_rate_comp_max_used", 8) or 8)
        used = comps[:max_used]
        snapshot["parking_rate_comp_count"] = len(used)
        snapshot["parking_rate_comps_used"] = [
            {
                "name": c.name,
                "hourly_mid_usd": c.hourly_mid_usd,
                "lat": c.lat,
                "lon": c.lon,
                "origin": c.origin,
            }
            for c in used
        ]
    return ScoreResult(total_score=total, breakdown=breakdown, pilot_snapshot=snapshot)

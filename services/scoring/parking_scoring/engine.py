from __future__ import annotations

from parking_core.models import ParcelFeature, ScoreBreakdown, ScoreResult
from parking_core.pilot import ParkingRateCompObservation, PilotConfig
from parking_core.rate_comps import parking_market_component
from parking_core.suitability import compute_parcel_suitability


def score_parcel(
    feature: ParcelFeature,
    pilot: PilotConfig,
    *,
    nearby_rate_comps: list[ParkingRateCompObservation] | None = None,
) -> ScoreResult:
    """Deterministic score from parcel features, pilot weights, and optional nearby rate comps."""
    w = pilot.scoring.weights
    notes: list[str] = []

    sym = (feature.zoning_principal_use_symbol or "").strip().upper()
    cond_pts = float(getattr(w, "zoning_conditional_surface_parking", 0) or 0)
    if feature.zoning_allows_surface_parking or sym == "P":
        zoning_pts = float(w.zoning_permitted_surface_parking)
    elif sym in ("CB", "M", "PV") and cond_pts > 0:
        zoning_pts = cond_pts
        if sym == "PV":
            notes.append(
                "WAZA commercial/mixed/industrial class — provisional prospect signal only "
                "(counsel must curate before treating as permitted)."
            )
        elif sym == "M":
            notes.append("Zoning is minor conditional use (M) — partial entitlement credit only.")
        else:
            notes.append("Zoning is BMZA conditional (CB) — partial entitlement credit only.")
    else:
        zoning_pts = 0.0
        if sym == "CB":
            notes.append("Zoning is BMZA conditional (CB) — not scored as outright permitted.")
        elif sym == "CO":
            notes.append("Zoning requires Council ordinance (CO) for principal parking lot.")
        elif not feature.zoning_allows_surface_parking:
            notes.append("Zoning does not explicitly allow surface parking in ingest flags.")

    lot = feature.lot_sqft or 0.0
    if lot < pilot.scoring.min_lot_sqft:
        lot_pts = 0.0
        notes.append(f"Lot {lot} sqft under pilot minimum {pilot.scoring.min_lot_sqft}.")
    else:
        lot_pts = float(w.lot_size)

    corner_pts = float(w.corner_lot if feature.is_corner_lot else 0)

    dist = feature.distance_to_nearest_demand_m
    demand_weight = float(w.near_demand_generator_m)
    buffer_m = float(pilot.scoring.demand_generator_buffer_m)
    poi_count = feature.poi_commercial_count_400m
    if poi_count is None and isinstance(feature.raw_properties, dict):
        raw_poi = feature.raw_properties.get("poi_commercial_count_400m")
        if raw_poi is not None:
            try:
                poi_count = int(raw_poi)
            except (TypeError, ValueError):
                poi_count = None
    if dist is not None and dist <= buffer_m:
        demand_pts = demand_weight
    elif poi_count is not None and poi_count >= 6:
        demand_pts = demand_weight
        notes.append(
            f"OSM commercial POI density ({poi_count} within ~400 m) — local demand credit."
        )
    elif poi_count is not None and poi_count >= 2:
        demand_pts = round(demand_weight * 0.5, 2)
        notes.append(
            f"Modest OSM commercial POI density ({poi_count} within ~400 m) — half demand credit."
        )
    elif dist is None:
        demand_pts = 0.0
        notes.append("No demand generator distance; scoring demand proximity as zero.")
    else:
        demand_pts = 0.0
        notes.append("Parcel outside configured demand-generator buffer.")

    comps = nearby_rate_comps or []
    parking_pts, parking_notes = parking_market_component(comps, pilot)
    notes.extend(parking_notes)

    suit = compute_parcel_suitability(feature.raw_properties)
    suit_weight = float(getattr(w, "vacant_or_underutilized", 0) or 0)
    category = suit["suitability"]
    suit_pts = 0.0
    if suit_weight > 0:
        if category == "existing_parking":
            suit_pts = 0.0
            use_code = suit.get("land_use_code")
            code_txt = f" (land use {use_code})" if use_code else ""
            notes.append(
                f"Assessor already classifies site as parking{code_txt} — "
                "poor fit for a new surface-lot conversion."
            )
        elif category == "vacant":
            suit_pts = suit_weight
            notes.append("Vacant land (no building value) — strong surface-parking candidate.")
        elif category == "underutilized":
            suit_pts = round(suit_weight * 0.5, 2)
            ratio = suit.get("improvement_ratio")
            ratio_txt = f" (improvement ratio {ratio:.2f})" if isinstance(ratio, float) else ""
            notes.append(
                f"Low improvement-to-land value{ratio_txt} — possible underutilized/teardown site."
            )
        elif category == "improved":
            notes.append("Existing structure has meaningful value — likely improved, not a bare lot.")
        else:
            notes.append("No assessor building/land value on file; site suitability unknown.")

    total = min(100.0, zoning_pts + lot_pts + corner_pts + demand_pts + parking_pts + suit_pts)
    breakdown = ScoreBreakdown(
        zoning_component=zoning_pts,
        lot_size_component=lot_pts,
        corner_component=corner_pts,
        demand_proximity_component=demand_pts,
        parking_market_component=parking_pts,
        suitability_component=suit_pts,
        notes=notes,
    )
    snapshot: dict = {
        "min_lot_sqft": pilot.scoring.min_lot_sqft,
        "weights": pilot.scoring.weights.model_dump(),
        "buffer_m": pilot.scoring.demand_generator_buffer_m,
        "suitability": category,
        "improvement_ratio": suit.get("improvement_ratio"),
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

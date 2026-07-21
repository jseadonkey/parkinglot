from __future__ import annotations

from parking_core.models import ParcelFeature, ScoreBreakdown, ScoreResult
from parking_core.pilot import ParkingRateCompObservation, PilotConfig
from parking_core.rate_comps import distance_comp_weight, parking_market_component
from parking_core.suitability import compute_parcel_suitability

# Weighted demand intensity where full demand credit is earned (downtown-core level).
DEMAND_INTENSITY_SATURATION = 30.0
# Market gate thresholds: below these (with no comps and no heavy anchor) a
# location likely has free street parking and no paid-parking opportunity.
MARKET_GATE_MIN_INTENSITY = 25.0
MARKET_GATE_MIN_POI_COUNT = 12
# Total score ceiling for gate failures — keeps them out of every qualified list.
MARKET_GATE_SCORE_CAP = 40.0


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
    intensity = feature.poi_demand_intensity
    heavy_anchors = feature.poi_heavy_anchor_count or 0

    if intensity is not None:
        # Magnitude-based demand: weighted anchor pull (a hospital or stadium is
        # worth many small shops). Saturates at DEMAND_INTENSITY_SATURATION so a
        # true downtown core earns full credit while a lone strip mall does not.
        frac = min(1.0, max(0.0, float(intensity)) / DEMAND_INTENSITY_SATURATION)
        demand_pts = round(demand_weight * frac, 2)
        anchor_txt = f", {heavy_anchors} heavy anchor(s)" if heavy_anchors else ""
        notes.append(
            f"Weighted demand intensity {intensity:.0f}{anchor_txt} — "
            f"{demand_pts:.1f} of {demand_weight:.0f} demand credit."
        )
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
    elif dist is not None and dist <= buffer_m:
        demand_pts = demand_weight
    elif dist is None:
        demand_pts = 0.0
        notes.append("No demand generator distance; scoring demand proximity as zero.")
    else:
        # Graduated decay past the buffer instead of a hard cliff: ~50% credit at
        # ~1.25x buffer beyond the edge, fading to zero for genuinely remote sites.
        # Keeps near-miss urban parcels competitive while rural lots earn ~nothing.
        decay = distance_comp_weight(dist - buffer_m, scale_m=buffer_m * 1.25)
        demand_pts = round(demand_weight * decay, 2)
        if demand_pts >= 0.5:
            notes.append(
                f"~{dist:.0f} m from nearest demand generator — partial demand credit "
                f"({demand_pts:.1f} of {demand_weight:.0f})."
            )
        else:
            demand_pts = 0.0
            notes.append("Parcel far outside configured demand-generator buffer.")

    comps = nearby_rate_comps or []
    parking_pts, parking_notes = parking_market_component(comps, pilot)
    notes.extend(parking_notes)

    # Paid-parking market gate: where demand is low, drivers park free on the
    # street and there is no opportunity — regardless of a town centroid nearby.
    # Evidence of a real market: paid comps, a heavy demand anchor, or a dense core.
    market_gate_failed = False
    demand_data_known = intensity is not None or poi_count is not None
    if demand_data_known:
        has_comps = len(comps) > 0
        has_heavy_anchor = heavy_anchors >= 1
        dense_core = (intensity is not None and intensity >= MARKET_GATE_MIN_INTENSITY) or (
            intensity is None and poi_count is not None and poi_count >= MARKET_GATE_MIN_POI_COUNT
        )
        if not (has_comps or has_heavy_anchor or dense_core):
            market_gate_failed = True
            demand_pts = 0.0
            notes.append(
                "No paid-parking market evidence (no rate comps, no heavy demand anchor, "
                "low commercial density) — likely free street parking; scored as no opportunity."
            )

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
    if market_gate_failed:
        total = min(total, MARKET_GATE_SCORE_CAP)
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
        "demand_intensity": intensity,
        "heavy_anchor_count": heavy_anchors or None,
        "market_gate_failed": market_gate_failed,
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

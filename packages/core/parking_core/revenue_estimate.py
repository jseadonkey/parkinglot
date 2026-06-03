"""Illustrative surface-parking revenue from lot layout and weighted nearby rate comps."""

from __future__ import annotations

import statistics
from typing import Any, Literal

from parking_core.pilot import ParkingRateCompObservation
from parking_core.rate_comps import distance_comp_weight, haversine_m

FacilityType = Literal["surface", "garage", "mixed", "unknown"]

_GARAGE_KEYWORDS = (
    "garage",
    "deck",
    "structure",
    "structured",
    "ramp",
    "underground",
    "parking structure",
    "parkade",
)
_SURFACE_KEYWORDS = (
    "surface",
    "surface lot",
    "open air",
    "outdoor",
    "meter",
    "surface parking",
    "valet lot",
    " lot",
    "lot ",
)


def classify_parking_facility(name: str, source_note: str | None = None) -> FacilityType:
    """Heuristic facility type from comp label (for surface-lot comparability)."""
    text = f"{name} {source_note or ''}".lower()
    garage = any(k in text for k in _GARAGE_KEYWORDS)
    surface = any(k in text for k in _SURFACE_KEYWORDS)
    if garage and surface:
        return "mixed"
    if garage:
        return "garage"
    if surface:
        return "surface"
    return "unknown"


def surface_comp_similarity(facility_type: FacilityType) -> float:
    """How comparable a comp is to a surface parking operator (0–1)."""
    return {
        "surface": 1.0,
        "mixed": 0.85,
        "unknown": 0.72,
        "garage": 0.55,
    }[facility_type]


def effective_hourly_for_surface(hourly_mid_usd: float, facility_type: FacilityType) -> float:
    """Adjust structured-parking rates toward open-lot pricing when needed."""
    if facility_type == "garage":
        return hourly_mid_usd * 0.88
    if facility_type == "mixed":
        return hourly_mid_usd * 0.94
    return hourly_mid_usd


def estimate_surface_stalls(
    lot_sqft: float,
    *,
    is_corner_lot: bool = False,
) -> dict[str, float | int]:
    """Estimate stall count range from developable area and typical surface layout."""
    layout_efficiency = 0.62
    if is_corner_lot:
        layout_efficiency += 0.05
    if lot_sqft < 8_000:
        layout_efficiency -= 0.08
    elif lot_sqft > 30_000:
        layout_efficiency += 0.03
    layout_efficiency = max(0.45, min(0.75, layout_efficiency))

    stall_sqft_tight = 280.0
    stall_sqft_mid = 325.0
    stall_sqft_loose = 380.0
    usable_sqft = lot_sqft * layout_efficiency

    return {
        "stalls_low": max(1, int(usable_sqft / stall_sqft_loose)),
        "stalls_mid": max(1, int(usable_sqft / stall_sqft_mid)),
        "stalls_high": max(1, int(usable_sqft / stall_sqft_tight)),
        "layout_efficiency": round(layout_efficiency, 3),
        "usable_sqft": round(usable_sqft, 0),
        "stall_sqft_effective": stall_sqft_mid,
    }


def enrich_rate_comps(
    comps: list[ParkingRateCompObservation],
    *,
    lat: float,
    lon: float,
    distance_scale_m: float = 450.0,
) -> list[dict[str, Any]]:
    """Attach distance, facility type, similarity, and comp weight for revenue math."""
    enriched: list[dict[str, Any]] = []
    for comp in comps:
        distance_m = comp.distance_m
        if distance_m is None:
            distance_m = haversine_m(lat, lon, comp.lat, comp.lon)
        facility_type = classify_parking_facility(comp.name, comp.source_note)
        similarity = surface_comp_similarity(facility_type)
        dist_weight = distance_comp_weight(distance_m, scale_m=distance_scale_m)
        effective_hourly = effective_hourly_for_surface(comp.hourly_mid_usd, facility_type)
        comp_weight = similarity * dist_weight
        enriched.append(
            {
                "name": comp.name,
                "lat": comp.lat,
                "lon": comp.lon,
                "hourly_mid_usd": float(comp.hourly_mid_usd),
                "effective_hourly_usd": round(effective_hourly, 2),
                "source_note": comp.source_note,
                "origin": comp.origin,
                "distance_m": round(float(distance_m), 1),
                "facility_type": facility_type,
                "similarity": round(similarity, 2),
                "distance_weight": round(dist_weight, 3),
                "comp_weight": round(comp_weight, 3),
            },
        )
    enriched.sort(key=lambda row: row["distance_m"])
    return enriched


def weighted_hourly_rate(enriched: list[dict[str, Any]]) -> float | None:
    total_w = sum(float(row["comp_weight"]) for row in enriched)
    if total_w <= 0:
        return None
    return sum(float(row["effective_hourly_usd"]) * float(row["comp_weight"]) for row in enriched) / total_w


def market_evidence_confidence(
    enriched: list[dict[str, Any]],
    *,
    strong_distance_m: float = 750.0,
    min_strong_comps: int = 2,
) -> dict[str, Any]:
    """How much to trust revenue from comp coverage (0–1). Penalizes few/distant comps."""
    n = len(enriched)
    if n == 0:
        return {
            "factor": 0.0,
            "tier": "none",
            "strong_comp_count": 0,
            "nearest_comp_distance_m": None,
            "notes": ["No paid parking comps within search radius."],
        }

    nearest_d = float(enriched[0]["distance_m"])
    strong = [
        row
        for row in enriched
        if float(row["distance_m"]) <= strong_distance_m and float(row["comp_weight"]) >= 0.2
    ]
    strong_n = len(strong)

    if strong_n >= min_strong_comps:
        count_f = 1.0
    elif strong_n == 1:
        count_f = 0.62
    elif n == 1:
        count_f = 0.42
    else:
        count_f = 0.52

    dist_f = distance_comp_weight(nearest_d, scale_m=500.0)
    if n == 1:
        dist_f = max(0.22, min(1.0, dist_f * 1.35))
    else:
        dist_f = max(0.45, dist_f)

    factor = max(0.2, min(1.0, count_f * dist_f))
    if strong_n >= min_strong_comps and nearest_d <= 500.0:
        tier = "high"
    elif factor >= 0.72:
        tier = "moderate"
    elif factor >= 0.45:
        tier = "low"
    else:
        tier = "very_low"

    notes: list[str] = []
    if n == 1:
        notes.append(
            f"Only 1 paid parking comp within radius (~{nearest_d:.0f} m away) — revenue discounted.",
        )
    elif strong_n < min_strong_comps:
        notes.append(
            f"Only {strong_n} comp(s) within {strong_distance_m:.0f} m — "
            f"need {min_strong_comps}+ for full market confidence.",
        )
    if nearest_d > strong_distance_m:
        notes.append(f"Nearest comp is ~{nearest_d:.0f} m — weak local rate evidence.")

    return {
        "factor": round(factor, 3),
        "tier": tier,
        "strong_comp_count": strong_n,
        "nearest_comp_distance_m": round(nearest_d, 1),
        "notes": notes,
    }


def estimate_parking_revenue(
    *,
    lot_sqft: float | None,
    comps: list[ParkingRateCompObservation],
    lat: float | None = None,
    lon: float | None = None,
    is_corner_lot: bool = False,
    hours_per_day: float = 10.0,
    days_per_month: float = 22.0,
    occupancy: float = 0.55,
    distance_scale_m: float = 450.0,
) -> dict[str, Any]:
    """Illustrative gross revenue using layout-based stalls and weighted nearby comps."""
    if lot_sqft is None or lot_sqft <= 0 or not comps:
        return {
            "available": False,
            "reason": "need lot_sqft and at least one parking rate comp",
        }

    stall_info = estimate_surface_stalls(lot_sqft, is_corner_lot=is_corner_lot)
    stalls_mid = int(stall_info["stalls_mid"])
    stalls_low = int(stall_info["stalls_low"])
    stalls_high = int(stall_info["stalls_high"])

    if lat is not None and lon is not None:
        enriched = enrich_rate_comps(comps, lat=lat, lon=lon, distance_scale_m=distance_scale_m)
    else:
        enriched = enrich_rate_comps(
            comps,
            lat=comps[0].lat,
            lon=comps[0].lon,
            distance_scale_m=distance_scale_m,
        )

    raw_rates = sorted(float(c.hourly_mid_usd) for c in comps)
    hourly_median = float(statistics.median(raw_rates))
    hourly_weighted = weighted_hourly_rate(enriched)
    hourly_used = hourly_weighted if hourly_weighted is not None else hourly_median

    def _monthly(stalls: int, hourly: float) -> float:
        return stalls * hourly * hours_per_day * days_per_month * occupancy

    monthly_raw = _monthly(stalls_mid, hourly_used)

    confidence = market_evidence_confidence(enriched)
    conf_f = float(confidence["factor"])
    spread = 1.35 if confidence["tier"] in ("very_low", "low") else 1.12

    monthly_mid = monthly_raw * conf_f
    monthly_low = monthly_raw * conf_f * (0.72 if conf_f < 0.75 else 0.88)
    monthly_high = monthly_raw * min(1.08, conf_f * spread)

    primary_comps = [row for row in enriched if row["comp_weight"] >= 0.15][:6]

    return {
        "available": True,
        "stalls_estimated": stalls_mid,
        "stalls_low": stalls_low,
        "stalls_high": stalls_high,
        "layout_efficiency": stall_info["layout_efficiency"],
        "usable_sqft": stall_info["usable_sqft"],
        "stall_sqft_effective": stall_info["stall_sqft_effective"],
        "hourly_rate_median_usd": round(hourly_median, 2),
        "hourly_rate_weighted_usd": round(hourly_used, 2),
        "hourly_rate_min_usd": round(raw_rates[0], 2),
        "hourly_rate_max_usd": round(raw_rates[-1], 2),
        "comp_count": len(comps),
        "comps_weighted": enriched,
        "primary_comps": primary_comps,
        "monthly_gross_raw_usd": round(monthly_raw, 0),
        "monthly_gross_usd": round(monthly_mid, 0),
        "monthly_gross_low_usd": round(monthly_low, 0),
        "monthly_gross_high_usd": round(monthly_high, 0),
        "annual_gross_usd": round(monthly_mid * 12, 0),
        "market_confidence": conf_f,
        "market_confidence_tier": confidence["tier"],
        "strong_comp_count": confidence["strong_comp_count"],
        "nearest_comp_distance_m": confidence["nearest_comp_distance_m"],
        "market_evidence_notes": confidence["notes"],
        "assumptions": {
            "hours_per_day": hours_per_day,
            "days_per_month": days_per_month,
            "occupancy": occupancy,
            "distance_scale_m": distance_scale_m,
            "is_corner_lot": is_corner_lot,
            "market_confidence_factor": conf_f,
        },
    }

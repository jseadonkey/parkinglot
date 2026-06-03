"""Demand proxies for revenue occupancy when paid parking rate comps are sparse."""

from __future__ import annotations

import math
from typing import Any

from parking_core.rate_comps import distance_comp_weight


def demand_occupancy_factor(
    distance_m: float | None,
    *,
    buffer_m: float = 400.0,
    min_factor: float = 0.35,
    peak_factor: float = 1.05,
) -> tuple[float, list[str]]:
    """Scale base occupancy by proximity to the nearest demand-generator POI (0.35–1.05×)."""
    if buffer_m <= 0:
        buffer_m = 400.0
    if distance_m is None:
        return min_factor, ["No demand-generator distance — using low occupancy assumption."]

    d = max(0.0, float(distance_m))
    if d <= buffer_m:
        t = d / buffer_m
        factor = peak_factor - (peak_factor - 0.75) * t
        if d <= buffer_m * 0.25:
            note = f"Within ~{d:.0f} m of a demand generator — high parking demand assumed."
        else:
            note = f"Inside {buffer_m:.0f} m demand buffer (~{d:.0f} m) — elevated occupancy."
        return round(factor, 3), [note]

    beyond = d - buffer_m
    decay = distance_comp_weight(beyond, scale_m=buffer_m * 1.25)
    factor = max(min_factor, 0.75 * decay)
    return round(factor, 3), [
        f"~{d:.0f} m from nearest demand generator — occupancy reduced for distance.",
    ]


def poi_density_occupancy_factor(
    poi_count: int | None,
    *,
    saturation_count: float = 12.0,
    min_factor: float = 0.40,
    max_factor: float = 1.05,
) -> tuple[float, list[str]]:
    """Scale occupancy from OSM commercial POI count within a radius (saturating curve)."""
    if poi_count is None:
        return min_factor, ["POI density not computed — run POST /internal/metrics/refresh-poi-density."]
    count = max(0, int(poi_count))
    scale = max(1.0, float(saturation_count))
    t = 1.0 - math.exp(-count / scale)
    factor = min_factor + t * (max_factor - min_factor)
    if count == 0:
        note = "No commercial POIs in OSM within radius — low local demand assumed."
    elif count <= 3:
        note = f"{count} commercial POI(s) nearby — modest demand."
    elif count <= 12:
        note = f"{count} commercial POIs nearby — moderate demand."
    else:
        note = f"{count} commercial POIs nearby — strong retail/service demand."
    return round(factor, 3), [note]


def combined_demand_occupancy_factor(
    *,
    distance_to_nearest_demand_m: float | None,
    poi_commercial_count: int | None,
    demand_buffer_m: float = 400.0,
    poi_saturation_count: float = 12.0,
) -> tuple[float, list[str], dict[str, Any]]:
    """Blend generator proximity and OSM POI density into one occupancy multiplier."""
    gen_f, gen_notes = demand_occupancy_factor(
        distance_to_nearest_demand_m,
        buffer_m=demand_buffer_m,
    )
    poi_f, poi_notes = poi_density_occupancy_factor(
        poi_commercial_count,
        saturation_count=poi_saturation_count,
    )

    has_gen = distance_to_nearest_demand_m is not None
    has_poi = poi_commercial_count is not None

    if has_gen and has_poi:
        combined = max(0.35, min(1.08, math.sqrt(gen_f * poi_f) * 1.03))
        notes = gen_notes + poi_notes + [
            f"Combined demand signal: generator × POI density → occupancy factor {combined:.2f}.",
        ]
    elif has_poi:
        combined = poi_f
        notes = poi_notes
    else:
        combined = gen_f
        notes = gen_notes

    return round(combined, 3), notes, {
        "generator_occupancy_factor": gen_f,
        "poi_density_occupancy_factor": poi_f if has_poi else None,
        "poi_commercial_count": poi_commercial_count,
    }

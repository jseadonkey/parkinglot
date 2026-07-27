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


def intensity_occupancy_factor(
    intensity: float | None,
    *,
    heavy_anchors: int | None = None,
    saturation_intensity: float = 25.0,
    min_factor: float = 0.40,
    max_factor: float = 1.12,
) -> tuple[float, list[str]]:
    """Scale occupancy from weighted demand intensity (hospitals/stadiums count more than shops).

    Intensity is the OSM pull weight used for scoring and shortlist ranking. Saturation
    aligns with the strong-demand band (~25) so large anchors drive near-peak occupancy.
    """
    if intensity is None and heavy_anchors is None:
        return min_factor, ["Demand intensity not computed — run POI density refresh."]

    inten = max(0.0, float(intensity or 0.0))
    heavy = max(0, int(heavy_anchors or 0))
    scale = max(1.0, float(saturation_intensity))
    t = 1.0 - math.exp(-inten / scale)
    factor = min_factor + t * (max_factor - min_factor)
    if heavy >= 1:
        # One hospital/stadium/university nearby should not look like a quiet strip mall.
        factor = max(factor, min(max_factor, 0.98 + 0.04 * min(heavy, 3)))

    if heavy >= 1 and inten >= 25:
        note = (
            f"Heavy demand anchors ({heavy}) with intensity {inten:.0f} — "
            "peak parking occupancy assumed."
        )
    elif heavy >= 1:
        note = f"{heavy} heavy demand anchor(s) nearby (intensity {inten:.0f}) — strong occupancy."
    elif inten >= 25:
        note = f"High demand intensity ({inten:.0f}) — strong local parking pull."
    elif inten >= 10:
        note = f"Moderate demand intensity ({inten:.0f}) — solid occupancy support."
    elif inten > 0:
        note = f"Low demand intensity ({inten:.0f}) — occupancy tempered."
    else:
        note = "No weighted demand intensity nearby — low occupancy assumed."

    return round(min(max_factor, factor), 3), [note]


def combined_demand_occupancy_factor(
    *,
    distance_to_nearest_demand_m: float | None,
    poi_commercial_count: int | None,
    demand_buffer_m: float = 400.0,
    poi_saturation_count: float = 12.0,
    poi_demand_intensity: float | None = None,
    poi_heavy_anchor_count: int | None = None,
    intensity_saturation: float = 25.0,
) -> tuple[float, list[str], dict[str, Any]]:
    """Blend generator proximity with intensity (preferred) or raw POI count."""
    gen_f, gen_notes = demand_occupancy_factor(
        distance_to_nearest_demand_m,
        buffer_m=demand_buffer_m,
    )

    has_gen = distance_to_nearest_demand_m is not None
    has_intensity = poi_demand_intensity is not None or poi_heavy_anchor_count is not None
    has_poi = poi_commercial_count is not None

    intensity_f: float | None = None
    poi_f: float | None = None
    size_notes: list[str] = []

    if has_intensity:
        intensity_f, size_notes = intensity_occupancy_factor(
            poi_demand_intensity,
            heavy_anchors=poi_heavy_anchor_count,
            saturation_intensity=intensity_saturation,
        )
        size_f = intensity_f
    elif has_poi:
        poi_f, size_notes = poi_density_occupancy_factor(
            poi_commercial_count,
            saturation_count=poi_saturation_count,
        )
        size_f = poi_f
    else:
        size_f = None

    if has_gen and size_f is not None:
        # Intensity can peak higher than raw POI (1.12); keep blend in a sane band.
        combined = max(0.35, min(1.15, math.sqrt(gen_f * size_f) * 1.03))
        label = "intensity" if has_intensity else "POI density"
        notes = gen_notes + size_notes + [
            f"Combined demand signal: generator × {label} → occupancy factor {combined:.2f}.",
        ]
    elif size_f is not None:
        combined = size_f
        notes = size_notes
    else:
        combined = gen_f
        notes = gen_notes

    if not has_intensity and has_poi:
        poi_f = size_f

    return round(combined, 3), notes, {
        "generator_occupancy_factor": gen_f,
        "poi_density_occupancy_factor": poi_f,
        "intensity_occupancy_factor": intensity_f,
        "poi_commercial_count": poi_commercial_count,
        "poi_demand_intensity": (
            round(float(poi_demand_intensity), 1) if poi_demand_intensity is not None else None
        ),
        "poi_heavy_anchor_count": (
            int(poi_heavy_anchor_count) if poi_heavy_anchor_count is not None else None
        ),
    }

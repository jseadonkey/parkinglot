"""Paid parking rate comp merge, proximity filter, and scoring contribution."""

from __future__ import annotations

import math
import statistics

from parking_core.pilot import ParkingRateCompObservation, PilotConfig


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_comp_weight(distance_m: float, *, scale_m: float = 450.0) -> float:
    """Smooth inverse-distance weight; ~50% at ``scale_m``."""
    d = max(0.0, float(distance_m))
    return 1.0 / (1.0 + (d / scale_m) ** 2)


def rate_comp_key(comp: ParkingRateCompObservation) -> tuple[str, float, float]:
    return (comp.name, round(comp.lat, 5), round(comp.lon, 5))


def merge_rate_comp_sequences(
    primary: list[ParkingRateCompObservation],
    secondary: list[ParkingRateCompObservation],
) -> list[ParkingRateCompObservation]:
    """Merge comp lists; ``primary`` wins on duplicate (name, lat, lon)."""
    out = list(primary)
    seen = {rate_comp_key(c) for c in primary}
    for comp in secondary:
        key = rate_comp_key(comp)
        if key in seen:
            continue
        seen.add(key)
        out.append(comp)
    return out


def filter_comps_within_radius(
    comps: list[ParkingRateCompObservation],
    *,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[ParkingRateCompObservation]:
    """Keep comps within ``radius_m`` of ``(lat, lon)``, sorted nearest first."""
    within: list[tuple[float, ParkingRateCompObservation]] = []
    for comp in comps:
        d = haversine_m(lat, lon, comp.lat, comp.lon)
        if d <= radius_m:
            within.append((d, comp))
    within.sort(key=lambda x: x[0])
    return [c.model_copy(update={"distance_m": d}) for d, c in within]


def lookup_parking_rate_fallback(
    pilot: PilotConfig,
    county_fips: str | None,
) -> tuple[float, str] | None:
    """County-specific or default indicative hourly rate when local comps are missing."""
    cfg = pilot.scoring.parking_rate_fallbacks
    if cfg is None:
        return None
    if county_fips:
        entry = cfg.counties.get(county_fips)
        if entry is not None:
            note = entry.source_note or f"County {county_fips} indicative surface rate"
            return float(entry.hourly_mid_usd), note
    if cfg.default_hourly_mid_usd > 0:
        note = cfg.default_source_note or "Pilot default indicative surface rate"
        return float(cfg.default_hourly_mid_usd), note
    return None


def _nearest_comp_distance_m(comps: list[ParkingRateCompObservation]) -> float | None:
    distances = [float(c.distance_m) for c in comps if c.distance_m is not None]
    return min(distances) if distances else None


def _distance_market_multiplier(
    comps: list[ParkingRateCompObservation],
    *,
    strong_distance_m: float = 750.0,
) -> tuple[float, str | None]:
    """Reduce market score when comps are sparse or far (aligns with revenue confidence)."""
    n = len(comps)
    if n == 0:
        return 0.0, None
    nearest = _nearest_comp_distance_m(comps)
    if nearest is None:
        return 1.0, None
    strong = sum(
        1
        for c in comps
        if c.distance_m is not None and float(c.distance_m) <= strong_distance_m
    )
    dist_mult = max(0.25, min(1.0, distance_comp_weight(nearest, scale_m=500.0) * (1.25 if n == 1 else 1.0)))
    if strong >= 2 and nearest <= 500.0:
        return 1.0, None
    if n == 1:
        return dist_mult, f"nearest comp ~{nearest:.0f} m — distance haircut on market score."
    if nearest > strong_distance_m:
        return max(0.55, dist_mult), f"nearest comp ~{nearest:.0f} m — weak local market evidence."
    return max(0.75, dist_mult), None


def parking_market_component(
    comps: list[ParkingRateCompObservation],
    pilot: PilotConfig,
) -> tuple[float, list[str]]:
    """Score contribution from multiple nearby paid parking benchmarks (0 – weight cap)."""
    cfg = pilot.scoring
    weight = float(getattr(cfg.weights, "near_paid_parking_comps", 0) or 0)
    if weight <= 0:
        return 0.0, []

    min_full = int(getattr(cfg, "parking_rate_comp_min_for_full_credit", 2) or 2)
    max_used = int(getattr(cfg, "parking_rate_comp_max_used", 8) or 8)
    used = comps[:max_used]
    n = len(used)

    if n == 0:
        return 0.0, ["No paid parking rate comps within radius — market component zero."]

    rates = [float(c.hourly_mid_usd) for c in used]
    median_rate = float(statistics.median(rates))
    dist_mult, dist_note = _distance_market_multiplier(used)

    if n == 1:
        pts = weight * 0.5 * dist_mult
        notes = [
            f"1 nearby paid parking comp ({used[0].name}, ${median_rate:.2f}/hr); "
            f"need {min_full}+ comps for full market credit.",
        ]
        if dist_note:
            notes.append(dist_note)
        return pts, notes

    fraction = min(1.0, n / max(min_full, 1))
    pts = weight * fraction * dist_mult
    preview = ", ".join(f"{c.name} (${c.hourly_mid_usd:.0f}/hr)" for c in used[:4])
    extra = f"; +{n - 4} more" if n > 4 else ""
    notes = [
        f"{n} nearby paid parking comps — {preview}{extra}; median ${median_rate:.2f}/hr.",
    ]
    if dist_note:
        notes.append(dist_note)
    return pts, notes

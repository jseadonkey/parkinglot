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

    if n == 1:
        pts = weight * 0.5
        notes = [
            f"1 nearby paid parking comp ({used[0].name}, ${median_rate:.2f}/hr); "
            f"need {min_full}+ comps for full market credit.",
        ]
        return pts, notes

    fraction = min(1.0, n / max(min_full, 1))
    pts = weight * fraction
    preview = ", ".join(f"{c.name} (${c.hourly_mid_usd:.0f}/hr)" for c in used[:4])
    extra = f"; +{n - 4} more" if n > 4 else ""
    notes = [
        f"{n} nearby paid parking comps — {preview}{extra}; median ${median_rate:.2f}/hr.",
    ]
    return pts, notes

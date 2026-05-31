"""Assessor building vs land value — skip built-out parcels before expensive metrics."""

from __future__ import annotations

from typing import Any


def _assessor_float(props: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = props.get(key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def building_value_share(props: dict[str, Any]) -> float | None:
    """Building value / (land + building). None when assessor values missing."""
    land = _assessor_float(props, "VALUE_LAND", "value_land")
    bldg = _assessor_float(props, "VALUE_BLDG", "value_bldg")
    if land is None and bldg is None:
        return None
    land_v = land or 0.0
    bldg_v = bldg or 0.0
    total = land_v + bldg_v
    if total <= 0:
        return None
    return bldg_v / total


def building_value_prescreen_pass(
    props: dict[str, Any] | None,
    *,
    max_building_share: float = 0.70,
) -> bool:
    """True when parcel is not dominated by improvement/building assessed value.

    Missing assessor values → pass (do not reject on unknown).
    """
    if not props:
        return True
    share = building_value_share(props)
    if share is None:
        return True
    return share <= max_building_share

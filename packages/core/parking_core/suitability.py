"""Site suitability from assessor value fields (vacant / underutilized detection).

WaTech (and most county assessor) parcel exports carry building and land market
values plus a land-use code. We use those to flag parcels that are physically
promising for a surface lot *before* zoning entitlement is curated:

- ``vacant``        — no building value (or a vacant land-use code): a bare lot.
- ``underutilized`` — small building value relative to land (teardown candidate).
- ``improved``      — meaningful structure present.
- ``unknown``       — no value fields available to judge.

This is deterministic and reads only ``raw_properties`` already stored at ingest,
so it works statewide with no new data source and no schema migration.
"""

from __future__ import annotations

from typing import Any

# A building worth <= this fraction of (building + land) value reads as
# "barely improved" — a likely teardown / underutilized parking candidate.
UNDERUTILIZED_MAX_IMPROVEMENT_RATIO: float = 0.15

_BLDG_VALUE_KEYS: tuple[str, ...] = (
    "VALUE_BLDG",
    "value_bldg",
    "BLDG_VALUE",
    "IMP_VALUE",
    "IMPROVEMENT_VALUE",
    "IMPRVALUE",
    "IMPR_VAL",
    "BLDGVAL",
    "IMPROV_VAL",
    "IMPROVEMENTS",
)
_LAND_VALUE_KEYS: tuple[str, ...] = (
    "VALUE_LAND",
    "value_land",
    "LAND_VALUE",
    "LANDVAL",
    "LAND_VAL",
    "ASSD_LAND_VAL",
)
_LANDUSE_KEYS: tuple[str, ...] = (
    "LANDUSE_CD",
    "landuse_cd",
    "ORIG_LANDUSE_CD",
    "orig_landuse_cd",
    "LAND_USE",
    "LANDUSE",
    "land_use",
    "USE_CODE",
    "USECODE",
    "PROPERTY_USE",
    "LU_CODE",
    "GIS_LU_CODE",
)

# Land-use description tokens that indicate a bare / undeveloped lot.
_VACANT_USE_TOKENS: tuple[str, ...] = ("VACANT", "UNIMPROVED", "UNDEVELOPED")

VACANT = "vacant"
UNDERUTILIZED = "underutilized"
IMPROVED = "improved"
UNKNOWN = "unknown"


def _num(props: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in props and props[key] is not None:
            try:
                return float(str(props[key]).replace(",", "").replace("$", "").strip())
            except (TypeError, ValueError):
                continue
    return None


def _text(props: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in props and props[key] is not None:
            value = str(props[key]).strip()
            if value:
                return value
    return None


def compute_parcel_suitability(raw_properties: dict[str, Any] | None) -> dict[str, Any]:
    """Derive vacancy / underutilization signals from assessor value fields.

    Returns a dict with ``suitability`` (vacant | underutilized | improved | unknown),
    ``is_vacant_land`` (bool), ``improvement_ratio`` (bldg / (bldg + land)), and the
    raw ``land_value`` / ``improvement_value`` / ``land_use_code`` used to derive it.
    """
    props = raw_properties or {}
    bldg = _num(props, _BLDG_VALUE_KEYS)
    land = _num(props, _LAND_VALUE_KEYS)
    use = _text(props, _LANDUSE_KEYS)
    use_upper = (use or "").upper()

    improvement_ratio: float | None = None
    if bldg is not None and land is not None:
        denom = bldg + land
        if denom > 0:
            improvement_ratio = bldg / denom

    vacant_by_value = bldg is not None and bldg <= 0 and (land or 0) > 0
    vacant_by_use = any(tok in use_upper for tok in _VACANT_USE_TOKENS)
    is_vacant = bool(vacant_by_value or vacant_by_use)

    if is_vacant:
        category = VACANT
    elif improvement_ratio is not None and improvement_ratio <= UNDERUTILIZED_MAX_IMPROVEMENT_RATIO:
        category = UNDERUTILIZED
    elif improvement_ratio is not None:
        category = IMPROVED
    else:
        category = UNKNOWN

    return {
        "land_value": land,
        "improvement_value": bldg,
        "improvement_ratio": improvement_ratio,
        "land_use_code": use,
        "is_vacant_land": is_vacant,
        "suitability": category,
    }


def suitability_category(raw_properties: dict[str, Any] | None) -> str:
    """Convenience: just the vacant/underutilized/improved/unknown bucket."""
    return str(compute_parcel_suitability(raw_properties)["suitability"])

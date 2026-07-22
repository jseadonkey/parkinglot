"""Site suitability from assessor value fields (vacant / underutilized / existing parking).

WaTech (and most county assessor) parcel exports carry building and land market
values plus a land-use code. We use those to flag parcels that are physically
promising for a surface lot *before* zoning entitlement is curated:

- ``existing_parking`` — assessor already classifies the site as parking (poor
  fit if we are hunting bare / teardown pads rather than operating lots).
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

# SLUCM (Standard Land Use Coding Manual) 2-digit codes, used by the WA
# statewide parcel export for most counties (this is why DOR class 46 =
# automobile parking works). Major category 9 = undeveloped land / water, where
# ``91`` is developable bare land. Major categories 2-7 (manufacturing,
# transportation/communication/utilities, trade, services, cultural/recreation)
# are *developed* uses that carry a real structure when in use — so a $0
# building value there means the parcel is tax-exempt / unassessed (government,
# church, school, utility, tribal), NOT an available bare pad. Counties that
# kept their own non-SLUCM code schemes (e.g. Clark's 3-digit codes) do not
# match and are left to the aerial rooftop backstop.
_SLUCM_UNDEVELOPED_VACANT: frozenset[str] = frozenset({"91"})
_SLUCM_DEVELOPED_MAJOR: frozenset[str] = frozenset({"2", "3", "4", "5", "6", "7"})

# Washington DOR property class (WAC 458-53-030): 46 = Automobile parking.
_WA_DOR_PARKING = {"46"}
# King County Present Use codes commonly seen as ORIG_LANDUSE_CD tails (e.g. 33-180).
_KING_PARKING_PRESENT_USE = {"159", "180", "182"}
# King County Present Use codes that mean undeveloped land (true vacant lots).
_KING_VACANT_PRESENT_USE = {"299", "300", "301", "309", "316"}
# Full King Present Use codebook (kca102). When LANDUSE_CD matches one of these,
# $0 building value alone is not enough — only the vacant codes above count.
_KING_PRESENT_USE_CODES = frozenset(
    {
        "2", "3", "4", "5", "6", "7", "8", "9", "11", "16", "17", "18", "20", "25", "29",
        "38", "48", "49", "51", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64",
        "96", "101", "104", "105", "106", "118", "122", "126", "130", "137", "138", "140",
        "141", "142", "143", "145", "146", "147", "149", "150", "152", "153", "156", "157",
        "159", "160", "161", "162", "163", "165", "166", "167", "168", "171", "172", "173",
        "179", "180", "182", "183", "184", "185", "186", "188", "189", "190", "191", "193",
        "194", "195", "202", "210", "216", "223", "245", "246", "247", "252", "261", "262",
        "263", "264", "266", "267", "271", "272", "273", "274", "275", "276", "277", "278",
        "279", "280", "299", "300", "301", "309", "316", "323", "324", "325", "326", "327",
        "328", "330", "331", "332", "333", "334", "335", "336", "337", "339", "340", "341",
        "342",
    }
)
# King Present Use codes that are not developable surface-lot sites even when
# VALUE_BLDG is $0 (ROW, water, parks, utilities, forest/open-space tax classes).
_KING_NON_DEVELOPABLE_PRESENT_USE = {
    "149",  # Park, Public
    "150",  # Park, Private
    "266",  # Utility, Public
    "267",  # Utility, Private
    "323",  # Reforestation
    "324",  # Forest Land (class)
    "325",  # Forest Land (desig)
    "326",  # Open Space (curr use)
    "327",  # Open Space (agric)
    "328",  # Open Space timber/greenbelt
    "330",  # Easement
    "331",  # Reserve/Wilderness
    "332",  # Right Of Way / Utility / Road
    "333",  # River/Creek/Stream
    "334",  # Tideland 1st
    "335",  # Tideland 2nd
    "336",  # Transferable Dev Rights
    "337",  # Water Body, Fresh
}
_NON_DEVELOPABLE_USE_TOKENS: tuple[str, ...] = (
    "RIGHT OF WAY",
    "RIGHT-OF-WAY",
    "EASEMENT",
    "TIDELAND",
    "WATER BODY",
    "RESERVE/WILDERNESS",
    "REFORESTATION",
    "FOREST LAND",
    "OPEN SPACE",
)
# Text tokens (assessor descriptions / Baltimore use strings).
_PARKING_USE_TOKENS: tuple[str, ...] = (
    "AUTOMOBILE PARKING",
    "PARKING LOT",
    "COMMERCIAL PARKING",
    "PARKING (COMMERCIAL",
    "PARKING (ASSOC",
    "PARKING GARAGE",
    "PARKING STRUCTURE",
    "SURFACE PARKING",
)

VACANT = "vacant"
UNDERUTILIZED = "underutilized"
IMPROVED = "improved"
EXISTING_PARKING = "existing_parking"
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


def _present_use_tail(code: str) -> str:
    """``33-180`` → ``180``; bare ``180`` stays ``180``."""
    text = code.strip()
    if "-" in text:
        return text.rsplit("-", 1)[-1].strip()
    return text


def _use_blob(props: dict[str, Any]) -> str:
    """Uppercased concat of common land-use / present-use fields."""
    parts: list[str] = []
    for key in (
        *_LANDUSE_KEYS,
        "USEGROUP",
        "SDATCODE",
        "DHCDUSE1",
        "DHCDUSE2",
        "DHCDUSE3",
        "DHCDUSE4",
        "PRESENT_USE",
        "PresentUse",
    ):
        val = props.get(key)
        if val is not None and str(val).strip():
            parts.append(str(val))
    return " ".join(parts).upper()


def _king_present_use_code(raw_properties: dict[str, Any] | None) -> str | None:
    """Return King-style Present Use code when LANDUSE_CD / ORIG looks numeric."""
    props = raw_properties or {}
    for key in ("LANDUSE_CD", "landuse_cd", "ORIG_LANDUSE_CD", "orig_landuse_cd"):
        raw = _text(props, (key,))
        if raw is None:
            continue
        tail = _present_use_tail(raw)
        if tail.isdigit():
            return tail
    return None


def _slucm_two_digit_code(raw_properties: dict[str, Any] | None) -> str | None:
    """Return a 2-digit SLUCM land-use code when present (e.g. ``91``, ``53``)."""
    props = raw_properties or {}
    for key in ("LANDUSE_CD", "landuse_cd", "ORIG_LANDUSE_CD", "orig_landuse_cd"):
        raw = _text(props, (key,))
        if raw is None:
            continue
        tail = _present_use_tail(raw)
        if tail.isdigit() and len(tail) == 2:
            return tail
    return None


def is_existing_parking_use(raw_properties: dict[str, Any] | None) -> bool:
    """True when assessor land-use already says this parcel is parking."""
    props = raw_properties or {}
    for key in ("LANDUSE_CD", "landuse_cd", "ORIG_LANDUSE_CD", "orig_landuse_cd"):
        raw = _text(props, (key,))
        if raw is None:
            continue
        code = raw.strip()
        if code in _WA_DOR_PARKING:
            return True
        # King often stores Present Use directly in LANDUSE_CD (159/180/182).
        if code in _KING_PARKING_PRESENT_USE or _present_use_tail(code) in _KING_PARKING_PRESENT_USE:
            return True
    blob = _use_blob(props)
    return any(tok in blob for tok in _PARKING_USE_TOKENS)


def is_non_developable_use(raw_properties: dict[str, Any] | None) -> bool:
    """True for ROW, water, parks, utilities, forest/open-space — not a buildable lot."""
    props = raw_properties or {}
    for key in ("LANDUSE_CD", "landuse_cd", "ORIG_LANDUSE_CD", "orig_landuse_cd"):
        raw = _text(props, (key,))
        if raw is None:
            continue
        code = raw.strip()
        tail = _present_use_tail(code)
        if code in _KING_NON_DEVELOPABLE_PRESENT_USE or tail in _KING_NON_DEVELOPABLE_PRESENT_USE:
            return True
    blob = _use_blob(props)
    return any(tok in blob for tok in _NON_DEVELOPABLE_USE_TOKENS)


def compute_parcel_suitability(raw_properties: dict[str, Any] | None) -> dict[str, Any]:
    """Derive vacancy / underutilization / existing-parking signals from assessor fields.

    Returns a dict with ``suitability`` (existing_parking | vacant | underutilized |
    improved | unknown), ``is_vacant_land``, ``is_existing_parking``,
    ``improvement_ratio``, and the raw value / land-use fields used.
    """
    props = raw_properties or {}
    bldg = _num(props, _BLDG_VALUE_KEYS)
    land = _num(props, _LAND_VALUE_KEYS)
    use = _text(props, _LANDUSE_KEYS)
    use_upper = (use or "").upper()
    existing_parking = is_existing_parking_use(props)
    non_developable = is_non_developable_use(props)

    improvement_ratio: float | None = None
    if bldg is not None and land is not None:
        denom = bldg + land
        if denom > 0:
            improvement_ratio = bldg / denom

    vacant_by_value = bldg is not None and bldg <= 0 and (land or 0) > 0
    vacant_by_use = any(tok in use_upper for tok in _VACANT_USE_TOKENS)
    # Baltimore RealProperty flags (merged at ingest when PIN matches).
    vacind = str(props.get("VACIND") or "").strip().upper()
    no_imprv = str(props.get("NO_IMPRV") or "").strip().upper()
    if vacind == "Y" or no_imprv in ("Y", "1", "TRUE"):
        vacant_by_use = True
    king_use = _king_present_use_code(props)
    if king_use is not None and king_use in _KING_PRESENT_USE_CODES:
        # King stores Present Use in LANDUSE_CD. $0 building on a coded office /
        # government / residential use is not a bare lot — require vacant codes.
        if king_use in _KING_VACANT_PRESENT_USE:
            vacant_by_use = True
        elif king_use not in _KING_PARKING_PRESENT_USE and king_use not in _KING_NON_DEVELOPABLE_PRESENT_USE:
            vacant_by_value = False
    else:
        # Statewide SLUCM counties: trust the undeveloped-land code, but do not
        # let a $0 building value alone mark a developed-use parcel as vacant —
        # that pattern is dominated by tax-exempt / unassessed public sites.
        slucm = _slucm_two_digit_code(props)
        if slucm is not None:
            if slucm in _SLUCM_UNDEVELOPED_VACANT:
                vacant_by_use = True
            elif slucm[0] in _SLUCM_DEVELOPED_MAJOR:
                vacant_by_value = False
    # ROW / water / park / utility with $0 building is not a vacant lot to convert.
    is_vacant = bool((vacant_by_value or vacant_by_use) and not non_developable)

    # Existing parking wins even when building value is $0 (common for open lots).
    if existing_parking:
        category = EXISTING_PARKING
    elif is_vacant:
        category = VACANT
    elif non_developable:
        category = UNKNOWN
    elif (
        bldg is not None
        and bldg > 0
        and improvement_ratio is not None
        and improvement_ratio <= UNDERUTILIZED_MAX_IMPROVEMENT_RATIO
    ):
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
        "is_vacant_land": is_vacant and not existing_parking,
        "is_existing_parking": existing_parking,
        "suitability": category,
    }


def suitability_category(raw_properties: dict[str, Any] | None) -> str:
    """Convenience: just the vacant/underutilized/improved/existing_parking/unknown bucket."""
    return str(compute_parcel_suitability(raw_properties)["suitability"])

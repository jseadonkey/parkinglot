"""Detect likely government / public-agency ownership from assessor owner names.

Private ground-lease deals are rarely viable on city, county, state, federal,
port, school-district, or transit-owned land — those parcels should score low
and rank last on operator shortlists.
"""

from __future__ import annotations

from typing import Any

# Explicit flag we persist after assessor lookup / enrichment.
_GOV_FLAG_KEYS = ("OWNER_GOVERNMENT", "owner_government", "IS_GOVERNMENT_OWNER")

# Taxpayer / owner display-name patterns (case-insensitive substring match).
# Hyphens/punctuation are normalized to spaces before matching.
_GOVERNMENT_NAME_MARKERS: tuple[str, ...] = (
    "CITY OF",
    "TOWN OF",
    "COUNTY OF",
    "STATE OF",
    "UNITED STATES",
    "U.S.A",
    "USA ",
    " US ",
    "KING COUNTY",
    "PIERCE COUNTY",
    "SNOHOMISH COUNTY",
    "CLARK COUNTY",
    "SPOKANE COUNTY",
    "THURSTON COUNTY",
    "WHATCOM COUNTY",
    "KITSAP COUNTY",
    "YAKIMA COUNTY",
    "BENTON COUNTY",
    "FRANKLIN COUNTY",
    "WA STATE",
    "WASHINGTON STATE",
    "STATE OF WASHINGTON",
    "PORT OF",
    "SCHOOL DIST",
    "SCHOOL DISTRICT",
    "PUBLIC SCHOOLS",
    "HOUSING AUTH",
    "HOUSING AUTHORITY",
    "SOUND TRANSIT",
    "METRO TRANSIT",
    "DEPARTMENT OF",
    "DEPT OF",
    "FMD FACILITIES",
    "FACILITIES MGMT",
    "FACILITIES MANAGEMENT",
    "PARKS DEPT",
    "PARK DISTRICT",
    "FIRE DIST",
    "FIRE DISTRICT",
    "LIBRARY DIST",
    "UTILITY DIST",
    "PUD ",
    "PUBLIC UTILITY",
    "IRRIGATION DIST",
    "RECLAMATION",
    "BUREAU OF",
    "BOARD OF REGENTS",
    "UNIVERSITY OF WASHINGTON",
    "WASHINGTON STATE UNIVERSITY",
    "COMMUNITY COLLEGE",
    "TECHNICAL COLLEGE",
)

_OWNER_NAME_KEYS = (
    "OWNER_NAME",
    "owner_name",
    "TAXPAYER_NAME",
    "taxpayer_name",
    "OWNERNAME",
    "OWNERNME",
    "TaxpayerName",
)


def owner_name_from_properties(raw_properties: dict[str, Any] | None) -> str | None:
    """Best-effort owner / taxpayer display name from assessor props."""
    props = raw_properties or {}
    for key in _OWNER_NAME_KEYS:
        raw = props.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def is_government_owner_name(owner_name: str | None) -> bool:
    """True when the recorded owner name looks like a public agency."""
    if not owner_name:
        return False
    # Pad so edge markers like "USA " / " US " match cleanly.
    upper = f" {owner_name.upper()} "
    for ch in (",", ".", "-", "/", "\\", "_", "(", ")", "[", "]", "'", '"'):
        upper = upper.replace(ch, " ")
    while "  " in upper:
        upper = upper.replace("  ", " ")
    return any(marker in upper for marker in _GOVERNMENT_NAME_MARKERS)


def government_owner_from_properties(
    raw_properties: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """Return ``(is_government, owner_name)`` from parcel ``raw_properties``.

    An explicit ``OWNER_GOVERNMENT=true`` forces a positive match. A stored
    ``false`` does **not** override name patterns (scrapers sometimes stamp
    false before classifying).
    """
    props = raw_properties or {}
    owner = owner_name_from_properties(props)

    for key in _GOV_FLAG_KEYS:
        raw = props.get(key)
        if isinstance(raw, bool) and raw:
            return True, owner
        if isinstance(raw, str) and raw.strip().lower() in ("true", "1", "yes", "y"):
            return True, owner
        if isinstance(raw, int | float) and int(raw) == 1:
            return True, owner

    return is_government_owner_name(owner), owner

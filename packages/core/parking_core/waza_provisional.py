"""Provisional surface-parking prospect signal from WAZA zone classification.

WAZA ``WAZAZoneGeneral`` is a statewide standardized category (COM / MXU / IND / …).
We use it only when counsel has not curated a jurisdiction YAML entry — never to set
``zoning_allows_surface_parking=true``. Humans still review before owner outreach.
"""

from __future__ import annotations

from typing import Any

# Commerce WAZA general classifications where surface parking is often feasible
# (commercial, mixed-use, industrial). Residential / rural / resource stay out.
PROVISIONAL_WAZA_GENERAL: frozenset[str] = frozenset({"COM", "MXU", "IND"})

# Principal-use symbol for scoring / UI (partial credit, not permitted-by-right).
PROVISIONAL_SYMBOL = "PV"


def waza_zone_general(raw_properties: dict[str, Any] | None) -> str | None:
    props = raw_properties or {}
    for key in ("WAZAZoneGeneral", "wazazonegeneral", "WAZA_ZONE_GENERAL"):
        val = props.get(key)
        if val is not None and str(val).strip():
            return str(val).strip().upper()
    return None


def provisional_symbol_from_raw(raw_properties: dict[str, Any] | None) -> str | None:
    """Return ``PV`` when WAZA general class is commercial / mixed-use / industrial."""
    zg = waza_zone_general(raw_properties)
    if zg in PROVISIONAL_WAZA_GENERAL:
        return PROVISIONAL_SYMBOL
    return None

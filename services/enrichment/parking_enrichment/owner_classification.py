"""Classify assessor / taxpayer names as entity vs individual (heuristic)."""

from __future__ import annotations

from parking_core.models import OwnerKind

_ENTITY_MARKERS = (
    " LLC",
    " L.L.C",
    " INC",
    " INC.",
    " CORP",
    " CORPORATION",
    " LP",
    " L.P.",
    " LLP",
    " L.L.P.",
    " PLLC",
    " LTD",
    " CO ",
    " COMPANY",
    " ASSOCIATION",
    " ASSOC",
    " TRUST",
    " PARTNERSHIP",
    " PARTNERS",
    " HOLDINGS",
    " PROPERTIES",
    " INVESTMENT",
    " ENTERPRISES",
    " CENTER IN",  # e.g. TEACHER CHILDCARE CENTER IN
)


def classify_owner_display_name(name: str | None) -> OwnerKind:
    if not name or not str(name).strip():
        return OwnerKind.unknown
    upper = f" {str(name).upper().strip()} "
    if any(marker in upper for marker in _ENTITY_MARKERS):
        return OwnerKind.entity
    if "+" in upper or " AND " in upper or "&" in upper:
        # Joint individuals on roll (e.g. SINGH A+SINGH B)
        return OwnerKind.individual
    return OwnerKind.individual


def is_entity_name(name: str | None) -> bool:
    return classify_owner_display_name(name) == OwnerKind.entity

from __future__ import annotations

from typing import Any

from parking_core.models import OwnerCandidate, OwnerKind


def enrich_from_parcel_row(raw_properties: dict[str, Any] | None) -> list[OwnerCandidate]:
    """
    Derive owner candidates from assessor-style properties with explicit confidence.
    Replace with SOS / vendor enrichment in production.
    """
    props = raw_properties or {}
    owner = props.get("OWNER_NAME") or props.get("owner_name")
    if not owner:
        return [
            OwnerCandidate(
                display_name="Unknown owner",
                kind=OwnerKind.unknown,
                confidence=0.0,
                source="assessor_stub",
                raw={"reason": "no_owner_field"},
            )
        ]

    upper = str(owner).upper()
    entity_markers = ("LLC", "INC", "LP", "TRUST")
    kind = OwnerKind.entity if any(x in upper for x in entity_markers) else OwnerKind.individual
    confidence = 0.55 if kind == OwnerKind.entity else 0.65
    return [
        OwnerCandidate(
            display_name=str(owner),
            kind=kind,
            confidence=confidence,
            source="assessor_roll",
            raw={"field": "OWNER_NAME"},
        )
    ]

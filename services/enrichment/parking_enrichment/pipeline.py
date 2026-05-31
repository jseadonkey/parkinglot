from __future__ import annotations

from typing import Any

from parking_enrichment.owner_classification import classify_owner_display_name
from parking_core.models import OwnerCandidate, OwnerKind


def enrich_from_parcel_row(raw_properties: dict[str, Any] | None) -> list[OwnerCandidate]:
    """
    Derive owner candidates from assessor-style properties with explicit confidence.
    Uses ``owner_record.taxpayer_name`` when ``OWNER_NAME`` is absent (King County enrichment).
    """
    props = raw_properties or {}
    owner = props.get("OWNER_NAME") or props.get("owner_name")
    block = props.get("owner_record")
    if not owner and isinstance(block, dict):
        owner = block.get("taxpayer_name")
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

    kind = classify_owner_display_name(str(owner))
    confidence = 0.55 if kind == OwnerKind.entity else 0.65
    source = "king_county_assessor" if isinstance(block, dict) and block.get("taxpayer_name") else "assessor_roll"
    return [
        OwnerCandidate(
            display_name=str(owner).strip(),
            kind=kind,
            confidence=confidence,
            source=source,
            raw={"field": "OWNER_NAME" if source == "assessor_roll" else "owner_record.taxpayer_name"},
        )
    ]

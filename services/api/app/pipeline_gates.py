from __future__ import annotations


def parcel_qualifies_for_human_gate(
    entitlement_score: float,
    strategic_score: float,
    *,
    min_entitlement: float,
    min_strategic: float,
) -> bool:
    """Pilot floors — same dual thresholds as outreach board and qualified parcel reports."""
    return entitlement_score >= min_entitlement and strategic_score >= min_strategic

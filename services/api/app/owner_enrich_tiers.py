"""Score-gated owner research depth (roll-only vs SOS/portfolio vs vendor webhook)."""

from __future__ import annotations

from typing import Literal

from app.pipeline_gates import parcel_qualifies_for_human_gate

OwnerResearchTier = Literal["basic", "standard", "deep"]


def parcel_meets_owner_lookup_tier(
    entitlement_score: float,
    strategic_score: float,
    *,
    min_entitlement: float,
    min_strategic: float,
) -> bool:
    """Dual pilot floors — same gate as deal memos and human approvals."""
    return parcel_qualifies_for_human_gate(
        entitlement_score,
        strategic_score,
        min_entitlement=min_entitlement,
        min_strategic=min_strategic,
    )


def resolve_owner_research_tier(
    *,
    dual_qualified: bool,
    vendor_attempted: bool,
) -> OwnerResearchTier:
    if not dual_qualified:
        return "basic"
    if vendor_attempted:
        return "deep"
    return "standard"

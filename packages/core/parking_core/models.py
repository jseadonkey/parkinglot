from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ParcelFeature(BaseModel):
    """Normalized parcel attributes used by scoring (deterministic inputs)."""

    apn: str
    county_fips: str
    lot_sqft: float | None = None
    zoning_code: str | None = None
    zoning_allows_surface_parking: bool = False
    is_corner_lot: bool = False
    distance_to_nearest_demand_m: float | None = None


class ScoreBreakdown(BaseModel):
    zoning_component: float
    lot_size_component: float
    corner_component: float
    demand_proximity_component: float
    notes: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    total_score: float
    breakdown: ScoreBreakdown
    pilot_snapshot: dict[str, Any] = Field(default_factory=dict)


class OwnerKind(StrEnum):
    individual = "individual"
    entity = "entity"
    unknown = "unknown"


class OwnerCandidate(BaseModel):
    display_name: str
    kind: OwnerKind
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    raw: dict[str, Any] = Field(default_factory=dict)


class DealMemoPayload(BaseModel):
    parcel_id: str
    title: str
    markdown: str
    open_questions: list[str] = Field(default_factory=list)


class ApprovalType(StrEnum):
    outbound_message = "outbound_message"
    contract_send = "contract_send"
    deal_memo_publish = "deal_memo_publish"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalRequestRead(BaseModel):
    id: str
    type: ApprovalType
    status: ApprovalStatus
    payload: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None


class AuditLogEntry(BaseModel):
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

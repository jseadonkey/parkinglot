from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParcelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    apn: str
    county_fips: str
    lot_sqft: float | None
    zoning_code: str | None
    zoning_allows_surface_parking: bool
    is_corner_lot: bool
    distance_to_nearest_demand_m: float | None
    owner_outreach_brief: dict[str, Any] | None = None
    created_at: datetime


class ParcelScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    total_score: float
    breakdown: dict[str, Any]
    pilot_snapshot: dict[str, Any] | None
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    payload: dict[str, Any]
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    approved_by: str = Field(min_length=1, max_length=256)
    note: str | None = None


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    meta: dict[str, Any] | None
    created_at: datetime


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    status: str
    current_step: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class IngestGeojsonServerPathRequest(BaseModel):
    """Absolute path on the API/worker host to a GeoJSON file (e.g. rsynced to the Droplet)."""

    path: str = Field(min_length=1, max_length=4096)
    default_county_fips: str | None = None
    auto_run_pipeline: bool = False
    max_auto_pipeline: int = Field(default=100, ge=1, le=5000)

    @field_validator("path")
    @classmethod
    def path_sanity(cls, v: str) -> str:
        if "\x00" in v or "\n" in v or "\r" in v:
            msg = "invalid path"
            raise ValueError(msg)
        parts = Path(v).parts
        if ".." in parts:
            msg = "path cannot contain parent directory segments"
            raise ValueError(msg)
        return v


class OwnerContactPointRead(BaseModel):
    id: uuid.UUID
    kind: str
    value: str
    source: str
    label: str | None = None
    confidence: float
    created_at: datetime


class OutreachAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    contact_point_id: uuid.UUID | None
    channel: str
    target_kind: str
    target_value: str
    result: str
    result_detail: str | None
    attempted_by: str
    attempted_at: datetime
    approval_request_id: uuid.UUID | None
    meta: dict[str, Any] | None
    created_at: datetime


class ParcelOutreachRead(BaseModel):
    brief: dict[str, Any]
    contact_points: list[OwnerContactPointRead]
    attempts: list[OutreachAttemptRead]


class OutreachAttemptCreate(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    target_kind: str = Field(min_length=1, max_length=32)
    target_value: str = Field(min_length=1, max_length=4000)
    attempted_by: str = Field(min_length=1, max_length=256)
    result: str = Field(default="attempted", min_length=1, max_length=64)
    result_detail: str | None = Field(default=None, max_length=4000)
    contact_point_id: uuid.UUID | None = None
    approval_request_id: uuid.UUID | None = None


class OwnerContactPointCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="manual", min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=256)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class OutreachTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    channel: str
    subject: str | None
    body: str
    updated_by: str | None
    updated_at: datetime


class OutreachTemplateUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=50000)
    subject: str | None = Field(default=None, max_length=512)
    updated_by: str = Field(min_length=1, max_length=256)


class OutreachTemplatePreview(BaseModel):
    slug: str
    subject: str | None = None
    body: str
    sample_context: dict[str, Any] = Field(default_factory=dict)


class OutreachTemplateMeta(BaseModel):
    placeholders: list[str]


class SlackTestMessageRequest(BaseModel):
    """One-off Slack message for smoke testing.

    Slack API expects a channel ID (e.g. C… or G…), not a channel name.
    If channel_id is omitted, uses SLACK_DIGEST_CHANNEL_ID.
    """

    text: str = Field(min_length=1, max_length=2000)
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)

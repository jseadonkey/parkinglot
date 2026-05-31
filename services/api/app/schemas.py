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
    distance_to_nearest_comp_parking_m: float | None = None
    nearest_parking_comp: dict[str, Any] | None = None
    owner_outreach_brief: dict[str, Any] | None = None
    created_at: datetime


class OwnerCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    kind: str
    confidence: float
    source: str
    normalized_owner_key: str | None = None
    created_at: datetime


class DealMemoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    title: str
    body_md: str
    open_questions: list[Any] | None = None
    created_at: datetime


class ContractDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    s3_key: str
    version: int
    created_at: datetime


class ParcelQualificationRead(BaseModel):
    meets_entitlement_floor: bool
    meets_strategic_floor: bool
    dual_qualified: bool
    qualified_min_entitlement: float
    qualified_min_strategic: float
    latest_entitlement_score: float | None = None
    latest_strategic_score: float | None = None


class OwnerContactRead(BaseModel):
    channel: str
    value: str
    label: str | None = None
    source: str | None = None
    verified: bool = False
    confidence: float | None = None


class OwnerFieldCandidateRead(BaseModel):
    value: str
    source: str | None = None
    label: str | None = None
    confidence: float | None = None


class OwnerPersonRead(BaseModel):
    name: str | None = None
    role: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    source: str | None = None


class OwnerRecordRead(BaseModel):
    """Taxpayer / owner of record from county assessor enrichment (when loaded)."""

    taxpayer_name: str | None = None
    taxpayer_attn: str | None = None
    mailing_address: str | None = None
    situs_address: str | None = None
    name_candidates: list[OwnerFieldCandidateRead] = Field(default_factory=list)
    mailing_address_candidates: list[OwnerFieldCandidateRead] = Field(default_factory=list)
    situs_address_candidates: list[OwnerFieldCandidateRead] = Field(default_factory=list)
    appraised_land: float | None = None
    appraised_improvements: float | None = None
    property_type: str | None = None
    erealproperty_url: str | None = None
    data_source: str | None = None
    enriched_at: str | None = None
    owner_kind: str | None = None
    is_entity: bool = False
    enrichment_status: str | None = None
    sos_search_url: str | None = None
    registered_agent: str | None = None
    registered_agent_address: str | None = None
    principal_address: str | None = None
    underlying_persons: list[OwnerPersonRead] = Field(default_factory=list)
    contacts: list[OwnerContactRead] = Field(default_factory=list)
    enrichment_gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    owner_research_tier: str | None = None


class ParcelDetailRead(BaseModel):
    """GET /parcels/{id}/detail — full operator view of one parcel."""

    id: uuid.UUID
    apn: str
    county_fips: str
    lot_sqft: float | None
    zoning_code: str | None
    zoning_allows_surface_parking: bool
    is_corner_lot: bool
    distance_to_nearest_demand_m: float | None
    distance_to_nearest_comp_parking_m: float | None = None
    nearest_parking_comp: dict[str, Any] | None = None
    pilot_in_scope: bool
    has_footprint: bool
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    owner_outreach_brief: dict[str, Any] | None = None
    raw_properties: dict[str, Any] | None = None
    assessor_summary: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    pilot_region: str
    qualification: ParcelQualificationRead
    scores: list[ParcelScoreRead] = Field(default_factory=list)
    owners: list[OwnerCandidateRead] = Field(default_factory=list)
    memos: list[DealMemoRead] = Field(default_factory=list)
    contract_drafts: list[ContractDraftRead] = Field(default_factory=list)
    approvals: list[ApprovalRead] = Field(default_factory=list)
    workflow_runs: list[WorkflowRunRead] = Field(default_factory=list)
    owner_record: OwnerRecordRead = Field(default_factory=OwnerRecordRead)


class ParcelListRead(ParcelRead):
    """Parcel row for list endpoints — latest score per profile when available."""

    latest_identification_score: float | None = None
    latest_entitlement_score: float | None = None
    latest_strategic_score: float | None = None


class ParcelScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    score_profile: str
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


class IngestWatechCountyRequest(BaseModel):
    """Fetch WaTech statewide ArcGIS parcels for one county, then enqueue ingest (Celery worker)."""

    county_fips: str = Field(
        min_length=5,
        max_length=5,
        pattern=r"^53\d{3}$",
        description="Washington 5-digit county FIPS (e.g. 53033 King).",
    )
    max_features: int | None = Field(
        default=5000,
        ge=1,
        le=750000,
        description="Cap returned parcels per job (full counties can be huge).",
    )
    auto_run_pipeline: bool = True
    max_auto_pipeline: int = Field(default=100, ge=1, le=5000)


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


class GapStat(BaseModel):
    """Single metric: count and percent of parcel rows."""

    count: int
    pct: float


class CeleryTaskIdResponse(BaseModel):
    """Async job accepted — poll ``GET /internal/tasks/{task_id}``."""

    task_id: str


class ParcelPipelineTaskResponse(BaseModel):
    """POST /parcels/{parcel_id}/pipeline/run — Celery scoring/enrichment job."""

    task_id: str
    parcel_id: str


class ServiceStatusResponse(BaseModel):
    """GET /health or /ready — process status and build version (no secrets)."""

    status: str
    version: str


class WaTechCountyQueuedResponse(BaseModel):
    """WaTech fetch+ingest scheduled on the worker."""

    fetch_task_id: str


class EnqueueUnscoredResponse(BaseModel):
    """Parcels missing entitlement score — pipelines enqueued directly (not a nested Celery task id)."""

    enqueued: int
    parcel_ids: list[str]


class EnqueueIncompleteResponse(BaseModel):
    """Parcels missing entitlement or strategic score — pipelines enqueued directly."""

    enqueued: int
    parcel_ids: list[str]
    mode: str = Field(description="missing_entitlement_or_strategic")


class ExportReadinessResponse(BaseModel):
    """Shape returned by GET /internal/stats/export-readiness (Phase A–C gap diagnostics)."""

    parcel_row_total: int
    parcels_missing_footprint: GapStat
    parcels_missing_zoning_code: GapStat
    parcels_missing_lot_sqft: GapStat
    parcels_missing_distance_to_nearest_demand_m: GapStat
    parcels_missing_score_identification: GapStat
    parcels_missing_score_entitlement: GapStat
    parcels_missing_score_strategic: GapStat
    parcels_missing_entitlement_or_strategic: GapStat
    parcels_missing_owner_outreach_brief: GapStat
    recommended_next_steps: list[str]


class OutreachPipelineRow(BaseModel):
    """One qualified parcel with latest workflow + outreach pipeline status."""

    parcel_id: str
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    workflow_run_id: str | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    has_outreach_brief: bool
    owner_research_tier: str | None = None
    pending_approval_count: int
    pipeline_stage: str


class OutreachPipelineBoardResponse(BaseModel):
    """GET /internal/pipeline/outreach-board — dual-qualified lots for owner outreach."""

    qualified_min_entitlement_score: float
    qualified_min_strategic_score: float
    row_count: int
    rows: list[OutreachPipelineRow]


class DealProgressRow(BaseModel):
    """One in-scope parcel with operator-friendly deal stage (latest workflow run)."""

    parcel_id: str
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    deal_stage: str
    deal_stage_label: str
    workflow_run_id: str | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    owner_research_tier: str | None = None
    pending_approval_count: int
    has_approved_memo: bool
    has_approved_contract: bool


class DealProgressBoardResponse(BaseModel):
    """GET /internal/pipeline/deal-progress — deal stages for operator console."""

    qualified_min_entitlement_score: float
    qualified_min_strategic_score: float
    stage_counts: dict[str, int]
    row_count: int
    rows: list[DealProgressRow]


class QualifiedMinScores(BaseModel):
    """Pilot qualification floors per score profile (from pilot YAML)."""

    entitlement: float
    strategic: float
    identification: float


class ScoringSummaryResponse(BaseModel):
    """GET /internal/stats/scoring-summary — counts vs pilot floors."""

    total_parcels: int
    parcels_with_latest_entitlement_score: int
    parcels_with_latest_strategic_score: int
    parcels_with_latest_identification_score: int
    parcels_with_both_profiles_scored: int
    qualified_count_entitlement: int
    qualified_count_strategic: int
    qualified_count_identification: int
    qualified_min_score: QualifiedMinScores
    pilot_region: str


class IngestStatusResponse(BaseModel):
    """GET /internal/stats/ingest-status — bulk load + scoring backlog for operator UI."""

    ingest_active: bool
    active_ingest_task_id: str | None = None
    active_ingest_path: str | None = None
    candidate_geojson_path: str
    candidate_feature_count: int | None = None
    parcels_total_db: int
    parcels_in_scope_db: int
    parcels_with_entitlement_score: int
    phase: str
    headline: str
    detail: str


class WorkflowFailureGroup(BaseModel):
    """One bucket of failed runs sharing step + error text."""

    current_step: str
    error_signature: str
    error_example: str
    count: int
    last_updated: datetime | None
    sample_parcel_ids: list[str]
    sample_run_ids: list[str]


class StorageProbeResponse(BaseModel):
    """Spaces/S3 bucket check (no secrets)."""

    configured: bool
    endpoint: str | None
    bucket: str | None
    region: str | None
    reachable: bool
    error: str | None
    fix_hint: str | None


class WorkflowFailuresResponse(BaseModel):
    """GET /internal/stats/workflow-failures — all failed enrich/pipeline runs (not UI-capped)."""

    total_runs: int
    failed_count: int
    blocked_count: int
    with_error_count: int
    ui_list_cap: int
    ui_note: str
    failed_by_step: dict[str, int]
    failure_groups: list[WorkflowFailureGroup]
    storage: StorageProbeResponse


class IngestSampleQueuedResponse(BaseModel):
    """Bundled sample GeoJSON — ingest Celery task queued."""

    task_id: str
    path: str
    auto_run_pipeline: bool
    max_auto_pipeline: int


class IngestGeojsonUploadQueuedResponse(BaseModel):
    """Uploaded GeoJSON — ingest Celery task queued."""

    task_id: str
    filename: str | None = None
    default_county_fips: str | None = None
    auto_run_pipeline: bool
    max_auto_pipeline: int


class IngestGeojsonPathQueuedResponse(BaseModel):
    """Server filesystem GeoJSON — ingest Celery task queued."""

    task_id: str
    path: str
    auto_run_pipeline: bool
    max_auto_pipeline: int


class FullSlackUpdateResponse(BaseModel):
    """POST /internal/slack/full-update-now — three Slack-related Celery tasks."""

    digest_task_id: str
    qualified_parcels_task_id: str
    agent_discussion_task_id: str


class SlackDigestPreviewResponse(BaseModel):
    """GET /internal/slack/digest-preview — Block Kit payload built from DB without posting."""

    hours: int = Field(ge=1, le=24)
    slack_digest_configured: bool
    digest_channel_id_set: bool
    fallback_preview: str
    blocks: list[dict[str, Any]]


class SlackAgentDiscussionMessagePreview(BaseModel):
    """One dual-agent Slack message (fallback + blocks)."""

    fallback: str
    blocks: list[dict[str, Any]]


class SlackAgentDiscussionPreviewResponse(BaseModel):
    """GET /internal/slack/agent-discussion-preview — payloads without posting."""

    message_count: int = Field(ge=0)
    messages: list[SlackAgentDiscussionMessagePreview]


class SlackTestMessagePostResponse(BaseModel):
    """POST /internal/slack/test-message — Slack chat.postMessage ack (subset)."""

    ok: bool
    ts: str | None = None
    channel: str | None = None


class SlackConfigStatusResponse(BaseModel):
    """GET /internal/slack/status — booleans only (no secrets)."""

    slack_digest_configured: bool
    has_bot_token: bool
    has_digest_channel_id: bool
    slack_dual_agent_configured: bool
    has_agent_discussion_channel_id: bool
    slack_agent_event_updates_enabled: bool


class CeleryTaskStatusResponse(BaseModel):
    """GET /internal/tasks/{task_id} — Celery AsyncResult snapshot."""

    task_id: str
    state: str
    ready: bool
    result: Any | None = None
    error: str | None = None
    traceback: str | None = None


class PeerParcelSummary(BaseModel):
    """One parcel in GET /internal/owners/peers-by-key (qualified by latest entitlement)."""

    parcel_id: str
    apn: str
    county_fips: str
    latest_entitlement_score: float


class OwnersPeersByKeyResponse(BaseModel):
    """GET /internal/owners/peers-by-key — qualified parcels sharing an owner key."""

    normalized_owner_key: str
    qualified_min_entitlement_score: float
    parcel_count: int
    parcels: list[PeerParcelSummary]


class OwnerPortfolioRankRow(BaseModel):
    """One row in GET /internal/owners/portfolios-ranked."""

    normalized_owner_key: str
    qualified_parcel_count: int


class OwnersPortfoliosRankedResponse(BaseModel):
    """GET /internal/owners/portfolios-ranked — keys with multiple qualified parcels."""

    qualified_min_entitlement_score: float
    min_peers: int
    portfolios: list[OwnerPortfolioRankRow]


class MergeGeojsonAttributesRequest(BaseModel):
    """Path to GeoJSON whose properties update existing parcels (same loader as full ingest)."""

    path: str = Field(min_length=1, max_length=4096)
    default_county_fips: str | None = None
    delete_after: bool = False
    refresh_pipeline: bool = True
    max_pipeline: int = Field(default=100, ge=0, le=5000)

    @field_validator("path")
    @classmethod
    def merge_path_sanity(cls, v: str) -> str:
        if "\x00" in v or "\n" in v or "\r" in v:
            msg = "invalid path"
            raise ValueError(msg)
        parts = Path(v).parts
        if ".." in parts:
            msg = "path cannot contain parent directory segments"
            raise ValueError(msg)
        return v


class SlackTestMessageRequest(BaseModel):
    """One-off Slack message for smoke testing.

    Slack API expects a channel ID (e.g. C… or G…), not a channel name.
    If channel_id is omitted, uses SLACK_DIGEST_CHANNEL_ID.
    """

    text: str = Field(min_length=1, max_length=2000)
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)

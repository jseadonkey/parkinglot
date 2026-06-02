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


class RateCompRead(BaseModel):
    name: str
    lat: float
    lon: float
    hourly_mid_usd: float
    source_note: str | None = None
    origin: str = "pilot"


class NearbyQualifiedParcelRead(BaseModel):
    parcel_id: str
    apn: str
    county_fips: str
    lot_sqft: float | None
    zoning_code: str | None = None
    entitlement_score: float
    distance_m: float | None = None


class ParkingRevenueEstimateRead(BaseModel):
    available: bool
    reason: str | None = None
    stalls_estimated: int | None = None
    hourly_rate_median_usd: float | None = None
    hourly_rate_min_usd: float | None = None
    hourly_rate_max_usd: float | None = None
    comp_count: int | None = None
    monthly_gross_usd: float | None = None
    annual_gross_usd: float | None = None
    assumptions: dict[str, float] | None = None


class ParcelDealContextResponse(BaseModel):
    """GET /parcels/{id}/deal-context — nearby comps and illustrative revenue for top deals."""

    found: bool
    parcel_id: str | None = None
    apn: str | None = None
    county_fips: str | None = None
    lot_sqft: float | None = None
    centroid: dict[str, float] | None = None
    entitlement_score: float | None = None
    qualified_floor: float | None = None
    rate_comp_radius_m: float | None = None
    rate_comps: list[RateCompRead] = Field(default_factory=list)
    revenue_estimate: ParkingRevenueEstimateRead | None = None
    nearby_qualified_parcels: list[NearbyQualifiedParcelRead] = Field(default_factory=list)


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


class WaRolloutCountyRow(BaseModel):
    county_fips: str
    parcels_in_db: int


class WaRolloutStatusResponse(BaseModel):
    """GET /internal/ingest/wa-rollout-status — slow statewide county ingest progress."""

    rollout_enabled: bool
    next_county_fips: str | None
    counties_in_priority_list: int
    counties_with_parcels: int
    counties_remaining: int
    parking_queue_depth: int | None = None
    counties: list[WaRolloutCountyRow]


class EnqueueUnscoredResponse(BaseModel):
    """Parcels missing entitlement score — pipelines enqueued directly (not a nested Celery task id)."""

    enqueued: int
    parcel_ids: list[str]


class EnqueueIncompleteResponse(BaseModel):
    """Prescreen-qualified parcels missing entitlement or strategic — pipelines enqueued directly."""

    enqueued: int
    parcel_ids: list[str]
    mode: str = Field(description="prescreen_qualified_missing_entitlement_or_strategic")
    prescreen_floor: float | None = None


class PrescreenGapStat(GapStat):
    floor: float = Field(description="Identification prescreen qualified_min_score from pilot_identification.yaml")


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
    parcels_prescreen_qualified: PrescreenGapStat
    parcels_pipeline_funnel_backlog: PrescreenGapStat
    parcels_ruled_out_by_prescreen: PrescreenGapStat
    parcels_ruled_out_at_atlas: PrescreenGapStat
    parcels_missing_owner_outreach_brief: GapStat
    recommended_next_steps: list[str]


class OutreachPipelineRow(BaseModel):
    """One qualified parcel with latest workflow + outreach pipeline status."""

    parcel_id: str
    apn: str
    county_fips: str
    entitlement_score: float | None
    identification_score: float | None
    workflow_run_id: str | None
    workflow_status: str | None
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    has_outreach_brief: bool
    pending_approval_count: int
    pipeline_stage: str
    monthly_gross_usd: float | None = None
    revenue_available: bool = False


class RateCompSeedResponse(BaseModel):
    inserted: int
    updated: int
    skipped: int
    total_seed_rows: int
    replace_existing: bool


class OutreachPipelineBoardResponse(BaseModel):
    """GET /internal/pipeline/outreach-board — qualified lots worth tracking for owner outreach."""

    qualified_min_entitlement_score: float
    row_count: int
    rows: list[OutreachPipelineRow]


class DealProgressSummary(BaseModel):
    total_parcels: int
    by_status: dict[str, int]
    by_step: dict[str, int]


class DealProgressRow(BaseModel):
    parcel_id: str
    apn: str
    county_fips: str
    workflow_run_id: str
    workflow_status: str
    workflow_step: str | None
    workflow_error: str | None
    workflow_updated_at: datetime | None
    pending_approval_count: int
    pipeline_stage: str


class DealProgressBoardResponse(BaseModel):
    """GET /internal/pipeline/deal-progress — latest workflow state per parcel."""

    summary: DealProgressSummary
    row_count: int
    rows: list[DealProgressRow]


class ParcelScoredListRow(BaseModel):
    """One parcel with latest entitlement, strategic, and identification scores."""

    parcel_id: str
    apn: str
    county_fips: str
    zoning_code: str | None
    lot_sqft: float | None
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    combined_score: float | None
    created_at: datetime


class ParcelScoredListResponse(BaseModel):
    """GET /internal/parcels/scored-list — operator parcel table sorted by score."""

    sort: str
    row_count: int
    rows: list[ParcelScoredListRow]


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


class PlatformShowcaseCountyRow(BaseModel):
    county_fips: str
    county_name: str
    parcels_in_db: int


class PlatformShowcaseTopParcel(BaseModel):
    parcel_id: str
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    lot_sqft: float | None
    zoning_code: str | None
    has_outreach_brief: bool


class PlatformSampleDeliverable(BaseModel):
    kind: str
    title: str
    excerpt: str
    parcel_apn: str
    redacted: bool = True


class PlatformShowcaseResponse(BaseModel):
    """GET /internal/stats/platform-showcase — partner-facing live platform metrics."""

    generated_at: datetime
    region_name: str
    state_name: str
    primary_metro_label: str | None
    pilot_county_count: int
    counties_with_ingested_parcels: int
    counties_loaded: list[PlatformShowcaseCountyRow]
    parcels_total: int
    parcels_prescreen_qualified: int
    parcels_qualified_entitlement: int
    parcels_with_full_pipeline_scores: int
    parcels_with_owner_brief: int
    parcels_pipeline_backlog: int
    qualified_floors: QualifiedMinScores
    pipeline_runs_total: int
    pipeline_by_stage: dict[str, int]
    pipeline_by_step: dict[str, int]
    top_parcels: list[PlatformShowcaseTopParcel]
    sample_deliverables: list[PlatformSampleDeliverable] = Field(default_factory=list)


class PilotCountyScopeRow(BaseModel):
    county_fips: str
    county_name: str
    parcels_in_db: int


class PilotScopeResponse(BaseModel):
    """GET /internal/stats/pilot-scope — geographic pilot boundaries."""

    region_name: str
    state_fips: str
    state_name: str
    primary_metro_cbsa: str | None
    primary_metro_label: str | None
    pilot_county_count: int
    counties_with_ingested_parcels: int
    parcels_in_pilot_counties: int
    min_lot_sqft: float
    qualified_min_score: QualifiedMinScores
    counties: list[PilotCountyScopeRow]


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


class SlackLastDigestResponse(BaseModel):
    """GET /internal/slack/last-digest — last successful scheduled/manual digest audit row."""

    found: bool
    created_at: str | None = None
    meta: dict[str, Any] | None = None


class SlackConfigStatusResponse(BaseModel):
    """GET /internal/slack/status — booleans only (no secrets)."""

    slack_digest_configured: bool
    has_bot_token: bool
    has_digest_channel_id: bool
    slack_dual_agent_configured: bool
    has_agent_discussion_channel_id: bool
    slack_agent_event_updates_enabled: bool


class SiteWatchdogCheckRead(BaseModel):
    name: str
    ok: bool
    detail: str
    latency_ms: float | None = None
    source: str = "droplet"


class SiteWatchdogStatusResponse(BaseModel):
    """GET /internal/watchdog/status — last check persisted in Redis."""

    found: bool
    ok: bool | None = None
    checked_at: str | None = None
    runner: str | None = None
    failure_count: int | None = None
    checks: list[SiteWatchdogCheckRead] = Field(default_factory=list)


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


class ParcelOutreachDraftRead(BaseModel):
    channel: str
    template_slug: str
    to_name: str | None = None
    to_email: str | None = None
    to_phone: str | None = None
    to_mailing_address: str | None = None
    from_name: str
    from_company: str | None = None
    from_email: str | None = None
    from_phone: str | None = None
    subject: str | None = None
    body: str
    has_recipient: bool = False


class OutreachApprovalRequest(BaseModel):
    requested_by: str = Field(min_length=1, max_length=256)


class SlackTestMessageRequest(BaseModel):
    """One-off Slack message for smoke testing.

    Slack API expects a channel ID (e.g. C… or G…), not a channel name.
    If channel_id is omitted, uses SLACK_DIGEST_CHANNEL_ID.
    """

    text: str = Field(min_length=1, max_length=2000)
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)

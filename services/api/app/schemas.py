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
    situs_address: str | None = None
    mailing_address: str | None = None
    lot_sqft: float | None
    zoning_code: str | None
    zoning_allows_surface_parking: bool
    zoning_principal_use_symbol: str | None = None
    zoning_entitlement_tier: str | None = None
    is_corner_lot: bool
    distance_to_nearest_demand_m: float | None
    owner_outreach_brief: dict[str, Any] | None = None
    created_at: datetime


class RateCompRead(BaseModel):
    name: str
    lat: float
    lon: float
    hourly_mid_usd: float
    effective_hourly_usd: float | None = None
    source_note: str | None = None
    origin: str = "pilot"
    distance_m: float | None = None
    facility_type: str | None = None
    similarity: float | None = None
    distance_weight: float | None = None
    comp_weight: float | None = None


class ParkingRevenueEstimateRead(BaseModel):
    available: bool
    reason: str | None = None
    stalls_estimated: int | None = None
    stalls_low: int | None = None
    stalls_high: int | None = None
    layout_efficiency: float | None = None
    usable_sqft: float | None = None
    stall_sqft_effective: float | None = None
    hourly_rate_median_usd: float | None = None
    hourly_rate_weighted_usd: float | None = None
    hourly_rate_min_usd: float | None = None
    hourly_rate_max_usd: float | None = None
    comp_count: int | None = None
    monthly_gross_raw_usd: float | None = None
    monthly_gross_raw_low_usd: float | None = None
    monthly_gross_raw_high_usd: float | None = None
    monthly_gross_usd: float | None = None
    monthly_gross_low_usd: float | None = None
    monthly_gross_high_usd: float | None = None
    monthly_net_estimated_usd: float | None = None
    lot_sqft_effective: float | None = None
    annual_gross_usd: float | None = None
    market_confidence: float | None = None
    market_confidence_tier: str | None = None
    strong_comp_count: int | None = None
    nearest_comp_distance_m: float | None = None
    market_evidence_notes: list[str] | None = None
    assumptions: dict[str, Any] | None = None


class NearbyQualifiedParcelRead(BaseModel):
    parcel_id: str
    apn: str
    county_fips: str
    lot_sqft: float | None
    zoning_code: str | None = None
    entitlement_score: float
    distance_m: float | None = None


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


class IngestBaltimoreCityRequest(BaseModel):
    """Fetch Baltimore City EGIS parcels (Maryland), then enqueue ingest (Celery worker)."""

    max_features: int | None = Field(
        default=None,
        ge=1,
        le=750000,
        description="Optional cap for test pulls. Omit/null to fetch all Baltimore City parcels.",
    )
    auto_run_pipeline: bool = True
    max_auto_pipeline: int = Field(default=100, ge=1, le=5000)


class IngestBaltimoreCountyRequest(BaseModel):
    """Fetch Baltimore County tax parcels (Maryland), then enqueue ingest (Celery worker)."""

    max_features: int | None = Field(
        default=5000,
        ge=1,
        le=750000,
        description="Cap returned parcels per job.",
    )
    auto_run_pipeline: bool = True
    max_auto_pipeline: int = Field(default=100, ge=1, le=5000)


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
    cooldown_ready: bool | None = None
    required_cooldown_days: float | None = None
    days_since_last_county_ingest: float | None = None
    last_ingested_county_fips: str | None = None
    last_ingested_county_parcels: int | None = None
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
    entitlement_floor: float | None = None
    strategic_floor: float | None = None
    priority_county_fips: list[str] | None = None


class PrescreenGapStat(GapStat):
    floor: float = Field(description="Identification prescreen qualified_min_score from pilot_identification.yaml")


class OwnerOutreachTargetStat(GapStat):
    entitlement_floor: float = Field(description="Minimum Atlas/entitlement score for owner outreach briefs")
    strategic_floor: float = Field(description="Minimum Beacon/strategic score for owner outreach briefs")


class OwnerOutreachBriefGapStat(OwnerOutreachTargetStat):
    target_count: int = Field(description="Number of parcels eligible for owner outreach briefs")


class PoiDensityGapStat(GapStat):
    candidate_mode: str | None = Field(
        default=None,
        description="POI enrichment candidate scope used for this gap count",
    )


class PoiDensityCandidateStat(GapStat):
    candidate_mode: str
    entitlement_floor: float
    strategic_floor: float


class ExportReadinessResponse(BaseModel):
    """Shape returned by GET /internal/stats/export-readiness (Phase A–C gap diagnostics)."""

    parcel_row_total: int
    parcels_missing_footprint: GapStat
    parcels_missing_zoning_code: GapStat
    parcels_missing_lot_sqft: GapStat
    parcels_missing_distance_to_nearest_demand_m: GapStat
    parcels_missing_poi_commercial_count_400m: PoiDensityGapStat
    parcels_poi_density_candidates: PoiDensityCandidateStat
    parcels_missing_poi_commercial_count_400m_all: GapStat
    parcels_missing_score_identification: GapStat
    parcels_missing_score_entitlement: GapStat
    parcels_missing_score_strategic: GapStat
    parcels_missing_entitlement_or_strategic: GapStat
    parcels_prescreen_qualified: PrescreenGapStat
    parcels_pipeline_funnel_backlog: PrescreenGapStat
    parcels_ruled_out_by_prescreen: PrescreenGapStat
    parcels_ruled_out_at_atlas: PrescreenGapStat
    parcels_owner_outreach_targets: OwnerOutreachTargetStat
    parcels_missing_owner_outreach_brief: OwnerOutreachBriefGapStat
    parcels_prescreen_qualified_missing_owner_outreach_brief: PrescreenGapStat
    recommended_next_steps: list[str]


class BacklogEtaItem(BaseModel):
    """One workstream with backlog count, value, and rough completion estimate."""

    key: str
    label: str
    status: str
    active_now: bool = False
    backlog_count: int
    total_count: int
    backlog_pct: float
    unit: str
    value: str
    work_type: str
    assumed_batch_size: int | None = None
    assumed_batches_per_day: float | None = None
    assumed_units_per_day: float | None = None
    eta_days: float | None = None
    eta_label: str
    eta_confidence: str
    recommendation: str
    why: str


class BacklogEtaSummary(BaseModel):
    active_parking_queue_depth: int
    active_slack_queue_depth: int
    workers_online: bool
    worker_detail: str | None = None
    ops_auto_fix_enabled: bool
    data_checked_at: datetime | None = None
    data_source: str
    high_value_remaining: int
    decision: str


class BacklogEtaResponse(BaseModel):
    """GET /internal/stats/backlog-eta — decision view for backlog value and estimated time."""

    generated_at: datetime
    summary: BacklogEtaSummary
    items: list[BacklogEtaItem]


class ParcelRevenueSummaryRead(BaseModel):
    """Illustrative revenue from weighted nearby comps + layout-based stalls."""

    revenue_available: bool = False
    monthly_gross_usd: float | None = None
    monthly_gross_low_usd: float | None = None
    monthly_gross_high_usd: float | None = None
    stalls_estimated: int | None = None
    stalls_low: int | None = None
    stalls_high: int | None = None
    hourly_rate_weighted_usd: float | None = None
    hourly_rate_median_usd: float | None = None
    comp_count: int | None = None
    nearest_comp_name: str | None = None
    nearest_comp_distance_m: float | None = None
    market_confidence: float | None = None
    market_confidence_tier: str | None = None
    strong_comp_count: int | None = None
    monthly_gross_raw_usd: float | None = None
    market_evidence_notes: list[str] | None = None


class OutreachPipelineRow(BaseModel):
    """One qualified parcel with latest workflow + outreach pipeline status."""

    parcel_id: str
    apn: str
    county_fips: str
    entitlement_score: float | None
    strategic_score: float | None = None
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
    revenue: ParcelRevenueSummaryRead | None = None


class RateCompSeedResponse(BaseModel):
    inserted: int
    updated: int
    skipped: int
    total_seed_rows: int
    replace_existing: bool


class OutreachPipelineBoardResponse(BaseModel):
    """GET /internal/pipeline/outreach-board — qualified lots worth tracking for owner outreach."""

    qualified_min_entitlement_score: float
    owner_outreach_min_entitlement_score: float
    owner_outreach_min_strategic_score: float
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
    situs_address: str | None = None
    mailing_address: str | None = None
    zoning_code: str | None
    lot_sqft: float | None
    zoning_principal_use_symbol: str | None = None
    zoning_entitlement_tier: str | None = None
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    combined_score: float | None
    created_at: datetime
    revenue: ParcelRevenueSummaryRead | None = None


class ParcelScoredListResponse(BaseModel):
    """GET /internal/parcels/scored-list — operator parcel table sorted by score."""

    sort: str
    row_count: int
    qualified_min_entitlement_score: float | None = None
    revenue_rows_computed: int = 0
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
    priority_market: bool = False


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
    states_in_scope: list[StateScopeRow] = Field(default_factory=list)
    primary_market_name: str = "Baltimore, Maryland"
    primary_market_state_fips: str = "24"
    priority_county_fips: list[str] = Field(default_factory=list)
    parcels_in_priority_counties: int = 0
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
    priority_market: bool = False


class StateScopeRow(BaseModel):
    state_fips: str
    state_name: str
    county_count: int


class PilotScopeResponse(BaseModel):
    """GET /internal/stats/pilot-scope — geographic pilot boundaries."""

    region_name: str
    state_fips: str
    state_name: str
    states_in_scope: list[StateScopeRow] = Field(default_factory=list)
    primary_market_name: str = "Baltimore, Maryland"
    primary_market_state_fips: str = "24"
    priority_county_fips: list[str] = Field(default_factory=list)
    parcels_in_priority_counties: int = 0
    primary_metro_cbsa: str | None
    primary_metro_label: str | None
    pilot_county_count: int
    counties_with_ingested_parcels: int
    parcels_in_pilot_counties: int
    min_lot_sqft: float
    qualified_min_score: QualifiedMinScores
    counties: list[PilotCountyScopeRow]


class BaltimoreZoningTierZoneRow(BaseModel):
    zoning_code: str
    parcel_count: int


class BaltimoreZoningTiersResponse(BaseModel):
    """GET /internal/stats/baltimore-zoning-tiers — MD principal-use parking tiers in Postgres."""

    county_fips: str
    total_parcels: int
    tiers: dict[str, int]
    top_permitted_zones: list[BaltimoreZoningTierZoneRow]
    rules_path: str


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
    """POST /internal/slack/full-update-now — Slack-related Celery tasks."""

    digest_task_id: str
    plan_progress_task_id: str
    qualified_parcels_task_id: str
    agent_discussion_task_id: str


class SlackDigestPreviewResponse(BaseModel):
    """GET /internal/slack/digest-preview — Block Kit payload built from DB without posting."""

    hours: int = Field(ge=1, le=24)
    slack_digest_configured: bool
    digest_channel_id_set: bool
    fallback_preview: str
    blocks: list[dict[str, Any]]


class SlackPlanProgressPreviewResponse(BaseModel):
    """GET /internal/slack/plan-progress-preview — A-E progress payload without posting."""

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


class LobConfigStatusResponse(BaseModel):
    """GET /internal/lob/status — booleans only (no secrets)."""

    lob_configured: bool
    has_api_key: bool
    has_from_address: bool
    lob_send_enabled: bool
    lob_test_mode: bool | None = None
    lob_mail_extra_service: str = "certified"


class LobVerifyResponse(BaseModel):
    """POST /internal/lob/verify — Lob API credential check."""

    ok: bool
    lob_configured: bool
    lob_test_mode: bool | None = None
    detail: str | None = None


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


class OpsRemediationStatusResponse(BaseModel):
    """GET /internal/ops/status — last ops remediation loop report (Redis)."""

    found: bool
    ok: bool | None = None
    checked_at: str | None = None
    issue_count: int | None = None
    critical_count: int | None = None
    auto_fix_enabled: bool | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    celery_workers: dict[str, Any] | None = None
    redis_queues: dict[str, Any] | None = None
    priority_counties: dict[str, Any] | None = None


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

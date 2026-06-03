from __future__ import annotations

import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baltimore_zoning_stats import baltimore_zoning_tiers_summary
from app.celery_app import celery
from app.config import get_settings
from app.db.models import AuditLog
from app.db.schema_compat import column_exists
from app.db.session import get_db
from app.deal_progress import query_deal_progress_board
from app.deps_internal import require_internal_key
from app.export_readiness import export_readiness_summary
from app.lob_client import lob_status_payload, verify_lob_api_key
from app.outreach_board import query_outreach_pipeline_board
from app.owner_portfolio import list_peer_parcel_summaries, rank_owner_portfolios
from app.parcel_deal_context import attach_revenue_summaries, qualified_min_entitlement_score
from app.parcel_scored_list import COMBINED, ParcelSortProfile, query_parcels_scored_list
from app.pilot_scope import pilot_scope_summary
from app.platform_showcase import build_platform_showcase
from app.rate_comp_seed import seed_baltimore_parking_rate_comps, seed_king_county_parking_rate_comps
from app.schemas import (
    BaltimoreZoningTiersResponse,
    BaltimoreZoningTierZoneRow,
    CeleryTaskIdResponse,
    CeleryTaskStatusResponse,
    DealProgressBoardResponse,
    DealProgressRow,
    DealProgressSummary,
    EnqueueIncompleteResponse,
    EnqueueUnscoredResponse,
    ExportReadinessResponse,
    FullSlackUpdateResponse,
    IngestBaltimoreCityRequest,
    IngestBaltimoreCountyRequest,
    IngestGeojsonPathQueuedResponse,
    IngestGeojsonServerPathRequest,
    IngestGeojsonUploadQueuedResponse,
    IngestSampleQueuedResponse,
    IngestWatechCountyRequest,
    LobConfigStatusResponse,
    LobVerifyResponse,
    MergeGeojsonAttributesRequest,
    OutreachPipelineBoardResponse,
    OutreachPipelineRow,
    OwnerPortfolioRankRow,
    OwnersPeersByKeyResponse,
    OwnersPortfoliosRankedResponse,
    ParcelRevenueSummaryRead,
    ParcelScoredListResponse,
    ParcelScoredListRow,
    PeerParcelSummary,
    PilotCountyScopeRow,
    PilotScopeResponse,
    PlatformShowcaseResponse,
    QualifiedMinScores,
    RateCompSeedResponse,
    ScoringSummaryResponse,
    SiteWatchdogCheckRead,
    SiteWatchdogStatusResponse,
    SlackAgentDiscussionMessagePreview,
    SlackAgentDiscussionPreviewResponse,
    SlackConfigStatusResponse,
    SlackDigestPreviewResponse,
    SlackLastDigestResponse,
    SlackTestMessagePostResponse,
    SlackTestMessageRequest,
    WaRolloutCountyRow,
    WaRolloutStatusResponse,
    WaTechCountyQueuedResponse,
)
from app.scoring_summary import scoring_summary_stats
from app.slack_digest import (
    build_dual_agent_discussion_posts,
    build_slack_digest_blocks,
    post_text_to_slack,
    slack_agent_event_updates_enabled,
)
from app.tasks import (
    enqueue_incomplete_pipeline_jobs,
    enqueue_priority_qualified_pipeline_jobs,
    enqueue_unscored_pipeline_jobs,
    fetch_baltimore_city_and_ingest,
    fetch_baltimore_county_and_ingest,
    fetch_watech_county_and_ingest,
    ingest_geojson_path,
    merge_parcel_attributes_geojson,
    refresh_demand_distances_batch,
    refresh_entitlement_scores_batch,
    refresh_identification_scores_batch,
    refresh_pipeline_scores_with_rate_comps_batch,
    refresh_poi_density_batch,
    site_watchdog_check,
    slack_agent_digest,
    slack_dual_agent_discussion,
    slack_qualified_parcels_report,
    wa_statewide_rollout_tick,
)
from app.wa_statewide_rollout import (
    county_priority_list,
    load_rollout_config,
    next_county_to_ingest,
    parcel_counts_by_county,
    parking_queue_depth,
)
from parking_core.pilot import load_pilot_config

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_key)],
)


@router.get("/tasks/{task_id}", response_model=CeleryTaskStatusResponse)
def celery_task_status(task_id: str) -> CeleryTaskStatusResponse:
    """Inspect a Celery task by id (ids from async POST endpoints).

    Requires ``X-Internal-Key`` when ``INTERNAL_API_KEY`` is set.
    """
    async_result = celery.AsyncResult(task_id)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "state": async_result.state,
        "ready": async_result.ready(),
    }
    if async_result.ready():
        if async_result.successful():
            payload["result"] = async_result.result
        else:
            err = async_result.result
            payload["error"] = str(err) if err is not None else None
            tb = async_result.traceback
            if isinstance(tb, str) and len(tb) > 4000:
                tb = tb[:4000] + "\n... (truncated)"
            payload["traceback"] = tb
    return CeleryTaskStatusResponse(**payload)


@router.get("/slack/last-digest", response_model=SlackLastDigestResponse)
def slack_last_digest(db: Session = Depends(get_db)) -> SlackLastDigestResponse:
    """When the worker last posted a digest to Slack (audit_log action slack_digest_posted)."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.action == "slack_digest_posted")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        return SlackLastDigestResponse(found=False)
    created = row.created_at.isoformat() if row.created_at else None
    return SlackLastDigestResponse(found=True, created_at=created, meta=row.meta)


@router.get("/slack/status", response_model=SlackConfigStatusResponse)
def slack_config_status() -> SlackConfigStatusResponse:
    """Whether Slack digest env is set (no token values returned)."""
    s = get_settings()
    has_token = bool((s.slack_bot_token or "").strip())
    has_channel = bool((s.slack_digest_channel_id or "").strip())
    has_agent_ch = bool((s.slack_agent_discussion_channel_id or "").strip())
    return SlackConfigStatusResponse(
        slack_digest_configured=has_token and has_channel,
        has_bot_token=has_token,
        has_digest_channel_id=has_channel,
        slack_dual_agent_configured=has_token and has_agent_ch,
        has_agent_discussion_channel_id=has_agent_ch,
        slack_agent_event_updates_enabled=slack_agent_event_updates_enabled(s),
    )


@router.get("/lob/status", response_model=LobConfigStatusResponse)
def lob_config_status() -> LobConfigStatusResponse:
    """Whether Lob certified-mail env is set (no API key returned)."""
    return LobConfigStatusResponse(**lob_status_payload(get_settings()))


@router.post("/lob/verify", response_model=LobVerifyResponse)
def lob_verify_credentials() -> LobVerifyResponse:
    """Call Lob API to confirm LOB_API_KEY is valid (read-only list addresses)."""
    s = get_settings()
    status = lob_status_payload(s)
    if not status["has_api_key"]:
        return LobVerifyResponse(
            ok=False,
            lob_configured=False,
            lob_test_mode=None,
            detail="LOB_API_KEY is not set",
        )
    ok, detail = verify_lob_api_key(s.lob_api_key)
    return LobVerifyResponse(
        ok=ok,
        lob_configured=bool(status["lob_configured"]),
        lob_test_mode=status["lob_test_mode"],
        detail=None if ok else detail,
    )


@router.get("/watchdog/status", response_model=SiteWatchdogStatusResponse)
def site_watchdog_status() -> SiteWatchdogStatusResponse:
    """Last site+server health check (Redis). Separate from pipeline Slack digest."""
    from app.site_watchdog import load_last_report

    report = load_last_report(get_settings())
    if report is None:
        return SiteWatchdogStatusResponse(found=False)
    checks = [SiteWatchdogCheckRead.model_validate(c) for c in (report.get("checks") or [])]
    return SiteWatchdogStatusResponse(
        found=True,
        ok=bool(report.get("ok")),
        checked_at=report.get("checked_at"),
        runner=report.get("runner"),
        failure_count=report.get("failure_count"),
        checks=checks,
    )


@router.post("/watchdog/run-now", response_model=CeleryTaskIdResponse)
def site_watchdog_run_now() -> CeleryTaskIdResponse:
    """Enqueue site watchdog on the Slack Celery queue (same as scheduled checks)."""
    async_result = site_watchdog_check.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.get("/stats/export-readiness", response_model=ExportReadinessResponse)
def export_readiness(db: Session = Depends(get_db)) -> ExportReadinessResponse:
    """Null/gap counts for CSV columns and score rows — run before stakeholder exports."""
    raw = export_readiness_summary(db)
    return ExportReadinessResponse(**raw)


@router.get("/stats/pilot-scope", response_model=PilotScopeResponse)
def pilot_scope(db: Session = Depends(get_db)) -> PilotScopeResponse:
    """Pilot region, in-scope counties, and ingested parcel counts per county."""
    raw = pilot_scope_summary(db)
    counties = [PilotCountyScopeRow(**row) for row in raw.pop("counties")]
    floors = raw.pop("qualified_min_score")
    return PilotScopeResponse(
        **raw,
        qualified_min_score=QualifiedMinScores(**floors),
        counties=counties,
    )


@router.get("/stats/baltimore-zoning-tiers", response_model=BaltimoreZoningTiersResponse)
def baltimore_zoning_tiers(db: Session = Depends(get_db)) -> BaltimoreZoningTiersResponse:
    """Baltimore City parcel counts by principal-use parking entitlement tier (Postgres)."""
    raw = baltimore_zoning_tiers_summary(db)
    top = [BaltimoreZoningTierZoneRow(**row) for row in raw.pop("top_permitted_zones")]
    return BaltimoreZoningTiersResponse(**raw, top_permitted_zones=top)


@router.get("/stats/scoring-summary", response_model=ScoringSummaryResponse)
def scoring_summary(db: Session = Depends(get_db)) -> ScoringSummaryResponse:
    """Counts parcels and latest scores vs pilot floors (read-only; no Slack)."""
    return ScoringSummaryResponse(**scoring_summary_stats(db))


@router.get("/stats/platform-showcase", response_model=PlatformShowcaseResponse)
def platform_showcase(db: Session = Depends(get_db)) -> PlatformShowcaseResponse:
    """Live metrics for partner platform page (aggregates scoring, scope, pipeline, top deals)."""
    return PlatformShowcaseResponse(**build_platform_showcase(db))


def _revenue_summary_read(raw: dict[str, float | bool | int | str | None]) -> ParcelRevenueSummaryRead:
    return ParcelRevenueSummaryRead(
        revenue_available=bool(raw.get("revenue_available")),
        monthly_gross_usd=raw.get("monthly_gross_usd"),  # type: ignore[arg-type]
        monthly_gross_low_usd=raw.get("monthly_gross_low_usd"),  # type: ignore[arg-type]
        monthly_gross_high_usd=raw.get("monthly_gross_high_usd"),  # type: ignore[arg-type]
        stalls_estimated=raw.get("stalls_estimated"),  # type: ignore[arg-type]
        stalls_low=raw.get("stalls_low"),  # type: ignore[arg-type]
        stalls_high=raw.get("stalls_high"),  # type: ignore[arg-type]
        hourly_rate_weighted_usd=raw.get("hourly_rate_weighted_usd"),  # type: ignore[arg-type]
        hourly_rate_median_usd=raw.get("hourly_rate_median_usd"),  # type: ignore[arg-type]
        comp_count=raw.get("comp_count"),  # type: ignore[arg-type]
        nearest_comp_name=raw.get("nearest_comp_name"),  # type: ignore[arg-type]
        nearest_comp_distance_m=raw.get("nearest_comp_distance_m"),  # type: ignore[arg-type]
        market_confidence=raw.get("market_confidence"),  # type: ignore[arg-type]
        market_confidence_tier=raw.get("market_confidence_tier"),  # type: ignore[arg-type]
        strong_comp_count=raw.get("strong_comp_count"),  # type: ignore[arg-type]
        monthly_gross_raw_usd=raw.get("monthly_gross_raw_usd"),  # type: ignore[arg-type]
        market_evidence_notes=raw.get("market_evidence_notes"),  # type: ignore[arg-type]
    )


@router.get("/pipeline/outreach-board", response_model=OutreachPipelineBoardResponse)
def outreach_pipeline_board(
    limit: int = Query(default=100, ge=1, le=2000),
    revenue_hints: int = Query(
        default=0,
        ge=0,
        le=500,
        description="Max rows with revenue analysis (0 = all rows returned, up to limit)",
    ),
    county_fips: str | None = Query(default=None, min_length=5, max_length=5),
    state_fips: str | None = Query(default=None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
) -> OutreachPipelineBoardResponse:
    """Qualified parcels (latest entitlement ≥ pilot floor) with workflow + outreach brief snapshot."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = qualified_min_entitlement_score(pilot)
    raw = query_outreach_pipeline_board(
        db,
        qualified_min_entitlement=floor,
        limit=limit,
        county_fips=county_fips,
        state_fips=state_fips,
    )
    hint_cap = len(raw) if revenue_hints == 0 else min(revenue_hints, len(raw))
    revenue_by_parcel = attach_revenue_summaries(
        db,
        parcel_ids=[r.parcel_id for r in raw[:hint_cap]],
        pilot=pilot,
    )
    rows = [
        OutreachPipelineRow(
            parcel_id=str(r.parcel_id),
            apn=r.apn,
            county_fips=r.county_fips,
            entitlement_score=r.entitlement_score,
            identification_score=r.identification_score,
            workflow_run_id=str(r.workflow_run_id) if r.workflow_run_id else None,
            workflow_status=r.workflow_status,
            workflow_step=r.workflow_step,
            workflow_error=r.workflow_error,
            workflow_updated_at=r.workflow_updated_at,
            has_outreach_brief=r.has_outreach_brief,
            pending_approval_count=r.pending_approval_count,
            pipeline_stage=r.pipeline_stage,
            monthly_gross_usd=revenue_by_parcel.get(str(r.parcel_id), {}).get("monthly_gross_usd"),
            revenue_available=bool(
                revenue_by_parcel.get(str(r.parcel_id), {}).get("revenue_available"),
            ),
            revenue=(
                _revenue_summary_read(revenue_by_parcel[str(r.parcel_id)])
                if str(r.parcel_id) in revenue_by_parcel
                else None
            ),
        )
        for r in raw
    ]
    return OutreachPipelineBoardResponse(
        qualified_min_entitlement_score=floor,
        row_count=len(rows),
        rows=rows,
    )


@router.post("/rate-comps/seed-king-pilot", response_model=RateCompSeedResponse)
def seed_king_pilot_rate_comps(
    replace_existing: bool = False,
    db: Session = Depends(get_db),
) -> RateCompSeedResponse:
    """Load Puget Sound parking rate benchmarks into ``parking_rate_comps`` (idempotent)."""
    raw = seed_king_county_parking_rate_comps(db, replace_existing=replace_existing)
    return RateCompSeedResponse(**raw)


@router.post("/rate-comps/seed-baltimore-pilot", response_model=RateCompSeedResponse)
def seed_baltimore_pilot_rate_comps(
    replace_existing: bool = False,
    db: Session = Depends(get_db),
) -> RateCompSeedResponse:
    """Load Baltimore metro parking rate benchmarks into ``parking_rate_comps`` (idempotent)."""
    raw = seed_baltimore_parking_rate_comps(db, replace_existing=replace_existing)
    return RateCompSeedResponse(**raw)


@router.get("/pipeline/deal-progress", response_model=DealProgressBoardResponse)
def deal_progress_board(
    limit: int = Query(default=200, ge=1, le=2000),
    county_fips: str | None = Query(default=None, min_length=5, max_length=5),
    state_fips: str | None = Query(default=None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
) -> DealProgressBoardResponse:
    """Latest workflow run per parcel — avoids duplicate runs from batch re-triggers."""
    summary, raw = query_deal_progress_board(
        db,
        limit=limit,
        county_fips=county_fips,
        state_fips=state_fips,
    )
    rows = [
        DealProgressRow(
            parcel_id=str(r.parcel_id),
            apn=r.apn,
            county_fips=r.county_fips,
            workflow_run_id=str(r.workflow_run_id),
            workflow_status=r.workflow_status,
            workflow_step=r.workflow_step,
            workflow_error=r.workflow_error,
            workflow_updated_at=r.workflow_updated_at,
            pending_approval_count=r.pending_approval_count,
            pipeline_stage=r.pipeline_stage,
        )
        for r in raw
    ]
    return DealProgressBoardResponse(
        summary=DealProgressSummary(
            total_parcels=summary.total_parcels,
            by_status=summary.by_status,
            by_step=summary.by_step,
        ),
        row_count=len(rows),
        rows=rows,
    )


@router.get("/parcels/scored-list", response_model=ParcelScoredListResponse)
def parcels_scored_list(
    limit: int = Query(default=100, ge=1, le=2000),
    sort: ParcelSortProfile = Query(default=COMBINED),
    county_fips: str | None = Query(default=None, min_length=5, max_length=5),
    state_fips: str | None = Query(default=None, min_length=2, max_length=2),
    zoning_tier: str | None = Query(
        default=None,
        description="Filter by entitlement tier: permitted, conditional, council, excluded",
    ),
    qualified_only: bool = Query(
        default=False,
        description="Only parcels with latest entitlement ≥ pilot qualified floor",
    ),
    include_revenue: bool = Query(
        default=True,
        description="Attach illustrative revenue analysis for high-scoring rows",
    ),
    revenue_max_rows: int = Query(
        default=200,
        ge=0,
        le=500,
        description="Cap revenue computations per request (highest scores first)",
    ),
    min_entitlement_score: float | None = Query(
        default=None,
        ge=0,
        le=100,
        description="Minimum entitlement score for list filter and revenue (defaults to pilot floor)",
    ),
    db: Session = Depends(get_db),
) -> ParcelScoredListResponse:
    """All parcels with latest entitlement / strategic / identification scores (operator table)."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    if min_entitlement_score is not None:
        floor = float(min_entitlement_score)
    else:
        floor = qualified_min_entitlement_score(pilot)
    raw = query_parcels_scored_list(
        db,
        limit=limit,
        sort=sort,
        county_fips=county_fips,
        state_fips=state_fips,
        zoning_tier=zoning_tier,
        min_entitlement_score=floor if qualified_only else None,
    )
    revenue_ids: list[uuid.UUID] = []
    if include_revenue and revenue_max_rows > 0:
        for r in raw:
            if r.entitlement_score is not None and r.entitlement_score >= floor:
                revenue_ids.append(r.parcel_id)
            if len(revenue_ids) >= revenue_max_rows:
                break
    revenue_by_parcel = attach_revenue_summaries(db, parcel_ids=revenue_ids, pilot=pilot)
    rows = [
        ParcelScoredListRow(
            parcel_id=str(r.parcel_id),
            apn=r.apn,
            county_fips=r.county_fips,
            zoning_code=r.zoning_code,
            lot_sqft=r.lot_sqft,
            zoning_principal_use_symbol=r.zoning_principal_use_symbol,
            zoning_entitlement_tier=r.zoning_entitlement_tier,
            entitlement_score=r.entitlement_score,
            strategic_score=r.strategic_score,
            identification_score=r.identification_score,
            combined_score=r.combined_score,
            created_at=r.created_at,
            revenue=(
                _revenue_summary_read(revenue_by_parcel[str(r.parcel_id)])
                if str(r.parcel_id) in revenue_by_parcel
                else None
            ),
        )
        for r in raw
    ]
    return ParcelScoredListResponse(
        sort=sort,
        row_count=len(rows),
        qualified_min_entitlement_score=floor,
        revenue_rows_computed=len(revenue_by_parcel),
        rows=rows,
    )


@router.get("/slack/digest-preview", response_model=SlackDigestPreviewResponse)
def slack_digest_preview(hours: int = 4, db: Session = Depends(get_db)) -> SlackDigestPreviewResponse:
    """Build the next digest body from the DB without posting to Slack (debug Beat / channel config)."""
    h = min(max(hours, 1), 24)
    blocks, fallback = build_slack_digest_blocks(db, hours=h)
    s = get_settings()
    ch = (s.slack_digest_channel_id or "").strip()
    return SlackDigestPreviewResponse(
        hours=h,
        slack_digest_configured=bool((s.slack_bot_token or "").strip() and ch),
        digest_channel_id_set=bool(ch),
        fallback_preview=fallback,
        blocks=blocks,
    )


@router.post("/slack/digest-now", response_model=CeleryTaskIdResponse)
def trigger_slack_digest() -> CeleryTaskIdResponse:
    """Enqueue the same digest task Beat runs (for testing or ad-hoc standup)."""
    async_result = slack_agent_digest.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/slack/qualified-parcels-now", response_model=CeleryTaskIdResponse)
def trigger_qualified_parcels_report() -> CeleryTaskIdResponse:
    """Enqueue qualified-parcels Slack report (same task Beat runs daily)."""
    async_result = slack_qualified_parcels_report.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.get("/slack/agent-discussion-preview", response_model=SlackAgentDiscussionPreviewResponse)
def slack_agent_discussion_preview(
    db: Session = Depends(get_db),
) -> SlackAgentDiscussionPreviewResponse:
    """Build dual-agent Slack payloads without posting (debug channel + DB)."""
    posts = build_dual_agent_discussion_posts(db, settings=get_settings())
    return SlackAgentDiscussionPreviewResponse(
        message_count=len(posts),
        messages=[
            SlackAgentDiscussionMessagePreview(fallback=fb, blocks=blocks) for blocks, fb in posts
        ],
    )


@router.post("/slack/agent-discussion-now", response_model=CeleryTaskIdResponse)
def trigger_agent_discussion() -> CeleryTaskIdResponse:
    """Enqueue dual-agent discussion (same task Beat posts to agent channel)."""
    async_result = slack_dual_agent_discussion.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/slack/full-update-now", response_model=FullSlackUpdateResponse)
def trigger_full_slack_update() -> FullSlackUpdateResponse:
    """Enqueue digest, qualified-parcels report, and dual-agent discussion (one POST)."""
    d = slack_agent_digest.delay()
    q = slack_qualified_parcels_report.delay()
    a = slack_dual_agent_discussion.delay()
    return FullSlackUpdateResponse(
        digest_task_id=d.id,
        qualified_parcels_task_id=q.id,
        agent_discussion_task_id=a.id,
    )


@router.post("/slack/test-message", response_model=SlackTestMessagePostResponse)
def slack_test_message(body: SlackTestMessageRequest) -> SlackTestMessagePostResponse:
    """Send a one-off message to Slack.

    Uses SLACK_DIGEST_CHANNEL_ID by default; override with body.channel_id (Slack channel ID).
    """
    settings = get_settings()
    resp = post_text_to_slack(settings, text=body.text, channel_id=body.channel_id)
    ts = resp.get("ts")
    ch = resp.get("channel")
    return SlackTestMessagePostResponse(
        ok=bool(resp.get("ok")),
        ts=str(ts) if ts is not None else None,
        channel=str(ch) if ch is not None else None,
    )


@router.post("/ingest/sample", response_model=IngestSampleQueuedResponse)
def ingest_sample(
    auto_run_pipeline: bool = Query(
        default=True,
        description="Enqueue scoring/enrichment pipeline per parcel after ingest (recommended).",
    ),
    max_auto_pipeline: int = Query(default=100, ge=1, le=5000),
) -> IngestSampleQueuedResponse:
    """Load bundled GeoJSON for the pilot county (dev convenience).

    By default runs the full pipeline so parcels get dual scores and workflow runs.
    Disable with ``auto_run_pipeline=false`` if you only want raw parcel rows.
    """
    path = Path("/app/data/sample_parcels.geojson")
    if not path.exists():
        alt = Path(get_settings().pilot_config_path).parent.parent / "data" / "sample_parcels.geojson"
        if alt.exists():
            path = alt
        else:
            raise HTTPException(status_code=500, detail="sample_parcels.geojson not found")
    async_result = ingest_geojson_path.delay(
        str(path),
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
        delete_after=False,
    )
    return IngestSampleQueuedResponse(
        task_id=async_result.id,
        path=str(path),
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
    )


_MAX_GEOJSON_BYTES = 50 * 1024 * 1024


@router.post("/ingest/geojson-upload", response_model=IngestGeojsonUploadQueuedResponse)
def ingest_geojson_upload(
    file: UploadFile = File(..., description="GeoJSON FeatureCollection or single Feature (polygons)."),
    default_county_fips: str | None = Form(
        default=None,
        description="When features omit COUNTY_FIPS, set to a pilot county (e.g. 53033 King).",
    ),
    auto_run_pipeline: bool = Form(
        default=False,
        description="Enqueue scoring pipeline per parcel (capped by max_auto_pipeline).",
    ),
    max_auto_pipeline: int = Form(default=100, ge=1, le=5000),
) -> IngestGeojsonUploadQueuedResponse:
    """Upload a parcel GeoJSON export; enqueue ``ingest_geojson_path`` (upsert by county + APN/PIN).

    Property aliases are normalized in ``parking_ingestion.geojson_loader`` (PIN, acres→sqft, etc.).
    Poll ``GET /internal/tasks/{task_id}`` for completion; then
    ``GET /parcels?qualified_only=true`` after pipelines run.
    """
    raw = file.file.read(_MAX_GEOJSON_BYTES + 1)
    if len(raw) > _MAX_GEOJSON_BYTES:
        raise HTTPException(status_code=413, detail="GeoJSON exceeds 50MB")
    suffix = Path(file.filename or "parcels.geojson").suffix or ".geojson"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    async_result = ingest_geojson_path.delay(
        tmp_path,
        default_county_fips=default_county_fips,
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
        delete_after=True,
    )
    return IngestGeojsonUploadQueuedResponse(
        task_id=async_result.id,
        filename=file.filename,
        default_county_fips=default_county_fips,
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
    )


@router.post("/ingest/geojson-server-path", response_model=IngestGeojsonPathQueuedResponse)
def ingest_geojson_server_path(body: IngestGeojsonServerPathRequest) -> IngestGeojsonPathQueuedResponse:
    """Enqueue ingest for a GeoJSON file already on the server (large county exports).

    Same task as upload; use when you ``scp`` or ``rsync`` the file to the Droplet first.
    """
    p = Path(body.path)
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"not a file or missing: {body.path}")
    async_result = ingest_geojson_path.delay(
        str(p.resolve()),
        default_county_fips=body.default_county_fips,
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
        delete_after=False,
    )
    return IngestGeojsonPathQueuedResponse(
        task_id=async_result.id,
        path=str(p.resolve()),
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
    )


@router.post("/ingest/baltimore-city", response_model=WaTechCountyQueuedResponse)
def ingest_baltimore_city(body: IngestBaltimoreCityRequest) -> WaTechCountyQueuedResponse:
    """Fetch Baltimore City EGIS parcel polygons; enqueue download+ingest on the worker."""
    async_result = fetch_baltimore_city_and_ingest.delay(
        max_features=body.max_features,
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
    )
    return WaTechCountyQueuedResponse(fetch_task_id=async_result.id)


@router.post("/ingest/baltimore-county", response_model=WaTechCountyQueuedResponse)
def ingest_baltimore_county(body: IngestBaltimoreCountyRequest) -> WaTechCountyQueuedResponse:
    """Fetch Baltimore County tax parcel polygons; enqueue download+ingest on the worker."""
    async_result = fetch_baltimore_county_and_ingest.delay(
        max_features=body.max_features,
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
    )
    return WaTechCountyQueuedResponse(fetch_task_id=async_result.id)


@router.post("/ingest/watech-county", response_model=WaTechCountyQueuedResponse)
def ingest_watech_county(body: IngestWatechCountyRequest) -> WaTechCountyQueuedResponse:
    """Fetch public WaTech parcel polygons for one county; enqueue download+ingest on the worker."""
    async_result = fetch_watech_county_and_ingest.delay(
        county_fips=body.county_fips,
        max_features=body.max_features,
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
    )
    return WaTechCountyQueuedResponse(fetch_task_id=async_result.id)


@router.get("/ingest/wa-rollout-status", response_model=WaRolloutStatusResponse)
def wa_rollout_status(db: Session = Depends(get_db)) -> WaRolloutStatusResponse:
    """Progress for slow statewide WaTech ingest (one county per day when enabled)."""
    settings = get_settings()
    rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
    priority = county_priority_list(rollout, pilot_config_path=settings.pilot_config_path)
    counts = parcel_counts_by_county(db, priority)
    with_data = sum(1 for f in priority if counts.get(f, 0) > 0)
    next_fips = next_county_to_ingest(db, config=rollout, pilot_config_path=settings.pilot_config_path)
    q_depth: int | None = None
    try:
        q_depth = parking_queue_depth(settings.redis_url)
    except Exception:
        q_depth = None
    rows = [
        WaRolloutCountyRow(county_fips=fips, parcels_in_db=counts.get(fips, 0))
        for fips in priority
    ]
    return WaRolloutStatusResponse(
        rollout_enabled=settings.wa_statewide_rollout_enabled,
        next_county_fips=next_fips,
        counties_in_priority_list=len(priority),
        counties_with_parcels=with_data,
        counties_remaining=len(priority) - with_data,
        parking_queue_depth=q_depth,
        counties=rows,
    )


@router.post("/ingest/wa-rollout-now", response_model=CeleryTaskIdResponse)
def wa_rollout_now() -> CeleryTaskIdResponse:
    """Enqueue the next county ingest immediately (same logic as daily Beat)."""
    async_result = wa_statewide_rollout_tick.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/pipeline/enqueue-unscored", response_model=EnqueueUnscoredResponse)
def enqueue_unscored_pipelines(
    limit: int = 100,
) -> EnqueueUnscoredResponse:
    """Enqueue ``run_pipeline`` for parcels missing latest **entitlement** score (cap 500)."""
    raw = enqueue_unscored_pipeline_jobs(limit)
    return EnqueueUnscoredResponse(**raw)


@router.post("/pipeline/enqueue-incomplete", response_model=EnqueueIncompleteResponse)
def enqueue_incomplete_pipelines(
    limit: int = 100,
) -> EnqueueIncompleteResponse:
    """Enqueue ``run_pipeline`` when **entitlement** or **strategic** score is missing (Atlas/Beacon pair)."""
    raw = enqueue_incomplete_pipeline_jobs(limit)
    return EnqueueIncompleteResponse(**raw)


@router.post("/pipeline/enqueue-priority", response_model=EnqueueIncompleteResponse)
def enqueue_priority_pipelines(
    limit: int = 75,
) -> EnqueueIncompleteResponse:
    """Enqueue pipeline for prescreen-qualified parcels, highest entitlement score first."""
    raw = enqueue_priority_qualified_pipeline_jobs(limit)
    return EnqueueIncompleteResponse(**raw)


@router.post("/ingest/merge-geojson-attributes", response_model=CeleryTaskIdResponse)
def merge_geojson_attributes(body: MergeGeojsonAttributesRequest) -> CeleryTaskIdResponse:
    """Update zoning/corner/demand/lot fields on existing parcels from a GeoJSON overlay (Celery)."""
    async_result = merge_parcel_attributes_geojson.delay(
        body.path,
        default_county_fips=body.default_county_fips,
        delete_after=body.delete_after,
        refresh_pipeline=body.refresh_pipeline,
        max_pipeline=body.max_pipeline,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/refresh-demand-distances", response_model=CeleryTaskIdResponse)
def refresh_demand_distances(
    limit: int = 500,
    county_fips: str | None = None,
    process_all: bool = Query(
        False,
        description="When true with county_fips, refresh every parcel in the county (chunked).",
    ),
) -> CeleryTaskIdResponse:
    """Recompute centroid→demand POI distance from ``pilot.yaml`` generators (Celery)."""
    async_result = refresh_demand_distances_batch.delay(
        limit=limit,
        county_fips=county_fips,
        process_all=process_all,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/refresh-poi-density", response_model=CeleryTaskIdResponse)
def refresh_poi_density(
    limit: int = 50,
    county_fips: str | None = None,
    only_missing: bool = True,
) -> CeleryTaskIdResponse:
    """Count OSM commercial POIs near parcel centroids for demand-based revenue (Celery, rate-limited)."""
    async_result = refresh_poi_density_batch.delay(
        limit=limit,
        county_fips=county_fips,
        only_missing=only_missing,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/refresh-identification-scores", response_model=CeleryTaskIdResponse)
def refresh_identification_scores(
    limit: int = 2000,
    county_fips: str | None = None,
) -> CeleryTaskIdResponse:
    """Upsert identification (Cartographer) scores where missing — no full re-ingest required (Celery)."""
    async_result = refresh_identification_scores_batch.delay(
        limit=limit,
        county_fips=county_fips,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/refresh-entitlement-scores", response_model=CeleryTaskIdResponse)
def refresh_entitlement_scores(
    limit: int = 2000,
    county_fips: str | None = None,
    min_entitlement_score: float | None = None,
    process_all: bool = Query(
        False,
        description="When true with county_fips, rescore every parcel in the county (chunked).",
    ),
) -> CeleryTaskIdResponse:
    """Recompute Atlas entitlement scores from parcel features (zoning, lot, demand, comps)."""
    async_result = refresh_entitlement_scores_batch.delay(
        limit=limit,
        county_fips=county_fips,
        process_all=process_all,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/refresh-rate-comp-scores", response_model=CeleryTaskIdResponse)
def refresh_rate_comp_scores(
    limit: int = 500,
    county_fips: str | None = None,
    min_entitlement_score: float | None = None,
) -> CeleryTaskIdResponse:
    """Recompute Atlas/Beacon scores using multiple nearby paid parking comps (Celery)."""
    async_result = refresh_pipeline_scores_with_rate_comps_batch.delay(
        limit=limit,
        county_fips=county_fips,
        min_entitlement_score=min_entitlement_score,
    )
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.get("/owners/peers-by-key", response_model=OwnersPeersByKeyResponse)
def peers_by_normalized_owner_key(
    normalized_owner_key: str,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> OwnersPeersByKeyResponse:
    """Qualified parcels (latest entitlement ≥ pilot floor) sharing ``normalized_owner_key``."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    if not column_exists(db, "owner_candidates", "normalized_owner_key"):
        return OwnersPeersByKeyResponse(
            normalized_owner_key=normalized_owner_key,
            qualified_min_entitlement_score=floor,
            parcel_count=0,
            parcels=[],
        )
    lim = min(max(limit, 1), 500)
    parcels = list_peer_parcel_summaries(
        db,
        normalized_owner_key=normalized_owner_key,
        entitlement_floor=floor,
        limit=lim,
    )
    return OwnersPeersByKeyResponse(
        normalized_owner_key=normalized_owner_key,
        qualified_min_entitlement_score=floor,
        parcel_count=len(parcels),
        parcels=[PeerParcelSummary(**p) for p in parcels],
    )


@router.get("/owners/portfolios-ranked", response_model=OwnersPortfoliosRankedResponse)
def portfolios_ranked(
    min_peers: int = 2,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> OwnersPortfoliosRankedResponse:
    """Owner keys with multiple qualified parcels (rollup candidates)."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    mp = min(max(min_peers, 2), 500)
    if not column_exists(db, "owner_candidates", "normalized_owner_key"):
        return OwnersPortfoliosRankedResponse(
            qualified_min_entitlement_score=floor,
            min_peers=mp,
            portfolios=[],
        )
    lim = min(max(limit, 1), 200)
    rows = rank_owner_portfolios(db, entitlement_floor=floor, min_peers=mp, limit=lim)
    return OwnersPortfoliosRankedResponse(
        qualified_min_entitlement_score=floor,
        min_peers=mp,
        portfolios=[OwnerPortfolioRankRow(**r) for r in rows],
    )

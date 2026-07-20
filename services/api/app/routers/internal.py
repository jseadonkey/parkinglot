from __future__ import annotations

import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backlog_eta import backlog_eta_summary
from app.baltimore_zoning_stats import baltimore_zoning_tiers_summary
from app.celery_app import celery
from app.config import get_settings
from app.db.models import AuditLog
from app.db.schema_compat import column_exists
from app.db.session import get_db
from app.deal_progress import query_deal_progress_board
from app.deps_internal import require_internal_key
from app.export_readiness import export_readiness_summary
from app.geo_markets import wa_rollout_pacing
from app.lob_client import lob_status_payload, verify_lob_api_key
from app.outreach_board import query_outreach_pipeline_board
from app.owner_portfolio import list_peer_parcel_summaries, rank_owner_portfolios
from app.parcel_deal_context import attach_revenue_summaries, qualified_min_entitlement_score
from app.parcel_scored_list import COMBINED, ParcelSortProfile, query_parcels_scored_list
from app.pilot_scope import pilot_scope_summary
from app.pipeline_retries import enqueue_draft_storage_failure_reruns
from app.platform_showcase import build_platform_showcase
from app.rate_comp_seed import seed_baltimore_parking_rate_comps, seed_king_county_parking_rate_comps
from app.schemas import (
    BacklogEtaResponse,
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
    LoadGovernorResponse,
    LobConfigStatusResponse,
    LobVerifyResponse,
    MergeGeojsonAttributesRequest,
    OpsRemediationStatusResponse,
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
    PipelineRetryDraftStorageResponse,
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
    SlackPlanProgressPreviewResponse,
    SlackReportCatalogItem,
    SlackTestMessagePostResponse,
    SlackTestMessageRequest,
    WaPhaseBCountyCandidateRow,
    WaPhaseBRolloutStatusResponse,
    WaRolloutCountyRow,
    WaRolloutStatusResponse,
    WaTechCountyQueuedResponse,
)
from app.scoring_summary import scoring_summary_stats
from app.site_watchdog import watchdog_slack_channel
from app.slack_digest import (
    build_dual_agent_discussion_posts,
    build_plan_progress_report_blocks,
    build_slack_digest_blocks,
    post_text_to_slack,
    slack_agent_event_updates_enabled,
    slack_reporting_catalog,
)
from app.tasks import (
    backfill_baltimore_property_addresses_batch,
    backfill_wa_centroid_addresses_batch,
    enqueue_incomplete_pipeline_jobs,
    enqueue_priority_qualified_pipeline_jobs,
    enqueue_unscored_pipeline_jobs,
    fetch_baltimore_city_and_ingest,
    fetch_baltimore_county_and_ingest,
    fetch_watech_county_and_ingest,
    ingest_geojson_path,
    merge_parcel_attributes_geojson,
    ops_remediation_loop,
    refresh_demand_distances_batch,
    refresh_entitlement_scores_batch,
    refresh_identification_scores_batch,
    refresh_pipeline_scores_with_rate_comps_batch,
    refresh_poi_density_batch,
    site_watchdog_check,
    slack_agent_digest,
    slack_dual_agent_discussion,
    slack_plan_progress_report,
    slack_qualified_parcels_report,
    wa_phase_b_rollout_tick,
    wa_statewide_rollout_tick,
)
from app.wa_phase_b_rollout import load_phase_b_config, phase_b_status_summary
from app.wa_statewide_rollout import (
    county_priority_list,
    load_rollout_config,
    merge_rollout_config,
    next_county_to_ingest,
    parcel_counts_by_county,
    parking_queue_depth,
    wa_rollout_cooldown_state,
    wa_rollout_pending_ingest_state,
)
from app.wa_zoning_followup import build_zoning_followup_summary
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
    wd_ch = bool(watchdog_slack_channel(s))
    catalog = [
        SlackReportCatalogItem.model_validate(row) for row in slack_reporting_catalog(s)
    ]
    return SlackConfigStatusResponse(
        slack_digest_configured=has_token and has_channel,
        has_bot_token=has_token,
        has_digest_channel_id=has_channel,
        slack_dual_agent_configured=has_token and has_agent_ch,
        has_agent_discussion_channel_id=has_agent_ch,
        slack_agent_event_updates_enabled=slack_agent_event_updates_enabled(s),
        site_watchdog_enabled=bool(s.site_watchdog_enabled),
        site_watchdog_slack_configured=has_token and wd_ch,
        slack_digest_window_hours=max(1, int(s.slack_digest_window_hours or 1)),
        reporting_catalog=catalog,
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


@router.get("/ops/status", response_model=OpsRemediationStatusResponse)
def ops_remediation_status() -> OpsRemediationStatusResponse:
    """Last ops remediation loop report (Redis) — gaps, actions, worker health."""
    from app.ops_remediation import load_last_report

    report = load_last_report(get_settings())
    if report is None:
        return OpsRemediationStatusResponse(found=False)
    return OpsRemediationStatusResponse(
        found=True,
        ok=bool(report.get("ok")),
        checked_at=report.get("checked_at"),
        issue_count=report.get("issue_count"),
        critical_count=report.get("critical_count"),
        auto_fix_enabled=report.get("auto_fix_enabled"),
        issues=list(report.get("issues") or []),
        actions=list(report.get("actions") or []),
        celery_workers=report.get("celery_workers"),
        redis_queues=report.get("redis_queues"),
        priority_counties=report.get("priority_counties"),
    )


@router.post("/ops/run-now", response_model=CeleryTaskIdResponse)
def ops_remediation_run_now() -> CeleryTaskIdResponse:
    """Enqueue ops remediation loop (diagnose + optional auto-fix) on the Slack queue."""
    async_result = ops_remediation_loop.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/ops/prune-poi-queue")
def ops_prune_poi_queue(
    dry_run: bool = Query(False, description="Inspect only; do not remove queued POI refresh tasks."),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove queued POI refresh tasks that no longer have matching missing POI work."""
    from app.ops_remediation import prune_queued_poi_refresh_tasks

    return prune_queued_poi_refresh_tasks(db, get_settings(), dry_run=dry_run)


@router.get("/stats/export-readiness", response_model=ExportReadinessResponse)
def export_readiness(db: Session = Depends(get_db)) -> ExportReadinessResponse:
    """Null/gap counts for CSV columns and score rows — run before stakeholder exports."""
    raw = export_readiness_summary(db)
    return ExportReadinessResponse(**raw)


@router.get("/stats/backlog-eta", response_model=BacklogEtaResponse)
def backlog_eta(db: Session = Depends(get_db)) -> BacklogEtaResponse:
    """Backlog size, value, and rough completion estimates for operational decisions."""
    raw = backlog_eta_summary(db, get_settings())
    return BacklogEtaResponse(**raw)


@router.get("/stats/load-governor", response_model=LoadGovernorResponse)
def load_governor_stats() -> LoadGovernorResponse:
    """Downstream load pressure and effective caps for pipeline enqueue / WA rollout."""
    from app.load_governor import refresh_load_governor

    settings = get_settings()
    if not settings.load_governor_enabled:
        raise HTTPException(status_code=503, detail="load_governor_disabled")
    raw = refresh_load_governor(settings)
    assessed = raw.get("assessed_at")
    return LoadGovernorResponse(
        assessed_at=assessed,
        pressure_level=str(raw.get("pressure_level") or "green"),
        parking_queue_depth=int(raw.get("parking_queue_depth") or 0),
        workers_online=bool(raw.get("workers_online")),
        worker_detail=raw.get("worker_detail"),
        score_gaps=int(raw.get("score_gaps") or 0),
        pipeline_funnel_backlog=int(raw.get("pipeline_funnel_backlog") or 0),
        signals=list(raw.get("signals") or []),
        decision=str(raw.get("decision") or ""),
        wa_rollout_allowed=bool(raw.get("wa_rollout_allowed", True)),
        ops_autofix_allowed=bool(raw.get("ops_autofix_allowed", True)),
        pipeline_enqueue_multiplier=float(raw.get("pipeline_enqueue_multiplier") or 1.0),
        max_auto_pipeline_effective=int(raw.get("max_auto_pipeline_effective") or 0),
        min_days_between_counties_effective=float(
            raw.get("min_days_between_counties_effective") or 0,
        ),
    )


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
    """Highest-scoring outreach target parcels with workflow + outreach brief snapshot."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = qualified_min_entitlement_score(pilot)
    outreach_ent_floor = float(settings.owner_outreach_min_entitlement_score)
    outreach_str_floor = float(settings.owner_outreach_min_strategic_score)
    raw = query_outreach_pipeline_board(
        db,
        min_entitlement=outreach_ent_floor,
        min_strategic=outreach_str_floor,
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
            strategic_score=r.strategic_score,
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
        owner_outreach_min_entitlement_score=outreach_ent_floor,
        owner_outreach_min_strategic_score=outreach_str_floor,
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
        description="Filter by entitlement tier: permitted, conditional, provisional, council, excluded, prospect",
    ),
    suitability: str | None = Query(
        default=None,
        description=(
            "Site suitability: vacant, underutilized, vacant_or_underutilized, "
            "existing_parking, not_existing_parking"
        ),
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
        suitability=suitability,
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
            situs_address=r.situs_address,
            mailing_address=r.mailing_address,
            situs_address_approximate=r.situs_address_approximate,
            zoning_code=r.zoning_code,
            lot_sqft=r.lot_sqft,
            zoning_principal_use_symbol=r.zoning_principal_use_symbol,
            zoning_entitlement_tier=r.zoning_entitlement_tier,
            suitability=r.suitability,
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
    s = get_settings()
    blocks, fallback = build_slack_digest_blocks(db, hours=h, settings=s)
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


@router.get("/slack/plan-progress-preview", response_model=SlackPlanProgressPreviewResponse)
def slack_plan_progress_preview(db: Session = Depends(get_db)) -> SlackPlanProgressPreviewResponse:
    """Build the A-E plan progress Slack payload without posting."""
    blocks, fallback = build_plan_progress_report_blocks(db)
    s = get_settings()
    ch = (s.slack_digest_channel_id or "").strip()
    return SlackPlanProgressPreviewResponse(
        slack_digest_configured=bool((s.slack_bot_token or "").strip() and ch),
        digest_channel_id_set=bool(ch),
        fallback_preview=fallback,
        blocks=blocks,
    )


@router.post("/slack/plan-progress-now", response_model=CeleryTaskIdResponse)
def trigger_plan_progress_report() -> CeleryTaskIdResponse:
    """Enqueue the hourly A-E plan progress report (same task Beat runs)."""
    async_result = slack_plan_progress_report.delay()
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
    """Enqueue digest, plan progress, qualified-parcels report, and dual-agent discussion."""
    d = slack_agent_digest.delay()
    p = slack_plan_progress_report.delay()
    q = slack_qualified_parcels_report.delay()
    a = slack_dual_agent_discussion.delay()
    return FullSlackUpdateResponse(
        digest_task_id=d.id,
        plan_progress_task_id=p.id,
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
    """Progress for slow statewide WaTech ingest (size-based cooldown between counties)."""
    settings = get_settings()
    rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
    merged = merge_rollout_config(rollout, wa_rollout_pacing())
    priority = county_priority_list(rollout, pilot_config_path=settings.pilot_config_path)
    counts = parcel_counts_by_county(db, priority)
    with_data = sum(1 for f in priority if counts.get(f, 0) > 0)
    next_fips = next_county_to_ingest(db, config=rollout, pilot_config_path=settings.pilot_config_path)
    cooldown = wa_rollout_cooldown_state(db, merged)
    pending = wa_rollout_pending_ingest_state(db, merged)
    q_depth: int | None = None
    try:
        q_depth = parking_queue_depth(settings.redis_url)
    except Exception:
        q_depth = None
    rows = [
        WaRolloutCountyRow(county_fips=fips, parcels_in_db=counts.get(fips, 0))
        for fips in priority
    ]
    zoning_followup = build_zoning_followup_summary(
        parcel_counts=counts,
        registry_path=settings.wa_jurisdiction_registry_path,
        priority_order=priority,
    )
    return WaRolloutStatusResponse(
        rollout_enabled=settings.wa_statewide_rollout_enabled,
        next_county_fips=next_fips,
        counties_in_priority_list=len(priority),
        counties_with_parcels=with_data,
        counties_remaining=len(priority) - with_data,
        parking_queue_depth=q_depth,
        cooldown_ready=cooldown.get("ready"),
        required_cooldown_days=cooldown.get("required_cooldown_days"),
        days_since_last_county_ingest=cooldown.get("days_since_last_ingest"),
        last_ingested_county_fips=cooldown.get("last_county_fips"),
        last_ingested_county_parcels=cooldown.get("last_county_parcels_in_db"),
        pending_ingest_county_fips=pending.get("pending_county_fips"),
        pending_ingest_age_days=pending.get("pending_age_days"),
        pending_ingest_lock_days=pending.get("pending_lock_days"),
        counties=rows,
        zoning_followup=zoning_followup,
    )


@router.post("/ingest/wa-rollout-now", response_model=CeleryTaskIdResponse)
def wa_rollout_now() -> CeleryTaskIdResponse:
    """Enqueue the next county ingest immediately (same logic as daily Beat)."""
    async_result = wa_statewide_rollout_tick.delay()
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.get("/ingest/wa-phase-b-rollout-status", response_model=WaPhaseBRolloutStatusResponse)
def wa_phase_b_rollout_status(db: Session = Depends(get_db)) -> WaPhaseBRolloutStatusResponse:
    """Progress for capacity-gated WA Phase B zoning overlay merges."""
    settings = get_settings()
    phase_b = load_phase_b_config(settings.wa_phase_b_rollout_config_path)
    parcel_rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
    raw = phase_b_status_summary(
        db,
        config=phase_b,
        pilot_config_path=settings.pilot_config_path,
        parcel_rollout_config=parcel_rollout,
        rollout_enabled=settings.wa_phase_b_rollout_enabled,
        redis_url=settings.redis_url,
    )
    counties = [WaPhaseBCountyCandidateRow(**row) for row in raw.get("counties") or []]
    zoning_raw = raw.get("zoning_followup")
    from app.schemas import WaZoningFollowupSummary

    zoning = WaZoningFollowupSummary(**zoning_raw) if isinstance(zoning_raw, dict) else None
    return WaPhaseBRolloutStatusResponse(
        rollout_enabled=bool(raw.get("rollout_enabled")),
        next_county_fips=raw.get("next_county_fips"),
        cooldown_ready=raw.get("cooldown_ready"),
        required_cooldown_hours=raw.get("required_cooldown_hours"),
        hours_since_last_merge=raw.get("hours_since_last_merge"),
        last_merged_county_fips=raw.get("last_merged_county_fips"),
        pending_merge_county_fips=raw.get("pending_merge_county_fips"),
        pending_merge_age_hours=raw.get("pending_merge_age_hours"),
        pending_merge_lock_hours=raw.get("pending_merge_lock_hours"),
        counties=counties,
        zoning_followup=zoning,
    )


@router.post("/ingest/wa-phase-b-rollout-now", response_model=CeleryTaskIdResponse)
def wa_phase_b_rollout_now() -> CeleryTaskIdResponse:
    """Enqueue the next county Phase B merge immediately (same logic as scheduled Beat)."""
    async_result = wa_phase_b_rollout_tick.delay()
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


@router.post("/pipeline/retry-draft-storage-failures", response_model=PipelineRetryDraftStorageResponse)
def retry_draft_storage_failures(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PipelineRetryDraftStorageResponse:
    """Rerun failed pipelines caused by the formerly missing draft-storage bucket."""
    raw = enqueue_draft_storage_failure_reruns(db, limit=limit)
    return PipelineRetryDraftStorageResponse(**raw)


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
    process_all: bool = Query(
        False,
        description="When true with county_fips, process all matching parcels in chunked batches.",
    ),
) -> CeleryTaskIdResponse:
    """Count OSM commercial POIs for qualified parcels, optionally scoped to one county."""
    async_result = refresh_poi_density_batch.delay(
        limit=limit,
        county_fips=county_fips,
        only_missing=only_missing,
        process_all=process_all,
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


@router.post("/metrics/backfill-baltimore-addresses", response_model=CeleryTaskIdResponse)
def backfill_baltimore_addresses(
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Measured batch size; start small while Postgres CPU is elevated.",
    ),
    dry_run: bool = Query(default=False, description="Fetch/match but do not update rows."),
) -> CeleryTaskIdResponse:
    """Backfill Baltimore City property/situs addresses from Realproperty_OB in a bounded batch."""
    async_result = backfill_baltimore_property_addresses_batch.delay(limit=limit, dry_run=dry_run)
    return CeleryTaskIdResponse(task_id=async_result.id)


@router.post("/metrics/backfill-wa-centroid-addresses", response_model=CeleryTaskIdResponse)
def backfill_wa_centroid_addresses(
    limit: int = Query(default=100, ge=1, le=1000),
    county_fips: str | None = Query(default=None, description="Optional 5-digit WA county FIPS (53xxx)."),
    dry_run: bool = Query(default=False),
) -> CeleryTaskIdResponse:
    """Candidate-only WA situs backfill using parcel centroid + assessor city/ZIP anchor."""
    async_result = backfill_wa_centroid_addresses_batch.delay(
        limit=limit,
        county_fips=county_fips,
        dry_run=dry_run,
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

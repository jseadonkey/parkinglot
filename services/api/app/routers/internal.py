from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config import get_settings
from app.db.models import AuditLog, Parcel
from app.db.schema_compat import column_exists
from app.db.session import get_db
from app.deal_progress import query_deal_progress_board
from app.deps_internal import require_internal_key
from app.export_readiness import export_readiness_summary
from app.pilot_scope import pilot_scope_summary
from app.outreach_board import query_outreach_pipeline_board
from app.owner_portfolio import list_peer_parcel_summaries, rank_owner_portfolios
from app.parcel_scored_list import COMBINED, ParcelSortProfile, query_parcels_scored_list
from app.schemas import (
    CeleryTaskIdResponse,
    CeleryTaskStatusResponse,
    DealProgressBoardResponse,
    DealProgressRow,
    DealProgressSummary,
    EnqueueIncompleteResponse,
    EnqueueUnscoredResponse,
    ExportReadinessResponse,
    FullSlackUpdateResponse,
    IngestGeojsonPathQueuedResponse,
    IngestGeojsonServerPathRequest,
    IngestGeojsonUploadQueuedResponse,
    IngestSampleQueuedResponse,
    IngestWatechCountyRequest,
    MergeGeojsonAttributesRequest,
    OutreachPipelineBoardResponse,
    OutreachPipelineRow,
    OwnerPortfolioRankRow,
    OwnersPeersByKeyResponse,
    OwnersPortfoliosRankedResponse,
    ParcelScoredListResponse,
    ParcelScoredListRow,
    PeerParcelSummary,
    PilotCountyScopeRow,
    PilotScopeResponse,
    QualifiedMinScores,
    ScoringSummaryResponse,
    SlackAgentDiscussionMessagePreview,
    SlackAgentDiscussionPreviewResponse,
    SlackConfigStatusResponse,
    SlackDigestPreviewResponse,
    SlackLastDigestResponse,
    SlackTestMessagePostResponse,
    SlackTestMessageRequest,
    WaTechCountyQueuedResponse,
)
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.slack_digest import (
    _fetch_latest_scores_per_parcel,
    _paired_latest_scores,
    build_dual_agent_discussion_posts,
    build_slack_digest_blocks,
    post_text_to_slack,
    slack_agent_event_updates_enabled,
)
from app.tasks import (
    enqueue_incomplete_pipeline_jobs,
    enqueue_unscored_pipeline_jobs,
    fetch_watech_county_and_ingest,
    ingest_geojson_path,
    merge_parcel_attributes_geojson,
    refresh_demand_distances_batch,
    refresh_identification_scores_batch,
    slack_agent_digest,
    slack_dual_agent_discussion,
    slack_qualified_parcels_report,
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


@router.get("/stats/scoring-summary", response_model=ScoringSummaryResponse)
def scoring_summary(db: Session = Depends(get_db)) -> ScoringSummaryResponse:
    """Counts parcels and latest scores vs pilot floors (read-only; no Slack)."""
    settings = get_settings()
    pilot_e = load_pilot_config(settings.pilot_config_path)
    pilot_s = load_pilot_config(settings.pilot_strategic_config_path)
    pilot_i = load_pilot_config(settings.pilot_identification_config_path)
    floor_e = float(pilot_e.scoring.qualified_min_score)
    floor_s = float(pilot_s.scoring.qualified_min_score)
    floor_i = float(pilot_i.scoring.qualified_min_score)

    ent_rows = _fetch_latest_scores_per_parcel(db, profile=ENTITLEMENT)
    str_rows = _fetch_latest_scores_per_parcel(db, profile=STRATEGIC)
    id_rows = _fetch_latest_scores_per_parcel(db, profile=IDENTIFICATION)
    paired = _paired_latest_scores(db)

    q_ent = sum(1 for _, ps in ent_rows if float(ps.total_score) >= floor_e)
    q_str = sum(1 for _, ps in str_rows if float(ps.total_score) >= floor_s)
    q_id = sum(1 for _, ps in id_rows if float(ps.total_score) >= floor_i)

    total_parcels = db.scalar(select(func.count()).select_from(Parcel))
    if total_parcels is None:
        total_parcels = 0

    return ScoringSummaryResponse(
        total_parcels=int(total_parcels),
        parcels_with_latest_entitlement_score=len(ent_rows),
        parcels_with_latest_strategic_score=len(str_rows),
        parcels_with_latest_identification_score=len(id_rows),
        parcels_with_both_profiles_scored=len(paired),
        qualified_count_entitlement=q_ent,
        qualified_count_strategic=q_str,
        qualified_count_identification=q_id,
        qualified_min_score={
            "entitlement": floor_e,
            "strategic": floor_s,
            "identification": floor_i,
        },
        pilot_region=pilot_e.region.name,
    )


@router.get("/pipeline/outreach-board", response_model=OutreachPipelineBoardResponse)
def outreach_pipeline_board(
    limit: int = Query(default=100, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> OutreachPipelineBoardResponse:
    """Qualified parcels (latest entitlement ≥ pilot floor) with workflow + outreach brief snapshot."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    raw = query_outreach_pipeline_board(db, qualified_min_entitlement=floor, limit=limit)
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
        )
        for r in raw
    ]
    return OutreachPipelineBoardResponse(
        qualified_min_entitlement_score=floor,
        row_count=len(rows),
        rows=rows,
    )


@router.get("/pipeline/deal-progress", response_model=DealProgressBoardResponse)
def deal_progress_board(
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> DealProgressBoardResponse:
    """Latest workflow run per parcel — avoids duplicate runs from batch re-triggers."""
    summary, raw = query_deal_progress_board(db, limit=limit)
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
    db: Session = Depends(get_db),
) -> ParcelScoredListResponse:
    """All parcels with latest entitlement / strategic / identification scores (operator table)."""
    raw = query_parcels_scored_list(db, limit=limit, sort=sort)
    rows = [
        ParcelScoredListRow(
            parcel_id=str(r.parcel_id),
            apn=r.apn,
            county_fips=r.county_fips,
            zoning_code=r.zoning_code,
            lot_sqft=r.lot_sqft,
            entitlement_score=r.entitlement_score,
            strategic_score=r.strategic_score,
            identification_score=r.identification_score,
            combined_score=r.combined_score,
            created_at=r.created_at,
        )
        for r in raw
    ]
    return ParcelScoredListResponse(sort=sort, row_count=len(rows), rows=rows)


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
) -> CeleryTaskIdResponse:
    """Recompute centroid→demand POI distance from ``pilot.yaml`` generators (Celery)."""
    async_result = refresh_demand_distances_batch.delay(
        limit=limit,
        county_fips=county_fips,
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

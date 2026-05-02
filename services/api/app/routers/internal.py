from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config import get_settings
from app.db.models import Parcel
from app.db.session import get_db
from app.owner_portfolio import list_peer_parcel_summaries, rank_owner_portfolios
from app.deps_internal import require_internal_key
from app.export_readiness import export_readiness_summary
from app.schemas import (
    IngestGeojsonServerPathRequest,
    IngestWatechCountyRequest,
    MergeGeojsonAttributesRequest,
    SlackTestMessageRequest,
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


@router.get("/tasks/{task_id}")
def celery_task_status(task_id: str) -> dict[str, Any]:
    """Inspect a Celery task by id (ids from async POST endpoints).

    Requires ``X-Internal-Key`` when ``INTERNAL_API_KEY`` is set.
    """
    result = celery.AsyncResult(task_id)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "state": result.state,
        "ready": result.ready(),
    }
    if result.ready():
        if result.successful():
            payload["result"] = result.result
        else:
            err = result.result
            payload["error"] = str(err) if err is not None else None
            tb = result.traceback
            if isinstance(tb, str) and len(tb) > 4000:
                tb = tb[:4000] + "\n... (truncated)"
            payload["traceback"] = tb
    return payload


@router.get("/slack/status")
def slack_config_status() -> dict[str, bool]:
    """Whether Slack digest env is set (no token values returned)."""
    s = get_settings()
    has_token = bool((s.slack_bot_token or "").strip())
    has_channel = bool((s.slack_digest_channel_id or "").strip())
    has_agent_ch = bool((s.slack_agent_discussion_channel_id or "").strip())
    return {
        "slack_digest_configured": has_token and has_channel,
        "has_bot_token": has_token,
        "has_digest_channel_id": has_channel,
        "slack_dual_agent_configured": has_token and has_agent_ch,
        "has_agent_discussion_channel_id": has_agent_ch,
        "slack_agent_event_updates_enabled": slack_agent_event_updates_enabled(s),
    }


@router.get("/stats/export-readiness")
def export_readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Null/gap counts for CSV columns and score rows — run before stakeholder exports."""
    return export_readiness_summary(db)


@router.get("/stats/scoring-summary")
def scoring_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
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

    return {
        "total_parcels": int(total_parcels),
        "parcels_with_latest_entitlement_score": len(ent_rows),
        "parcels_with_latest_strategic_score": len(str_rows),
        "parcels_with_latest_identification_score": len(id_rows),
        "parcels_with_both_profiles_scored": len(paired),
        "qualified_count_entitlement": q_ent,
        "qualified_count_strategic": q_str,
        "qualified_count_identification": q_id,
        "qualified_min_score": {"entitlement": floor_e, "strategic": floor_s, "identification": floor_i},
        "pilot_region": pilot_e.region.name,
    }


@router.get("/slack/digest-preview")
def slack_digest_preview(hours: int = 4, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Build the next digest body from the DB without posting to Slack (debug Beat / channel config)."""
    h = min(max(hours, 1), 24)
    blocks, fallback = build_slack_digest_blocks(db, hours=h)
    s = get_settings()
    ch = (s.slack_digest_channel_id or "").strip()
    return {
        "hours": h,
        "slack_digest_configured": bool((s.slack_bot_token or "").strip() and ch),
        "digest_channel_id_set": bool(ch),
        "fallback_preview": fallback,
        "blocks": blocks,
    }


@router.post("/slack/digest-now")
def trigger_slack_digest() -> dict[str, str]:
    """Enqueue the same digest task Beat runs (for testing or ad-hoc standup)."""
    async_result = slack_agent_digest.delay()
    return {"task_id": async_result.id}


@router.post("/slack/qualified-parcels-now")
def trigger_qualified_parcels_report() -> dict[str, str]:
    """Enqueue qualified-parcels Slack report (same task Beat runs daily)."""
    async_result = slack_qualified_parcels_report.delay()
    return {"task_id": async_result.id}


@router.get("/slack/agent-discussion-preview")
def slack_agent_discussion_preview(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Build dual-agent Slack payloads without posting (debug channel + DB)."""
    posts = build_dual_agent_discussion_posts(db, settings=get_settings())
    return {
        "message_count": len(posts),
        "messages": [{"fallback": fb, "blocks": blocks} for blocks, fb in posts],
    }


@router.post("/slack/agent-discussion-now")
def trigger_agent_discussion() -> dict[str, str]:
    """Enqueue dual-agent discussion (same task Beat posts to agent channel)."""
    async_result = slack_dual_agent_discussion.delay()
    return {"task_id": async_result.id}


@router.post("/slack/full-update-now")
def trigger_full_slack_update() -> dict[str, str]:
    """Enqueue digest, qualified-parcels report, and dual-agent discussion (one POST)."""
    d = slack_agent_digest.delay()
    q = slack_qualified_parcels_report.delay()
    a = slack_dual_agent_discussion.delay()
    return {
        "digest_task_id": d.id,
        "qualified_parcels_task_id": q.id,
        "agent_discussion_task_id": a.id,
    }


@router.post("/slack/test-message")
def slack_test_message(body: SlackTestMessageRequest) -> dict[str, object]:
    """Send a one-off message to Slack.

    Uses SLACK_DIGEST_CHANNEL_ID by default; override with body.channel_id (Slack channel ID).
    """
    settings = get_settings()
    resp = post_text_to_slack(settings, text=body.text, channel_id=body.channel_id)
    return {"ok": bool(resp.get("ok")), "ts": resp.get("ts"), "channel": resp.get("channel")}


@router.post("/ingest/sample")
def ingest_sample(
    auto_run_pipeline: bool = Query(
        default=True,
        description="Enqueue scoring/enrichment pipeline per parcel after ingest (recommended).",
    ),
    max_auto_pipeline: int = Query(default=100, ge=1, le=5000),
) -> dict[str, object]:
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
    return {
        "task_id": async_result.id,
        "path": str(path),
        "auto_run_pipeline": auto_run_pipeline,
        "max_auto_pipeline": max_auto_pipeline,
    }


_MAX_GEOJSON_BYTES = 50 * 1024 * 1024


@router.post("/ingest/geojson-upload")
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
) -> dict[str, object]:
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
    return {
        "task_id": async_result.id,
        "filename": file.filename,
        "default_county_fips": default_county_fips,
        "auto_run_pipeline": auto_run_pipeline,
        "max_auto_pipeline": max_auto_pipeline,
    }


@router.post("/ingest/geojson-server-path")
def ingest_geojson_server_path(body: IngestGeojsonServerPathRequest) -> dict[str, object]:
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
    return {
        "task_id": async_result.id,
        "path": str(p.resolve()),
        "auto_run_pipeline": body.auto_run_pipeline,
        "max_auto_pipeline": body.max_auto_pipeline,
    }


@router.post("/ingest/watech-county")
def ingest_watech_county(body: IngestWatechCountyRequest) -> dict[str, object]:
    """Fetch public WaTech parcel polygons for one county; enqueue download+ingest on the worker."""
    async_result = fetch_watech_county_and_ingest.delay(
        county_fips=body.county_fips,
        max_features=body.max_features,
        auto_run_pipeline=body.auto_run_pipeline,
        max_auto_pipeline=body.max_auto_pipeline,
    )
    return {"fetch_task_id": async_result.id}


@router.post("/pipeline/enqueue-unscored")
def enqueue_unscored_pipelines(
    limit: int = 100,
) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` for parcels missing latest **entitlement** score (cap 500)."""
    return enqueue_unscored_pipeline_jobs(limit)


@router.post("/pipeline/enqueue-incomplete")
def enqueue_incomplete_pipelines(
    limit: int = 100,
) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` when **entitlement** or **strategic** score is missing (Atlas/Beacon pair)."""
    return enqueue_incomplete_pipeline_jobs(limit)


@router.post("/ingest/merge-geojson-attributes")
def merge_geojson_attributes(body: MergeGeojsonAttributesRequest) -> dict[str, Any]:
    """Update zoning/corner/demand/lot fields on existing parcels from a GeoJSON overlay (Celery)."""
    async_result = merge_parcel_attributes_geojson.delay(
        body.path,
        default_county_fips=body.default_county_fips,
        delete_after=body.delete_after,
        refresh_pipeline=body.refresh_pipeline,
        max_pipeline=body.max_pipeline,
    )
    return {"task_id": async_result.id}


@router.post("/metrics/refresh-demand-distances")
def refresh_demand_distances(
    limit: int = 500,
    county_fips: str | None = None,
) -> dict[str, Any]:
    """Recompute centroid→demand POI distance from ``pilot.yaml`` generators (Celery)."""
    async_result = refresh_demand_distances_batch.delay(
        limit=limit,
        county_fips=county_fips,
    )
    return {"task_id": async_result.id}


@router.post("/metrics/refresh-identification-scores")
def refresh_identification_scores(
    limit: int = 2000,
    county_fips: str | None = None,
) -> dict[str, Any]:
    """Upsert identification (Cartographer) scores where missing — no full re-ingest required (Celery)."""
    async_result = refresh_identification_scores_batch.delay(
        limit=limit,
        county_fips=county_fips,
    )
    return {"task_id": async_result.id}


@router.get("/owners/peers-by-key")
def peers_by_normalized_owner_key(
    normalized_owner_key: str,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Qualified parcels (latest entitlement ≥ pilot floor) sharing ``normalized_owner_key``."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    lim = min(max(limit, 1), 500)
    parcels = list_peer_parcel_summaries(
        db,
        normalized_owner_key=normalized_owner_key,
        entitlement_floor=floor,
        limit=lim,
    )
    return {
        "normalized_owner_key": normalized_owner_key,
        "qualified_min_entitlement_score": floor,
        "parcel_count": len(parcels),
        "parcels": parcels,
    }


@router.get("/owners/portfolios-ranked")
def portfolios_ranked(
    min_peers: int = 2,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Owner keys with multiple qualified parcels (rollup candidates)."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    mp = min(max(min_peers, 2), 500)
    lim = min(max(limit, 1), 200)
    rows = rank_owner_portfolios(db, entitlement_floor=floor, min_peers=mp, limit=lim)
    return {
        "qualified_min_entitlement_score": floor,
        "min_peers": mp,
        "portfolios": rows,
    }

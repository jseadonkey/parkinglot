from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config import get_settings
from app.db.models import Parcel, ParcelScore
from app.db.session import get_db
from app.deps_internal import require_internal_key
from app.schemas import IngestGeojsonServerPathRequest, SlackTestMessageRequest
from app.slack_digest import post_text_to_slack
from app.tasks import ingest_geojson_path, run_pipeline, slack_agent_digest

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
    return {
        "slack_digest_configured": has_token and has_channel,
        "has_bot_token": has_token,
        "has_digest_channel_id": has_channel,
    }


@router.post("/slack/digest-now")
def trigger_slack_digest() -> dict[str, str]:
    """Enqueue the same digest task Beat runs (for testing or ad-hoc standup)."""
    async_result = slack_agent_digest.delay()
    return {"task_id": async_result.id}


@router.post("/slack/test-message")
def slack_test_message(body: SlackTestMessageRequest) -> dict[str, object]:
    """Send a one-off message to Slack.

    Uses SLACK_DIGEST_CHANNEL_ID by default; override with body.channel_id (Slack channel ID).
    """
    settings = get_settings()
    resp = post_text_to_slack(settings, text=body.text, channel_id=body.channel_id)
    return {"ok": bool(resp.get("ok")), "ts": resp.get("ts"), "channel": resp.get("channel")}


@router.post("/ingest/sample")
def ingest_sample() -> dict[str, object]:
    """Load bundled GeoJSON for the pilot county (dev convenience)."""
    path = Path("/app/data/sample_parcels.geojson")
    if not path.exists():
        alt = Path(get_settings().pilot_config_path).parent.parent / "data" / "sample_parcels.geojson"
        if alt.exists():
            path = alt
        else:
            raise HTTPException(status_code=500, detail="sample_parcels.geojson not found")
    async_result = ingest_geojson_path.delay(str(path))
    return {"task_id": async_result.id, "path": str(path)}


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


@router.post("/pipeline/enqueue-unscored")
def enqueue_unscored_pipelines(
    limit: int = 100,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` for parcels that have no ``parcel_scores`` row yet (cap 500)."""
    cap = min(max(limit, 1), 500)
    stmt = (
        select(Parcel.id)
        .where(~exists(select(1).where(ParcelScore.parcel_id == Parcel.id)))
        .order_by(Parcel.created_at.desc())
        .limit(cap)
    )
    ids = [str(i) for i in db.scalars(stmt)]
    for pid in ids:
        run_pipeline.delay(pid)
    return {"enqueued": len(ids), "parcel_ids": ids}

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.celery_app import celery
from app.config import get_settings
from app.deps_internal import require_internal_key
from app.schemas import SlackTestMessageRequest
from app.slack_digest import post_text_to_slack
from app.tasks import ingest_geojson_path, slack_agent_digest

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

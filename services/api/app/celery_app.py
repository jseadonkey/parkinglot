from __future__ import annotations

import logging
import os

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.config import get_settings

broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

logger = logging.getLogger(__name__)

PARKING_QUEUE = "parking"
SLACK_QUEUE = "slack"

SLACK_TASK_NAMES: tuple[str, ...] = (
    "app.tasks.slack_agent_digest",
    "app.tasks.slack_qualified_parcels_report",
    "app.tasks.slack_dual_agent_discussion",
    "app.tasks.site_watchdog_check",
)

_SLACK_BEAT_OPTIONS = {"queue": SLACK_QUEUE}

_s = get_settings()

beat_schedule: dict = {
    "slack-parking-digest-hourly": {
        "task": "app.tasks.slack_agent_digest",
        "schedule": crontab(
            minute=_s.slack_digest_crontab_minute,
            hour=_s.slack_digest_crontab_hour,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    },
    "slack-qualified-parcels-daily": {
        "task": "app.tasks.slack_qualified_parcels_report",
        "schedule": crontab(minute=0, hour=14),
        "options": _SLACK_BEAT_OPTIONS,
    },
    "slack-dual-agent-discussion-daily": {
        "task": "app.tasks.slack_dual_agent_discussion",
        "schedule": crontab(minute=30, hour=15),
        "options": _SLACK_BEAT_OPTIONS,
    },
}

logger.info(
    "Beat: pipeline Slack digest — hour=%s minute=%02d window=%sh (slack queue)",
    _s.slack_digest_crontab_hour,
    _s.slack_digest_crontab_minute,
    _s.slack_digest_window_hours,
)

if _s.site_watchdog_enabled:
    _wd_minute = (_s.site_watchdog_crontab_minute or "0").strip()
    beat_schedule["site-watchdog"] = {
        "task": "app.tasks.site_watchdog_check",
        "schedule": crontab(minute=_wd_minute),
        "options": _SLACK_BEAT_OPTIONS,
    }
    logger.info(
        "Beat: site watchdog at minute=%s UTC, heartbeat=%sh (slack queue)",
        _wd_minute,
        _s.site_watchdog_heartbeat_hours,
    )

_ingest_path = (_s.scheduled_geojson_ingest_path or "").strip()
if _ingest_path:
    _fips = (_s.scheduled_geojson_ingest_default_county_fips or "").strip()
    beat_schedule["scheduled-geojson-ingest"] = {
        "task": "app.tasks.ingest_geojson_path",
        "schedule": crontab(
            minute=_s.scheduled_geojson_ingest_crontab_minute,
            hour=_s.scheduled_geojson_ingest_crontab_hour,
        ),
        "kwargs": {
            "path": _ingest_path,
            "default_county_fips": _fips or None,
            "auto_run_pipeline": _s.scheduled_geojson_ingest_auto_run_pipeline,
            "max_auto_pipeline": _s.scheduled_geojson_ingest_max_auto_pipeline,
            "delete_after": False,
        },
    }
    logger.info(
        "Beat: scheduled GeoJSON ingest → %s at %02d:%02d UTC",
        _ingest_path,
        _s.scheduled_geojson_ingest_crontab_hour,
        _s.scheduled_geojson_ingest_crontab_minute,
    )

if _s.exploration_campaign_enabled:
    beat_schedule["wa-exploration-campaign-daily"] = {
        "task": "app.tasks.exploration_campaign_tick",
        "schedule": crontab(
            minute=_s.exploration_campaign_crontab_minute,
            hour=_s.exploration_campaign_crontab_hour,
        ),
    }
    logger.info(
        "Beat: WA exploration campaign daily at %02d:%02d UTC",
        _s.exploration_campaign_crontab_hour,
        _s.exploration_campaign_crontab_minute,
    )

if _s.wa_statewide_rollout_enabled:
    beat_schedule["wa-statewide-rollout-daily"] = {
        "task": "app.tasks.wa_statewide_rollout_tick",
        "schedule": crontab(
            minute=_s.wa_statewide_rollout_crontab_minute,
            hour=_s.wa_statewide_rollout_crontab_hour,
        ),
    }
    logger.info(
        "Beat: WA statewide rollout (one county/day) at %02d:%02d UTC",
        _s.wa_statewide_rollout_crontab_hour,
        _s.wa_statewide_rollout_crontab_minute,
    )

if _s.scheduled_priority_pipeline_enabled:
    beat_schedule["enqueue-priority-qualified"] = {
        "task": "app.tasks.enqueue_priority_qualified_scheduled",
        "schedule": crontab(
            minute=_s.scheduled_priority_pipeline_crontab_minute,
            hour=_s.scheduled_priority_pipeline_crontab_hour,
        ),
        "kwargs": {"limit": _s.scheduled_priority_pipeline_limit},
    }
    logger.info(
        "Beat: priority qualified pipelines — hour=%s minute=%02d limit=%s",
        _s.scheduled_priority_pipeline_crontab_hour,
        _s.scheduled_priority_pipeline_crontab_minute,
        _s.scheduled_priority_pipeline_limit,
    )

if _s.scheduled_enqueue_unscored_enabled:
    beat_schedule["enqueue-unscored-pipelines"] = {
        "task": "app.tasks.enqueue_unscored_pipelines_scheduled",
        "schedule": crontab(
            minute=_s.scheduled_enqueue_unscored_crontab_minute,
            hour=_s.scheduled_enqueue_unscored_crontab_hour,
        ),
        "kwargs": {"limit": _s.scheduled_enqueue_unscored_limit},
    }
    logger.info(
        "Beat: enqueue unscored pipelines — hour=%s minute=%02d limit=%s",
        _s.scheduled_enqueue_unscored_crontab_hour,
        _s.scheduled_enqueue_unscored_crontab_minute,
        _s.scheduled_enqueue_unscored_limit,
    )

if _s.scheduled_refresh_identification_enabled:
    _id_cf = (_s.scheduled_refresh_identification_county_fips or "").strip()
    beat_schedule["refresh-identification-scores-scheduled"] = {
        "task": "app.tasks.refresh_identification_scores_batch",
        "schedule": crontab(
            minute=_s.scheduled_refresh_identification_crontab_minute,
            hour=_s.scheduled_refresh_identification_crontab_hour,
        ),
        "kwargs": {
            "limit": _s.scheduled_refresh_identification_limit,
            "county_fips": _id_cf or None,
        },
    }
    logger.info(
        "Beat: refresh identification scores — hour=%s minute=%02d limit=%s county=%s",
        _s.scheduled_refresh_identification_crontab_hour,
        _s.scheduled_refresh_identification_crontab_minute,
        _s.scheduled_refresh_identification_limit,
        _id_cf or "*",
    )

if _s.scheduled_refresh_demand_enabled:
    _dem_cf = (_s.scheduled_refresh_demand_county_fips or "").strip()
    beat_schedule["refresh-demand-distances-scheduled"] = {
        "task": "app.tasks.refresh_demand_distances_batch",
        "schedule": crontab(
            minute=_s.scheduled_refresh_demand_crontab_minute,
            hour=_s.scheduled_refresh_demand_crontab_hour,
        ),
        "kwargs": {
            "limit": _s.scheduled_refresh_demand_limit,
            "county_fips": _dem_cf or None,
        },
    }
    logger.info(
        "Beat: refresh demand distances — hour=%s minute=%02d limit=%s county=%s",
        _s.scheduled_refresh_demand_crontab_hour,
        _s.scheduled_refresh_demand_crontab_minute,
        _s.scheduled_refresh_demand_limit,
        _dem_cf or "*",
    )

_task_routes = {name: {"queue": SLACK_QUEUE} for name in SLACK_TASK_NAMES}

celery = Celery("parking", broker=broker, backend=backend)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue=PARKING_QUEUE,
    task_queues=(
        Queue(PARKING_QUEUE),
        Queue(SLACK_QUEUE),
    ),
    beat_schedule=beat_schedule,
    task_routes=_task_routes,
)

import app.tasks  # noqa: E402,F401 — register Celery tasks

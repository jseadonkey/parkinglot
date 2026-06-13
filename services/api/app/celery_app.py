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
    "app.tasks.slack_plan_progress_report",
    "app.tasks.slack_qualified_parcels_report",
    "app.tasks.slack_dual_agent_discussion",
    "app.tasks.site_watchdog_check",
    "app.tasks.ops_remediation_loop",
)

_SLACK_BEAT_OPTIONS = {"queue": SLACK_QUEUE}

_s = get_settings()


def _slack_crontab(*, minute: int, hour: int | str, day_of_week: str = "*") -> crontab:
    kwargs: dict = {"minute": minute, "hour": hour}
    if day_of_week != "*":
        kwargs["day_of_week"] = day_of_week
    return crontab(**kwargs)


beat_schedule: dict = {
    "slack-parking-digest": {
        "task": "app.tasks.slack_agent_digest",
        "schedule": _slack_crontab(
            minute=_s.slack_digest_crontab_minute,
            hour=_s.slack_digest_crontab_hour,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    },
}

if _s.slack_plan_progress_enabled:
    beat_schedule["slack-plan-progress"] = {
        "task": "app.tasks.slack_plan_progress_report",
        "schedule": _slack_crontab(
            minute=_s.slack_plan_progress_crontab_minute,
            hour=_s.slack_plan_progress_crontab_hour,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    }

if _s.slack_qualified_parcels_enabled:
    beat_schedule["slack-qualified-parcels"] = {
        "task": "app.tasks.slack_qualified_parcels_report",
        "schedule": _slack_crontab(
            minute=_s.slack_qualified_parcels_crontab_minute,
            hour=_s.slack_qualified_parcels_crontab_hour,
            day_of_week=_s.slack_qualified_parcels_crontab_day_of_week,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    }

if _s.slack_dual_agent_discussion_enabled:
    beat_schedule["slack-dual-agent-discussion"] = {
        "task": "app.tasks.slack_dual_agent_discussion",
        "schedule": _slack_crontab(
            minute=_s.slack_dual_agent_discussion_crontab_minute,
            hour=_s.slack_dual_agent_discussion_crontab_hour,
            day_of_week=_s.slack_dual_agent_discussion_crontab_day_of_week,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    }

logger.info(
    "Beat: pipeline Slack digest — hour=%s minute=%02d window=%sh (slack queue)",
    _s.slack_digest_crontab_hour,
    _s.slack_digest_crontab_minute,
    _s.slack_digest_window_hours,
)
if _s.slack_plan_progress_enabled:
    logger.info(
        "Beat: A-E plan progress Slack report — hour=%s minute=%02d (slack queue)",
        _s.slack_plan_progress_crontab_hour,
        _s.slack_plan_progress_crontab_minute,
    )
else:
    logger.info("Beat: A-E plan progress Slack report disabled (SLACK_PLAN_PROGRESS_ENABLED=false)")

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

if _s.ops_remediation_enabled:
    beat_schedule["ops-remediation-loop"] = {
        "task": "app.tasks.ops_remediation_loop",
        "schedule": crontab(
            minute=_s.ops_remediation_crontab_minute,
            hour=_s.ops_remediation_crontab_hour,
        ),
        "options": _SLACK_BEAT_OPTIONS,
    }
    logger.info(
        "Beat: ops remediation loop — hour=%s minute=%s auto_fix=%s db_writes_allowed=%s (slack queue)",
        _s.ops_remediation_crontab_hour,
        _s.ops_remediation_crontab_minute,
        bool(_s.ops_remediation_auto_fix and _s.ops_remediation_allow_db_writes),
        _s.ops_remediation_allow_db_writes,
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

if _s.address_health_agent_enabled:
    _ah_hour = (_s.address_health_agent_crontab_hour or "*/12").strip()
    beat_schedule["address-health-agent"] = {
        "task": "app.tasks.address_health_agent_tick",
        "schedule": crontab(
            minute=_s.address_health_agent_crontab_minute,
            hour=_ah_hour,
        ),
    }
    logger.info(
        "Beat: address health agent at hour=%s minute=%02d UTC",
        _ah_hour,
        _s.address_health_agent_crontab_minute,
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

if _s.load_governor_enabled:
    beat_schedule["load-governor-refresh"] = {
        "task": "app.tasks.load_governor_refresh",
        "schedule": crontab(minute="*/30"),
    }
    logger.info("Beat: load governor refresh every 30 minutes")

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

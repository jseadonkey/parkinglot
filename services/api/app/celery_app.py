from __future__ import annotations

import logging
import os

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

logger = logging.getLogger(__name__)

beat_schedule: dict = {
    "slack-parking-digest-20m": {
        "task": "app.tasks.slack_agent_digest",
        "schedule": crontab(minute="*/20"),
    },
    "slack-qualified-parcels-daily": {
        "task": "app.tasks.slack_qualified_parcels_report",
        "schedule": crontab(minute=0, hour=14),
    },
    "slack-dual-agent-discussion-daily": {
        "task": "app.tasks.slack_dual_agent_discussion",
        "schedule": crontab(minute=30, hour=15),
    },
}

_s = get_settings()
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

if _s.wa_sos_beat_enabled and _s.wa_sos_lookup_enabled:
    beat_schedule["enrich-wa-sos-entities"] = {
        "task": "app.tasks.enrich_wa_sos_entities_batch",
        "schedule": crontab(minute=f"*/{_s.wa_sos_beat_crontab_minute}"),
        "kwargs": {"limit": _s.wa_sos_beat_limit, "county_fips": "53033"},
        "options": {"queue": "sos"},
    }
    logger.info(
        "Beat: WA SOS entity enrichment every %s min, limit=%s (sos queue)",
        _s.wa_sos_beat_crontab_minute,
        _s.wa_sos_beat_limit,
    )

celery = Celery("parking", broker=broker, backend=backend)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="parking",
    task_routes={
        "app.tasks.enrich_wa_sos_parcel": {"queue": "sos"},
        "app.tasks.enrich_wa_sos_entities_batch": {"queue": "sos"},
    },
    beat_schedule=beat_schedule,
)

import app.tasks  # noqa: E402,F401 — register Celery tasks

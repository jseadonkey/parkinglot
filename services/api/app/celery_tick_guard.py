"""Guard Beat-driven parking-queue ticks from piling up when workers fall behind."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from app.config import Settings
from app.wa_phase_b_rollout import celery_task_still_active

logger = logging.getLogger(__name__)

PARKING_QUEUE = "parking"

# Beat tasks that should have at most one pending copy and one in-flight run.
GUARDED_TICK_KEYS: frozenset[str] = frozenset(
    {
        "load_governor_refresh",
        "rollout_orchestrator_tick",
        "wa_statewide_rollout_tick",
        "wa_phase_b_rollout_tick",
        "enqueue_priority_qualified_scheduled",
        "enqueue_unscored_pipelines_scheduled",
        "address_health_agent_tick",
        "county_source_agent_tick",
    }
)

IN_FLIGHT_KEY_PREFIX = "celery_tick:in_flight:"
DEFAULT_IN_FLIGHT_TTL_SEC = 3 * 3600


def _redis_client(settings: Settings) -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def task_suffix(full_task_name: str) -> str:
    return full_task_name.rsplit(".", 1)[-1]


def count_queued_tick_tasks(settings: Settings, tick_key: str) -> int:
    """Count messages waiting in the parking queue for a given tick suffix."""
    if tick_key not in GUARDED_TICK_KEYS:
        return 0
    client = _redis_client(settings)
    items = client.lrange(PARKING_QUEUE, 0, -1)
    count = 0
    for raw in items:
        try:
            msg = json.loads(raw)
            name = str(msg.get("headers", {}).get("task") or "")
            if task_suffix(name) == tick_key:
                count += 1
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    return count


def purge_queued_tick_tasks(settings: Settings, tick_key: str) -> int:
    """Drop queued copies of a tick task; return number removed."""
    if tick_key not in GUARDED_TICK_KEYS:
        return 0
    client = _redis_client(settings)
    items = client.lrange(PARKING_QUEUE, 0, -1)
    if not items:
        return 0
    kept: list[str] = []
    removed = 0
    for raw in items:
        try:
            msg = json.loads(raw)
            name = str(msg.get("headers", {}).get("task") or "")
            if task_suffix(name) == tick_key:
                removed += 1
                continue
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        kept.append(raw)
    if removed:
        pipe = client.pipeline()
        pipe.delete(PARKING_QUEUE)
        if kept:
            pipe.rpush(PARKING_QUEUE, *kept)
        pipe.execute()
        logger.info("celery_tick_guard: purged %s queued %s task(s)", removed, tick_key)
    return removed


def _in_flight_key(tick_key: str) -> str:
    return f"{IN_FLIGHT_KEY_PREFIX}{tick_key}"


def release_tick_in_flight(settings: Settings, tick_key: str, task_id: str) -> None:
    client = _redis_client(settings)
    key = _in_flight_key(tick_key)
    if client.get(key) == task_id:
        client.delete(key)


def guard_scheduled_tick(
    settings: Settings,
    *,
    tick_key: str,
    task_id: str,
    in_flight_ttl_sec: int = DEFAULT_IN_FLIGHT_TTL_SEC,
) -> dict[str, Any] | None:
    """Claim a tick slot or return a skip payload when another run is active."""
    if tick_key not in GUARDED_TICK_KEYS:
        return None

    client = _redis_client(settings)
    holder = client.get(_in_flight_key(tick_key))
    if holder and holder != task_id and celery_task_still_active(holder):
        queued = count_queued_tick_tasks(settings, tick_key)
        return {
            "skipped": True,
            "reason": "tick_in_flight",
            "tick_key": tick_key,
            "holder_task_id": holder,
            "queued_siblings": queued,
        }

    purged = purge_queued_tick_tasks(settings, tick_key)
    client.set(_in_flight_key(tick_key), task_id, ex=in_flight_ttl_sec)
    return {"tick_guard_purged": purged}


def finish_guarded_tick(settings: Settings, tick_key: str, task_id: str) -> None:
    release_tick_in_flight(settings, tick_key, task_id)


def run_guarded_tick(tick_key: str, body) -> dict[str, Any]:
    """Run a Beat tick body under in-flight + backlog guards."""
    from celery import current_task

    from app.config import get_settings

    settings = get_settings()
    task_id = current_task.request.id
    pre = guard_scheduled_tick(settings, tick_key=tick_key, task_id=task_id)
    if pre and pre.get("skipped"):
        return pre
    purged = int((pre or {}).get("tick_guard_purged") or 0)
    try:
        out = body()
        if isinstance(out, dict) and purged:
            out.setdefault("tick_guard_purged", purged)
        return out
    finally:
        finish_guarded_tick(settings, tick_key, task_id)

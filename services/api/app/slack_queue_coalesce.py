"""Drop superseded Slack-queue runs — only the newest snapshot task should execute."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from typing import Any

import redis
from redis.exceptions import WatchError

from app.config import Settings

logger = logging.getLogger(__name__)

SLACK_QUEUE = "slack"

# Beat-scheduled snapshot reports: stale runs are useless once a newer copy is queued.
SLACK_COALESCE_TASK_NAMES: frozenset[str] = frozenset(
    {
        "app.tasks.slack_plan_progress_report",
        "app.tasks.site_watchdog_check",
        "app.tasks.slack_agent_digest",
        "app.tasks.ops_remediation_loop",
        "app.tasks.slack_qualified_parcels_report",
        "app.tasks.slack_dual_agent_discussion",
    }
)


@dataclass(frozen=True)
class QueuedSlackTask:
    task_name: str
    task_id: str
    index: int


def _redis_client(settings: Settings, **kwargs: Any) -> redis.Redis:
    return redis.from_url(settings.redis_url, **kwargs)


def _decode_celery_body(envelope: dict[str, Any]) -> Any:
    body = envelope.get("body")
    if isinstance(body, str):
        try:
            body_bytes = base64.b64decode(body)
        except (binascii.Error, ValueError):
            return None
        encoding = envelope.get("content-encoding") or "utf-8"
        try:
            return json.loads(body_bytes.decode(str(encoding)))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None
    return body


def parse_queued_slack_task(raw: str | bytes, *, index: int) -> QueuedSlackTask | None:
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None

    headers = envelope.get("headers") if isinstance(envelope.get("headers"), dict) else {}
    properties = envelope.get("properties") if isinstance(envelope.get("properties"), dict) else {}
    task_name = headers.get("task")
    task_id = headers.get("id") or properties.get("correlation_id")

    decoded = _decode_celery_body(envelope)
    if isinstance(decoded, dict):
        task_name = task_name or decoded.get("task")
        task_id = task_id or decoded.get("id")

    if not isinstance(task_name, str) or not task_name:
        return None
    return QueuedSlackTask(task_name=task_name, task_id=str(task_id or ""), index=index)


def _plan_coalesce_prune(messages: list[str | bytes]) -> dict[str, Any]:
    parsed: list[QueuedSlackTask] = []
    for index, raw in enumerate(messages):
        item = parse_queued_slack_task(raw, index=index)
        if item is not None:
            parsed.append(item)

    last_index_by_task: dict[str, int] = {}
    for item in parsed:
        if item.task_name in SLACK_COALESCE_TASK_NAMES:
            last_index_by_task[item.task_name] = item.index

    keep_indices: set[int] = set()
    for index, raw in enumerate(messages):
        item = parse_queued_slack_task(raw, index=index)
        if item is None or item.task_name not in SLACK_COALESCE_TASK_NAMES:
            keep_indices.add(index)
            continue
        if last_index_by_task.get(item.task_name) == index:
            keep_indices.add(index)

    kept_messages = [messages[i] for i in range(len(messages)) if i in keep_indices]
    removed = [
        {"task_name": p.task_name, "task_id": p.task_id, "index": p.index}
        for p in parsed
        if p.task_name in SLACK_COALESCE_TASK_NAMES and p.index not in keep_indices
    ]
    return {
        "ok": True,
        "scanned": len(messages),
        "kept": len(kept_messages),
        "removable": len(removed),
        "removals": removed,
        "_kept_messages": kept_messages,
    }


def count_pending_slack_tasks(
    settings: Settings,
    task_name: str,
    *,
    queue_name: str = SLACK_QUEUE,
) -> int:
    client = _redis_client(settings, decode_responses=False, socket_timeout=2.0)
    messages = list(client.lrange(queue_name, 0, -1) or [])
    return sum(
        1
        for index, raw in enumerate(messages)
        if (parsed := parse_queued_slack_task(raw, index=index)) is not None and parsed.task_name == task_name
    )


def prune_coalesce_slack_queue(
    settings: Settings,
    *,
    queue_name: str = SLACK_QUEUE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Keep only the newest queued copy of each coalesce-eligible Slack task."""
    client = _redis_client(settings, decode_responses=False, socket_timeout=2.0)
    removed_task_ids: list[str] = []
    plan: dict[str, Any] = {"ok": False}
    for _attempt in range(3):
        with client.pipeline() as pipe:
            try:
                pipe.watch(queue_name)
                messages = list(pipe.lrange(queue_name, 0, -1) or [])
                plan = _plan_coalesce_prune(messages)
                kept_messages = list(plan.pop("_kept_messages"))
                plan["queue"] = queue_name
                plan["dry_run"] = dry_run
                if dry_run or not plan["removable"]:
                    pipe.unwatch()
                    plan["revoked_task_ids"] = []
                    return plan

                pipe.multi()
                pipe.delete(queue_name)
                if kept_messages:
                    pipe.rpush(queue_name, *kept_messages)
                pipe.execute()
                removed_task_ids = [str(r["task_id"]) for r in plan["removals"] if r.get("task_id")]
                break
            except WatchError:
                continue
    else:
        return {
            "ok": False,
            "queue": queue_name,
            "dry_run": dry_run,
            "detail": "Redis queue changed while pruning; retry later",
        }

    if removed_task_ids:
        logger.info(
            "pruned %s stale Slack queue task(s) from %s (kept=%s)",
            len(removed_task_ids),
            queue_name,
            plan.get("kept"),
        )
    plan["revoked_task_ids"] = removed_task_ids
    return plan


def maybe_skip_stale_slack_run(settings: Settings, task_name: str) -> dict[str, Any] | None:
    """Return a skip payload when a newer run of the same Slack task is still queued."""
    if not getattr(settings, "slack_coalesce_enabled", True):
        return None
    if task_name not in SLACK_COALESCE_TASK_NAMES:
        return None

    prune_coalesce_slack_queue(settings)

    pending = count_pending_slack_tasks(settings, task_name)
    if pending <= 0:
        return None

    logger.info(
        "skipping stale Slack task %s (%s newer run(s) still queued)",
        task_name,
        pending,
    )
    return {
        "skipped": True,
        "reason": "superseded_by_newer_slack_run",
        "task": task_name,
        "pending_same_task": pending,
    }

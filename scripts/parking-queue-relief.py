#!/usr/bin/env python3
"""Relieve an overloaded Celery parking queue (Droplet ops).

Revokes stuck tick tasks, purges redundant Beat backlog, and optionally
priority-bumps Phase B build/merge jobs to the front of the queue.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.celery_tick_guard import (  # noqa: E402
    GUARDED_TICK_KEYS,
    PARKING_QUEUE,
    purge_queued_tick_tasks,
    task_suffix,
)
from app.config import get_settings  # noqa: E402
from app.wa_phase_b_rollout import celery_task_still_active  # noqa: E402

PRIORITY_SUFFIXES = frozenset(
    {
        "fetch_build_merge_wa_county_zoning",
        "build_county_zoning_overlay",
        "merge_county_wa_zoning_overlay",
    }
)
ALWAYS_KEEP_SUFFIXES = frozenset({"run_pipeline", "ingest_geojson_path"})


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _revoke(task_ids: list[str]) -> None:
    if not task_ids:
        return
    ids = " ".join(task_ids)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "deploy/docker-compose.production.yml",
            "--env-file",
            "deploy/.env",
            "exec",
            "-T",
            "worker",
            "celery",
            "-A",
            "app.celery_app",
            "control",
            "revoke",
            *task_ids,
        ],
        cwd=REPO_ROOT,
        check=False,
    )


def _active_tick_ids() -> list[str]:
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "deploy/docker-compose.production.yml",
            "--env-file",
            "deploy/.env",
            "exec",
            "-T",
            "worker",
            "celery",
            "-A",
            "app.celery_app",
            "inspect",
            "active",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout or ""
    ids: list[str] = []
    for line in out.splitlines():
        if "id" not in line:
            continue
        for suffix in GUARDED_TICK_KEYS:
            if suffix in line:
                start = line.find("'id': '")
                if start == -1:
                    continue
                start += len("'id': '")
                end = line.find("'", start)
                if end > start:
                    ids.append(line[start:end])
                break
    return ids


def rebuild_queue(*, priority_front: bool) -> dict[str, int]:
    client = _redis()
    items = client.lrange(PARKING_QUEUE, 0, -1)
    priority: list[str] = []
    keep: list[str] = []
    dropped = 0
    for raw in items:
        try:
            msg = json.loads(raw)
            suffix = task_suffix(str(msg.get("headers", {}).get("task") or ""))
        except (json.JSONDecodeError, TypeError, AttributeError):
            keep.append(raw)
            continue
        if suffix in GUARDED_TICK_KEYS:
            dropped += 1
            continue
        if priority_front and suffix in PRIORITY_SUFFIXES:
            priority.append(raw)
        elif suffix in ALWAYS_KEEP_SUFFIXES or suffix in PRIORITY_SUFFIXES:
            keep.append(raw)
        else:
            keep.append(raw)
    ordered = (priority + keep) if priority_front else (keep + priority)
    pipe = client.pipeline()
    pipe.delete(PARKING_QUEUE)
    if ordered:
        pipe.rpush(PARKING_QUEUE, *ordered)
    pipe.execute()
    return {
        "before": len(items),
        "after": len(ordered),
        "dropped_ticks": dropped,
        "priority_front": len(priority),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Relieve parking Celery queue backlog")
    parser.add_argument("--no-revoke", action="store_true")
    parser.add_argument("--no-purge", action="store_true")
    parser.add_argument("--no-priority-phase-b", action="store_true")
    args = parser.parse_args()
    settings = get_settings()

    report: dict[str, object] = {}

    if not args.no_revoke:
        stuck = _active_tick_ids()
        _revoke(stuck)
        report["revoked"] = stuck

    if not args.no_purge:
        purged_total = 0
        for key in GUARDED_TICK_KEYS:
            purged_total += purge_queued_tick_tasks(settings, key)
        report["purged_ticks"] = purged_total

    if not args.no_priority_phase_b:
        report["queue"] = rebuild_queue(priority_front=True)

    client = _redis()
    report["final_depth"] = client.llen(PARKING_QUEUE)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

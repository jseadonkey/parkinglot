from __future__ import annotations

import json
from unittest.mock import patch

from app.config import Settings
from app.slack_queue_coalesce import (
    SLACK_COALESCE_TASK_NAMES,
    _plan_coalesce_prune,
    maybe_skip_stale_slack_run,
    parse_queued_slack_task,
)


def _envelope(task_name: str, task_id: str) -> str:
    body = "W1tdLCB7fSwgeyJjYWxsYmFja3MiOiBudWxsLCAiZXJyYmFja3MiOiBudWxsLCAiY2hhaW4iOiBudWxsLCAiY2hvcmQiOiBudWxsfV0="
    return json.dumps(
        {
            "body": body,
            "content-encoding": "utf-8",
            "content-type": "application/json",
            "headers": {"task": task_name, "id": task_id},
            "properties": {"correlation_id": task_id},
        }
    )


def test_plan_coalesce_prune_keeps_only_newest_per_task() -> None:
    messages = [
        _envelope("app.tasks.ops_remediation_loop", "ops-old"),
        _envelope("app.tasks.slack_plan_progress_report", "pp-old"),
        _envelope("app.tasks.ops_remediation_loop", "ops-new"),
        _envelope("app.tasks.slack_plan_progress_report", "pp-new"),
    ]
    plan = _plan_coalesce_prune(messages)
    kept = plan["_kept_messages"]
    assert plan["removable"] == 2
    assert len(kept) == 2
    assert "ops-new" in kept[0]
    assert "pp-new" in kept[1]


def test_maybe_skip_ops_remediation_when_newer_pending() -> None:
    settings = Settings(slack_coalesce_enabled=True)
    with (
        patch("app.slack_queue_coalesce.prune_coalesce_slack_queue", return_value={"ok": True, "removable": 0}),
        patch("app.slack_queue_coalesce.count_pending_slack_tasks", return_value=1),
    ):
        out = maybe_skip_stale_slack_run(settings, "app.tasks.ops_remediation_loop")
    assert out and out["reason"] == "superseded_by_newer_slack_run"


def test_coalesce_includes_all_snapshot_tasks() -> None:
    assert "app.tasks.ops_remediation_loop" in SLACK_COALESCE_TASK_NAMES
    assert "app.tasks.slack_agent_digest" in SLACK_COALESCE_TASK_NAMES


def test_parse_queued_slack_task() -> None:
    parsed = parse_queued_slack_task(_envelope("app.tasks.site_watchdog_check", "wd-1"), index=0)
    assert parsed is not None
    assert parsed.task_name == "app.tasks.site_watchdog_check"

from __future__ import annotations

from app.celery_app import PARKING_QUEUE, SLACK_QUEUE, SLACK_TASK_NAMES, celery


def test_slack_tasks_route_to_slack_queue() -> None:
    routes = celery.conf.task_routes or {}
    for name in SLACK_TASK_NAMES:
        assert routes[name]["queue"] == SLACK_QUEUE


def test_default_queue_is_parking() -> None:
    assert celery.conf.task_default_queue == PARKING_QUEUE


def test_beat_slack_entries_target_slack_queue() -> None:
    schedule = celery.conf.beat_schedule or {}
    for key in ("slack-parking-digest", "slack-qualified-parcels"):
        entry = schedule[key]
        assert entry["options"]["queue"] == SLACK_QUEUE
    for key in (
        "slack-plan-progress",
        "slack-dual-agent-discussion",
        "site-watchdog",
        "ops-remediation-loop",
    ):
        if key not in schedule:
            continue
        assert schedule[key]["options"]["queue"] == SLACK_QUEUE

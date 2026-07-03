from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from app.celery_tick_guard import (
    collapse_queued_tick_tasks_to_one,
    count_queued_tick_tasks,
    guard_scheduled_tick,
    janitor_purge_stale_tick_backlogs,
    purge_queued_tick_tasks,
    should_skip_beat_tick_dispatch,
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(redis_url="redis://127.0.0.1:6379/0")


def test_purge_queued_tick_tasks_removes_backlog() -> None:
    payload = json.dumps(
        {
            "headers": {
                "task": "app.tasks.load_governor_refresh",
                "id": "a",
            }
        }
    )
    keep = json.dumps({"headers": {"task": "app.tasks.run_pipeline", "id": "b"}})

    class FakeRedis:
        def __init__(self) -> None:
            self.deleted = False
            self.pushed: list[str] = []

        def lrange(self, _name, _start, _end):
            return [payload, keep, payload]

        def pipeline(self):
            return self

        def delete(self, _name):
            self.deleted = True

        def rpush(self, _name, *items):
            self.pushed.extend(items)

        def execute(self):
            return None

    fake = FakeRedis()
    with patch("app.celery_tick_guard._redis_client", return_value=fake):
        removed = purge_queued_tick_tasks(_settings(), "load_governor_refresh")
    assert removed == 2
    assert fake.deleted is True
    assert len(fake.pushed) == 1


def test_guard_skips_when_holder_still_active() -> None:
    with (
        patch("app.celery_tick_guard._redis_client") as mock_redis,
        patch("app.celery_tick_guard.celery_task_still_active", return_value=True),
        patch("app.celery_tick_guard.count_queued_tick_tasks", return_value=5),
        patch("app.celery_tick_guard.purge_queued_tick_tasks", return_value=0),
    ):
        client = mock_redis.return_value
        client.get.return_value = "other-task"
        out = guard_scheduled_tick(_settings(), tick_key="load_governor_refresh", task_id="mine")
    assert out is not None
    assert out["skipped"] is True
    assert out["reason"] == "tick_in_flight"


def test_count_queued_tick_tasks() -> None:
    rows = [
        json.dumps({"headers": {"task": "app.tasks.run_pipeline"}}),
        json.dumps({"headers": {"task": "app.tasks.load_governor_refresh"}}),
    ]
    with patch("app.celery_tick_guard._redis_client") as mock_redis:
        mock_redis.return_value.lrange.return_value = rows
        assert count_queued_tick_tasks(_settings(), "load_governor_refresh") == 1


def test_should_skip_when_tick_already_queued() -> None:
    with (
        patch("app.celery_tick_guard._redis_client") as mock_redis,
        patch("app.celery_tick_guard.celery_task_still_active", return_value=False),
        patch("app.celery_tick_guard.count_queued_tick_tasks", return_value=2),
    ):
        mock_redis.return_value.get.return_value = None
        out = should_skip_beat_tick_dispatch(_settings(), "load_governor_refresh")
    assert out is not None
    assert out["reason"] == "tick_already_queued"
    assert out["queued_siblings"] == 2


def test_should_skip_pipeline_enqueue_when_governor_paused() -> None:
    settings = SimpleNamespace(redis_url="redis://127.0.0.1:6379/0", load_governor_enabled=True)
    with (
        patch("app.celery_tick_guard._redis_client") as mock_redis,
        patch("app.celery_tick_guard.celery_task_still_active", return_value=False),
        patch("app.celery_tick_guard.count_queued_tick_tasks", return_value=0),
        patch("app.load_governor.current_governor_state", return_value={"pressure_level": "orange"}),
        patch("app.load_governor.effective_pipeline_limit", return_value=0),
    ):
        mock_redis.return_value.get.return_value = None
        out = should_skip_beat_tick_dispatch(settings, "enqueue_priority_qualified_scheduled")
    assert out is not None
    assert out["reason"] == "load_governor_paused_pipeline_enqueue"


def test_collapse_queued_tick_tasks_to_one_keeps_newest() -> None:
    tick_a = json.dumps({"headers": {"task": "app.tasks.load_governor_refresh", "id": "a"}})
    tick_b = json.dumps({"headers": {"task": "app.tasks.load_governor_refresh", "id": "b"}})
    keep = json.dumps({"headers": {"task": "app.tasks.run_pipeline", "id": "c"}})

    class FakeRedis:
        def __init__(self) -> None:
            self.pushed: list[str] = []

        def lrange(self, _name, _start, _end):
            return [tick_a, keep, tick_b]

        def pipeline(self):
            return self

        def delete(self, _name):
            return None

        def rpush(self, _name, *items):
            self.pushed.extend(items)

        def execute(self):
            return None

    fake = FakeRedis()
    with patch("app.celery_tick_guard._redis_client", return_value=fake):
        removed = collapse_queued_tick_tasks_to_one(_settings(), "load_governor_refresh")
    assert removed == 1
    assert fake.pushed == [keep, tick_b]


def test_janitor_purges_while_in_flight() -> None:
    with (
        patch("app.celery_tick_guard._redis_client") as mock_redis,
        patch("app.celery_tick_guard.celery_task_still_active", return_value=True),
        patch("app.celery_tick_guard.purge_queued_tick_tasks", return_value=3) as purge,
        patch("app.celery_tick_guard.collapse_queued_tick_tasks_to_one", return_value=0),
    ):
        mock_redis.return_value.get.return_value = "live-task"
        out = janitor_purge_stale_tick_backlogs(_settings())
    assert out["removed_total"] > 0
    assert purge.called

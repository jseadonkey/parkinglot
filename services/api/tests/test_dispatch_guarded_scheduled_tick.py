from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tasks import dispatch_guarded_scheduled_tick


def test_dispatch_skips_when_gate_blocks() -> None:
    with patch(
        "app.celery_tick_guard.should_skip_beat_tick_dispatch",
        return_value={"skipped": True, "reason": "tick_already_queued"},
    ):
        out = dispatch_guarded_scheduled_tick.run(
            "load_governor_refresh",
            "app.tasks.load_governor_refresh",
        )
    assert out["skipped"] is True
    assert out["reason"] == "tick_already_queued"


def test_dispatch_enqueues_target_on_parking_queue() -> None:
    sent = MagicMock(id="child-task")
    with (
        patch("app.celery_tick_guard.should_skip_beat_tick_dispatch", return_value=None),
        patch("app.tasks.get_settings", return_value=SimpleNamespace()),
        patch("app.celery_app.celery.send_task", return_value=sent) as send_task,
    ):
        out = dispatch_guarded_scheduled_tick.run(
            "load_governor_refresh",
            "app.tasks.load_governor_refresh",
            {"limit": 5},
        )
    send_task.assert_called_once_with(
        "app.tasks.load_governor_refresh",
        kwargs={"limit": 5},
        queue="parking",
        expires=3600,
    )
    assert out["dispatched"] is True
    assert out["target_task_id"] == "child-task"

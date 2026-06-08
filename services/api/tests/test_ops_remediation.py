from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

from app.ops_remediation import (
    OpsIssue,
    _missing_poi_refresh_count,
    apply_remediation,
    build_slack_text,
    diagnose,
    effective_auto_fix_enabled,
    inspect_poi_refresh_queue,
    prune_queued_poi_refresh_tasks,
    should_post_slack,
)


def test_missing_poi_refresh_count_uses_candidate_scope() -> None:
    db = MagicMock()
    with (
        patch("app.ops_remediation.column_exists", return_value=True),
        patch("app.ops_remediation.count_poi_density_candidates", return_value=0) as count_candidates,
    ):
        out = _missing_poi_refresh_count(db, "24510")

    assert out == 0
    count_candidates.assert_called_once_with(
        db,
        county_fips="24510",
        missing_only=True,
        require_footprint=True,
    )


def test_build_slack_text_lists_critical_issues() -> None:
    report = {
        "ok": False,
        "checked_at": "2026-06-03T12:00:00+00:00",
        "issue_count": 1,
        "critical_count": 1,
        "issues": [
            {
                "code": "celery_workers_down",
                "severity": "critical",
                "message": "No workers",
            },
        ],
        "actions": [],
        "celery_workers": {"ok": False},
    }
    text = build_slack_text(report)
    assert "celery_workers_down" in text
    assert "Celery" in text


def test_should_post_slack_on_critical() -> None:
    settings = MagicMock(ops_remediation_heartbeat_hours=12, ops_remediation_notify_on_warnings=True)
    report = {"ok": False, "critical_count": 1, "issue_count": 1}
    post, recovered = should_post_slack(settings, report, None)
    assert post is True
    assert recovered is False


def test_effective_auto_fix_requires_explicit_db_write_opt_in() -> None:
    assert effective_auto_fix_enabled(
        MagicMock(ops_remediation_auto_fix=True, ops_remediation_allow_db_writes=False),
    ) is False
    assert effective_auto_fix_enabled(
        MagicMock(ops_remediation_auto_fix=True, ops_remediation_allow_db_writes=True),
    ) is True


def test_apply_remediation_respects_cooldown(monkeypatch) -> None:
    settings = MagicMock(
        ops_remediation_auto_fix=True,
        ops_remediation_cooldown_sec=3600,
        ops_remediation_priority_county_fips="24510",
        ops_remediation_batch_limit=100,
        ops_remediation_poi_batch_limit=50,
        ops_remediation_pipeline_enqueue_limit=10,
    )
    issues = [
        OpsIssue(
            code="missing_poi",
            severity="info",
            message="many missing",
            fix_action="refresh_poi_batch",
        ),
    ]
    monkeypatch.setattr("app.ops_remediation.cooldown_active", lambda _s, _a: True)
    actions = apply_remediation(MagicMock(), settings, issues, auto_fix=True)
    assert actions[0].status == "skipped_cooldown"


def test_diagnose_flags_missing_workers() -> None:
    settings = MagicMock(site_watchdog_parking_queue_warn=50_000)
    with (
        patch("app.ops_remediation.inspect_celery_workers", return_value={"ok": False, "detail": "down"}),
        patch("app.ops_remediation.inspect_redis_queues", return_value={"ok": True, "parking_depth": 0}),
        patch("app.ops_remediation.load_watchdog_report", return_value=None),
        patch("app.ops_remediation.priority_county_fips", return_value=[]),
        patch(
            "app.ops_remediation.export_readiness_summary",
            return_value={"parcels_pipeline_funnel_backlog": {"count": 0}},
        ),
    ):
        issues = diagnose(MagicMock(), settings)
    assert any(i.code == "celery_workers_down" for i in issues)


def _celery_message(task_id: str, kwargs: dict) -> str:
    body = base64.b64encode(json.dumps([[], kwargs, {}]).encode()).decode()
    return json.dumps(
        {
            "body": body,
            "content-encoding": "utf-8",
            "content-type": "application/json",
            "headers": {"task": "app.tasks.refresh_poi_density_batch", "id": task_id},
            "properties": {"correlation_id": task_id},
        },
    )


class _FakeRedis:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def lrange(self, _key: str, _start: int, _end: int) -> list[str]:
        return list(self.messages)

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client
        self.ops: list[tuple[str, tuple]] = []

    def __enter__(self) -> _FakePipeline:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def watch(self, _key: str) -> None:
        return None

    def unwatch(self) -> None:
        return None

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return self.client.lrange(key, start, end)

    def multi(self) -> None:
        return None

    def delete(self, key: str) -> None:
        self.ops.append(("delete", (key,)))

    def rpush(self, key: str, *messages: str) -> None:
        self.ops.append(("rpush", (key, *messages)))

    def execute(self) -> None:
        for op, args in self.ops:
            if op == "delete":
                self.client.messages = []
            elif op == "rpush":
                self.client.messages.extend(args[1:])


def test_inspect_poi_refresh_queue_marks_excess_batches_removable(monkeypatch) -> None:
    redis_client = _FakeRedis(
        [
            _celery_message("task-1", {"limit": 50, "county_fips": "24510"}),
            _celery_message("task-2", {"limit": 50, "county_fips": "24510"}),
            _celery_message("task-3", {"limit": 50, "county_fips": "24510"}),
        ],
    )
    monkeypatch.setattr("app.ops_remediation._redis_client", lambda _settings: redis_client)
    monkeypatch.setattr("app.ops_remediation._missing_poi_refresh_count", lambda _db, _cf: 75)

    out = inspect_poi_refresh_queue(MagicMock(), MagicMock())

    assert out["poi_refresh_tasks"] == 3
    assert out["removable"] == 1
    assert out["removals"][0]["task_id"] == "task-3"
    assert out["removals"][0]["reason"] == "covered_by_earlier_queued_poi_refresh"


def test_prune_queued_poi_refresh_tasks_removes_noop_tasks(monkeypatch) -> None:
    keep = json.dumps({"headers": {"task": "app.tasks.run_pipeline", "id": "pipeline-1"}})
    remove = _celery_message("poi-1", {"limit": 50, "county_fips": "24510"})
    redis_client = _FakeRedis([keep, remove])
    revoke = MagicMock()
    monkeypatch.setattr("app.ops_remediation._redis_client", lambda _settings: redis_client)
    monkeypatch.setattr("app.ops_remediation._missing_poi_refresh_count", lambda _db, _cf: 0)
    monkeypatch.setattr("app.ops_remediation.celery.control.revoke", revoke)

    out = prune_queued_poi_refresh_tasks(MagicMock(), MagicMock())

    assert out["removable"] == 1
    assert redis_client.messages == [keep]
    revoke.assert_called_once_with(["poi-1"], terminate=False)

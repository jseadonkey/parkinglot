from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.ops_remediation import (
    OpsIssue,
    apply_remediation,
    build_slack_text,
    diagnose,
    should_post_slack,
    skip_trace_metrics,
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


def test_skip_trace_metrics_handles_missing_outreach_brief_column(monkeypatch) -> None:
    db = MagicMock()
    monkeypatch.setattr("app.ops_remediation.column_exists", lambda *_args: False)

    metrics = skip_trace_metrics(db, "24510", total=7)

    assert metrics["owner_outreach_brief_count"] == 0
    assert metrics["missing_owner_outreach_brief"] == 7
    assert metrics["skip_trace_vendor_lookup_count"] == 0
    assert metrics["skip_trace_vendor_hit_count"] == 0
    assert metrics["skip_trace_outcomes"] == {}
    db.execute.assert_not_called()

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.load_governor import (
    assess_load_pressure,
    effective_pipeline_limit,
    governor_allows_wa_rollout,
)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(redis_url="redis://127.0.0.1:6379/0")


def test_assess_green_when_queue_empty() -> None:
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True, "detail": "2 workers"}),
        patch("app.load_governor.load_watchdog_report", return_value={"ok": True}),
        patch("app.load_governor.load_last_report", return_value=None),
    ):
        out = assess_load_pressure(_settings())
    assert out["pressure_level"] == "green"
    assert out["wa_rollout_allowed"] is True
    assert out["pipeline_enqueue_multiplier"] == 1.0


def test_assess_orange_on_deep_queue() -> None:
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 800}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=None),
        patch("app.load_governor.load_last_report", return_value=None),
    ):
        out = assess_load_pressure(_settings())
    assert out["pressure_level"] == "orange"
    assert out["wa_rollout_allowed"] is False
    assert effective_pipeline_limit(75, _settings(), out) == 18


def test_assess_yellow_on_score_gaps_snapshot() -> None:
    report = {
        "export_readiness": {
            "parcels_missing_score_identification": {"count": 25_000},
            "parcels_missing_score_entitlement": {"count": 0},
            "parcels_pipeline_funnel_backlog": {"count": 0},
        }
    }
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=None),
    ):
        out = assess_load_pressure(_settings(), cached_ops_report=report)
    assert out["pressure_level"] == "yellow"
    assert governor_allows_wa_rollout(_settings(), out)[0] is True


def test_assess_ignores_broad_entitlement_gaps_without_pipeline_funnel() -> None:
    report = {
        "export_readiness": {
            "parcels_missing_score_identification": {"count": 0},
            "parcels_missing_score_entitlement": {"count": 1_462_340},
            "parcels_pipeline_funnel_backlog": {"count": 0},
        }
    }
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=None),
    ):
        out = assess_load_pressure(_settings(), cached_ops_report=report)
    assert out["pressure_level"] == "green"
    assert out["score_gaps"] == 0
    assert out["gross_entitlement_gaps"] == 1_462_340
    assert out["wa_rollout_allowed"] is True


def test_assess_counts_pipeline_funnel_as_actionable_score_gap() -> None:
    report = {
        "export_readiness": {
            "parcels_missing_score_identification": {"count": 0},
            "parcels_missing_score_entitlement": {"count": 1_462_340},
            "parcels_pipeline_funnel_backlog": {"count": 1_500},
        }
    }
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=None),
    ):
        out = assess_load_pressure(_settings(), cached_ops_report=report)
    assert out["pressure_level"] == "yellow"
    assert out["score_gaps"] == 1_500


def test_assess_does_not_pause_rollout_for_operator_ui_only_watchdog_failure() -> None:
    watchdog = {
        "ok": False,
        "checks": [
            {
                "name": "operator_ui",
                "ok": False,
                "detail": "https://vspecialist.com/operator — timed out",
            },
        ],
    }
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=watchdog),
        patch("app.load_governor.load_last_report", return_value=None),
    ):
        out = assess_load_pressure(_settings())
    assert out["pressure_level"] == "green"
    assert out["wa_rollout_allowed"] is True
    assert out["signals"] == []


def test_assess_pauses_rollout_for_api_watchdog_failure() -> None:
    watchdog = {
        "ok": False,
        "checks": [
            {"name": "operator_ui", "ok": False, "detail": "timed out"},
            {"name": "api_ready", "ok": False, "detail": "HTTP 503"},
        ],
    }
    with (
        patch("app.load_governor.inspect_redis_queues", return_value={"parking_depth": 0}),
        patch("app.load_governor.inspect_celery_workers", return_value={"ok": True}),
        patch("app.load_governor.load_watchdog_report", return_value=watchdog),
        patch("app.load_governor.load_last_report", return_value=None),
    ):
        out = assess_load_pressure(_settings())
    assert out["pressure_level"] == "orange"
    assert out["wa_rollout_allowed"] is False
    assert out["signals"] == [{"code": "site_watchdog_failed", "failures": ["api_ready"]}]

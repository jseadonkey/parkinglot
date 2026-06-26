"""Tests for Rollout Orchestrator supervisor."""

from __future__ import annotations

from app.config import Settings
from app.rollout_orchestrator import (
    clear_stale_phase_b_locks,
    format_slack_status,
    summary_changed,
)


def test_clear_stale_lock_when_task_dead(monkeypatch) -> None:
    settings = Settings(redis_url="redis://localhost:6379/0")
    released: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.rollout_orchestrator.phase_b_merge_lock_holder",
        lambda _url, fips: "dead-task-id" if fips == "53053" else None,
    )
    monkeypatch.setattr(
        "app.rollout_orchestrator.celery_task_still_active",
        lambda _tid: False,
    )
    monkeypatch.setattr(
        "app.rollout_orchestrator.release_phase_b_merge_lock",
        lambda _url, fips, tid: released.append((fips, tid)),
    )

    result = clear_stale_phase_b_locks(settings, county_fips="53053")
    assert result["cleared"] is True
    assert result["former_holder"] == "dead-task-id"
    assert released == [("53053", "dead-task-id")]


def test_clear_stale_lock_skips_active_task(monkeypatch) -> None:
    settings = Settings(redis_url="redis://localhost:6379/0")
    monkeypatch.setattr(
        "app.rollout_orchestrator.phase_b_merge_lock_holder",
        lambda _url, _fips: "live-task-id",
    )
    monkeypatch.setattr(
        "app.rollout_orchestrator.celery_task_still_active",
        lambda _tid: True,
    )

    result = clear_stale_phase_b_locks(settings, county_fips="53053")
    assert result["cleared"] is False
    assert result["reason"] == "task_still_active"


def test_summary_changed_on_next_county() -> None:
    prev = {"phase_b": {"next_county_fips": "53053", "pending_merge_county_fips": None}}
    cur = {"phase_b": {"next_county_fips": "53061", "pending_merge_county_fips": None}}
    assert summary_changed(prev, cur) is True


def test_summary_unchanged_when_same() -> None:
    block = {
        "next_county_fips": "53053",
        "pending_merge_county_fips": "53053",
        "last_merged_county_fips": "53033",
    }
    assert summary_changed({"phase_b": block}, {"phase_b": dict(block)}) is False


def test_format_slack_status_includes_actions() -> None:
    text = format_slack_status(
        {
            "parking_queue_depth": 12,
            "phase_b": {
                "next_county_fips": "53053",
                "pending_merge_county_fips": "53053",
                "pending_merge_age_hours": 1.5,
                "last_merged_county_fips": "53033",
                "hours_since_last_merge": 4.2,
            },
            "merge_locks": [],
        },
        actions=["cleared lock 53053", "kicked phase_b tick (abc)"],
    )
    assert "Rollout Orchestrator" in text
    assert "53053" in text
    assert "cleared lock" in text


def test_run_orchestrator_kicks_after_stale_lock(monkeypatch) -> None:
    from app.rollout_orchestrator import run_orchestrator_tick

    settings = Settings(
        redis_url="redis://localhost:6379/0",
        wa_phase_b_rollout_enabled=True,
        wa_phase_b_rollout_config_path="/app/config/wa_phase_b_rollout.yaml",
        wa_statewide_rollout_config_path="/app/config/wa_statewide_rollout.yaml",
        pilot_config_path="/app/config/pilot.yaml",
    )
    slack_posts: list[str] = []

    monkeypatch.setattr(
        "app.rollout_orchestrator.load_phase_b_config",
        lambda _path: {"county_fips_priority": ["53053"], "max_parking_queue_depth": 300},
    )
    monkeypatch.setattr(
        "app.rollout_orchestrator.clear_stale_phase_b_locks",
        lambda _s, county_fips: {"cleared": True, "county_fips": county_fips},
    )
    monkeypatch.setattr(
        "app.rollout_orchestrator.rollout_health_snapshot",
        lambda _db, _s: {
            "at": "2026-06-25T00:00:00+00:00",
            "parking_queue_depth": 0,
            "phase_b": {
                "next_county_fips": "53053",
                "pending_merge_county_fips": None,
            },
            "merge_locks": [],
        },
    )
    monkeypatch.setattr("app.rollout_orchestrator._load_last_summary", lambda _s: None)
    monkeypatch.setattr("app.rollout_orchestrator._save_summary", lambda _s, _d: None)

    class _AR:
        id = "kick-123"

    monkeypatch.setattr(
        "app.tasks.wa_phase_b_rollout_tick.delay",
        lambda: _AR(),
    )
    monkeypatch.setattr(
        "app.slack_digest.post_agent_event_to_slack",
        lambda _s, *, agent, detail: slack_posts.append(f"{agent}:{detail}"),
    )

    result = run_orchestrator_tick(None, settings)
    assert "kicked phase_b tick" in " ".join(result["actions"])
    assert result["kick_task_id"] == "kick-123"
    assert slack_posts

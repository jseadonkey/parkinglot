"""Tests for capacity-gated WA Phase B rollout scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.wa_phase_b_rollout import (
    acquire_phase_b_merge_lock_or_skip,
    county_ready_for_phase_b,
    load_phase_b_config,
    next_county_for_phase_b,
    release_phase_b_merge_lock,
    try_acquire_phase_b_merge_lock,
    wa_phase_b_cooldown_state,
    wa_phase_b_pending_merge_state,
)

_CONFIG = str(Path(__file__).resolve().parents[3] / "config/wa_phase_b_rollout.yaml")
_PILOT = str(Path(__file__).resolve().parents[3] / "config/pilot.yaml")


def test_next_county_for_phase_b_picks_benton_when_ready(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)

    def fake_counts(_db, county_fips):
        return {f: (30_000 if f == "53005" else 0) for f in county_fips}

    def fake_missing(_db, county_fips):
        return {"total": 30_000, "missing_zoning": 30_000}

    monkeypatch.setattr("app.wa_phase_b_rollout.parcel_counts_by_county", fake_counts)
    monkeypatch.setattr("app.wa_phase_b_rollout.county_missing_zoning_stats", fake_missing)
    monkeypatch.setattr("app.wa_phase_b_rollout._latest_county_merge_completed", lambda _db, _fips: None)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.build_zoning_followup_summary",
        lambda **kwargs: {
            "counties": [
                {
                    "county_fips": "53005",
                    "needs_followup": True,
                    "zoning_status": "in_progress",
                    "jurisdiction_status_counts": {"source_found": 2},
                }
            ]
        },
    )

    county = next_county_for_phase_b(
        None,
        config=config,
        pilot_config_path=_PILOT,
        parcel_rollout_config={"county_fips_priority": ["53005"]},
    )
    assert county == "53005"


def test_county_ready_skips_when_zoning_mostly_present(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 100, "missing_zoning": 0},
    )
    ok, reason = county_ready_for_phase_b(
        None,
        county_fips="53005",
        config=config,
        followup_row={
            "needs_followup": True,
            "zoning_status": "in_progress",
            "jurisdiction_status_counts": {"source_found": 1},
        },
    )
    assert ok is False
    assert reason == "zoning_mostly_present"


def test_county_ready_skips_after_recent_completion_when_coverage_sufficient(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 1000, "missing_zoning": 45},
    )
    monkeypatch.setattr(
        "app.wa_phase_b_rollout._latest_county_merge_completed",
        lambda _db, _fips: SimpleNamespace(entity_id="53033"),
    )
    ok, reason = county_ready_for_phase_b(
        None,
        county_fips="53033",
        config=config,
        followup_row={
            "needs_followup": True,
            "zoning_status": "needs_source_discovery",
            "jurisdiction_status_counts": {"not_started": 1},
        },
    )
    assert ok is False
    assert reason == "phase_b_recently_completed"


def test_county_ready_auto_build_allows_blocked_registry_status(monkeypatch) -> None:
    config = load_phase_b_config(_CONFIG)
    monkeypatch.setattr(
        "app.wa_phase_b_rollout.county_missing_zoning_stats",
        lambda _db, _fips: {"total": 100, "missing_zoning": 100},
    )
    monkeypatch.setattr("app.wa_phase_b_rollout._latest_county_merge_completed", lambda _db, _fips: None)
    ok, reason = county_ready_for_phase_b(
        None,
        county_fips="53005",
        config=config,
        followup_row={
            "needs_followup": True,
            "zoning_status": "blocked",
            "jurisdiction_status_counts": {"source_found": 4, "blocked": 1},
        },
    )
    assert ok is True
    assert reason == "ready"


def test_cooldown_blocks_recent_merge(monkeypatch) -> None:
    from datetime import UTC, datetime

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                action="wa_phase_b_county_merge_completed",
                entity_id="53005",
                created_at=datetime.now(UTC),
            )

    db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result())
    state = wa_phase_b_cooldown_state(db, {"min_hours_between_county_merges": 6})
    assert state["ready"] is False
    assert state["last_county_fips"] == "53005"


def test_cooldown_allows_different_next_county(monkeypatch) -> None:
    """Cooldown applies to re-merge of the same county, not the next county in queue."""
    from datetime import UTC, datetime

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                action="wa_phase_b_county_merge_completed",
                entity_id="53033",
                created_at=datetime.now(UTC),
            )

    db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result())
    state = wa_phase_b_cooldown_state(db, {"min_hours_between_county_merges": 6})
    assert state["ready"] is False
    assert state["last_county_fips"] == "53033"
    # Tick logic: Pierce (53053) should not be blocked by King (53033) completion.
    assert state["last_county_fips"] != "53053"


def test_pending_merge_locks_after_start(monkeypatch) -> None:
    started = SimpleNamespace(
        action="wa_phase_b_county_merge_started",
        entity_id="53005",
        created_at=datetime.now(UTC),
    )

    class _Result:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    calls = {"n": 0}

    def execute(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Result(started)
        return _Result(None)

    db = SimpleNamespace(execute=execute)
    monkeypatch.setattr("app.wa_phase_b_rollout.phase_b_merge_lock_holder", lambda *_a, **_k: "task-live")
    monkeypatch.setattr("app.wa_phase_b_rollout.celery_task_still_active", lambda _tid: True)
    state = wa_phase_b_pending_merge_state(db, {"pending_merge_stale_hours": 72}, redis_url="redis://unused")
    assert state["pending"] is True
    assert state["pending_county_fips"] == "53005"


def test_pending_merge_clears_when_started_but_no_live_task(monkeypatch) -> None:
    started = SimpleNamespace(
        action="wa_phase_b_county_merge_started",
        entity_id="53053",
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    class _Result:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    calls = {"n": 0}

    def execute(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Result(started)
        return _Result(None)

    db = SimpleNamespace(execute=execute)
    monkeypatch.setattr("app.wa_phase_b_rollout.phase_b_merge_lock_holder", lambda *_a, **_k: None)
    state = wa_phase_b_pending_merge_state(db, {"pending_merge_stale_hours": 72}, redis_url="redis://unused")
    assert state["pending"] is False


def test_pending_merge_stays_locked_while_live_task_runs(monkeypatch) -> None:
    started = SimpleNamespace(
        action="wa_phase_b_county_merge_started",
        entity_id="53033",
        created_at=datetime.now(UTC) - timedelta(hours=20),
    )

    class _Result:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    calls = {"n": 0}

    def execute(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Result(started)
        return _Result(None)

    db = SimpleNamespace(execute=execute)
    monkeypatch.setattr("app.wa_phase_b_rollout.phase_b_merge_lock_holder", lambda *_a, **_k: "task-live")
    monkeypatch.setattr("app.wa_phase_b_rollout.celery_task_still_active", lambda _tid: True)
    state = wa_phase_b_pending_merge_state(db, {"pending_merge_stale_hours": 72}, redis_url="redis://unused")
    assert state["pending"] is True
    assert state["pending_county_fips"] == "53033"


def test_pending_merge_clears_when_same_county_completed_after_start(monkeypatch) -> None:
    started_at = datetime.now(UTC) - timedelta(hours=2)
    started = SimpleNamespace(
        action="wa_phase_b_county_merge_started",
        entity_id="53033",
        created_at=started_at,
    )
    completed = SimpleNamespace(
        action="wa_phase_b_county_merge_completed",
        entity_id="53033",
        created_at=started_at + timedelta(minutes=30),
    )

    class _Result:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    calls = {"n": 0}

    def execute(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Result(started)
        return _Result(completed)

    db = SimpleNamespace(execute=execute)
    state = wa_phase_b_pending_merge_state(db, {"pending_merge_stale_hours": 72})
    assert state["pending"] is False


def test_phase_b_merge_lock_blocks_second_acquirer(monkeypatch) -> None:
    class _FakeRedis:
        def __init__(self) -> None:
            self._data: dict[str, str] = {}

        def set(self, key: str, val: str, nx: bool = False, ex: int | None = None) -> bool:
            if nx and key in self._data:
                return False
            self._data[key] = val
            return True

        def get(self, key: str) -> str | None:
            return self._data.get(key)

        def delete(self, key: str) -> None:
            self._data.pop(key, None)

        def close(self) -> None:
            return None

    fake = _FakeRedis()
    monkeypatch.setattr("redis.from_url", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr("app.wa_phase_b_rollout.celery_task_still_active", lambda task_id: task_id == "task-a")

    assert try_acquire_phase_b_merge_lock("redis://unused", "53033", "task-a") is True
    acquired, blocking = acquire_phase_b_merge_lock_or_skip("redis://unused", "53033", "task-b")
    assert acquired is False
    assert blocking == "task-a"
    release_phase_b_merge_lock("redis://unused", "53033", "task-a")
    acquired, blocking = acquire_phase_b_merge_lock_or_skip("redis://unused", "53033", "task-b")
    assert acquired is True
    assert blocking is None
